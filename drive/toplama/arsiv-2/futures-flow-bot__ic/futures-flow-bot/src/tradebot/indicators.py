"""Artimli (incremental) RSI ve MACD - her mum kapanisinda tek adim hesap."""
from __future__ import annotations


class RSI:
    def __init__(self, period: int = 14):
        self.p = period
        self.prev: float | None = None
        self.avg_gain: float | None = None
        self.avg_loss: float | None = None
        self._sg: list[float] = []
        self._sl: list[float] = []
        self.value: float | None = None

    def update(self, close: float) -> float | None:
        if self.prev is None:
            self.prev = close
            return None
        ch = close - self.prev
        self.prev = close
        gain, loss = max(ch, 0.0), max(-ch, 0.0)
        if self.avg_gain is None:
            self._sg.append(gain)
            self._sl.append(loss)
            if len(self._sg) < self.p:
                return None
            self.avg_gain = sum(self._sg) / self.p
            self.avg_loss = sum(self._sl) / self.p
        else:
            self.avg_gain = (self.avg_gain * (self.p - 1) + gain) / self.p
            self.avg_loss = (self.avg_loss * (self.p - 1) + loss) / self.p
        if self.avg_loss == 0:
            self.value = 50.0 if self.avg_gain == 0 else 100.0
        else:
            self.value = 100.0 - 100.0 / (1.0 + self.avg_gain / self.avg_loss)
        return self.value


class EMA:
    def __init__(self, n: int):
        self.k = 2.0 / (n + 1)
        self.value: float | None = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        return self.value


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast, self.slow, self.sig = EMA(fast), EMA(slow), EMA(signal)
        self.warm = slow + signal
        self.n = 0
        self.hist: float | None = None
        self.prev_hist: float | None = None

    def update(self, close: float) -> None:
        self.n += 1
        line = self.fast.update(close) - self.slow.update(close)
        sig = self.sig.update(line)
        if self.n >= self.warm:
            self.prev_hist = self.hist
            self.hist = line - sig

    @property
    def ready(self) -> bool:
        return self.hist is not None and self.prev_hist is not None
