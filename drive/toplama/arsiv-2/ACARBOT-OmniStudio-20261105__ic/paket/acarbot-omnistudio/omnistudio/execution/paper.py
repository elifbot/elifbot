"""PAPER icra motoru — gerçek piyasa verisiyle sanal defter.

NE YAPAR
  Gerçek canlı fiyat/makas/tick verisini kullanarak emir dolumunu simüle eder,
  pozisyon açar/kapatır, ücret ve PnL muhasebesi yapar.

NE YAPMAZ
  Borsaya HİÇBİR emir göndermez. Ağ üzerinden yazma işlemi yapan hiçbir kod
  yolu bu sınıfta yoktur. `live_guard.py` ayrıca LIVE modunu kilitler.

GERÇEKÇİLİK SINIRLARI (raporda açıkça yazılır)
  * Maker dolumu iyimser olabilir: gerçek kuyruk önceliği bilinmez.
    Bu yüzden `require_trade_through` varsayılan AÇIK: fiyat seviyemi
    geçmeli ki dolum sayılsın (yalnız dokunma yetmez).
  * Kısmi dolum mevcut likiditeye göre sınırlanır.
  * Funding yalnız gözlenirse uygulanır; uydurulmaz.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..core.clock import get_logger, now_ms
from ..core.types import (Order, OrderState, Position, Quote, Side, Tick)
from ..risk.manager import RiskManager, SizingPlan

log = get_logger("exec.paper")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class PaperConfig:
    maker_timeout_sec: float = 20.0
    require_trade_through: bool = True   # maker: fiyat seviyeyi geçmeli
    max_fill_ratio_per_tick: float = 0.25  # tick hacminin en çok %25'i
    taker_slippage_bps: float = 3.0
    allow_taker_entry: bool = False      # maker_only politikasıyla uyumlu
    exit_as_taker: bool = True           # çıkışlar gerçekçi biçimde taker
    max_pending_orders: int = 32


@dataclass
class FillEvent:
    order_id: str
    symbol: str
    qty: float
    price: float
    is_maker: bool
    fee: float
    ts_ms: int


class PaperExecutor:
    """Sanal emir defteri + pozisyon yönetimi. Gerçek veri, sıfır gerçek emir."""

    def __init__(self, risk: RiskManager, config: PaperConfig | None = None) -> None:
        self.cfg = config or PaperConfig()
        self.risk = risk
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}
        self.closed: list[Position] = []
        self.fills: list[FillEvent] = []
        self.marks: dict[str, float] = {}
        self.quotes: dict[str, Quote] = {}
        self.stats = {
            "intents": 0, "submitted": 0, "filled": 0, "partial": 0,
            "expired": 0, "cancelled": 0, "rejected": 0,
            "maker_fills": 0, "taker_fills": 0,
            "positions_opened": 0, "positions_closed": 0,
        }

    # ---------- piyasa ----------
    def on_quote(self, q: Quote) -> None:
        self.quotes[q.symbol] = q
        self.marks[q.symbol] = q.mid

    def on_tick(self, t: Tick) -> None:
        self.marks[t.symbol] = t.price
        self._try_fill(t)

    # ---------- emir ----------
    def submit_entry(self, symbol: str, exchange: str, side: Side,
                     plan: SizingPlan, signal_id: str = "",
                     bar_key: str = "", ts_ms: int | None = None) -> Order | None:
        ts = ts_ms if ts_ms is not None else now_ms()
        self.stats["intents"] += 1
        if sum(1 for o in self.orders.values() if not o.is_terminal) >= self.cfg.max_pending_orders:
            self.stats["rejected"] += 1
            return None
        q = self.quotes.get(symbol)
        if q is None:
            self.stats["rejected"] += 1
            log.debug("%s için quote yok; emir reddedildi", symbol)
            return None
        # Maker: LONG alışta bid'e, SHORT satışta ask'a pasif yazılır.
        limit = q.bid if side is Side.LONG else q.ask
        o = Order(
            order_id=_id("ord"), intent_id=_id("int"), exchange=exchange,
            symbol=symbol, side=side, qty=plan.qty, limit_price=limit,
            is_maker=True, state=OrderState.PENDING, created_ms=ts,
            updated_ms=ts, closed_bar_key=bar_key,
        )
        self.orders[o.order_id] = o
        # niyet metadata'sı
        o.meta["plan"] = plan
        o.meta["signal_id"] = signal_id
        self.stats["submitted"] += 1
        o.state = OrderState.OPEN
        return o

    def _try_fill(self, t: Tick) -> None:
        for o in list(self.orders.values()):
            if o.is_terminal or o.symbol != t.symbol or o.limit_price is None:
                continue
            # süresi dolan pasif emir
            if (t.ts_ms - o.created_ms) / 1000.0 > self.cfg.maker_timeout_sec:
                o.state = OrderState.EXPIRED
                o.updated_ms = t.ts_ms
                o.reason = "maker_timeout_unfilled"
                self.stats["expired"] += 1
                continue
            lp = o.limit_price
            if o.side is Side.LONG:
                # alış: işlemler limitin ALTINDAN geçmeli
                ok = t.price < lp if self.cfg.require_trade_through else t.price <= lp
            else:
                ok = t.price > lp if self.cfg.require_trade_through else t.price >= lp
            if not ok:
                continue
            qty = min(o.remaining, t.qty * self.cfg.max_fill_ratio_per_tick)
            if qty <= 0:
                continue
            self._apply_fill(o, qty, lp, True, t.ts_ms)

    def _apply_fill(self, o: Order, qty: float, price: float,
                    is_maker: bool, ts_ms: int) -> None:
        fee = self.risk.fee(qty * price, is_maker)
        prev_qty = o.filled_qty
        prev_cost = prev_qty * o.avg_fill_price
        o.filled_qty += qty
        o.avg_fill_price = (prev_cost + qty * price) / o.filled_qty
        o.fee_paid += fee
        o.updated_ms = ts_ms
        o.state = (OrderState.FILLED if o.remaining <= 1e-12 else OrderState.PARTIAL)
        self.stats["partial" if o.state is OrderState.PARTIAL else "filled"] += 1
        self.stats["maker_fills" if is_maker else "taker_fills"] += 1
        self.fills.append(FillEvent(o.order_id, o.symbol, qty, price, is_maker, fee, ts_ms))

        plan: SizingPlan | None = o.meta.get("plan")
        if plan is not None:
            self._open_or_extend(o, plan, ts_ms)
        else:
            self._reduce(o, qty, price, fee, ts_ms, o.meta.get("exit_reason", "MANUAL"))

    def _open_or_extend(self, o: Order, plan: SizingPlan, ts_ms: int) -> None:
        existing = next((p for p in self.positions.values()
                         if p.symbol == o.symbol and p.is_open
                         and p.meta.get("entry_order") == o.order_id), None)
        if existing is None:
            p = Position(
                position_id=_id("pos"), exchange=o.exchange, symbol=o.symbol,
                side=o.side, qty=o.filled_qty, entry_price=o.avg_fill_price,
                entry_ms=ts_ms, entry_fee=o.fee_paid,
                stop_price=plan.stop_price, take_profit_price=plan.take_profit_price,
                signal_id=o.meta.get("signal_id", ""), peak_price=o.avg_fill_price,
            )
            p.meta["entry_order"] = o.order_id
            self.positions[p.position_id] = p
            self.stats["positions_opened"] += 1
            log.info("PAPER AÇILIŞ %s %s qty=%.6f @%.6f stop=%.6f tp=%.6f",
                     p.symbol, p.side.value, p.qty, p.entry_price,
                     p.stop_price, p.take_profit_price)
        else:
            existing.qty = o.filled_qty
            existing.entry_price = o.avg_fill_price
            existing.entry_fee = o.fee_paid

    def _reduce(self, o: Order, qty: float, price: float, fee: float,
                ts_ms: int, reason: str) -> None:
        pid = o.meta.get("position_id", "")
        p = self.positions.get(pid)
        if p is None or not p.is_open:
            return
        take = min(qty, p.qty)
        gross = (price - p.entry_price) * take * p.side.sign
        entry_fee_share = p.entry_fee * (take / p.qty if p.qty > 0 else 1.0)
        net = gross - entry_fee_share - fee - p.funding_paid
        p.qty -= take
        p.exit_price = price
        p.exit_fee += fee
        if p.qty <= 1e-12:
            p.qty = 0.0
            p.closed_ms = ts_ms
            p.exit_reason = reason
            p.realized_net = net
            self.closed.append(p)
            self.risk.state.record_close(net, entry_fee_share + fee, p.funding_paid)
            self.stats["positions_closed"] += 1
            log.info("PAPER KAPANIŞ %s %s net=%+.6f USDT neden=%s",
                     p.symbol, p.side.value, net, reason)
        else:
            self.risk.state.realized_net += net
            self.risk.state.equity += net
            p.entry_fee -= entry_fee_share

    # ---------- çıkış ----------
    def close_position(self, p: Position, reason: str,
                       ts_ms: int | None = None) -> None:
        ts = ts_ms if ts_ms is not None else now_ms()
        mark = self.marks.get(p.symbol, p.entry_price)
        q = self.quotes.get(p.symbol)
        if q is not None:
            mark = q.bid if p.side is Side.LONG else q.ask
        slip = self.cfg.taker_slippage_bps / 10_000.0
        px = mark * (1.0 - slip * p.side.sign)
        fee = self.risk.fee(p.qty * px, is_maker=False)
        o = Order(
            order_id=_id("exit"), intent_id=_id("int"), exchange=p.exchange,
            symbol=p.symbol, side=p.side.opposite, qty=p.qty, limit_price=None,
            is_maker=False, state=OrderState.OPEN, created_ms=ts, updated_ms=ts,
            reason=reason,
        )
        o.meta["position_id"] = p.position_id
        o.meta["exit_reason"] = reason
        self.orders[o.order_id] = o
        self._apply_fill(o, p.qty, px, False, ts)
        if o.remaining <= 1e-12:
            o.state = OrderState.FILLED

    def manage_open(self, ts_ms: int | None = None,
                    atr_by_symbol: dict[str, float] | None = None) -> list[str]:
        """Tüm açık pozisyonları risk yöneticisiyle günceller, gerekeni kapatır."""
        ts = ts_ms if ts_ms is not None else now_ms()
        atrs = atr_by_symbol or {}
        closed_ids: list[str] = []
        open_now = [p for p in self.positions.values() if p.is_open]
        self.risk.update_breaker(open_now, self.marks)
        for p in open_now:
            mark = self.marks.get(p.symbol)
            if mark is None or mark <= 0:
                continue
            reason = self.risk.manage(p, mark, ts, atrs.get(p.symbol))
            if reason:
                self.close_position(p, reason, ts)
                closed_ids.append(p.position_id)
        return closed_ids

    def apply_funding(self, symbol: str, rate: float, ts_ms: int) -> float:
        """Gerçek funding oranı gözlemlendiğinde açık pozisyonlara uygular."""
        total = 0.0
        mark = self.marks.get(symbol, 0.0)
        if mark <= 0 or rate == 0:
            return 0.0
        for p in self.positions.values():
            if p.symbol != symbol or not p.is_open:
                continue
            # LONG pozitif funding öder, SHORT alır
            cost = p.qty * mark * rate * p.side.sign
            p.funding_paid += cost
            total += cost
        return total

    # ---------- görünümler ----------
    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.is_open]

    def equity_snapshot(self) -> dict[str, Any]:
        unreal = sum(p.unrealized(self.marks.get(p.symbol, p.entry_price))
                     for p in self.open_positions)
        st = self.risk.state
        return {
            "realized_equity": round(st.equity, 6),
            "unrealized": round(unreal, 6),
            "total_equity": round(st.equity + unreal, 6),
            "open_positions": len(self.open_positions),
            "note": ("total_equity açık unrealized içerir; GERÇEKLEŞMİŞ kâr "
                     "değildir. Çıkış ücretleri düşülmemiştir."),
        }

    def summary(self) -> dict[str, Any]:
        reasons: dict[str, int] = {}
        for p in self.closed:
            reasons[p.exit_reason] = reasons.get(p.exit_reason, 0) + 1
        net = sum(p.realized_net or 0.0 for p in self.closed)
        holds = [(p.closed_ms - p.entry_ms) / 1000.0
                 for p in self.closed if p.closed_ms]
        return {
            "mode": "PAPER",
            "real_orders_sent_to_exchange": 0,
            "stats": dict(self.stats),
            "closed_trades": len(self.closed),
            "closed_net_total": round(net, 6),
            "exit_reasons": reasons,
            "mean_hold_sec": round(sum(holds) / len(holds), 3) if holds else 0.0,
            "open_positions": [p.to_dict() for p in self.open_positions],
            "risk": self.risk.state.summary(),
            "equity": self.equity_snapshot(),
        }