"""Rolling volume-spike detector for public futures ticker streams."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite

from core.risk import (
    MIN_24H_VOLUME,
    VOLUME_SPIKE_LOOKBACK_SECONDS,
    VOLUME_SPIKE_MULTIPLIER,
)
from infra.exchanges.base import Ticker


@dataclass(frozen=True)
class VolumeSpike:
    symbol: str
    quote_volume: float
    average_quote_volume_per_second: float
    multiplier: float
    direction: str | None
    impulse_percent: float
    price: float
    timestamp_ms: int


@dataclass
class _SymbolVolume:
    cumulative_quote_volume: float
    last_price: float
    last_second: int
    buckets: deque[tuple[int, float]] = field(
        default_factory=lambda: deque(maxlen=VOLUME_SPIKE_LOOKBACK_SECONDS + 1)
    )
    rolling_sum: float = 0.0
    last_spike_second: int | None = None


class VolumeSpikeDetector:
    def __init__(
        self,
        multiplier: float = VOLUME_SPIKE_MULTIPLIER,
        minimum_24h_volume: float = MIN_24H_VOLUME,
        lookback_seconds: int = VOLUME_SPIKE_LOOKBACK_SECONDS,
    ) -> None:
        if not isfinite(multiplier) or multiplier <= 0:
            raise ValueError("volume spike multiplier must be positive and finite")
        if not isfinite(minimum_24h_volume) or minimum_24h_volume < 0:
            raise ValueError("minimum 24h volume must be finite and non-negative")
        if (
            isinstance(lookback_seconds, bool)
            or not isinstance(lookback_seconds, int)
            or lookback_seconds < 1
        ):
            raise ValueError("lookback_seconds must be a positive integer")
        self.multiplier = multiplier
        self.minimum_24h_volume = minimum_24h_volume
        self.lookback_seconds = lookback_seconds
        self._states: dict[str, _SymbolVolume] = {}

    def update(self, ticker: Ticker) -> VolumeSpike | None:
        symbol = ticker.symbol.upper()
        if (
            not symbol
            or not isfinite(ticker.quote_volume_24h)
            or ticker.quote_volume_24h < 0
            or not isfinite(ticker.last_price)
            or ticker.last_price <= 0
            or ticker.timestamp_ms < 0
        ):
            raise ValueError("ticker contains invalid volume, price, or timestamp")

        current_second = ticker.timestamp_ms // 1000
        state = self._states.get(symbol)
        if state is None:
            self._states[symbol] = _SymbolVolume(
                ticker.quote_volume_24h,
                ticker.last_price,
                current_second,
                deque([(current_second, 0.0)],
                      maxlen=self.lookback_seconds + 1),
            )
            return None
        if current_second < state.last_second:
            return None

        price_change = (
            (ticker.last_price / state.last_price - 1.0) * 100.0
            if ticker.last_price != state.last_price else 0.0
        )
        delta = ticker.quote_volume_24h - state.cumulative_quote_volume
        # A rolling 24h ticker can decrease when old trades leave its window.
        # Treat that reset as zero rather than inventing negative traded volume.
        delta = max(delta, 0.0)
        if current_second > state.last_second:
            elapsed_seconds = current_second - state.last_second
            per_second_volume = delta / elapsed_seconds
            if elapsed_seconds > self.lookback_seconds:
                state.buckets.clear()
                state.rolling_sum = 0.0
                first_second = current_second - self.lookback_seconds
            else:
                first_second = state.last_second + 1
            for second in range(first_second, current_second + 1):
                self._append_bucket(state, second, per_second_volume)
            delta = 0.0
        bucket_second, bucket_volume = state.buckets[-1]
        if bucket_second == current_second:
            state.buckets[-1] = (bucket_second, bucket_volume + delta)
            state.rolling_sum += delta
        state.cumulative_quote_volume = ticker.quote_volume_24h
        state.last_price = ticker.last_price
        state.last_second = current_second

        if ticker.quote_volume_24h < self.minimum_24h_volume:
            return None
        if len(state.buckets) < self.lookback_seconds + 1:
            return None
        current_volume = state.buckets[-1][1]
        average = (state.rolling_sum - current_volume) / self.lookback_seconds
        if average <= 0:
            return None
        multiple = current_volume / average
        if multiple < self.multiplier:
            return None
        if state.last_spike_second == current_second:
            return None
        state.last_spike_second = current_second
        direction = (
            "LONG" if price_change > 0
            else "SHORT" if price_change < 0
            else None
        )
        return VolumeSpike(
            symbol=symbol,
            quote_volume=current_volume,
            average_quote_volume_per_second=average,
            multiplier=multiple,
            direction=direction,
            impulse_percent=price_change,
            price=ticker.last_price,
            timestamp_ms=ticker.timestamp_ms,
        )

    @staticmethod
    def _append_bucket(
        state: _SymbolVolume, second: int, volume: float
    ) -> None:
        if len(state.buckets) == state.buckets.maxlen:
            _, expired_volume = state.buckets.popleft()
            state.rolling_sum -= expired_volume
        state.buckets.append((second, volume))
        state.rolling_sum += volume
