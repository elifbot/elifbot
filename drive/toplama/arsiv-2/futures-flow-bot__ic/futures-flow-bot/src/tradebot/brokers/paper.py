"""Paper (sanal) broker: GERCEK veri akisi, SANAL emirler.

Dolum modeli (muhafazakar):
 - maker giris: limit fiyat, fiyat limitin ICINDEN gecerse dolar (dokunmak yetmez). Timeout'ta iptal.
 - stop: tetiklenince stop fiyatindan (veya daha kotu gap fiyatindan) kayma ile taker olarak kapanir.
 - cikis: taker (kayma + taker komisyonu).
 - funding simule edilmez (v1).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Config, ExchangeCfg
from ..models import AccountView, EntryPlan, Position, Side
from .base import Broker, EventCb


@dataclass
class _Pending:
    plan: EntryPlan
    expires: float


class PaperBroker(Broker):
    def __init__(self, exchange: str, cfg: Config, ex_cfg: ExchangeCfg, on_event: EventCb):
        self.exchange = exchange
        self.cfg = cfg
        self.fees = ex_cfg
        self.on_event = on_event
        self.cash = ex_cfg.paper_balance_usd
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, _Pending] = {}
        self.last_price: dict[str, float] = {}
        self._day: int | None = None
        self.realized_today = 0.0

    # ---- hesap
    def _gross(self, pos: Position, price: float) -> float:
        return (price - pos.entry_price) * pos.qty * pos.side.sign

    def account(self) -> AccountView:
        unreal = sum(self._gross(p, self.last_price.get(p.symbol, p.entry_price)) for p in self.positions.values())
        locked = sum(p.margin for p in self.positions.values()) + sum(o.plan.margin for o in self.pending.values())
        return AccountView(equity=self.cash + unreal, available=self.cash - locked,
                           open_positions=len(self.positions), pending=len(self.pending),
                           realized_today=self.realized_today)

    def unrealized(self, pos: Position, price: float) -> float:
        est_exit_fee = pos.qty * price * self.fees.taker_fee
        return self._gross(pos, price) - pos.entry_fee - est_exit_fee

    def has_pending(self, symbol: str) -> bool:
        return symbol in self.pending

    # ---- emirler
    async def place_entry(self, plan: EntryPlan, now: float) -> bool:
        if plan.symbol in self.positions or plan.symbol in self.pending:
            return False
        if self.cfg.entry_order.mode == "taker":
            slip = self.cfg.paper.slippage_pct / 100
            px = plan.price * (1 + plan.side.sign * slip)
            self._open(plan, px, now, self.fees.taker_fee, "taker")
        else:
            self.pending[plan.symbol] = _Pending(plan, now + self.cfg.entry_order.timeout_sec)
        return True

    def _open(self, plan: EntryPlan, fill: float, ts: float, fee_rate: float, kind: str) -> None:
        qty = plan.notional / fill
        fee = plan.notional * fee_rate
        self.cash -= fee
        stop = fill * (1 - plan.side.sign * plan.stop_dist)
        pos = Position(exchange=self.exchange, symbol=plan.symbol, side=plan.side, entry_price=fill, qty=qty,
                       notional=plan.notional, margin=plan.margin, stop_price=stop, opened_ts=ts,
                       entry_fee=fee, entry_reasons=list(plan.signal.reasons), score=plan.signal.score)
        self.positions[plan.symbol] = pos
        self.on_event("entry", {"exchange": self.exchange, "symbol": plan.symbol, "side": plan.side.value,
                                "price": fill, "fill": kind, "stop": stop, "ts": ts,
                                "reasons": pos.entry_reasons})

    def _close(self, pos: Position, px: float, ts: float, reason: str, detail: list[str] | None = None) -> None:
        gross = self._gross(pos, px)
        fee = pos.qty * px * self.fees.taker_fee
        self.cash += gross - fee
        net = gross - fee - pos.entry_fee
        day = int(ts // 86400)
        if self._day != day:
            self._day, self.realized_today = day, 0.0
        self.realized_today += net
        self.positions.pop(pos.symbol, None)
        self.on_event("exit", {
            "exchange": self.exchange, "symbol": pos.symbol, "side": pos.side.value, "opened_ts": pos.opened_ts,
            "closed_ts": ts, "entry": pos.entry_price, "exit": px, "notional": pos.notional,
            "pnl_gross": gross, "fees": fee + pos.entry_fee, "pnl_net": net, "reason": reason,
            "entry_reasons": pos.entry_reasons, "exit_reasons": detail or [], "score": pos.score})

    async def close_position(self, pos: Position, reason: str, now: float, price: float,
                             detail: list[str] | None = None) -> None:
        if pos.symbol not in self.positions:
            return
        slip = self.cfg.paper.slippage_pct / 100
        self._close(pos, price * (1 - pos.side.sign * slip), now, reason, detail)

    async def update_stop(self, pos: Position, new_stop: float) -> None:
        # stop sadece lehe cekilir
        if (pos.side is Side.LONG and new_stop > pos.stop_price) or (pos.side is Side.SHORT and new_stop < pos.stop_price):
            pos.stop_price = new_stop

    # ---- akis
    def on_trade(self, t) -> None:
        sym, p = t.symbol, t.price
        self.last_price[sym] = p
        o = self.pending.get(sym)
        if o is not None:
            plan = o.plan
            if (plan.side is Side.LONG and p < plan.price) or (plan.side is Side.SHORT and p > plan.price):
                del self.pending[sym]
                self._open(plan, plan.price, t.ts, self.fees.maker_fee, "maker")
        pos = self.positions.get(sym)
        if pos is not None:
            hit = (pos.side is Side.LONG and p <= pos.stop_price) or (pos.side is Side.SHORT and p >= pos.stop_price)
            if hit:
                slip = self.cfg.paper.stop_slippage_pct / 100
                base = min(pos.stop_price, p) if pos.side is Side.LONG else max(pos.stop_price, p)
                self._close(pos, base * (1 - pos.side.sign * slip), t.ts, "stop")

    async def tick(self, now: float) -> None:
        for sym, o in list(self.pending.items()):
            if now >= o.expires:
                del self.pending[sym]
                self.on_event("entry_cancel", {"exchange": self.exchange, "symbol": sym, "ts": now})
