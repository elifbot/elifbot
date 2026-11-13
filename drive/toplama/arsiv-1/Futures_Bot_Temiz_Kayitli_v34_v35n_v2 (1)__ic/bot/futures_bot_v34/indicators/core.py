"""
indicators/core.py — Trend / momentum / volatilite göstergeleri.

Tüm fonksiyonlar yalnızca KAPANMIŞ mumlardan oluşan DataFrame alır.
Warmup semantiği bilinçli olarak muhafazakârdır: yeterli geçmiş yoksa
sonuç NaN kalır ve NaN asla 0 ile ikame EDİLMEZ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


# ---------------------------------------------------------------------------
# Hareketli ortalamalar
# ---------------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    """EMA — adjust=False, min_periods=period (warmup korunur)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Basit hareketli ortalama."""
    return series.rolling(window=period, min_periods=period).mean()


def ema_ribbon(
    df: pd.DataFrame, periods: tuple[int, ...] = config.EMA_PERIODS
) -> pd.DataFrame:
    """EMA şeridini kolonlar halinde döndürür (ema_5 ... ema_200)."""
    close = df["close"]
    return pd.DataFrame(
        {f"ema_{p}": ema(close, p) for p in periods}, index=df.index
    )


def ribbon_direction(
    ribbon: pd.DataFrame, periods: tuple[int, ...] = config.EMA_PERIODS
) -> tuple[str, dict[str, object]]:
    """
    EMA şeridi yönünü belirler.

    BULLISH: ema_5 > ema_8 > ... > ema_200 (her komşu çiftte KESİN büyüktür)
    BEARISH: ema_5 < ema_8 < ... < ema_200 (her komşu çiftte KESİN küçüktür)
    HERHANGİ bir çiftte eşitlik veya NaN -> HOLD

    # BUG FIX: prior code substituted 0 for NaN ema_200, corrupting ribbon
    #          width and the bullish flag. NaN now propagates to HOLD.

    NOT: EMA şeridini zorunlu giriş kapısı yapmak deneysel bir yaklaşımdır
    (Shadow Lab alanı); tek başına kanıtlanmış bir avantaj iddiası değildir.
    """
    detail: dict[str, object] = {"pairs_total": len(periods) - 1, "pairs_ok": 0}
    if ribbon.empty:
        detail["reason"] = "bos_serit"
        return "HOLD", detail

    last = ribbon.iloc[-1]
    cols = [f"ema_{p}" for p in periods]

    if last[cols].isna().any():
        detail["reason"] = "nan_ema"
        return "HOLD", detail

    values = [float(last[c]) for c in cols]
    detail["ema_200"] = values[-1]

    strictly_desc = all(a > b for a, b in zip(values, values[1:]))
    strictly_asc = all(a < b for a, b in zip(values, values[1:]))

    if strictly_desc and not strictly_asc:
        detail["pairs_ok"] = len(periods) - 1
        return "BULLISH", detail
    if strictly_asc and not strictly_desc:
        detail["pairs_ok"] = len(periods) - 1
        return "BEARISH", detail

    detail["reason"] = "esitlik_veya_karmasik"
    detail["pairs_ok"] = sum(
        1 for a, b in zip(values, values[1:]) if (a > b) or (a < b)
    )
    return "HOLD", detail


# ---------------------------------------------------------------------------
# Volatilite
# ---------------------------------------------------------------------------
def bollinger(
    series: pd.Series,
    period: int = config.BOLLINGER_PERIOD,
    num_std: float = config.BOLLINGER_STD,
) -> pd.DataFrame:
    """
    Bollinger bantları.

    # ddof=1: örneklem standart sapması, TradingView varsayılanıyla aynı
    #         yöndedir; ddof=0 daha dar bant verir. Tüm TV sürümleriyle
    #         birebir aynı olduğu iddia EDİLMEZ.
    """
    mid = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=1)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid
    return pd.DataFrame(
        {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width},
        index=series.index,
    )


def atr_wilder(df: pd.DataFrame, period: int = config.ATR_PERIOD) -> pd.Series:
    """ATR — Wilder yumuşatması (alpha = 1/period)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------
def rsi_wilder(series: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    """RSI — Wilder yumuşatması. Kayıp sıfırsa RSI=100."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 ve avg_gain > 0 -> 100; ikisi de 0 -> NaN bırakılır.
    rsi = rsi.where(~((avg_loss == 0.0) & (avg_gain > 0.0)), 100.0)
    return rsi


def macd(
    series: pd.Series,
    fast: int = config.MACD_FAST,
    slow: int = config.MACD_SLOW,
    signal: int = config.MACD_SIGNAL,
) -> pd.DataFrame:
    """MACD çizgisi, sinyal ve histogram."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": signal_line, "macd_hist": hist},
        index=series.index,
    )


def adx(
    df: pd.DataFrame, period: int = config.ADX_PERIOD
) -> pd.DataFrame:
    """ADX, +DI, -DI — zincirli Wilder warmup."""
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    alpha = 1 / period
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_sm = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_sm = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    plus_di = 100.0 * plus_sm / atr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_sm / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_line = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    return pd.DataFrame(
        {"adx": adx_line, "plus_di": plus_di, "minus_di": minus_di}, index=df.index
    )


def stoch_rsi(
    series: pd.Series,
    period: int = config.STOCH_RSI_PERIOD,
    k: int = config.STOCH_RSI_K,
    d: int = config.STOCH_RSI_D,
) -> pd.DataFrame:
    """Stokastik RSI (%K, %D)."""
    rsi = rsi_wilder(series, period)
    lowest = rsi.rolling(window=period, min_periods=period).min()
    highest = rsi.rolling(window=period, min_periods=period).max()
    rng = (highest - lowest).replace(0.0, np.nan)
    stoch_k = 100.0 * (rsi - lowest) / rng
    stoch_k = stoch_k.rolling(window=k, min_periods=k).mean()
    stoch_d = stoch_k.rolling(window=d, min_periods=d).mean()
    return pd.DataFrame({"stoch_rsi_k": stoch_k, "stoch_rsi_d": stoch_d}, index=series.index)


# ---------------------------------------------------------------------------
# Supertrend
# ---------------------------------------------------------------------------
def supertrend(
    df: pd.DataFrame,
    period: int = config.SUPERTREND_PERIOD,
    multiplier: float = config.SUPERTREND_MULT,
) -> pd.DataFrame:
    """
    Supertrend — iteratif flip mantığı.

    trend: 1 = yukarı, -1 = aşağı, NaN = warmup (ATR hazır değil).
    """
    atr = atr_wilder(df, period)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper = (hl2 + multiplier * atr).to_numpy(dtype=float)
    lower = (hl2 - multiplier * atr).to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr_np = atr.to_numpy(dtype=float)

    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = np.full(n, np.nan)

    start = int(np.argmax(~np.isnan(atr_np))) if np.any(~np.isnan(atr_np)) else n
    if start >= n:
        return pd.DataFrame(
            {"supertrend": np.nan, "st_trend": np.nan}, index=df.index
        )

    final_upper[start] = upper[start]
    final_lower[start] = lower[start]
    trend[start] = 1.0

    for i in range(start + 1, n):
        final_upper[i] = (
            upper[i]
            if (np.isnan(final_upper[i - 1]) or upper[i] < final_upper[i - 1]
                or close[i - 1] > final_upper[i - 1])
            else final_upper[i - 1]
        )
        final_lower[i] = (
            lower[i]
            if (np.isnan(final_lower[i - 1]) or lower[i] > final_lower[i - 1]
                or close[i - 1] < final_lower[i - 1])
            else final_lower[i - 1]
        )

        if trend[i - 1] == 1.0 and close[i] < final_lower[i]:
            trend[i] = -1.0
        elif trend[i - 1] == -1.0 and close[i] > final_upper[i]:
            trend[i] = 1.0
        else:
            trend[i] = trend[i - 1]

    line = np.where(trend == 1.0, final_lower, final_upper)
    return pd.DataFrame({"supertrend": line, "st_trend": trend}, index=df.index)


def add_core_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Sık kullanılan çekirdek göstergeleri tek çağrıda ekler."""
    out = df.copy()
    out = pd.concat([out, ema_ribbon(out)], axis=1)
    out = pd.concat([out, bollinger(out["close"])], axis=1)
    out["rsi"] = rsi_wilder(out["close"])
    out = pd.concat([out, macd(out["close"])], axis=1)
    out["atr"] = atr_wilder(out)
    out = pd.concat([out, adx(out)], axis=1)
    out = pd.concat([out, stoch_rsi(out["close"])], axis=1)
    out = pd.concat([out, supertrend(out)], axis=1)
    return out
