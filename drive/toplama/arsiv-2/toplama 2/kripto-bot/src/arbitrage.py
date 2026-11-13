"""Çapraz Borsa Arbitrajı (Cross-Exchange Arbitrage: Binance ↔ OKX).

Aynı coinin fiyatı iki borsada anlık ayrıştığında (ör. Binance'te ask ucuz,
OKX'te bid pahalıyken veya tam tersi):
  1) Her iki borsanın alış/satış (bid/ask) fiyatlarını milisaniyelik izler.
  2) İki borsanın komisyonlarını + kayma (slippage) payını düşerek NET SPREAD hesaplar.
  3) Net spread >= min_net_kar_yuzde ise ucuz borsadan AL + pahalı borsadan SAT
     emirlerini eşzamanlı yürütür (Delta-Nötr / Piyasa Yönünden Bağımsız Kâr).
"""
from __future__ import annotations

import time
from collections import deque


class ArbitrageEngine:
    def __init__(
        self,
        min_net_spread_pct: float = 0.08,
        fee_per_leg_pct: float = 0.04,
        slippage_pct: float = 0.02,
        trade_notional_usdt: float = 1_000.0,
        cooldown_sec: float = 10.0,
        max_quote_age_sec: float = 15.0,
        enabled: bool = True,
        state_store=None,
    ):
        self.min_net_spread_pct = min_net_spread_pct
        self.fee_per_leg_pct = fee_per_leg_pct
        self.slippage_pct = slippage_pct
        self.trade_notional_usdt = trade_notional_usdt
        self.cooldown_sec = cooldown_sec
        self.max_quote_age_sec = max_quote_age_sec
        self.enabled = enabled
        self.state_store = state_store

        # quotes[symbol][exchange] = {"bid": float, "ask": float, "ts": float}
        self.quotes: dict[str, dict[str, dict]] = {}
        self._last_exec: dict[str, float] = {}
        self.history: deque[dict] = deque(maxlen=200)
        self.total_profit_usdt: float = 0.0
        self.total_trades: int = 0

    def update_quote(
        self,
        exchange: str,
        symbol: str,
        bid: float,
        ask: float | None = None,
        ts: float | None = None,
    ):
        """Borsadan gelen fiyat veya bookTicker verisini kaydeder."""
        if bid <= 0:
            return
        ask_px = ask if (ask is not None and ask > 0) else bid
        if ask_px < bid:
            ask_px = bid
        now = ts if ts is not None else time.time()
        self.quotes.setdefault(symbol, {})[exchange] = {
            "bid": float(bid),
            "ask": float(ask_px),
            "mid": float((bid + ask_px) / 2.0),
            "ts": now,
        }

    def evaluate_symbol(self, symbol: str, now: float | None = None) -> dict | None:
        """Verilen sembol için tüm borsa çiftlerini karşılaştırır, en iyi spread'i döner."""
        now = now if now is not None else time.time()
        ex_map = self.quotes.get(symbol, {})
        if len(ex_map) < 2:
            return None

        valid = {
            ex: q
            for ex, q in ex_map.items()
            if (now - q["ts"]) <= self.max_quote_age_sec and q["ask"] > 0 and q["bid"] > 0
        }
        if len(valid) < 2:
            return None

        total_cost_pct = 2.0 * self.fee_per_leg_pct + self.slippage_pct
        best: dict | None = None

        exchanges = list(valid.keys())
        for i in range(len(exchanges)):
            for j in range(len(exchanges)):
                if i == j:
                    continue
                buy_ex = exchanges[i]
                sell_ex = exchanges[j]
                buy_ask = valid[buy_ex]["ask"]
                sell_bid = valid[sell_ex]["bid"]

                gross_pct = (sell_bid - buy_ask) / buy_ask * 100.0
                net_pct = gross_pct - total_cost_pct
                est_profit = self.trade_notional_usdt * (net_pct / 100.0)

                cand = {
                    "symbol": symbol,
                    "buy_exchange": buy_ex,
                    "sell_exchange": sell_ex,
                    "buy_price": round(buy_ask, 6),
                    "sell_price": round(sell_bid, 6),
                    "gross_spread_pct": round(gross_pct, 4),
                    "total_cost_pct": round(total_cost_pct, 4),
                    "net_spread_pct": round(net_pct, 4),
                    "est_profit_usdt": round(est_profit, 2),
                    "notional_usdt": self.trade_notional_usdt,
                    "actionable": bool(
                        self.enabled and net_pct >= self.min_net_spread_pct
                    ),
                    "ts": now,
                }
                if best is None or cand["net_spread_pct"] > best["net_spread_pct"]:
                    best = cand

        return best

    def check_opportunity(self, symbol: str, now: float | None = None) -> dict | None:
        """Eğer net spread eşiği aşılmışsa ve bekleme süresi dolmuşsa fırsatı döner."""
        now = now if now is not None else time.time()
        if not self.enabled:
            return None
        if now - self._last_exec.get(symbol, 0.0) < self.cooldown_sec:
            return None
        best = self.evaluate_symbol(symbol, now)
        if best and best["actionable"]:
            return best
        return None

    async def execute_arbitrage(
        self, opp: dict, broker=None, alert=None
    ) -> dict:
        """Çapraz borsa arbitrajını eşzamanlı yürütür (ucuzdan AL + pahalıdan SAT)."""
        symbol = opp["symbol"]
        buy_ex = opp["buy_exchange"]
        sell_ex = opp["sell_exchange"]
        buy_px = opp["buy_price"]
        sell_px = opp["sell_price"]
        notional = opp["notional_usdt"]
        qty = notional / buy_px if buy_px > 0 else 0.0
        profit_usdt = opp["est_profit_usdt"]

        self._last_exec[symbol] = time.time()

        if broker is not None:
            if getattr(broker, "mode", "paper") == "paper":
                # Paper modda net arbitraj kârını kasaya yansıt
                broker.paper.balance += profit_usdt
            else:
                # Canlı/testnet modda iki borsaya eşzamanlı market emri gönder
                import asyncio
                await asyncio.gather(
                    broker.market_order(symbol, "buy", qty, price_hint=buy_px, exchange=buy_ex),
                    broker.market_order(symbol, "sell", qty, price_hint=sell_px, exchange=sell_ex),
                )

        record = {
            **opp,
            "qty": round(qty, 6),
            "profit_usdt": round(profit_usdt, 2),
            "executed_at": time.time(),
            "status": "EXECUTED",
        }
        self.history.appendleft(record)
        self.total_profit_usdt = round(self.total_profit_usdt + profit_usdt, 2)
        self.total_trades += 1

        if self.state_store is not None:
            try:
                self.state_store.record_arb(
                    symbol=symbol,
                    buy_ex=buy_ex,
                    sell_ex=sell_ex,
                    buy_px=buy_px,
                    sell_px=sell_px,
                    gross_spread_pct=opp["gross_spread_pct"],
                    net_spread_pct=opp["net_spread_pct"],
                    profit_usdt=profit_usdt,
                    notional_usdt=notional,
                )
            except Exception:
                pass

        msg = (
            f"⚡ ÇAPRAZ ARBİTRAJ YAKALANDI | {symbol} | "
            f"{buy_ex.upper()} AL @ {buy_px:,.4f} → {sell_ex.upper()} SAT @ {sell_px:,.4f} | "
            f"Net Fark: %{opp['net_spread_pct']:+.3f} | Net Kâr: +${profit_usdt:.2f}"
        )
        print(msg, flush=True)
        if alert:
            try:
                await alert(msg)
            except Exception:
                pass
        return record

    def scan_all(self, symbols: list[str] | None = None) -> list[dict]:
        """Dashboard için tüm sembollerin güncel çapraz borsa fiyat farkı tablosu."""
        syms = symbols or list(self.quotes.keys())
        rows = []
        for s in syms:
            ev = self.evaluate_symbol(s)
            if ev:
                rows.append(ev)
        return rows
