"""Risk motoru - deterministik. LLM/ajanlar burayi atlayamaz; her giris buradan gecer."""
from __future__ import annotations

from .config import Config
from .models import AccountView, EntryPlan, Signal
from .safety import SafetyMonitor


class RiskManager:
    def __init__(self, cfg: Config, safety: SafetyMonitor):
        self.cfg = cfg
        self.safety = safety
        self.last_activity: dict[tuple[str, str], float] = {}

    def mark(self, exchange: str, symbol: str, ts: float) -> None:
        self.last_activity[(exchange, symbol)] = ts

    def approve(self, sig: Signal, acct: AccountView, positions: list, now: float,
                has_symbol: bool) -> EntryPlan | str:
        """Plan dondurur ya da ret nedenini (str)."""
        r = self.cfg.risk
        if not self.safety.can_enter(sig.exchange):
            return "halted"
        if has_symbol:
            return "has_position"
        last = self.last_activity.get((sig.exchange, sig.symbol))
        if last is not None and now - last < r.symbol_cooldown_sec:
            return "cooldown"
        reserve = acct.equity * r.free_margin_reserve_pct / 100
        if acct.available < r.margin_per_trade_usd + reserve:
            return "no_margin"
        if r.max_open_positions is not None and acct.open_positions + acct.pending >= r.max_open_positions:
            return "max_positions"
        if r.daily_loss_limit_usd is not None and acct.realized_today <= -r.daily_loss_limit_usd:
            return "daily_loss_limit"
        if r.max_same_direction_positions is not None:
            same = sum(1 for p in positions if p.side is sig.side)
            if same >= r.max_same_direction_positions:
                return "max_same_direction"
        notional = r.margin_per_trade_usd * r.leverage
        dist = self.cfg.stop_distance
        stop = sig.price * (1 - sig.side.sign * dist)
        return EntryPlan(signal=sig, price=sig.price, notional=notional, margin=r.margin_per_trade_usd,
                         leverage=r.leverage, stop_dist=dist, stop_price=stop)
