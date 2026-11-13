"""Gösterge testleri — ribbon yönü, ddof=1, warmup semantiği."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import config
from indicators.core import (
    adx,
    add_core_indicators,
    atr_wilder,
    bollinger,
    ema_ribbon,
    macd,
    ribbon_direction,
    rsi_wilder,
)


def _ribbon(values: list[float]) -> pd.DataFrame:
    cols = {f"ema_{p}": v for p, v in zip(config.EMA_PERIODS, values)}
    return pd.DataFrame([cols])


def test_ribbon_bullish_direction() -> None:
    """ema_5 > ema_8 > ... > ema_200 -> BULLISH."""
    vals = [200.0 - i * 10 for i in range(len(config.EMA_PERIODS))]
    direction, _ = ribbon_direction(_ribbon(vals))
    assert direction == "BULLISH"


def test_ribbon_bearish_direction() -> None:
    """ema_5 < ema_8 < ... < ema_200 -> BEARISH."""
    vals = [100.0 + i * 10 for i in range(len(config.EMA_PERIODS))]
    direction, _ = ribbon_direction(_ribbon(vals))
    assert direction == "BEARISH"


def test_ribbon_equality_is_hold() -> None:
    """Herhangi bir komşu çiftte eşitlik -> HOLD."""
    vals = [200.0 - i * 10 for i in range(len(config.EMA_PERIODS))]
    vals[3] = vals[2]  # eşitlik
    direction, detail = ribbon_direction(_ribbon(vals))
    assert direction == "HOLD"
    assert detail["reason"] == "esitlik_veya_karmasik"


def test_ribbon_nan_is_hold() -> None:
    """Herhangi bir EMA NaN ise -> HOLD (0 ikamesi YOK)."""
    vals = [200.0 - i * 10 for i in range(len(config.EMA_PERIODS))]
    vals[-1] = float("nan")
    direction, detail = ribbon_direction(_ribbon(vals))
    assert direction == "HOLD"
    assert detail["reason"] == "nan_ema"


def test_ema200_nan_guard_no_zero_substitution() -> None:
    """Yetersiz satırda ema_200 NaN kalır, 0'a çevrilmez; sinyal HOLD."""
    df = pd.DataFrame(
        {
            "open_time": range(150),
            "open": np.arange(150, dtype=float) + 100,
            "high": np.arange(150, dtype=float) + 101,
            "low": np.arange(150, dtype=float) + 99,
            "close": np.arange(150, dtype=float) + 100,
            "volume": np.ones(150),
        }
    )
    ribbon = ema_ribbon(df)
    assert ribbon["ema_200"].isna().all(), "ema_200 NaN olmalı, 0 ile ikame edilmemeli"
    direction, detail = ribbon_direction(ribbon)
    assert direction == "HOLD"
    assert detail["reason"] == "nan_ema"


def test_ema200_requires_200_rows() -> None:
    """200 satırın altında ema_200 NaN; üstünde hesaplanır."""
    short = pd.DataFrame({"close": np.arange(199, dtype=float) + 1})
    assert ema_ribbon(short)["ema_200"].isna().all()
    long = pd.DataFrame({"close": np.arange(260, dtype=float) + 1})
    assert pd.notna(ema_ribbon(long)["ema_200"].iloc[-1])


def test_bollinger_ddof1_matches_sample_std() -> None:
    """Bollinger örneklem standart sapması (ddof=1) kullanmalı."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    bb = bollinger(s, period=10, num_std=2.0)
    expected_std = s.std(ddof=1)
    expected_upper = s.mean() + 2 * expected_std
    assert bb["bb_upper"].iloc[-1] == pytest.approx(expected_upper, abs=1e-12)
    # ddof=0 ile farklı olmalı (gerçekten ddof=1 kullanıldığının kanıtı)
    assert bb["bb_upper"].iloc[-1] != pytest.approx(s.mean() + 2 * s.std(ddof=0), abs=1e-12)


def test_rsi_monotonic_increase_hits_100() -> None:
    """Kesintisiz artan seride RSI 100'e yaklaşır."""
    s = pd.Series(np.arange(1, 60, dtype=float))
    rsi = rsi_wilder(s, 14)
    assert rsi.iloc[-1] == pytest.approx(100.0, abs=1e-9)


def test_rsi_bounds() -> None:
    """RSI daima 0-100 aralığında."""
    rng = np.random.default_rng(3)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 500)))
    rsi = rsi_wilder(s, 14).dropna()
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_rsi_warmup_is_nan() -> None:
    """RSI, Wilder warmup'ı tamamlanana kadar (ilk 14 değer) NaN olmalı."""
    s = pd.Series(np.arange(1, 40, dtype=float))
    rsi = rsi_wilder(s, 14)
    assert rsi.iloc[:14].isna().all()
    assert pd.notna(rsi.iloc[14])


def test_atr_wilder_warmup() -> None:
    """ATR Wilder ilk 13 satırda NaN, 14. satırda hesaplanır."""
    rng = np.random.default_rng(11)
    close = 100 + np.cumsum(rng.normal(0, 1, 100))
    df = pd.DataFrame(
        {
            "open": close - 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.ones(100),
        }
    )
    atr = atr_wilder(df, 14)
    assert atr.iloc[:13].isna().all()
    assert pd.notna(atr.iloc[13])


def test_macd_hist_warmup() -> None:
    """MACD histogram ısınma bitmeden NaN döner."""
    s = pd.Series(np.arange(1, 100, dtype=float))
    m = macd(s)
    assert m["macd_hist"].iloc[:30].isna().all()
    assert pd.notna(m["macd_hist"].iloc[-1])


def test_adx_warmup_and_range() -> None:
    """ADX zincirli warmup sonrası 0-100 aralığında olmalı."""
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(0, 1, 200))
    df = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.9,
            "low": close - 0.9,
            "close": close,
            "volume": np.ones(200),
        }
    )
    out = adx(df, 14)
    assert out["adx"].iloc[:13].isna().all()
    valid = out["adx"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_add_core_indicators_columns(ohlcv: pd.DataFrame) -> None:
    """Çekirdek gösterge kolonları ve NaN sözleşmesi."""
    out = add_core_indicators(ohlcv)
    for col in ("ema_5", "ema_200", "rsi", "macd_hist", "atr", "adx", "supertrend"):
        assert col in out.columns
    # EMA şeridi 0 ile doldurulmuş olmamalı
    assert not (out["ema_200"].dropna() == 0).any()
