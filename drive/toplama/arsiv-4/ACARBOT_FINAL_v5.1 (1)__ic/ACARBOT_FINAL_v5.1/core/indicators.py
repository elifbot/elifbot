"""Pure-Python technical indicators used by the paper-trading strategy."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Sequence


IndicatorSeries = list[float | None]


@dataclass(frozen=True)
class Macd:
    line: IndicatorSeries
    signal: IndicatorSeries
    histogram: IndicatorSeries


@dataclass(frozen=True)
class DirectionalMovement:
    adx: IndicatorSeries
    plus_di: IndicatorSeries
    minus_di: IndicatorSeries


@dataclass(frozen=True)
class Stochastic:
    percent_k: IndicatorSeries
    percent_d: IndicatorSeries


@dataclass(frozen=True)
class BollingerBands:
    middle: IndicatorSeries
    upper: IndicatorSeries
    lower: IndicatorSeries


@dataclass(frozen=True)
class Supertrend:
    line: IndicatorSeries
    direction: list[int | None]


def _period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")


def _series(values: Sequence[float], name: str = "values") -> list[float]:
    """v5.1: TEK geçişte dönüştür + doğrula.

    Eski hâl iki geçiş yapıyordu (list comprehension + any(genexpr)) ve
    backtest'te sıcak noktaydı: 600 barlık koşuda 5,4 milyon isfinite
    çağrısı. Anlam değişmedi, yalnızca geçiş sayısı yarıya indi.
    """
    result: list[float] = []
    append = result.append
    for value in values:
        number = float(value)
        if not isfinite(number):
            raise ValueError(f"{name} must contain only finite numbers")
        append(number)
    return result


def _ohlc(
    high: Sequence[float], low: Sequence[float], close: Sequence[float]
) -> tuple[list[float], list[float], list[float]]:
    highs = _series(high, "high")
    lows = _series(low, "low")
    closes = _series(close, "close")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("high, low, and close must have equal lengths")
    for index in range(len(highs)):
        if highs[index] < lows[index]:
            raise ValueError("high cannot be lower than low")
    return highs, lows, closes


def _sma_valid(values: Sequence[float], period: int) -> list[float | None]:
    _period(period)
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    window_sum = sum(values[:period])
    result[period - 1] = window_sum / period
    for index in range(period, len(values)):
        window_sum += values[index] - values[index - period]
        result[index] = window_sum / period
    return result


def sma(values: Sequence[float], period: int) -> IndicatorSeries:
    """Return a simple moving average; values before the first full window are None."""
    data = _series(values)
    return _sma_valid(data, period)


def ema(values: Sequence[float], period: int) -> IndicatorSeries:
    """Return an EMA seeded by the first full-window SMA."""
    _period(period)
    data = _series(values)
    result: IndicatorSeries = [None] * len(data)
    if len(data) < period:
        return result

    seed = sum(data[:period]) / period
    result[period - 1] = seed
    multiplier = 2.0 / (period + 1)
    current = seed
    for index in range(period, len(data)):
        current += multiplier * (data[index] - current)
        result[index] = current
    return result


def rsi(values: Sequence[float], period: int = 14) -> IndicatorSeries:
    """Return Wilder's RSI, with 50 for a flat series and 100/0 for one-way movement."""
    _period(period)
    data = _series(values)
    result: IndicatorSeries = [None] * len(data)
    if len(data) <= period:
        return result

    gains = [max(data[i] - data[i - 1], 0.0) for i in range(1, period + 1)]
    losses = [max(data[i - 1] - data[i], 0.0) for i in range(1, period + 1)]
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        if gain == 0:
            return 0.0
        relative_strength = gain / loss
        return 100.0 - 100.0 / (1.0 + relative_strength)

    result[period] = value(average_gain, average_loss)
    for index in range(period + 1, len(data)):
        gain = max(data[index] - data[index - 1], 0.0)
        loss = max(data[index - 1] - data[index], 0.0)
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
        result[index] = value(average_gain, average_loss)
    return result


def true_range(
    high: Sequence[float], low: Sequence[float], close: Sequence[float]
) -> IndicatorSeries:
    highs, lows, closes = _ohlc(high, low, close)
    result: IndicatorSeries = []
    for index, (h, l) in enumerate(zip(highs, lows)):
        if index == 0:
            result.append(h - l)
        else:
            result.append(
                max(
                    h - l,
                    abs(h - closes[index - 1]),
                    abs(l - closes[index - 1]),
                )
            )
    return result


def atr(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> IndicatorSeries:
    """Return Wilder's ATR, initialized with the first period true ranges."""
    _period(period)
    ranges = true_range(high, low, close)
    result: IndicatorSeries = [None] * len(ranges)
    if len(ranges) < period:
        return result
    current = sum(float(item) for item in ranges[:period]) / period
    result[period - 1] = current
    for index in range(period, len(ranges)):
        current = (current * (period - 1) + float(ranges[index])) / period
        result[index] = current
    return result


def macd(
    values: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Macd:
    """Return MACD line, signal line, and histogram."""
    _period(fast_period)
    _period(slow_period)
    _period(signal_period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")
    data = _series(values)
    fast = ema(data, fast_period)
    slow = ema(data, slow_period)
    line: IndicatorSeries = [None] * len(data)
    first_valid = slow_period - 1
    for index in range(first_valid, len(data)):
        line[index] = float(fast[index]) - float(slow[index])

    valid_line = [float(item) for item in line[first_valid:]]
    signal_values = ema(valid_line, signal_period)
    signal: IndicatorSeries = [None] * len(data)
    histogram: IndicatorSeries = [None] * len(data)
    for offset, signal_value in enumerate(signal_values):
        index = first_valid + offset
        if signal_value is not None:
            signal[index] = signal_value
            histogram[index] = float(line[index]) - signal_value
    return Macd(line=line, signal=signal, histogram=histogram)


def directional_movement(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> DirectionalMovement:
    """Return Wilder-smoothed ADX, +DI, and -DI series."""
    _period(period)
    highs, lows, closes = _ohlc(high, low, close)
    size = len(highs)
    ranges = true_range(highs, lows, closes)
    plus_dm = [0.0] * size
    minus_dm = [0.0] * size
    for index in range(1, size):
        up_move = highs[index] - highs[index - 1]
        down_move = lows[index - 1] - lows[index]
        if up_move > down_move and up_move > 0:
            plus_dm[index] = up_move
        elif down_move > up_move and down_move > 0:
            minus_dm[index] = down_move

    adx_values: IndicatorSeries = [None] * size
    plus_di: IndicatorSeries = [None] * size
    minus_di: IndicatorSeries = [None] * size
    if size < period:
        return DirectionalMovement(adx_values, plus_di, minus_di)

    smooth_range = sum(float(item) for item in ranges[:period])
    smooth_plus = sum(plus_dm[:period])
    smooth_minus = sum(minus_dm[:period])
    dx: IndicatorSeries = [None] * size

    for index in range(period - 1, size):
        if index >= period:
            smooth_range += float(ranges[index]) - smooth_range / period
            smooth_plus += plus_dm[index] - smooth_plus / period
            smooth_minus += minus_dm[index] - smooth_minus / period

        if smooth_range == 0:
            plus_value = minus_value = 0.0
        else:
            plus_value = 100.0 * smooth_plus / smooth_range
            minus_value = 100.0 * smooth_minus / smooth_range
        plus_di[index] = plus_value
        minus_di[index] = minus_value
        denominator = plus_value + minus_value
        dx[index] = (
            0.0
            if denominator == 0
            else 100.0 * abs(plus_value - minus_value) / denominator
        )

    first_adx = 2 * period - 2
    if size > first_adx:
        current = sum(float(item) for item in dx[period - 1 : first_adx + 1]) / period
        adx_values[first_adx] = current
        for index in range(first_adx + 1, size):
            current = (current * (period - 1) + float(dx[index])) / period
            adx_values[index] = current
    return DirectionalMovement(adx_values, plus_di, minus_di)


def adx(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 14,
) -> DirectionalMovement:
    """Alias for directional_movement, returning ADX and both directional indices."""
    return directional_movement(high, low, close, period)


def stochastic(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> Stochastic:
    """Return raw stochastic %K and its simple-moving-average %D."""
    _period(k_period)
    _period(d_period)
    highs, lows, closes = _ohlc(high, low, close)
    percent_k: IndicatorSeries = [None] * len(closes)
    for index in range(k_period - 1, len(closes)):
        top = max(highs[index - k_period + 1 : index + 1])
        bottom = min(lows[index - k_period + 1 : index + 1])
        percent_k[index] = (
            50.0
            if top == bottom
            else 100.0 * (closes[index] - bottom) / (top - bottom)
        )

    first = k_period - 1
    valid_k = [float(item) for item in percent_k[first:] if item is not None]
    valid_d = _sma_valid(valid_k, d_period)
    percent_d: IndicatorSeries = [None] * len(closes)
    for offset, item in enumerate(valid_d):
        percent_d[first + offset] = item
    return Stochastic(percent_k, percent_d)


def obv(close: Sequence[float], volume: Sequence[float]) -> IndicatorSeries:
    """Return on-balance volume, starting at zero."""
    closes = _series(close, "close")
    volumes = _series(volume, "volume")
    if len(closes) != len(volumes):
        raise ValueError("close and volume must have equal lengths")
    if any(item < 0 for item in volumes):
        raise ValueError("volume cannot be negative")
    if not closes:
        return []
    result: IndicatorSeries = [0.0]
    for index in range(1, len(closes)):
        change = 1 if closes[index] > closes[index - 1] else -1
        if closes[index] == closes[index - 1]:
            change = 0
        result.append(float(result[-1]) + change * volumes[index])
    return result


def cci(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 20,
) -> IndicatorSeries:
    """Return the Commodity Channel Index using the conventional 0.015 factor."""
    _period(period)
    highs, lows, closes = _ohlc(high, low, close)
    typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    result: IndicatorSeries = [None] * len(typical)
    for index in range(period - 1, len(typical)):
        window = typical[index - period + 1 : index + 1]
        average = sum(window) / period
        mean_deviation = sum(abs(item - average) for item in window) / period
        result[index] = (
            0.0
            if mean_deviation == 0
            else (typical[index] - average) / (0.015 * mean_deviation)
        )
    return result


def supertrend(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> Supertrend:
    """Return the Supertrend line and direction (+1 bullish, -1 bearish)."""
    _period(period)
    if not isfinite(multiplier) or multiplier <= 0:
        raise ValueError("multiplier must be a positive finite number")
    highs, lows, closes = _ohlc(high, low, close)
    average_range = atr(highs, lows, closes, period)
    size = len(closes)
    line: IndicatorSeries = [None] * size
    direction: list[int | None] = [None] * size
    upper: IndicatorSeries = [None] * size
    lower: IndicatorSeries = [None] * size

    for index in range(size):
        if average_range[index] is None:
            continue
        midpoint = (highs[index] + lows[index]) / 2.0
        basic_upper = midpoint + multiplier * float(average_range[index])
        basic_lower = midpoint - multiplier * float(average_range[index])
        if index == 0 or direction[index - 1] is None:
            upper[index] = basic_upper
            lower[index] = basic_lower
            direction[index] = 1
        else:
            previous_upper = float(upper[index - 1])
            previous_lower = float(lower[index - 1])
            previous_direction = int(direction[index - 1])
            upper[index] = (
                min(basic_upper, previous_upper)
                if closes[index - 1] <= previous_upper
                else basic_upper
            )
            lower[index] = (
                max(basic_lower, previous_lower)
                if closes[index - 1] >= previous_lower
                else basic_lower
            )
            if previous_direction == 1:
                direction[index] = -1 if closes[index] < float(lower[index]) else 1
            else:
                direction[index] = 1 if closes[index] > float(upper[index]) else -1
        line[index] = (
            float(lower[index]) if direction[index] == 1 else float(upper[index])
        )
    return Supertrend(line, direction)


def vwap(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    period: int = 20,
) -> IndicatorSeries:
    """Return rolling VWAP of typical price; zero-volume windows are None."""
    _period(period)
    highs, lows, closes = _ohlc(high, low, close)
    volumes = _series(volume, "volume")
    if len(volumes) != len(closes):
        raise ValueError("high, low, close, and volume must have equal lengths")
    if any(item < 0 for item in volumes):
        raise ValueError("volume cannot be negative")
    typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    result: IndicatorSeries = [None] * len(closes)
    for index in range(period - 1, len(closes)):
        start = index - period + 1
        window_volume = sum(volumes[start : index + 1])
        if window_volume:
            result[index] = sum(
                price * amount
                for price, amount in zip(
                    typical[start : index + 1], volumes[start : index + 1]
                )
            ) / window_volume
    return result


def bollinger_bands(
    values: Sequence[float], period: int = 20, deviations: float = 2.0
) -> BollingerBands:
    """Return simple-average Bollinger middle, upper, and lower bands."""
    _period(period)
    if not isfinite(deviations) or deviations <= 0:
        raise ValueError("deviations must be a positive finite number")
    data = _series(values)
    middle = _sma_valid(data, period)
    upper: IndicatorSeries = [None] * len(data)
    lower: IndicatorSeries = [None] * len(data)
    for index in range(period - 1, len(data)):
        window = data[index - period + 1 : index + 1]
        mean = float(middle[index])
        standard_deviation = sqrt(sum((item - mean) ** 2 for item in window) / period)
        upper[index] = mean + deviations * standard_deviation
        lower[index] = mean - deviations * standard_deviation
    return BollingerBands(middle, upper, lower)


__all__ = [
    "BollingerBands",
    "DirectionalMovement",
    "IndicatorSeries",
    "Macd",
    "Stochastic",
    "Supertrend",
    "adx",
    "atr",
    "bollinger_bands",
    "cci",
    "directional_movement",
    "ema",
    "macd",
    "obv",
    "rsi",
    "sma",
    "stochastic",
    "supertrend",
    "true_range",
    "vwap",
]
