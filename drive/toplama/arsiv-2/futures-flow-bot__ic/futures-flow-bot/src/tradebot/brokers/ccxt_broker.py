"""Gercek emir katmani (CCXT): Binance USDT-M ve OKX swap.

!!! UYARI !!!  Bu dosya gercek borsaya karsi YAZILDI ama TEST EDILMEDI (gelistirme ortaminda ag yoktu).
Once testnet/demo ile dogrulayin:
  - Binance Futures Testnet ve OKX Demo Trading icin ayri API anahtari olusturun.
  - mode: testnet ile en az birkac gun calistirin; emir/stop/pozisyon davranisini borsa arayuzunden kontrol edin.
Varsayimlar: tek yonlu (one-way/net) pozisyon modu, isolated marjin, USDT-marjinli surekli kontratlar.
Guvenlik: stop emri YERLESTIRILEMEZSE pozisyon hemen piyasa emriyle kapatilir ve bot elle devam gerektiren
duraklamaya alinir. Giris maker (post-only); cikis taker (piyasa, reduceOnly). Stop: borsada duran stop-market.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from ..config import Config, ExchangeCfg
from ..models import AccountView, EntryPlan, Position, Side
from ..safety import SafetyMonitor
from .base import Broker

log = logging.getLogger("ccxt")


class CcxtBroker(Broker):
    def __init__(self, exchange: str, cfg: Config, ex_cfg: ExchangeCfg, safety: SafetyMonitor, sandbox: bool):
        try:
            import ccxt.async_support as ccxt
        except ImportError as e:
            raise RuntimeError("testnet/live icin `pip install ccxt` gerekli") from e
        self.ccxt = ccxt
        self.exchange = exchange
        self.cfg, self.fees, self.safety = cfg, ex_cfg, safety
        self.on_event = lambda k, p: None
        up = exchange.upper()
        key, secret = os.getenv(f"{up}_API_KEY", ""), os.getenv(f"{up}_API_SECRET", "")
        if not key or not secret:
            raise RuntimeError(f"{up}_API_KEY / {up}_API_SECRET ortam degiskenleri bos")
        params = {"apiKey": key, "secret": secret, "enableRateLimit": True, "options": {"defaultType": "swap"}}
        if exchange == "okx":
            params["password"] = os.getenv("OKX_API_PASSPHRASE", "")
        self.ex = (ccxt.binanceusdm if exchange == "binance" else ccxt.okx)(params)
        if sandbox:
            self.ex.set_sandbox_mode(True)
        self.positions: dict[str, Position] = {}
        self._pending: set[str] = set()
        self._lev_set: set[str] = set()
        self._equity = 0.0
        self._free = 0.0
        self._realized_today = 0.0
        self._day: int | None = None
        self._last_bal = 0.0
        self._last_recon = 0.0

    # ---- yardimcilar
    def _alert(self, msg: str) -> None:
        self.on_event("alert", {"msg": f"[{self.exchange}] {msg}"})

    def _err(self, e: Exception, ctx: str) -> None:
        log.warning("%s %s: %s %s", self.exchange, ctx, type(e).__name__, str(e)[:200])
        for m in self.safety.api_error(self.exchange, time.time(), type(e).__name__):
            self._alert(m)

    def _params(self, extra: dict | None = None) -> dict:
        p = dict(extra or {})
        if self.exchange == "okx":
            p["tdMode"] = "isolated"
        return p

    async def _refresh_balance(self) -> None:
        bal = await self.ex.fetch_balance()
        u = bal.get("USDT", {})
        self._equity = float(u.get("total") or 0.0)
        self._free = float(u.get("free") or 0.0)
        self._last_bal = time.time()
        self.safety.api_ok(self.exchange)

    async def _open_exchange_symbols(self) -> dict[str, float]:
        out = {}
        for p in await self.ex.fetch_positions():
            c = abs(float(p.get("contracts") or 0.0))
            if c > 0:
                out[p["symbol"]] = c
        return out

    async def startup(self) -> None:
        await self.ex.load_markets()
        await self._refresh_balance()
        foreign = await self._open_exchange_symbols()
        if foreign:
            self._alert(self.safety.halt("*", "foreign_positions",
                                         f"{self.exchange} hesabinda zaten acik pozisyon var: {sorted(foreign)}. "
                                         "Kapatin veya bot icin bos bir alt hesap kullanin.", manual=True))

    # ---- hesap
    def account(self) -> AccountView:
        pend = len(self._pending) * self.cfg.risk.margin_per_trade_usd
        return AccountView(equity=self._equity, available=self._free - pend, open_positions=len(self.positions),
                           pending=len(self._pending), realized_today=self._realized_today)

    def unrealized(self, pos: Position, price: float) -> float:
        gross = (price - pos.entry_price) * pos.qty * pos.side.sign
        return gross - pos.entry_fee - pos.qty * price * self.fees.taker_fee

    def has_pending(self, symbol: str) -> bool:
        return symbol in self._pending

    async def _ensure_leverage(self, sym: str) -> None:
        if sym in self._lev_set:
            return
        lev = self.cfg.risk.leverage
        try:
            if self.exchange == "binance":
                try:
                    await self.ex.set_margin_mode("isolated", sym)
                except Exception as e:  # noqa: BLE001
                    if "No need to change" not in str(e):
                        raise
                await self.ex.set_leverage(lev, sym)
            else:
                await self.ex.set_leverage(lev, sym, params={"mgnMode": "isolated"})
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"kaldirac/marjin modu ayarlanamadi: {e}") from e
        self._lev_set.add(sym)

    # ---- giris
    async def place_entry(self, plan: EntryPlan, now: float) -> bool:
        sym = plan.symbol
        if sym in self.positions or sym in self._pending:
            return False
        self._pending.add(sym)
        try:
            m = self.ex.market(sym)
            cs = float(m.get("contractSize") or 1.0)
            amount = float(self.ex.amount_to_precision(sym, plan.notional / plan.price / cs))
            lim = m.get("limits", {})
            min_amt = (lim.get("amount") or {}).get("min")
            min_cost = (lim.get("cost") or {}).get("min")
            if amount <= 0 or (min_amt and amount < min_amt) or (min_cost and amount * plan.price * cs < min_cost):
                return False
            await self._ensure_leverage(sym)
            side = "buy" if plan.side is Side.LONG else "sell"
            price = float(self.ex.price_to_precision(sym, plan.price))
            try:
                order = await self.ex.create_order(sym, "limit", side, amount, price, self._params({"postOnly": True}))
            except getattr(self.ccxt, "OrderImmediatelyFillable", ()):  # post-only reddi: hata degil
                return False
            self.safety.api_ok(self.exchange)
            oid, filled, avg, status = order["id"], 0.0, price, order.get("status")
            deadline = time.monotonic() + self.cfg.entry_order.timeout_sec
            while status not in ("closed", "canceled", "rejected", "expired") and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                o = await self.ex.fetch_order(oid, sym)
                status, filled, avg = o.get("status"), float(o.get("filled") or 0), float(o.get("average") or price)
            if status != "closed":
                try:
                    await self.ex.cancel_order(oid, sym)
                except Exception:  # noqa: BLE001 - zaten dolmus/iptal olabilir
                    pass
                o = await self.ex.fetch_order(oid, sym)
                filled, avg = float(o.get("filled") or 0), float(o.get("average") or price)
            if filled <= 0:
                self.on_event("entry_cancel", {"exchange": self.exchange, "symbol": sym, "ts": now})
                return True   # istek gecerliydi, dolmadi
            qty = filled * cs
            notional = qty * avg
            pos = Position(exchange=self.exchange, symbol=sym, side=plan.side, entry_price=avg, qty=qty,
                           notional=notional, margin=notional / plan.leverage,
                           stop_price=avg * (1 - plan.side.sign * plan.stop_dist), opened_ts=time.time(),
                           entry_fee=notional * self.fees.maker_fee, entry_reasons=list(plan.signal.reasons),
                           score=plan.signal.score, order_amount=filled)
            self.positions[sym] = pos
            self.on_event("entry", {"exchange": self.exchange, "symbol": sym, "side": plan.side.value,
                                    "price": avg, "fill": "maker", "stop": pos.stop_price, "ts": pos.opened_ts,
                                    "reasons": pos.entry_reasons})
            await self._place_stop(pos)
            return True
        except Exception as e:  # noqa: BLE001
            self._err(e, "place_entry")
            return False
        finally:
            self._pending.discard(sym)

    async def _place_stop(self, pos: Position) -> None:
        side = "sell" if pos.side is Side.LONG else "buy"
        px = float(self.ex.price_to_precision(pos.symbol, pos.stop_price))
        try:
            o = await self.ex.create_order(pos.symbol, "market", side, pos.order_amount, None,
                                           self._params({"stopLossPrice": px, "reduceOnly": True}))
            pos.stop_order_id = o["id"]
        except Exception as e:  # noqa: BLE001
            self._alert(f"STOP EMRI KOYULAMADI ({pos.symbol}): {type(e).__name__}. Pozisyon kapatiliyor.")
            await self._emergency_close(pos)
            self._alert(self.safety.halt("*", "stop_failed", f"{pos.symbol} icin stop emri konulamadi", manual=True))

    async def _market_close(self, pos: Position) -> float:
        side = "sell" if pos.side is Side.LONG else "buy"
        o = await self.ex.create_order(pos.symbol, "market", side, pos.order_amount, None,
                                       self._params({"reduceOnly": True}))
        return float(o.get("average") or o.get("price") or pos.entry_price)

    async def _emergency_close(self, pos: Position) -> None:
        try:
            px = await self._market_close(pos)
            self._record_exit(pos, px, "emergency_close", [])
        except Exception as e:  # noqa: BLE001
            self._alert(f"ACIL KAPATMA BASARISIZ ({pos.symbol}): {type(e).__name__} - ELLE MUDAHALE EDIN")

    def _record_exit(self, pos: Position, px: float, reason: str, detail: list[str]) -> None:
        gross = (px - pos.entry_price) * pos.qty * pos.side.sign
        fee = pos.qty * px * self.fees.taker_fee
        net = gross - fee - pos.entry_fee
        now = time.time()
        day = int(now // 86400)
        if self._day != day:
            self._day, self._realized_today = day, 0.0
        self._realized_today += net
        self.positions.pop(pos.symbol, None)
        self.on_event("exit", {"exchange": self.exchange, "symbol": pos.symbol, "side": pos.side.value,
                               "opened_ts": pos.opened_ts, "closed_ts": now, "entry": pos.entry_price, "exit": px,
                               "notional": pos.notional, "pnl_gross": gross, "fees": fee + pos.entry_fee,
                               "pnl_net": net, "reason": reason, "entry_reasons": pos.entry_reasons,
                               "exit_reasons": detail, "score": pos.score})

    # ---- cikis / stop guncelleme
    async def close_position(self, pos: Position, reason: str, now: float, price: float,
                             detail: list[str] | None = None) -> None:
        if pos.symbol not in self.positions:
            return
        try:
            if pos.stop_order_id:
                try:
                    await self.ex.cancel_order(pos.stop_order_id, pos.symbol, self._params())
                except Exception:  # noqa: BLE001 - stop zaten tetiklenmis olabilir
                    pass
            px = await self._market_close(pos)
            self._record_exit(pos, px, reason, detail or [])
            self.safety.api_ok(self.exchange)
        except Exception as e:  # noqa: BLE001
            self._err(e, "close_position")

    async def update_stop(self, pos: Position, new_stop: float) -> None:
        better = (pos.side is Side.LONG and new_stop > pos.stop_price) or (pos.side is Side.SHORT and new_stop < pos.stop_price)
        if not better:
            return
        old_id = pos.stop_order_id
        pos.stop_price = new_stop
        await self._place_stop(pos)            # once yenisini koy, sonra eskisini iptal et (korumasiz kalma)
        if old_id and pos.symbol in self.positions:
            try:
                await self.ex.cancel_order(old_id, pos.symbol, self._params())
            except Exception:  # noqa: BLE001
                pass

    # ---- periyodik: bakiye + mutabakat
    async def tick(self, now: float) -> None:
        t = time.time()
        try:
            if t - self._last_bal >= 10:
                await self._refresh_balance()
            if t - self._last_recon >= 30:
                self._last_recon = t
                exch = await self._open_exchange_symbols()
                for sym, pos in list(self.positions.items()):
                    if sym not in exch:        # borsada kapanmis: buyuk olasilikla stop tetiklendi
                        self._record_exit(pos, pos.stop_price, "stop_exchange", ["mutabakat: borsada pozisyon yok"])
                unknown = set(exch) - set(self.positions) - self._pending
                if unknown and ("*", "recon") not in self.safety.halts:
                    self._alert(self.safety.halt("*", "recon", f"botun bilmedigi acik pozisyon: {sorted(unknown)}",
                                                 manual=True))
        except Exception as e:  # noqa: BLE001
            self._err(e, "tick")
