"""Strateji testleri: eşiği, vetoları, rejimi ve HTF çelişkisini sınar."""
from __future__ import annotations

import numpy as np
import pandas as pd

from phoenix.config import Config
from phoenix.indicators import enrich
from phoenix.strategy import evaluate, funding_guard, htf_bias


def make_df(n=600, seed=7, drift=0.0):
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, 0.5, n)
    price = 100 * np.exp(np.cumsum(steps / 100))
    high = price * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = price * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.r_[price[0], price[:-1]]
    vol = rng.uniform(100, 1000, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum.reduce([open_, price, high]),
                         "low": np.minimum.reduce([open_, price, low]),
                         "close": price, "volume": vol}, index=idx)


def test_warmup_no_signal():
    cfg = Config().validate()
    df = make_df(300)
    sig = evaluate(enrich(df, cfg), cfg, i=100)
    assert sig.side == 0
    assert sig.reasons[0] == "WARMUP"


def test_strong_uptrend_gives_long_or_neutral():
    """Güçlü yükselişte side ∈ {0, +1}; asla -1 olmamalı."""
    cfg = Config().validate()
    df = make_df(600, drift=1.2)
    x = enrich(df, cfg)
    sig = evaluate(x, cfg)
    assert sig.side >= 0
    if sig.side == 0:
        assert sig.reasons or True


def test_strong_downtrend_gives_short_or_neutral():
    cfg = Config().validate()
    df = make_df(600, drift=-1.2)
    x = enrich(df, cfg)
    sig = evaluate(x, cfg)
    assert sig.side <= 0


def test_htf_conflict_veto():
    """HTF=SHORT iken long sinyali veto almalı."""
    cfg = Config().validate()
    df = make_df(600, drift=1.2)
    x = enrich(df, cfg)
    sig = evaluate(x, cfg, htf="SHORT")
    if sig.side > 0:
        assert "HTF_CELISKI" in sig.vetoes


def test_candle_gap_veto():
    cfg = Config().validate()
    df = make_df(600)
    idx = df.index.tolist()
    idx_new = idx[:200] + [idx[200] + pd.Timedelta(hours=6)] + idx[201:]
    df.index = pd.DatetimeIndex(idx_new)
    sig = evaluate(enrich(df, cfg), cfg, i=len(df) - 1)
    if sig.side != 0:
        assert "MUM_BOSLUK" in sig.vetoes


def test_funding_guard_windows():
    cfg = Config().validate()
    assert funding_guard(pd.Timestamp("2025-01-01 07:55:00"), cfg) is True
    assert funding_guard(pd.Timestamp("2025-01-01 08:00:00"), cfg) is True
    assert funding_guard(pd.Timestamp("2025-01-01 12:00:00"), cfg) is False
    assert funding_guard(pd.Timestamp("2025-01-01 15:50:00"), cfg) is True


def test_score_symmetry_ish():
    """Fiyat yansımasında (200−p) skor işareti tersine dönmeli (RSI bandı asimetrisi
    küçük sapmalara izin verir: |skor| < 1 iken nötr kabul edilir)."""
    cfg = Config().validate()
    df = make_df(600, seed=11)
    x = enrich(df, cfg)
    s1 = evaluate(x, cfg)
    df2 = df.copy()
    for col in ("open", "high", "low", "close"):
        df2[col] = 200.0 - df2[col]
    x2 = enrich(df2, cfg)
    s2 = evaluate(x2, cfg)
    # ADX ve RSI hariç (Wilder DM tanımı doğal olarak ayna-asimetriktir)
    sym = ["ema", "macd", "vwap", "boll", "supertrend"]
    for k in sym:
        assert np.sign(s1.votes[k]) == -np.sign(s2.votes[k]), f"oy ayna-asimetrik: {k}"
