"""Risk yönetimi — pozisyon boyutu, stop/TP, portföy limitleri, devre kesici.

SINIRLAR (dürüstçe belirtilir)
  * Stop mesafesi MAKSİMUM ZARAR GARANTİSİ DEĞİLDİR. Gap, slippage, likidite
    boşluğu ve gelecekteki ücretler hariçtir.
  * Korelasyon riski tam modellenmez; yalnız sembol ve yön bazlı kaba limit var.
  * Bu katman gerçek emir GÖNDERMEZ. PAPER'da sanal deftere yazar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.clock import mono
from ..core.types import GateResult, Position, Side


@dataclass
class RiskConfig:
    equity_start: float = 10_000.0
    risk_per_trade_pct: float = 0.35
    max_position_notional: float = 1_500.0
    min_position_notional: float = 25.0
    max_open_positions: int = 6
    max_positions_per_symbol: int = 1
    max_same_side_positions: int = 4
    max_gross_exposure: float = 6_000.0
    atr_stop_mult: float = 1.6
    atr_tp_mult: float = 2.6
    min_stop_pct: float = 0.25
    max_stop_pct: float = 3.0
    # kâr kilidi / iz süren stop
    breakeven_at_r: float = 0.9
    trail_start_r: float = 1.3
    trail_atr_mult: float = 1.1
    # süre
    max_hold_sec: float = 1_800.0
    # devre kesici
    daily_loss_limit_pct: float = 3.0
    max_consecutive_losses: int = 5
    cooldown_after_loss_sec: float = 120.0
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 5.0


@dataclass
class RiskState:
    equity: float = 10_000.0
    realized_net: float = 0.0
    fees_paid: float = 0.0
    funding_paid: float = 0.0
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    peak_equity: float = 10_000.0
    max_drawdown: float = 0.0
    breaker_tripped: bool = False
    breaker_reason: str = ""
    last_loss_mono: float = 0.0

    def record_close(self, net: float, fee: float, funding: float = 0.0) -> None:
        self.realized_net += net
        self.equity += net
        self.fees_paid += fee
        self.funding_paid += funding
        self.closed_trades += 1
        if net > 0:
            self.wins += 1
            self.consecutive_losses = 0
        elif net < 0:
            self.losses += 1
            self.consecutive_losses += 1
            self.last_loss_mono = mono()
        self.peak_equity = max(self.peak_equity, self.equity)
        dd = (self.peak_equity - self.equity)
        self.max_drawdown = max(self.max_drawdown, dd)

    def summary(self) -> dict[str, Any]:
        wr = (self.wins / self.closed_trades * 100.0) if self.closed_trades else 0.0
        return {
            "equity": round(self.equity, 6),
            "realized_net": round(self.realized_net, 6),
            "fees_paid": round(self.fees_paid, 6),
            "funding_paid": round(self.funding_paid, 6),
            "closed_trades": self.closed_trades, "wins": self.wins,
            "losses": self.losses, "win_rate_pct": round(wr, 2),
            "consecutive_losses": self.consecutive_losses,
            "max_drawdown": round(self.max_drawdown, 6),
            "breaker_tripped": self.breaker_tripped,
            "breaker_reason": self.breaker_reason,
        }


@dataclass
class SizingPlan:
    qty: float
    notional: float
    stop_price: float
    take_profit_price: float
    stop_distance: float
    risk_amount: float
    r_multiple: float


class RiskManager:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.cfg = config or RiskConfig()
        self.state = RiskState(equity=self.cfg.equity_start,
                               peak_equity=self.cfg.equity_start)

    # ---------- portföy kapıları ----------
    def check_portfolio(self, symbol: str, side: Side,
                        open_positions: list[Position]) -> list[GateResult]:
        cfg, st = self.cfg, self.state
        out: list[GateResult] = []

        def g(name: str, ok: bool, code: str, detail: str = "",
              v: float | None = None, t: float | None = None) -> None:
            out.append(GateResult(name, ok, code, detail, v, t))

        g("circuit_breaker", not st.breaker_tripped, "BREAKERS_TRIPPED",
          st.breaker_reason)
        if st.last_loss_mono:
            wait = cfg.cooldown_after_loss_sec - (mono() - st.last_loss_mono)
            g("loss_cooldown", wait <= 0, "LOSS_COOLDOWN",
              "Kayıp sonrası soğuma", max(0.0, wait), 0.0)
        g("max_open", len(open_positions) < cfg.max_open_positions,
          "MAX_OPEN_POSITIONS", "Açık pozisyon limiti",
          float(len(open_positions)), float(cfg.max_open_positions))
        same_sym = sum(1 for p in open_positions if p.symbol == symbol)
        g("per_symbol", same_sym < cfg.max_positions_per_symbol,
          "SYMBOL_ALREADY_OPEN", "Sembolde açık pozisyon var",
          float(same_sym), float(cfg.max_positions_per_symbol))
        same_side = sum(1 for p in open_positions if p.side is side)
        g("side_balance", same_side < cfg.max_same_side_positions,
          "SIDE_CONCENTRATION", "Aynı yönde yığılma",
          float(same_side), float(cfg.max_same_side_positions))
        gross = sum(p.entry_price * p.qty for p in open_positions)
        g("gross_exposure", gross < cfg.max_gross_exposure,
          "GROSS_EXPOSURE_LIMIT", "Brüt maruziyet limiti",
          gross, cfg.max_gross_exposure)
        return out

    def update_breaker(self, open_positions: list[Position],
                       marks: dict[str, float]) -> None:
        cfg, st = self.cfg, self.state
        if st.breaker_tripped:
            return
        unreal = sum(p.unrealized(marks.get(p.symbol, p.entry_price))
                     for p in open_positions)
        total_eq = st.equity + unreal
        day_loss_pct = (cfg.equity_start - total_eq) / cfg.equity_start * 100.0
        if day_loss_pct >= cfg.daily_loss_limit_pct:
            st.breaker_tripped = True
            st.breaker_reason = (f"Günlük zarar limiti: {day_loss_pct:.2f}% "
                                 f">= {cfg.daily_loss_limit_pct}%")
            return
        if st.consecutive_losses >= cfg.max_consecutive_losses:
            st.breaker_tripped = True
            st.breaker_reason = (f"Ardışık kayıp: {st.consecutive_losses} "
                                 f">= {cfg.max_consecutive_losses}")

    # ---------- boyut ve seviyeler ----------
    def plan(self, side: Side, price: float, atr_abs: float) -> SizingPlan | None:
        cfg, st = self.cfg, self.state
        if price <= 0 or atr_abs <= 0:
            return None
        dist = atr_abs * cfg.atr_stop_mult
        stop_pct = dist / price * 100.0
        if stop_pct < cfg.min_stop_pct:
            dist = price * cfg.min_stop_pct / 100.0
        elif stop_pct > cfg.max_stop_pct:
            dist = price * cfg.max_stop_pct / 100.0
        risk_amount = st.equity * cfg.risk_per_trade_pct / 100.0
        qty = risk_amount / dist if dist > 0 else 0.0
        notional = qty * price
        if notional > cfg.max_position_notional:
            qty = cfg.max_position_notional / price
            notional = qty * price
        if notional < cfg.min_position_notional:
            return None
        rr = cfg.atr_tp_mult / cfg.atr_stop_mult
        tp_dist = dist * rr
        stop = price - dist * side.sign
        tp = price + tp_dist * side.sign
        if stop <= 0 or tp <= 0:
            return None
        return SizingPlan(qty=qty, notional=notional, stop_price=stop,
                          take_profit_price=tp, stop_distance=dist,
                          risk_amount=min(risk_amount, qty * dist), r_multiple=rr)

    # ---------- çıkış yönetimi ----------
    def manage(self, p: Position, mark: float, now_ms: int,
               atr_abs: float | None = None) -> str | None:
        """Açık pozisyonu günceller; çıkış nedeni döndürür (yoksa None).

        Öncelik: stop -> TP -> kâr kilidi/iz süren -> zaman.
        """
        cfg = self.cfg
        s = p.side.sign
        pnl = p.unrealized(mark)
        p.mfe = max(p.mfe, pnl)
        p.mae = min(p.mae, pnl)
        if s > 0:
            p.peak_price = max(p.peak_price or p.entry_price, mark)
        else:
            p.peak_price = min(p.peak_price or p.entry_price, mark)

        if (mark - p.stop_price) * s <= 0:
            return "STOP_LOSS"
        if (mark - p.take_profit_price) * s >= 0:
            return "TAKE_PROFIT"

        risk = abs(p.entry_price - p.stop_price)
        if risk > 0:
            moved = (mark - p.entry_price) * s
            r_now = moved / risk
            # kâr kilidi: başabaşa çek
            if r_now >= cfg.breakeven_at_r:
                be = p.entry_price + s * (p.entry_price * cfg.taker_fee_bps * 2 / 10_000.0)
                if (be - p.stop_price) * s > 0:
                    p.stop_price = be
                    p.trail_active = True
            # iz süren stop
            if r_now >= cfg.trail_start_r and atr_abs and atr_abs > 0:
                new_stop = p.peak_price - s * atr_abs * cfg.trail_atr_mult
                if (new_stop - p.stop_price) * s > 0:
                    p.stop_price = new_stop
                    p.trail_active = True
                if (mark - p.stop_price) * s <= 0:
                    return "TRAILING_STOP"

        held = (now_ms - p.entry_ms) / 1000.0
        if held >= cfg.max_hold_sec:
            return "MAX_HOLD_TIME"
        return None

    def fee(self, notional: float, is_maker: bool) -> float:
        bps = self.cfg.maker_fee_bps if is_maker else self.cfg.taker_fee_bps
        return abs(notional) * bps / 10_000.0