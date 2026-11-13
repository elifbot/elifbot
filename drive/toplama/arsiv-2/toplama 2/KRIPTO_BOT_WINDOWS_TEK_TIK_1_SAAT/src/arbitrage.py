"""Borsalar Arası (Binance ↔ OKX) Çapraz Fiyat Farkı & Paper Arbitraj Motoru."""
from __future__ import annotations

import time
from collections import deque
from typing import Any


class ArbitrageEngine:
    """İki borsa arasındaki anlık bid/ask makasını tarar; canlı modda emir göndermez."""

    def __init__(
        self,
        min_net_spread_pct: float = 0.08,
        fee_per_leg_pct: float = 0.05,
        trade_notional_usdt: float = 1000.0,
        cooldown_sec: float = 10.0,
        max_quote_age_sec: float = 10.0,
        enabled: bool = True,
        state_store: Any | None = None,
    ):
        self.min_net_spread_pct = float(min_net_spread_pct)
        self.fee_per_leg_pct = float(fee_per_leg_pct)
        self.trade_notional_usdt = float(trade_notional_usdt)
        self.cooldown_sec = float(cooldown_sec)
        self.max_quote_age_sec = float(max_quote_age_sec)
        self.enabled = bool(enabled)
        self.state_store = state_store

        # quotes[symbol][exchange] = {"bid": float, "ask": float, "ts": float}
        self.quotes: dict[str, dict[str, dict]] = {}
        self._last_exec: dict[str, float] = {}
        self._live_warning_sent = False
        self.history: deque[dict] = deque(maxlen=200)
        self.total_profit_usdt: float = 0.0
        self.total_trades: int = 0

    def update_quote(
        self,
        exchange: str,
        symbol: str,
        bid: float,
        ask: float,
        ts: float | None = None,
    ) -> None:
        if bid <= 0 or ask <= 0:
            return
        sym_map = self.quotes.setdefault(symbol, {})
        sym_map[exchange.lower()] = {
            "bid": float(bid),
            "ask": float(ask),
            "ts": float(ts if ts is not None else time.time()),
        }

    def _best_pair(self, symbol: str, now: float | None = None) -> dict | None:
        sym_map = self.quotes.get(symbol)
        if not sym_map or len(sym_map) < 2:
            return None
        now_ts = float(now if now is not None else time.time())
        fresh = {
            ex: q
            for ex, q in sym_map.items()
            if (now_ts - float(q.get("ts", 0.0))) <= self.max_quote_age_sec
            and q.get("bid", 0.0) > 0
            and q.get("ask", 0.0) > 0
        }
        if len(fresh) < 2:
            return None

        best: dict | None = None
        for buy_ex, bq in fresh.items():
            for sell_ex, sq in fresh.items():
                if buy_ex == sell_ex:
                    continue
                buy_px = float(bq["ask"])
                sell_px = float(sq["bid"])
                if buy_px <= 0:
                    continue
                gross_pct = (sell_px - buy_px) / buy_px * 100.0
                net_pct = gross_pct - (2.0 * self.fee_per_leg_pct)
                if best is None or net_pct > best["net_spread_pct"]:
                    best = {
                        "symbol": symbol,
                        "buy_exchange": buy_ex,
                        "sell_exchange": sell_ex,
                        "buy_price": round(buy_px, 6),
                        "sell_price": round(sell_px, 6),
                        "gross_spread_pct": round(gross_pct, 4),
                        "net_spread_pct": round(net_pct, 4),
                        "opportunity": net_pct >= self.min_net_spread_pct,
                    }
        return best

    def check_opportunity(self, symbol: str) -> dict | None:
        if not self.enabled:
            return None
        now = time.time()
        if (now - self._last_exec.get(symbol, 0.0)) < self.cooldown_sec:
            return None
        best = self._best_pair(symbol, now=now)
        if best is None or best["net_spread_pct"] < self.min_net_spread_pct:
            return None
        return best

    def scan_all(self, symbols: list[str] | None = None) -> list[dict]:
        targets = symbols if symbols is not None else list(self.quotes.keys())
        rows: list[dict] = []
        now = time.time()
        for sym in targets:
            best = self._best_pair(sym, now=now)
            if best is not None:
                rows.append(best)
        rows.sort(key=lambda r: r["net_spread_pct"], reverse=True)
        return rows

    async def execute_arbitrage(
        self, opp: dict, broker: Any | None = None, alert: Any | None = None
    ) -> dict:
        symbol = str(opp["symbol"])
        buy_px = float(opp["buy_price"])
        net_pct = float(opp["net_spread_pct"])
        qty = self.trade_notional_usdt / buy_px if buy_px > 0 else 0.0
        profit_usdt = self.trade_notional_usdt * (net_pct / 100.0)

        if broker is not None:
            if getattr(broker, "mode", "paper") == "paper":
                # Paper modda tahmini net arbitraj kârını kasaya yansıt.
                broker.paper.balance += profit_usdt
            else:
                # İki bacaklı canlı arbitraj; bakiye/envanter kontrolü, bacağın
                # biri dolmazsa hedge, gerçek doluluk ve transfer maliyeti olmadan
                # "delta-nötr garantili kâr" değildir. Güvenli varsayılan: emir yok.
                record = {
                    **opp,
                    "qty": round(qty, 6),
                    "profit_usdt": 0.0,
                    "executed_at": time.time(),
                    "status": "DISABLED_LIVE",
                }
                if not self._live_warning_sent:
                    self._live_warning_sent = True
                    msg = (
                        "🛡️ Canlı/testnet arbitraj emirleri güvenlik nedeniyle kapalı: "
                        "iki bacaklı doluluk ve envanter mutabakatı henüz yok. "
                        "Yalnızca fiyat taraması ve paper simülasyonu aktif."
                    )
                    print(msg, flush=True)
                    if alert:
                        try:
                            await alert(msg)
                        except Exception:
                            pass
                return record

        record = {
            **opp,
            "qty": round(qty, 6),
            "profit_usdt": round(profit_usdt, 4),
            "executed_at": time.time(),
            "status": "PAPER_FILLED",
        }
        self._last_exec[symbol] = record["executed_at"]
        self.total_profit_usdt = round(self.total_profit_usdt + profit_usdt, 4)
        self.total_trades += 1
        self.history.append(record)
        if self.state_store is not None:
            try:
                self.state_store.record_arbitrage(record)
            except Exception:
                pass
        return record
