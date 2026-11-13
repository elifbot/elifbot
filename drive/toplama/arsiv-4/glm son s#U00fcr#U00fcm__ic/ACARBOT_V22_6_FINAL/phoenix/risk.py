from dataclasses import dataclass
from .models import Position


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def target_notional(self):
        return self.cfg.entry_notional_usd

    def required_margin(self, notional):
        if self.cfg.leverage <= 0:
            return float("inf")
        return notional / self.cfg.leverage

    def estimated_entry_fee(self, notional):
        return abs(notional) * self.cfg.fee_bps_per_side / 10000

    def stop_price(self, entry, side, qty_contracts, contract_size=1.0, entry_fee=0, atr_pct=0.0):
        """Return a stop whose modeled round-trip net loss is <= max_loss_usd.

        The dollar budget is authoritative. One physics cap applies: the stop distance can never
        exceed liquidation_buffer_fraction/leverage of entry (0.70/10 = 7% at 10x). In margin mode
        ($50 x 10 = $500) the -$20 stop is a 4% move - the cap never binds and the stop is real.
        In notional mode ($50) the -$20 budget would be a ~40% move, far beyond isolated
        liquidation (~10%); the cap keeps the protective stop inside the liquidation region
        (modeled loss then ~-$3.9, not -$20). If ATR is enabled it may tighten further.
        This is a conservative heuristic, NOT an exchange liquidation-price guarantee.
        """
        exposure = abs(float(qty_contracts)) * max(float(contract_size or 0.0), 0.0)
        entry = float(entry)
        if exposure <= 0 or entry <= 0:
            return 0.0
        exit_rate = (self.cfg.fee_bps_per_side + self.cfg.slippage_bps_reserve) / 10000.0
        remaining = self.cfg.max_loss_usd - max(0.0, float(entry_fee)) - entry * exposure * exit_rate
        if remaining <= 0:
            return entry
        if str(side).upper() == "LONG":
            denom = exposure * max(1e-12, 1.0 - exit_rate)
        else:
            denom = exposure * (1.0 + exit_rate)
        distance = remaining / denom
        buffer_fraction = float(getattr(self.cfg, "liquidation_buffer_fraction", 0.70) or 0.0)
        if buffer_fraction > 0 and self.cfg.leverage > 0:
            distance = min(distance, entry * (buffer_fraction / self.cfg.leverage))
        if atr_pct and float(atr_pct) > 0 and self.cfg.atr_stop_multiplier > 0:
            distance = min(distance, entry * float(atr_pct) * self.cfg.atr_stop_multiplier)
        return max(0.0, entry - distance) if str(side).upper() == "LONG" else entry + distance

    def used_margin(self, positions, pending_reserved=0):
        return sum(
            (p.reserved_margin if p.reserved_margin > 0 else p.margin)
            + max(0.0, float(getattr(p, "entry_fee", 0.0) or 0.0))
            for p in positions if p.status == "OPEN"
        ) + max(0.0, pending_reserved)

    def available_margin(self, equity, positions, pending_reserved=0):
        cap = max(0.0, equity) * self.cfg.max_reserved_margin_pct
        return max(0.0, cap - self.used_margin(positions, pending_reserved))

    def can_enter(
        self,
        equity,
        positions,
        pending_reserved,
        notional,
        daily_loss=0.0,
        weekly_loss=0.0,
        peak_equity=None,
    ):
        if equity <= 0:
            return RiskDecision(False, "non_positive_equity")
        if self.cfg.daily_loss_limit_usd > 0 and daily_loss <= -self.cfg.daily_loss_limit_usd:
            return RiskDecision(False, "daily_loss_kill_switch")
        if self.cfg.weekly_loss_limit_usd > 0 and weekly_loss <= -self.cfg.weekly_loss_limit_usd:
            return RiskDecision(False, "weekly_loss_kill_switch")
        if self.cfg.max_drawdown_pct < 1.0 and peak_equity is not None and peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity
            if drawdown >= self.cfg.max_drawdown_pct:
                return RiskDecision(False, "max_drawdown_kill_switch")

        need = self.required_margin(notional)
        opens = [p for p in positions if p.status == "OPEN"]
        cap = equity * self.cfg.max_reserved_margin_pct
        used = self.used_margin(opens, pending_reserved)
        if self.cfg.max_open_positions > 0 and len(opens) >= self.cfg.max_open_positions:
            return RiskDecision(False, "max_open_positions")
        if need <= 0 or notional <= 0:
            return RiskDecision(False, "invalid_margin")
        if used + need > cap + 1e-9:
            return RiskDecision(False, f"reserved_margin_cap:{used + need:.2f}>{cap:.2f}")
        return RiskDecision(True)
