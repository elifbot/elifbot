"""Gösterge testleri: nedensellik (look-ahead yok) + bilinen değerler."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from phoenix.config import Config
from phoenix.indicators import adx, atr, bollinger, choppiness, ema, enrich, rsi, supertrend


def make_df(n=600, seed=42):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.5, n)
    price = 100 * np.exp(np.cumsum(steps / 100))
    high = price * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = price * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.r_[price[0], price[:-1]]
    vol = rng.uniform(100, 1000, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum.reduce([open_, price, high]),
                         "low": np.minimum.reduce([open_, price, low]),
                         "close": price, "volume": vol}, index=idx)


def test_ema_causal():
    """EMA[i], i-1'deki veriyi değiştirmemeli (shift invariance)."""
    df = make_df()
    e1 = ema(df.close, 20)
    df2 = df.copy()
    df2.loc[df2.index[-1], "close"] = df.close.iloc[-1] * 3  # son mumu boz
    e2 = ema(df2.close, 20)
    # son mumun değerleri değişir ama ÖNCEKİLER DEĞİŞMEZ (NaN'ler eşit kabul edilir)
    assert np.allclose(e1.iloc[:-1], e2.iloc[:-1], equal_nan=True)
    assert not np.isclose(e1.iloc[-1], e2.iloc[-1])


def test_rsi_range():
    df = make_df()
    r = rsi(df.close)
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_positive_after_warmup():
    df = make_df()
    a = atr(df)
    assert (a.iloc[20:] > 0).all()


def test_adx_bounds():
    df = make_df()
    d = adx(df)
    assert ((d.adx.dropna() >= 0) & (d.adx.dropna() <= 100)).all()


def test_supertrend_directional():
    df = make_df()
    st = supertrend(df)
    assert set(st.unique()) <= {-1.0, 0.0, 1.0}


def test_chop_high_in_range():
    """Yatay seride choppiness yükselecek (100'e yakın)."""
    n = 300
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    flat = pd.DataFrame({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0,
                         "volume": 500.0}, index=idx)
    c = choppiness(flat)
    assert c.iloc[-1] > 70


def test_enrich_columns_and_no_nan_after_warmup():
    cfg = Config().validate()
    df = make_df()
    x = enrich(df, cfg)
    need = {"ema_f", "ema_m", "ema_s", "rsi", "atr", "adx", "pdi", "mdi", "macd_hist",
            "bb_mid", "vwap", "chop", "st", "vol_z", "atrp", "bb_width_pct"}
    assert need <= set(x.columns)
    tail = x.iloc[-100:]
    assert tail[["ema_f", "ema_m", "ema_s", "rsi", "atr", "adx", "chop"]].notna().all().all()


def test_bb_width_zero_on_flat():
    n = 60
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    flat = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
                         "volume": 500.0}, index=idx)
    mid, hi, lo, sd = bollinger(flat.close)
    assert sd.iloc[-1] == 0
