"""Long-only two-candle mean-reversion FADE setup."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from core.risk import MIN_IMPULSE_PERCENT, MIN_RVOL_FOR_ENTRY
from infra.market_data.models import Candle


MINIMUM_RVOL = 2.0


def measure_impulse_rvol(
    candles: Sequence[Candle], rvol_lookback: int = 20
) -> tuple[float, float]:
    if isinstance(rvol_lookback, bool) or not isinstance(rvol_lookback, int) or rvol_lookback < 1:
        raise ValueError("rvol_lookback must be a positive integer")
    if len(candles) < rvol_lookback + 3:
        return 0.0, 0.0
    impulse_pct = (candles[-1].close / candles[-3].close - 1.0) * 100.0
    baseline = candles[-rvol_lookback - 1:-1]
    average_volume = sum(item.volume for item in baseline) / rvol_lookback
    rvol = candles[-1].volume / average_volume if average_volume > 0 else 0.0
    return impulse_pct, rvol


@dataclass(frozen=True)
class Signal:
    side: str
    impulse_pct: float
    rvol: float
    stop_distance_fraction: float | None
    motor: str = "fade"
    rejection_code: str | None = None


class FadeStrategy:
    """Fade a sharp, high-relative-volume down move; never issue a short signal."""

    def __init__(
        self,
        impulse_threshold_pct: float = 0.35,
        minimum_rvol: float = MINIMUM_RVOL,
        rvol_lookback: int = 20,
    ) -> None:
        if (
            not isfinite(impulse_threshold_pct)
            or not isfinite(minimum_rvol)
            or impulse_threshold_pct <= 0
            or minimum_rvol <= 0
            or isinstance(rvol_lookback, bool)
            or not isinstance(rvol_lookback, int)
            or rvol_lookback < 1
        ):
            raise ValueError("FADE thresholds and lookback must be positive")
        self.impulse_threshold_pct = impulse_threshold_pct
        self.minimum_rvol = minimum_rvol
        self.rvol_lookback = rvol_lookback

    def evaluate(self, candles: Sequence[Candle]) -> Signal:
        if len(candles) < self.rvol_lookback + 3:
            return Signal("HOLD", 0.0, 0.0, None)

        impulse_pct, rvol = measure_impulse_rvol(candles, self.rvol_lookback)

        if abs(impulse_pct) < MIN_IMPULSE_PERCENT:
            return Signal(
                "HOLD", impulse_pct, rvol, None, "fade",
                "dusuk_momentum",
            )
        if rvol < MIN_RVOL_FOR_ENTRY:
            return Signal(
                "HOLD", impulse_pct, rvol, None, "fade",
                "dusuk_hacim",
            )
        if (
            impulse_pct < -self.impulse_threshold_pct
            and rvol >= self.minimum_rvol
        ):
            return Signal(
                "LONG",
                impulse_pct,
                rvol,
                abs(impulse_pct) / 100.0,
                "fade",
            )
        return Signal(
            "HOLD", impulse_pct, rvol, None, "fade",
            "FADE_PATTERN_NOT_MET",
        )


class TrendMomentumStrategy:
    """EMA(20/50) and MACD directional trend-following strategy."""

    def __init__(
        self,
        stop_atr_multiple: float = 2.5,
        minimum_stop_fraction: float = 0.001,
    ) -> None:
        if (
            not isfinite(stop_atr_multiple)
            or not isfinite(minimum_stop_fraction)
            or stop_atr_multiple <= 0
            or minimum_stop_fraction <= 0
        ):
            raise ValueError("trend stop parameters must be positive finite values")
        self.stop_atr_multiple = stop_atr_multiple
        self.minimum_stop_fraction = minimum_stop_fraction

    def evaluate(self, candles: Sequence[Candle]) -> Signal:
        from core.indicators import atr, ema, macd

        if len(candles) < 60:
            return Signal(
                "HOLD", 0.0, 0.0, None, "trend", "TREND_WARMUP"
            )
        close = [item.close for item in candles]
        high = [item.high for item in candles]
        low = [item.low for item in candles]
        fast = ema(close, 20)[-1]
        slow = ema(close, 50)[-1]
        macd_values = macd(close)
        line = macd_values.line[-1]
        signal_line = macd_values.signal[-1]
        average_range = atr(high, low, close)[-1]
        if any(value is None for value in (fast, slow, line, signal_line, average_range)):
            return Signal(
                "HOLD", 0.0, 0.0, None, "trend", "TREND_WARMUP"
            )

        impulse_pct, rvol = measure_impulse_rvol(candles)
        if fast > slow and line > signal_line:
            side = "LONG"
        elif fast < slow and line < signal_line:
            side = "SHORT"
        else:
            side = "HOLD"
        rejection = None
        if side == "HOLD":
            rejection = "TREND_NOT_CONFIRMED"
        elif abs(impulse_pct) < MIN_IMPULSE_PERCENT:
            side = "HOLD"
            rejection = "dusuk_momentum"
        elif rvol < MIN_RVOL_FOR_ENTRY:
            side = "HOLD"
            rejection = "dusuk_hacim"
        stop_fraction = max(
            self.minimum_stop_fraction,
            self.stop_atr_multiple * float(average_range) / close[-1],
        ) if side != "HOLD" else None
        return Signal(
            side=side,
            impulse_pct=impulse_pct,
            rvol=rvol,
            stop_distance_fraction=stop_fraction,
            motor="trend",
            rejection_code=rejection,
        )
