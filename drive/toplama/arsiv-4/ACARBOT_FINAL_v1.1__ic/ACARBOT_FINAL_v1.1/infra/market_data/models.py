"""Normalized candle model shared by exchanges, strategy, and backtest."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp cannot be negative")
        if not all(isfinite(value) for value in (
            self.open, self.high, self.low, self.close, self.volume
        )):
            raise ValueError("candle values must be finite")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC values must be positive")
        if self.volume < 0 or self.high < self.low:
            raise ValueError("invalid candle range or volume")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("high/low must contain open and close")
