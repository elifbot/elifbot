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
        """Return the per-position hard-loss stop.

        The stop is derived from max_loss_usd after reserving estimated entry/exit
        fees and slippage. ATR is intentionally NOT allowed to tighten this stop:
        the user's rule is a dollar loss limit per position, not an ATR exit.
        Exchange gaps, execution slippage beyond the reserve and funding can still
        make the realized loss exceed the configured amount.
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
        # The configured dollar budget is a ceiling, not a reason to place a stop
        # beyond a plausible liquidation region. At 10x and a 0.70 buffer fraction,
        # the maximum adverse move is 7%. Exchange maintenance tiers and cross-margin
        # equity can move liquidation; this heuristic is deliberately conservative
        # but is NOT a substitute for the venue's live liquidationPrice.
        budget_distance = remaining / denom
        leverage_distance = entry * (self.cfg.liquidation_buffer_fraction / self.cfg.leverage)
        distance = min(budget_distance, leverage_distance)
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
        if daily_loss <= -self.cfg.daily_loss_limit_usd:
            return RiskDecision(False, "daily_loss_kill_switch")
        if weekly_loss <= -self.cfg.weekly_loss_limit_usd:
            return RiskDecision(False, "weekly_loss_kill_switch")
        if peak_equity is not None and peak_equity > 0:
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
