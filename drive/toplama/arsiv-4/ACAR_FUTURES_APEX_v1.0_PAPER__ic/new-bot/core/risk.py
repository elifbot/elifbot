"""Fixed-notional, loss-capped sizing for long and short paper positions."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


MAX_LOSS_PER_POS = 25.0
DAILY_MAX_LOSS_USDT = 100.0
MIN_IMPULSE_PERCENT = 0.30
MIN_RVOL_FOR_ENTRY = 1.5
MIN_RVOL_FOR_EXIT = 1.0
MAKS_POZ_SABİT = 20
VOLUME_SPIKE_MULTIPLIER = 3.0
MIN_24H_VOLUME = 1_000_000.0
VOLUME_SPIKE_LOOKBACK_SECONDS = 15 * 60
KÂR_KİLİTLEME_ESİĞİ = 250.0
TRAILING_ACTIVATION_USDT = 100.0
TRAILING_DISTANCE_PERCENT = 2.0


@dataclass(frozen=True)
class TradePlan:
    side: str
    entry: float
    quantity: float
    margin: float
    notional: float
    stop_loss: float
    leverage: float
    estimated_cost: float


class MaxPositionsReached(Exception):
    """A valid signal was rejected because the portfolio is at its position cap."""

    code = "MAX_POSITIONS_REACHED"


class InsufficientFunds(ValueError):
    """Paper wallet has less free balance than the margin required for entry."""

    code = "INSUFFICIENT_FUNDS"


class DailyLossLimitReached(ValueError):
    """New entries are paused after the configured UTC-day loss limit."""

    code = "DAILY_LOSS_LIMIT"


class RiskManager:
    def __init__(
        self,
        margin_usdt: float = 50.0,
        leverage: float = 10.0,
        max_loss_usdt: float = 25.0,
        max_notional_usdt: float = 500.0,
        maker_fee_rate: float = 0.0002,
        stop_taker_fee_rate: float = 0.0004,
        stop_slippage_rate: float = 0.0005,
        max_positions: int = MAKS_POZ_SABİT,
        funding_buffer_usdt: float = 0.01,
    ) -> None:
        numeric = (
            margin_usdt, leverage, max_loss_usdt, max_notional_usdt,
            maker_fee_rate, stop_taker_fee_rate, stop_slippage_rate,
            funding_buffer_usdt,
        )
        if any(not isfinite(value) for value in numeric):
            raise ValueError("risk settings must be finite")
        if any(value <= 0 for value in numeric[:4]):
            raise ValueError("margin, leverage, loss, and notional must be positive")
        if any(value < 0 for value in numeric[4:7]) or funding_buffer_usdt < 0:
            raise ValueError("fee, slippage, and funding buffer cannot be negative")
        if any(value >= 1 for value in numeric[4:7]):
            raise ValueError("fee and slippage rates must be below 1")
        if abs(margin_usdt * leverage - max_notional_usdt) > 1e-8:
            raise ValueError("margin_usdt * leverage must equal max_notional_usdt")
        if (
            isinstance(max_positions, bool)
            or not isinstance(max_positions, int)
            or max_positions < 1
        ):
            raise ValueError("max_positions must be a positive integer")
        self.margin_usdt = margin_usdt
        self.leverage = leverage
        self.max_loss_usdt = max_loss_usdt
        self.max_notional_usdt = max_notional_usdt
        self.maker_fee_rate = maker_fee_rate
        self.stop_taker_fee_rate = stop_taker_fee_rate
        self.stop_slippage_rate = stop_slippage_rate
        self.max_positions = min(max_positions, MAKS_POZ_SABİT)
        self.funding_buffer_usdt = funding_buffer_usdt

    @property
    def required_balance_per_position(self) -> float:
        return (
            self.margin_usdt
            + self.max_notional_usdt * self.maker_fee_rate
            + self.funding_buffer_usdt
        )

    def dynamic_position_limit(self, equity: float) -> int:
        if not isfinite(equity) or equity < 0:
            raise ValueError("equity must be finite and non-negative")
        dynamic_limit = int(
            (equity - 49.0 - 5.0) // self.required_balance_per_position
        )
        return min(max(dynamic_limit, 0), self.max_positions, MAKS_POZ_SABİT)

    def ensure_position_capacity(
        self, open_positions: int, equity: float | None = None
    ) -> None:
        if isinstance(open_positions, bool) or not isinstance(open_positions, int) or open_positions < 0:
            raise ValueError("open_positions must be a non-negative integer")
        position_limit = (
            self.max_positions
            if equity is None
            else self.dynamic_position_limit(equity)
        )
        if open_positions >= position_limit:
            raise MaxPositionsReached(
                f"MAX_POSITIONS_REACHED: {open_positions}/{position_limit}"
            )

    def ensure_daily_loss_allowance(self, daily_pnl: float) -> None:
        if not isfinite(daily_pnl):
            raise ValueError("daily_pnl must be finite")
        if daily_pnl <= -DAILY_MAX_LOSS_USDT:
            raise DailyLossLimitReached(
                f"DAILY_LOSS_LIMIT: daily_pnl={daily_pnl:.2f} USDT"
            )

    def estimated_cost_for_stop(self, stop_distance_fraction: float) -> float:
        if (
            not isfinite(stop_distance_fraction)
            or stop_distance_fraction < 0
            or stop_distance_fraction >= 1
        ):
            raise ValueError("stop distance must be finite and in [0, 1)")
        adverse_stop_multiplier = 1.0 + stop_distance_fraction
        return self.max_notional_usdt * (
            self.maker_fee_rate
            + adverse_stop_multiplier * (self.stop_taker_fee_rate + self.stop_slippage_rate)
        )

    def plan(
        self,
        balance: float,
        entry: float,
        stop_distance_fraction: float,
        side: str = "LONG",
        open_positions: int = 0,
        equity: float | None = None,
    ) -> TradePlan:
        self.ensure_position_capacity(open_positions, equity)
        if any(not isfinite(value) or value <= 0 for value in (
            balance, entry, stop_distance_fraction
        )):
            raise ValueError("balance, entry, and stop distance must be positive and finite")
        if not 0 < stop_distance_fraction < 1:
            raise ValueError("stop distance fraction must be less than 1")
        normalized_side = side.upper()
        if normalized_side not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")
        required_balance = (
            self.margin_usdt
            + self.max_notional_usdt * self.maker_fee_rate
            + self.funding_buffer_usdt
        )
        if balance < required_balance:
            raise InsufficientFunds(
                f"INSUFFICIENT_FUNDS: available={balance:.8f}, "
                f"required_balance={required_balance:.8f}"
            )

        cost = self.estimated_cost_for_stop(stop_distance_fraction)
        risk_budget_after_cost = self.max_loss_usdt - cost
        if risk_budget_after_cost <= 0:
            raise ValueError("estimated fees and slippage consume the full loss budget")
        quantity = min(
            self.max_notional_usdt / entry,
            risk_budget_after_cost / (stop_distance_fraction * entry),
        )
        if not isfinite(quantity) or quantity <= 0:
            raise ValueError("risk limits produce a non-positive position size")
        notional = quantity * entry
        direction = 1.0 if normalized_side == "LONG" else -1.0
        stop_loss = entry * (1.0 - direction * stop_distance_fraction)
        return TradePlan(
            side=normalized_side,
            entry=entry,
            quantity=quantity,
            margin=self.margin_usdt,
            notional=notional,
            stop_loss=stop_loss,
            leverage=self.leverage,
            estimated_cost=cost,
        )
