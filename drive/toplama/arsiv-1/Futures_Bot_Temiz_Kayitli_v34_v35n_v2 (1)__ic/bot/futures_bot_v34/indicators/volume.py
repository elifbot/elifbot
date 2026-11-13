"""
indicators/volume.py — Hacim / kanal tabanlı göstergeler.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume (kapanış yönüne göre kümülatif hacim)."""
    direction = np.sign(df["close"].diff()).fillna(0.0)
    return (direction * df["volume"]).cumsum()


def session_vwap(df: pd.DataFrame, session_ms: int = 86_400_000) -> pd.Series:
    """
    Oturum VWAP'ı — her gün (UTC) başında sıfırlanır.

    Typical price = (H + L + C) / 3.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"]
    session_id = (df["open_time"] // session_ms).astype("int64")
    cum_pv = pv.groupby(session_id).cumsum()
    cum_v = df["volume"].groupby(session_id).cumsum()
    return cum_pv / cum_v.replace(0.0, np.nan)


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    raw_flow = tp * df["volume"]
    delta = tp.diff()
    pos = raw_flow.where(delta > 0, 0.0)
    neg = raw_flow.where(delta < 0, 0.0)
    pos_sum = pos.rolling(period, min_periods=period).sum()
    neg_sum = neg.rolling(period, min_periods=period).sum()
    ratio = pos_sum / neg_sum.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + ratio))


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    ma = tp.rolling(period, min_periods=period).mean()
    # Ortalama mutlak sapma (mean absolute deviation) — klasik CCI tanımı.
    mad = tp.rolling(period, min_periods=period).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    )
    return (tp - ma) / (0.015 * mad.replace(0.0, np.nan))


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R (-100..0)."""
    highest = df["high"].rolling(period, min_periods=period).max()
    lowest = df["low"].rolling(period, min_periods=period).min()
    rng = (highest - lowest).replace(0.0, np.nan)
    return -100.0 * (highest - df["close"]) / rng


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian kanalı."""
    upper = df["high"].rolling(period, min_periods=period).max()
    lower = df["low"].rolling(period, min_periods=period).min()
    mid = (upper + lower) / 2.0
    return pd.DataFrame(
        {"dc_upper": upper, "dc_lower": lower, "dc_mid": mid}, index=df.index
    )


def keltner(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """Keltner kanalı (EMA + ATR)."""
    from indicators.core import atr_wilder, ema

    mid = ema(df["close"], period)
    atr = atr_wilder(df, period)
    return pd.DataFrame(
        {
            "kc_mid": mid,
            "kc_upper": mid + mult * atr,
            "kc_lower": mid - mult * atr,
        },
        index=df.index,
    )


def bb_keltner_squeeze(
    df: pd.DataFrame, period: int = config.SQUEEZE_LOOKBACK
) -> pd.DataFrame:
    """
    BB-Keltner squeeze: Bollinger bantları Keltner kanalının içine sıkıştığında
    squeeze açıktır (volatilite sıkışması).

    'squeeze_on' = bb_upper < kc_upper AND bb_lower > kc_lower
    """
    from indicators.core import bollinger

    bb = bollinger(df["close"], period)
    kc = keltner(df, period)
    on = (bb["bb_upper"] < kc["kc_upper"]) & (bb["bb_lower"] > kc["kc_lower"])
    width = (bb["bb_upper"] - bb["bb_lower"]).replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "squeeze_on": on,
            "squeeze_release": on.shift(1, fill_value=False) & ~on,
            "bb_kc_ratio": width / (kc["kc_upper"] - kc["kc_lower"]).replace(0.0, np.nan),
        },
        index=df.index,
    )


def volume_zscore(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Hacim z-skoru (ddof=1 örneklem standart sapması)."""
    mean = df["volume"].rolling(period, min_periods=period).mean()
    std = df["volume"].rolling(period, min_periods=period).std(ddof=1)
    return (df["volume"] - mean) / std.replace(0.0, np.nan)


def add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Hacim göstergelerini tek çağrıda ekler."""
    out = df.copy()
    out["obv"] = obv(out)
    out["vwap"] = session_vwap(out)
    out["mfi"] = mfi(out)
    out["cci"] = cci(out)
    out["williams_r"] = williams_r(out)
    out = pd.concat([out, donchian(out)], axis=1)
    out = pd.concat([out, bb_keltner_squeeze(out)], axis=1)
    out["volume_z"] = volume_zscore(out)
    return out
