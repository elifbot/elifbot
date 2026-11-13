"""Teknik indikatörler — saf Python, bağımlılıksız, deterministik.

numpy/pandas zorunlu değildir; test edilebilirlik için kapalı formda yazıldı.
Yeterli veri yoksa None döner; sıfır uydurulmaz. Bu, sahte geçiş üretmemek
için önemlidir.
"""
from __future__ import annotations

import math
from typing import Sequence

from ..core.types import Candle


def ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(0.0, d)
        losses += max(0.0, -d)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (period - 1) + max(0.0, d)) / period
        al = (al * (period - 1) + max(0.0, -d)) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def true_range(c: Candle, prev_close: float) -> float:
    return max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))


def atr(candles: Sequence[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs = [true_range(candles[i], candles[i - 1].close)
           for i in range(1, len(candles))]
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def choppiness(candles: Sequence[Candle], period: int = 14) -> float | None:
    """Choppiness Index: 0-100. Yüksek => testere, düşük => trend."""
    if len(candles) < period + 1 or period <= 1:
        return None
    win = candles[-period:]
    trs = [true_range(win[i], (candles[-period - 1 + i].close))
           for i in range(len(win))]
    s = sum(trs)
    hi = max(c.high for c in win)
    lo = min(c.low for c in win)
    rng = hi - lo
    if rng <= 0 or s <= 0:
        return None
    return 100.0 * math.log10(s / rng) / math.log10(period)


def supertrend(candles: Sequence[Candle], period: int = 10,
               multiplier: float = 3.0) -> tuple[float, int] | None:
    """(seviye, yön) döndürür. Yön +1 = yükseliş, -1 = düşüş."""
    if len(candles) < period + 2:
        return None
    a = atr(candles, period)
    if a is None or a <= 0:
        return None
    c = candles[-1]
    mid = (c.high + c.low) / 2.0
    upper, lower = mid + multiplier * a, mid - multiplier * a
    prev = candles[-2]
    prev_mid = (prev.high + prev.low) / 2.0
    direction = 1 if c.close > prev_mid else -1
    return (lower if direction > 0 else upper), direction


def ema_trend(closes: Sequence[float], fast: int = 21,
              slow: int = 55) -> int | None:
    ef, es = ema(closes, fast), ema(closes, slow)
    if ef is None or es is None:
        return None
    if ef > es * 1.0005:
        return 1
    if ef < es * 0.9995:
        return -1
    return 0


def bollinger_width(closes: Sequence[float], period: int = 20,
                    mult: float = 2.0) -> float | None:
    if len(closes) < period:
        return None
    win = closes[-period:]
    m = sum(win) / period
    var = sum((x - m) ** 2 for x in win) / period
    sd = math.sqrt(var)
    return (2.0 * mult * sd / m * 100.0) if m > 0 else None


def structure_break(candles: Sequence[Candle], lookback: int = 20) -> int | None:
    """Basit BOS: son kapanış önceki pencerenin ekstremumunu kırdı mı?"""
    if len(candles) < lookback + 1:
        return None
    win = candles[-lookback - 1:-1]
    c = candles[-1].close
    if c > max(x.high for x in win):
        return 1
    if c < min(x.low for x in win):
        return -1
    return 0


def snapshot(candles: Sequence[Candle]) -> dict[str, float | int | None]:
    """Konsey ve kapılar için tek özet. Veri yoksa None korunur."""
    closes = [c.close for c in candles]
    a = atr(candles, 14)
    last = closes[-1] if closes else 0.0
    st = supertrend(candles)
    return {
        "atr": a,
        "atr_pct": (a / last * 100.0) if (a and last > 0) else None,
        "rsi": rsi(closes, 14),
        "choppiness": choppiness(candles, 14),
        "ema_trend": ema_trend(closes),
        "bos": structure_break(candles),
        "supertrend_dir": st[1] if st else None,
        "supertrend_level": st[0] if st else None,
        "bb_width_pct": bollinger_width(closes),
        "candles": len(candles),
    }