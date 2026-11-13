"""Göstergeler — saf pandas/numpy, tamamen nedensel (sadece geçmiş veriyi kullanır).

sentez-bot disiplini: her seri `min_periods` ile üretilir; i. mumda okunan değer
yalnızca ≤ i verisinden hesaplanabilir. İleriye bakış (look-ahead) yoktur ve test
süiti bunu shift-testiyle kanıtlar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df.close.shift(1)
    return pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """ADX, +DI, −DI (Wilder)."""
    h, l = df.high, df.low
    up, dn = h.diff(), -l.diff()
    plus = up.where((up > dn) & (up > 0), 0.0)
    minus = dn.where((dn > up) & (dn > 0), 0.0)
    tr_s = true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr_s.replace(0, np.nan)
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr_s.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(),
                         "pdi": pdi, "mdi": mdi})


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    m = ema(close, fast) - ema(close, slow)
    sig = m.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return m, sig, m - sig


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    return mid, mid + k * sd, mid - k * sd, sd


def vwap(df: pd.DataFrame, n: int = 30) -> pd.Series:
    pv = (df.close * df.volume).rolling(n, min_periods=n).sum()
    vv = df.volume.rolling(n, min_periods=n).sum()
    return pv / vv.replace(0, np.nan)


def stoch(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    lo, hi = df.low.rolling(n, min_periods=n).min(), df.high.rolling(n, min_periods=n).max()
    k = 100 * (df.close - lo) / (hi - lo).replace(0, np.nan)
    return pd.DataFrame({"k": k, "d": k.rolling(3, min_periods=3).mean()})


def choppiness(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr1 = true_range(df).rolling(n, min_periods=n).sum()
    rng = df.high.rolling(n, min_periods=n).max() - df.low.rolling(n, min_periods=n).min()
    return 100 * np.log10(tr1 / rng.replace(0, np.nan)) / np.log10(n)


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.Series:
    """Yön işaretli supertrend: >0 long rejimi, <0 short rejimi. Kapanışa göre güncellenir.

    Başlangıç yönü close vs hl2 ile belirlenir — bu, fiyat yansıması altında
    anti-simetriyi (mirror testi) mümkün kılar.
    """
    a = atr(df, n)
    hl2 = (df.high + df.low) / 2
    ub = (hl2 + mult * a).values
    lb = (hl2 - mult * a).values
    close = df.close.values
    st = np.zeros(len(df))
    dirn = np.ones(len(df))
    dirn[0] = 1.0 if close[0] >= hl2.iloc[0] else -1.0
    st[0] = dirn[0]
    fub, flb = ub[0], lb[0]
    for i in range(1, len(df)):
        fub = ub[i] if (ub[i] < fub or close[i - 1] > fub) else fub
        flb = lb[i] if (lb[i] > flb or close[i - 1] < flb) else flb
        if st[i - 1] >= 0:
            dirn[i] = -1.0 if close[i] < flb else 1.0
        else:
            dirn[i] = 1.0 if close[i] > fub else -1.0
        st[i] = dirn[i]
    return pd.Series(st, index=df.index)


def volume_zscore(volume: pd.Series, n: int = 30) -> pd.Series:
    m = volume.rolling(n, min_periods=n).mean()
    sd = volume.rolling(n, min_periods=n).std()
    return (volume - m) / sd.replace(0, np.nan)


def enrich(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Tüm göstergeleri tek DataFrame'e ekler. Sıralama korunur, sadece geçmiş kullanılır."""
    x = df.copy().sort_index()
    s = cfg.strategy
    x["ema_f"] = ema(x.close, s.ema_fast)
    x["ema_m"] = ema(x.close, s.ema_mid)
    x["ema_s"] = ema(x.close, s.ema_slow)
    x["rsi"] = rsi(x.close, s.rsi_len)
    x["atr"] = atr(x, s.adx_len)
    dx = adx(x, s.adx_len)
    x["adx"], x["pdi"], x["mdi"] = dx.adx, dx.pdi, dx.mdi
    m, sg, h = macd(x.close)
    x["macd"], x["macd_sig"], x["macd_hist"] = m, sg, h
    x["bb_mid"], x["bb_hi"], x["bb_lo"], x["bb_sd"] = bollinger(x.close)
    x["vwap"] = vwap(x)
    stx = stoch(x)
    x["stoch_k"], x["stoch_d"] = stx.k, stx.d
    x["chop"] = choppiness(x)
    x["st"] = supertrend(x)
    x["vol_z"] = volume_zscore(x.volume)
    x["atrp"] = x.atr / x.close * 100.0
    x["bb_width_pct"] = (x.bb_hi - x.bb_lo) / x.close * 100.0
    return x
