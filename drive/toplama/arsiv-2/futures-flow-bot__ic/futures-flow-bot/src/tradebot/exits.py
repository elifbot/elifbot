"""Pozisyon cikis karari: iz suren stop, akis donusu, zaman stopu.
Zarar stopu (25$) ayrica borsada duran stop emridir; burasi dinamik cikislardir."""
from __future__ import annotations

from .config import Config
from .features import Features
from .models import Position
from .scoring import score_exit


def decide_exit(pos: Position, f: Features | None, pnl: float, now: float, cfg: Config):
    """Doner: (neden, detay) veya None. pnl = tahmini net (komisyon dahil) kar/zarar, USD."""
    x = cfg.exit
    if pos.peak_pnl >= x.trail_activation_usd and pnl <= pos.peak_pnl * (1 - x.trail_giveback_pct / 100):
        return "trailing", [f"tepe {pos.peak_pnl:.2f}$ -> {pnl:.2f}$"]
    if f is not None:
        score, reasons = score_exit(pos.side, f, x)
        if score >= x.score_threshold:
            if pnl >= x.min_net_profit_usd:
                return "flow_reversal", reasons
            if pnl < 0 and x.exit_when_losing_on_reversal:
                return "flow_reversal_loss", reasons
    if now - pos.opened_ts >= x.time_stop_minutes * 60 and pnl < x.min_net_profit_usd:
        return "time_stop", [f"{x.time_stop_minutes:.0f} dk doldu"]
    return None
