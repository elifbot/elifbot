"""Rolling quote-volume spike detector fed by individual public trades."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite

from core.risk import (
    MIN_24H_VOLUME,
    MIN_IMPULSE_PERCENT,
    VOLUME_SPIKE_LOOKBACK_SECONDS,
    VOLUME_SPIKE_MULTIPLIER,
)
from infra.exchanges.base import PublicTrade


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
    last_price: float
    last_second: int
    buckets: deque[tuple[int, float, float]]
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
        self._volumes_24h: dict[str, float] = {}

    def set_24h_volume(self, symbol: str, quote_volume: float) -> None:
        if not symbol or not isfinite(quote_volume) or quote_volume < 0:
            raise ValueError("symbol and finite non-negative 24h volume are required")
        self._volumes_24h[symbol.upper()] = quote_volume

    def update_trade(self, trade: PublicTrade) -> VolumeSpike | None:
        symbol = trade.symbol.upper()
        if (
            not symbol
            or not isfinite(trade.quote_volume)
            or trade.quote_volume <= 0
            or not isfinite(trade.price)
            or trade.price <= 0
            or trade.timestamp_ms < 0
        ):
            raise ValueError("trade contains invalid volume, price, or timestamp")

        current_second = trade.timestamp_ms // 1000
        state = self._states.get(symbol)
        if state is None:
            self._states[symbol] = _SymbolVolume(
                last_price=trade.price,
                last_second=current_second,
                buckets=deque(
                    [(current_second, trade.quote_volume, trade.price)],
                    maxlen=self.lookback_seconds + 1,
                ),
                rolling_sum=trade.quote_volume,
            )
            return None
        if current_second < state.last_second:
            return None

        if current_second > state.last_second:
            elapsed = current_second - state.last_second
            if elapsed > self.lookback_seconds:
                state.buckets.clear()
                state.rolling_sum = 0.0
                first_second = current_second - self.lookback_seconds
            else:
                first_second = state.last_second + 1
            for second in range(first_second, current_second + 1):
                bucket_price = trade.price if second == current_second else state.last_price
                self._append_bucket(state, second, 0.0, bucket_price)

        second, volume, _ = state.buckets[-1]
        if second == current_second:
            state.buckets[-1] = (
                second,
                volume + trade.quote_volume,
                trade.price,
            )
            state.rolling_sum += trade.quote_volume

        old_price = state.last_price
        state.last_price = trade.price
        state.last_second = current_second
        quote_volume_24h = self._volumes_24h.get(symbol, 0.0)
        if quote_volume_24h < self.minimum_24h_volume:
            return None
        if len(state.buckets) < self.lookback_seconds + 1:
            return None

        current_volume = state.buckets[-1][1]
        average = (state.rolling_sum - current_volume) / self.lookback_seconds
        if average <= 0:
            return None
        multiple = current_volume / average
        if multiple < self.multiplier or state.last_spike_second == current_second:
            return None
        state.last_spike_second = current_second

        direction_lookback = min(5, self.lookback_seconds)
        baseline_price = state.buckets[-direction_lookback - 1][2]
        impulse_percent = (
            (trade.price / baseline_price - 1.0) * 100.0
            if baseline_price > 0 else 0.0
        )
        if impulse_percent == 0 and old_price != trade.price:
            impulse_percent = (trade.price / old_price - 1.0) * 100.0
        direction = (
            "LONG" if impulse_percent > 0
            else "SHORT" if impulse_percent < 0
            else None
        )
        if abs(impulse_percent) < MIN_IMPULSE_PERCENT:
            direction = None
        return VolumeSpike(
            symbol=symbol,
            quote_volume=current_volume,
            average_quote_volume_per_second=average,
            multiplier=multiple,
            direction=direction,
            impulse_percent=impulse_percent,
            price=trade.price,
            timestamp_ms=trade.timestamp_ms,
        )

    @staticmethod
    def _append_bucket(
        state: _SymbolVolume, second: int, volume: float, price: float
    ) -> None:
        if len(state.buckets) == state.buckets.maxlen:
            _, expired_volume, _ = state.buckets.popleft()
            state.rolling_sum -= expired_volume
        state.buckets.append((second, volume, price))
        state.rolling_sum += volume
