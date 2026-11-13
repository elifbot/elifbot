"""PDF araştırma paketi — yalnız kapanmış OHLCV'den hesaplanan ek göstergeler.

Bu modül baseline skorunu değiştirmez. ``pdf_v2_snapshot`` çıktısı giriş
bağlamına eklenir ve isteğe bağlı ``pdf-confluence`` Shadow varyantı tarafından
kullanılır. Harici veri gerektiren on-chain/opsiyon/makro/sosyal seriler burada
uydurulmaz. Karmaşık market-structure alanları deterministik araştırma
yaklaşımlarıdır; borsa gerçeği veya kâr garantisi olarak sunulmaz.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from .indicators import Indicators


def _last(series: pd.Series, default: float = 0.0) -> float:
    try:
        value = float(series.iloc[-1])
        return value if math.isfinite(value) else float(default)
    except (IndexError, TypeError, ValueError, OverflowError):
        return float(default)


def _sign(value: float, tolerance: float = 1e-12) -> int:
    try:
        value = float(value)
        if not math.isfinite(value) or abs(value) <= tolerance:
            return 0
        return 1 if value > 0 else -1
    except (TypeError, ValueError, OverflowError):
        return 0


def _majority(values: Iterable[float], minimum: int = 1) -> int:
    votes = [_sign(value) for value in values]
    nonzero = [vote for vote in votes if vote]
    if len(nonzero) < minimum:
        return 0
    return _sign(sum(nonzero))


def _true_range(df: pd.DataFrame) -> pd.Series:
    previous = df["close"].shift(1)
    return pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - previous).abs(),
            (df["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def wma(series: pd.Series, period: int) -> pd.Series:
    period = max(1, int(period))
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period, min_periods=period).apply(
        lambda values: float(np.dot(values, weights) / weights.sum()), raw=True
    )


def hma(series: pd.Series, period: int = 16) -> pd.Series:
    period = max(2, int(period))
    raw = 2 * wma(series, max(1, period // 2)) - wma(series, period)
    return wma(raw, max(1, int(round(math.sqrt(period)))))


def dema(series: pd.Series, period: int = 20) -> pd.Series:
    first = Indicators.ema(series, period)
    return 2 * first - Indicators.ema(first, period)


def tema(series: pd.Series, period: int = 20) -> pd.Series:
    first = Indicators.ema(series, period)
    second = Indicators.ema(first, period)
    third = Indicators.ema(second, period)
    return 3 * first - 3 * second + third


def kama(series: pd.Series, period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    price = series.astype(float)
    change = (price - price.shift(period)).abs()
    volatility = price.diff().abs().rolling(period, min_periods=period).sum()
    efficiency = change / volatility.replace(0, np.nan)
    fastest = 2.0 / (int(fast) + 1.0)
    slowest = 2.0 / (int(slow) + 1.0)
    smoothing = (efficiency * (fastest - slowest) + slowest) ** 2
    values = price.to_numpy(dtype=float)
    weights = smoothing.to_numpy(dtype=float)
    output = np.full(len(price), np.nan)
    for i, current in enumerate(values):
        if not math.isfinite(current):
            continue
        if i == 0 or not math.isfinite(output[i - 1]):
            output[i] = current
            continue
        weight = weights[i] if math.isfinite(weights[i]) else 0.0
        output[i] = output[i - 1] + weight * (current - output[i - 1])
    return pd.Series(output, index=series.index)


def trix(series: pd.Series, period: int = 15) -> pd.Series:
    first = Indicators.ema(series, period)
    second = Indicators.ema(first, period)
    third = Indicators.ema(second, period)
    return third.pct_change() * 100.0


def roc(series: pd.Series, period: int = 12) -> pd.Series:
    return series.pct_change(periods=period) * 100.0


def tsi(series: pd.Series, long: int = 25, short: int = 13) -> pd.Series:
    momentum = series.diff()
    numerator = Indicators.ema(Indicators.ema(momentum, long), short)
    denominator = Indicators.ema(Indicators.ema(momentum.abs(), long), short)
    return (100 * numerator / denominator.replace(0, np.nan)).fillna(0.0)


def awesome_oscillator(df: pd.DataFrame) -> pd.Series:
    median = (df["high"] + df["low"]) / 2.0
    return Indicators.sma(median, 5) - Indicators.sma(median, 34)


def fisher_transform(df: pd.DataFrame, period: int = 9) -> pd.Series:
    median = (df["high"] + df["low"]) / 2.0
    lowest = median.rolling(period, min_periods=period).min()
    highest = median.rolling(period, min_periods=period).max()
    normalized = (2 * ((median - lowest) / (highest - lowest).replace(0, np.nan) - 0.5)).fillna(0.0)
    normalized = normalized.clip(-0.999, 0.999)
    values = normalized.to_numpy(dtype=float)
    transformed = np.zeros(len(values), dtype=float)
    fish = np.zeros(len(values), dtype=float)
    for i, value in enumerate(values):
        previous_value = transformed[i - 1] if i else 0.0
        previous_fish = fish[i - 1] if i else 0.0
        transformed[i] = np.clip(0.66 * value + 0.67 * previous_value, -0.999, 0.999)
        fish[i] = 0.5 * math.log((1 + transformed[i]) / (1 - transformed[i])) + 0.5 * previous_fish
    return pd.Series(fish, index=df.index)


def wavetrend(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    esa = Indicators.ema(typical, 10)
    deviation = Indicators.ema((typical - esa).abs(), 10)
    ci = (typical - esa) / (0.015 * deviation.replace(0, np.nan))
    wt1 = Indicators.ema(ci.fillna(0.0), 21)
    wt2 = Indicators.sma(wt1, 4)
    return wt1.fillna(0.0), wt2.fillna(0.0)


def choppiness(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr_sum = _true_range(df).rolling(period, min_periods=period).sum()
    highest = df["high"].rolling(period, min_periods=period).max()
    lowest = df["low"].rolling(period, min_periods=period).min()
    ratio = tr_sum / (highest - lowest).replace(0, np.nan)
    return (100 * np.log10(ratio.replace(0, np.nan)) / math.log10(period)).clip(0, 100).fillna(50.0)


def hurst_exponent(close: pd.Series, window: int = 100) -> float:
    values = close.astype(float).tail(max(40, int(window))).to_numpy(dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if len(values) < 40 or np.allclose(values, values[0]):
        return 0.5
    logs = np.log(values)
    lags = [lag for lag in (2, 4, 8, 16) if lag < len(logs) // 2]
    if len(lags) < 2:
        return 0.5
    tau = []
    for lag in lags:
        difference = logs[lag:] - logs[:-lag]
        value = float(np.std(difference, ddof=0))
        tau.append(value if value > 1e-12 else np.nan)
    valid = np.isfinite(tau)
    if valid.sum() < 2:
        return 0.5
    slope = np.polyfit(np.log(np.asarray(lags)[valid]), np.log(np.asarray(tau)[valid]), 1)[0]
    return float(np.clip(slope, 0.0, 1.0)) if math.isfinite(slope) else 0.5


def volatility_pack(df: pd.DataFrame, window: int = 20) -> dict[str, float]:
    sample = df.tail(max(10, int(window)))
    close = sample["close"].astype(float)
    log_returns = np.log(close / close.shift(1).replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    realized = float(log_returns.std(ddof=0) * 100) if len(log_returns) > 1 else 0.0
    high_low = np.log(sample["high"].astype(float) / sample["low"].astype(float).replace(0, np.nan))
    high_low = high_low.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    parkinson = math.sqrt(max(0.0, float((high_low**2).mean()) / (4 * math.log(2)))) * 100
    open_close = np.log(sample["close"].astype(float) / sample["open"].astype(float).replace(0, np.nan))
    open_close = open_close.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    garman = math.sqrt(max(0.0, float((0.5 * high_low**2 - (2 * math.log(2) - 1) * open_close**2).mean()))) * 100
    return {
        "realized_volatility_pct": realized if math.isfinite(realized) else 0.0,
        "parkinson_volatility_pct": parkinson if math.isfinite(parkinson) else 0.0,
        "garman_klass_volatility_pct": garman if math.isfinite(garman) else 0.0,
    }


def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    high, low, close, volume = (df[name].astype(float) for name in ("high", "low", "close", "volume"))
    multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    flow = multiplier.fillna(0.0) * volume
    return (flow.rolling(period, min_periods=period).sum() / volume.rolling(period, min_periods=period).sum().replace(0, np.nan)).fillna(0.0)


def accumulation_distribution(df: pd.DataFrame) -> pd.Series:
    high, low, close, volume = (df[name].astype(float) for name in ("high", "low", "close", "volume"))
    multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    return (multiplier.fillna(0.0) * volume).cumsum()


def vortex(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series]:
    high, low = df["high"].astype(float), df["low"].astype(float)
    plus = (high - low.shift(1)).abs()
    minus = (low - high.shift(1)).abs()
    denominator = _true_range(df).rolling(period, min_periods=period).sum().replace(0, np.nan)
    return (
        (plus.rolling(period, min_periods=period).sum() / denominator).fillna(0.0),
        (minus.rolling(period, min_periods=period).sum() / denominator).fillna(0.0),
    )


def ichimoku(df: pd.DataFrame) -> dict[str, pd.Series]:
    def midpoint(period: int) -> pd.Series:
        return (df["high"].rolling(period, min_periods=period).max() + df["low"].rolling(period, min_periods=period).min()) / 2.0
    tenkan = midpoint(9)
    kijun = midpoint(26)
    span_a = (tenkan + kijun) / 2.0
    span_b = midpoint(52)
    return {"tenkan": tenkan, "kijun": kijun, "span_a": span_a, "span_b": span_b}


def parabolic_sar(df: pd.DataFrame, step: float = 0.02, maximum: float = 0.2) -> tuple[pd.Series, pd.Series]:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    sar_values = np.full(n, np.nan)
    directions = np.zeros(n, dtype=int)
    if n == 0:
        return pd.Series(sar_values, index=df.index), pd.Series(directions, index=df.index)
    uptrend = bool(n < 2 or close[1] >= close[0])
    sar = low[0] if uptrend else high[0]
    extreme = high[0] if uptrend else low[0]
    acceleration = float(step)
    for i in range(n):
        if i:
            previous_sar = sar
            sar = previous_sar + acceleration * (extreme - previous_sar)
            if uptrend:
                sar = min(sar, low[i - 1], low[max(0, i - 2)])
                if low[i] < sar:
                    uptrend = False
                    sar = extreme
                    extreme = low[i]
                    acceleration = float(step)
                elif high[i] > extreme:
                    extreme = high[i]
                    acceleration = min(float(maximum), acceleration + float(step))
            else:
                sar = max(sar, high[i - 1], high[max(0, i - 2)])
                if high[i] > sar:
                    uptrend = True
                    sar = extreme
                    extreme = high[i]
                    acceleration = float(step)
                elif low[i] < extreme:
                    extreme = low[i]
                    acceleration = min(float(maximum), acceleration + float(step))
        sar_values[i] = sar
        directions[i] = 1 if uptrend else -1
    return pd.Series(sar_values, index=df.index), pd.Series(directions, index=df.index)


def alligator(df: pd.DataFrame) -> dict[str, pd.Series]:
    median = (df["high"] + df["low"]) / 2.0
    def smma(period: int, shift: int) -> pd.Series:
        return median.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().shift(shift)
    return {"jaw": smma(13, 8), "teeth": smma(8, 5), "lips": smma(5, 3)}


def chandelier(df: pd.DataFrame, period: int = 22, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    atr = Indicators.atr(df["high"], df["low"], df["close"], period)
    long = df["high"].rolling(period, min_periods=period).max() - multiplier * atr
    short = df["low"].rolling(period, min_periods=period).min() + multiplier * atr
    return long, short


def linear_regression(close: pd.Series, window: int = 50) -> dict[str, float]:
    values = close.astype(float).tail(max(10, int(window))).to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 10:
        return {"center": _last(close), "upper": _last(close), "lower": _last(close), "slope_pct": 0.0}
    x = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    fitted = intercept + slope * x
    deviation = float(np.std(values - fitted, ddof=0))
    center = float(fitted[-1])
    base = abs(center) if abs(center) > 1e-12 else 1.0
    return {"center": center, "upper": center + 2 * deviation, "lower": center - 2 * deviation, "slope_pct": float(slope / base * 100)}


def _swing_indices(values: np.ndarray, left: int = 2, right: int = 2, high: bool = True) -> list[int]:
    result = []
    for i in range(left, len(values) - right):
        window = values[i - left:i + right + 1]
        current = values[i]
        if not math.isfinite(current):
            continue
        if (high and current == np.nanmax(window)) or (not high and current == np.nanmin(window)):
            result.append(i)
    return result


def divergence(df: pd.DataFrame, oscillator: pd.Series, lookback: int = 50) -> int:
    start = max(0, len(df) - int(lookback))
    price = df["close"].astype(float).to_numpy()[start:]
    osc = oscillator.astype(float).to_numpy()[start:]
    lows = _swing_indices(price, high=False)
    highs = _swing_indices(price, high=True)
    if len(lows) >= 2:
        first, second = lows[-2], lows[-1]
        if price[second] < price[first] and osc[second] > osc[first]:
            return 1
    if len(highs) >= 2:
        first, second = highs[-2], highs[-1]
        if price[second] > price[first] and osc[second] < osc[first]:
            return -1
    return 0


def market_structure(df: pd.DataFrame) -> dict[str, float | int | str]:
    close = df["close"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    highs = _swing_indices(high, left=3, right=3, high=True)
    lows = _swing_indices(low, left=3, right=3, high=False)
    last_high = high[highs[-1]] if highs else 0.0
    last_low = low[lows[-1]] if lows else 0.0
    trend = 0
    if len(highs) >= 2 and len(lows) >= 2:
        hh = high[highs[-1]] > high[highs[-2]]
        hl = low[lows[-1]] > low[lows[-2]]
        lh = high[highs[-1]] < high[highs[-2]]
        ll = low[lows[-1]] < low[lows[-2]]
        trend = 1 if hh and hl else (-1 if lh and ll else 0)
    bos = 1 if last_high and close[-1] > last_high else (-1 if last_low and close[-1] < last_low else 0)
    choch = bos if bos and trend and bos != trend else 0
    sweep = 0
    if last_high and high[-1] > last_high and close[-1] < last_high:
        sweep = -1
    elif last_low and low[-1] < last_low and close[-1] > last_low:
        sweep = 1
    structure_direction = choch or bos or trend
    return {
        "structure_trend": trend,
        "bos": bos,
        "choch": choch,
        "liquidity_sweep": sweep,
        "structure_direction": structure_direction,
        "last_swing_high": last_high,
        "last_swing_low": last_low,
    }


def fair_value_gap(df: pd.DataFrame) -> dict[str, float | int]:
    if len(df) < 3:
        return {"fvg_direction": 0, "fvg_lower": 0.0, "fvg_upper": 0.0, "fvg_size_pct": 0.0}
    first, third = df.iloc[-3], df.iloc[-1]
    price = float(third["close"])
    if float(third["low"]) > float(first["high"]):
        lower, upper, direction = float(first["high"]), float(third["low"]), 1
    elif float(third["high"]) < float(first["low"]):
        lower, upper, direction = float(third["high"]), float(first["low"]), -1
    else:
        return {"fvg_direction": 0, "fvg_lower": 0.0, "fvg_upper": 0.0, "fvg_size_pct": 0.0}
    return {"fvg_direction": direction, "fvg_lower": lower, "fvg_upper": upper, "fvg_size_pct": (upper - lower) / max(price, 1e-12) * 100}


def order_block(df: pd.DataFrame) -> dict[str, float | int]:
    if len(df) < 5:
        return {"order_block_direction": 0, "order_block_lower": 0.0, "order_block_upper": 0.0}
    atr = Indicators.atr(df["high"], df["low"], df["close"], 14).fillna(0.0).to_numpy()
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    direction = 0
    lower = upper = 0.0
    for i in range(max(1, len(df) - 25), len(df) - 1):
        body = closes[i] - opens[i]
        if atr[i] <= 0 or abs(body) < 1.5 * atr[i]:
            continue
        if body > 0 and closes[i - 1] < opens[i - 1]:
            direction, lower, upper = 1, float(lows[i - 1]), float(highs[i - 1])
        elif body < 0 and closes[i - 1] > opens[i - 1]:
            direction, lower, upper = -1, float(lows[i - 1]), float(highs[i - 1])
    midpoint = (lower + upper) / 2 if direction else 0.0
    if direction and abs(closes[-1] - midpoint) > max(atr[-1], 1e-12) * 2:
        direction = 0
    return {"order_block_direction": direction, "order_block_lower": lower, "order_block_upper": upper}


def candle_patterns(df: pd.DataFrame) -> dict[str, int]:
    if len(df) < 2:
        return {"bullish_engulfing": 0, "bearish_engulfing": 0, "pin_bar_direction": 0}
    previous, current = df.iloc[-2], df.iloc[-1]
    bullish = int(previous["close"] < previous["open"] and current["close"] > current["open"] and current["open"] <= previous["close"] and current["close"] >= previous["open"])
    bearish = int(previous["close"] > previous["open"] and current["close"] < current["open"] and current["open"] >= previous["close"] and current["close"] <= previous["open"])
    body = abs(float(current["close"] - current["open"]))
    upper = float(current["high"] - max(current["close"], current["open"]))
    lower = float(min(current["close"], current["open"]) - current["low"])
    pin = 1 if lower >= max(2 * body, 1e-12) and upper <= max(body, 1e-12) else (-1 if upper >= max(2 * body, 1e-12) and lower <= max(body, 1e-12) else 0)
    return {"bullish_engulfing": bullish, "bearish_engulfing": bearish, "pin_bar_direction": pin}


def pivot_and_fibonacci(df: pd.DataFrame) -> dict[str, float]:
    if len(df) < 2:
        price = _last(df["close"])
        return {"pivot": price, "pivot_r1": price, "pivot_r2": price, "pivot_s1": price, "pivot_s2": price, "fib_382": price, "fib_500": price, "fib_618": price}
    previous = df.iloc[-2]
    pivot = float((previous["high"] + previous["low"] + previous["close"]) / 3)
    r1 = 2 * pivot - float(previous["low"])
    s1 = 2 * pivot - float(previous["high"])
    r2 = pivot + float(previous["high"] - previous["low"])
    s2 = pivot - float(previous["high"] - previous["low"])
    sample = df.tail(50)
    highest, lowest = float(sample["high"].max()), float(sample["low"].min())
    difference = highest - lowest
    return {"pivot": pivot, "pivot_r1": r1, "pivot_r2": r2, "pivot_s1": s1, "pivot_s2": s2, "fib_382": highest - 0.382 * difference, "fib_500": highest - 0.5 * difference, "fib_618": highest - 0.618 * difference}


def pdf_v2_snapshot(df: pd.DataFrame) -> dict:
    """Kapanmış mumlardan PDF teknik paketinin JSON-güvenli özetini üret."""
    if df is None or len(df) < 10:
        return {"schema": "pdf-v2-technical-v1", "data_ready": False, "values": {}, "family_votes": {}, "family_details": {}}
    close, high, low = (df[name].astype(float) for name in ("close", "high", "low"))
    price = float(close.iloc[-1])
    kama_s, hma_s, dema_s, tema_s = kama(close), hma(close), dema(close), tema(close)
    trix_s, roc_s, tsi_s = trix(close), roc(close), tsi(close)
    ao_s, fisher_s = awesome_oscillator(df), fisher_transform(df)
    wt1_s, wt2_s = wavetrend(df)
    chop_s = choppiness(df)
    adx_s, pdi_s, mdi_s = Indicators.adx(high, low, close)
    adxr_s = (adx_s + adx_s.shift(14)) / 2.0
    dx_s = (100 * (pdi_s - mdi_s).abs() / (pdi_s + mdi_s).replace(0, np.nan)).fillna(0.0)
    vi_plus_s, vi_minus_s = vortex(df)
    cloud = ichimoku(df)
    psar_s, psar_dir_s = parabolic_sar(df)
    gator = alligator(df)
    chandelier_long_s, chandelier_short_s = chandelier(df)
    cmf_s, ad_s = cmf(df), accumulation_distribution(df)
    obv_s = Indicators.obv(close, df["volume"].astype(float))
    bb_u, bb_m, bb_l = Indicators.bollinger(close)
    bb_percent = ((close - bb_l) / (bb_u - bb_l).replace(0, np.nan)).fillna(0.5)
    structure = market_structure(df)
    fvg = fair_value_gap(df)
    ob = order_block(df)
    patterns = candle_patterns(df)
    levels = pivot_and_fibonacci(df)
    regression = linear_regression(close)
    volatility = volatility_pack(df)
    rsi_s = Indicators.rsi(close)
    _, _, macd_h_s = Indicators.macd(close)
    rsi_div = divergence(df, rsi_s)
    macd_div = divergence(df, macd_h_s)
    kama_value, hma_value, tema_value = (_last(series, price) for series in (kama_s, hma_s, tema_s))
    trend_parts = [
        price - kama_value,
        price - hma_value,
        price - tema_value,
        kama_value - _last(kama_s.iloc[:-1], kama_value),
        price - max(_last(cloud["span_a"], price), _last(cloud["span_b"], price)) if price else 0,
        _last(psar_dir_s, 0),
        _last(gator["lips"], price) - _last(gator["jaw"], price),
        regression["slope_pct"],
    ]
    momentum_parts = [
        _last(roc_s), _last(tsi_s), _last(ao_s), _last(fisher_s),
        _last(wt1_s) - _last(wt2_s), rsi_div, macd_div,
    ]
    volume_parts = [
        _last(cmf_s),
        _last(ad_s) - _last(ad_s.iloc[:-6], _last(ad_s)),
        _last(obv_s) - _last(obv_s.iloc[:-6], _last(obv_s)),
    ]
    structure_parts = [structure["structure_direction"], structure["liquidity_sweep"], fvg["fvg_direction"], ob["order_block_direction"], patterns["bullish_engulfing"] - patterns["bearish_engulfing"], patterns["pin_bar_direction"]]
    chop_value = _last(chop_s, 50.0)
    hurst_value = hurst_exponent(close)
    di_direction = _sign(_last(pdi_s) - _last(mdi_s)) if _last(adx_s) >= 20 and chop_value < 60 else 0
    regime_parts = [di_direction, di_direction if hurst_value >= 0.55 else 0]
    family_details = {
        "trend": [_sign(value) for value in trend_parts],
        "momentum": [_sign(value) for value in momentum_parts],
        "volume": [_sign(value) for value in volume_parts],
        "structure": [_sign(value) for value in structure_parts],
        "regime": [_sign(value) for value in regime_parts],
    }
    family_votes = {name: _majority(parts, minimum=1) for name, parts in family_details.items()}
    values = {
        "kama": kama_value, "hma": hma_value, "dema": _last(dema_s, price), "tema": tema_value,
        "trix": _last(trix_s), "roc": _last(roc_s), "tsi": _last(tsi_s),
        "awesome_oscillator": _last(ao_s), "fisher_transform": _last(fisher_s),
        "wavetrend": _last(wt1_s), "wavetrend_signal": _last(wt2_s),
        "choppiness": chop_value, "hurst": hurst_value,
        "adx": _last(adx_s), "adxr": _last(adxr_s), "dx": _last(dx_s),
        "vortex_plus": _last(vi_plus_s), "vortex_minus": _last(vi_minus_s),
        "ichimoku_tenkan": _last(cloud["tenkan"], price), "ichimoku_kijun": _last(cloud["kijun"], price),
        "ichimoku_span_a": _last(cloud["span_a"], price), "ichimoku_span_b": _last(cloud["span_b"], price),
        "parabolic_sar": _last(psar_s, price), "parabolic_sar_direction": _last(psar_dir_s),
        "alligator_jaw": _last(gator["jaw"], price), "alligator_teeth": _last(gator["teeth"], price), "alligator_lips": _last(gator["lips"], price),
        "linear_regression_center": regression["center"], "linear_regression_upper": regression["upper"], "linear_regression_lower": regression["lower"], "linear_regression_slope_pct": regression["slope_pct"],
        "cmf": _last(cmf_s), "accumulation_distribution": _last(ad_s),
        "bollinger_percent_b": _last(bb_percent, 0.5),
        "chandelier_long": _last(chandelier_long_s, price), "chandelier_short": _last(chandelier_short_s, price),
        "rsi_divergence": rsi_div, "macd_divergence": macd_div,
        **volatility, **structure, **fvg, **ob, **patterns, **levels,
    }
    return {
        "schema": "pdf-v2-technical-v1",
        "data_ready": bool(len(df) >= 60 and price > 0),
        "source": "closed OHLCV only; no external/on-chain/options/macro data",
        "values": values,
        "family_votes": family_votes,
        "family_details": family_details,
    }
