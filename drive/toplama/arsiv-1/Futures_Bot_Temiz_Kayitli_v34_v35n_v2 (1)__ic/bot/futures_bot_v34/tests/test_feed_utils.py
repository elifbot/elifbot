"""Veri yardımcıları — doğrulama, kapalı mum filtresi, URL allowlist."""
from __future__ import annotations

import pandas as pd
import pytest

from data.feed_utils import (
    CandleValidationError,
    check_candle_gaps,
    filter_closed_candles,
    is_url_allowed,
    sort_and_dedup,
    to_ms,
    validate_candle_row,
)


def _row(**kw):
    base = {
        "open_time": 1_700_000_000_000,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 12.0,
    }
    base.update(kw)
    return base


def test_valid_row_passes() -> None:
    """Geçerli satır hata vermez."""
    validate_candle_row(_row())


@pytest.mark.parametrize(
    "bad",
    [
        _row(high=98.0),           # high < open
        _row(low=100.8),           # low > close
        _row(close=0.0),           # pozitif değil
        _row(volume=-1.0),         # negatif hacim
        _row(open=float("nan")),   # NaN
        _row(open_time=0),         # geçersiz ts
    ],
)
def test_invalid_rows_rejected(bad) -> None:
    """Geçersiz satırlar CandleValidationError ile reddedilir."""
    with pytest.raises(CandleValidationError):
        validate_candle_row(bad)


def test_filter_closed_candles_excludes_open_bar() -> None:
    """Kapanmamış son mum dışlanmalı (lookahead koruması)."""
    df = pd.DataFrame(
        {
            "open_time": [0, 60_000, 120_000],
            "open": [1.0, 1.0, 1.0],
            "high": [2.0, 2.0, 2.0],
            "low": [0.5, 0.5, 0.5],
            "close": [1.5, 1.5, 1.5],
            "volume": [1.0, 1.0, 1.0],
            "close_time": [60_000, 120_000, 180_000],
        }
    )
    out = filter_closed_candles(df, now_ms=150_000, timeframe_ms=60_000)
    assert len(out) == 2
    assert out["open_time"].max() == 60_000


def test_sort_and_dedup() -> None:
    """Sıralama artan olur ve tekrarlarda son kayıt tutulur."""
    df = pd.DataFrame(
        {
            "open_time": [120_000, 0, 60_000, 60_000],
            "open": [3.0, 1.0, 2.0, 2.5],
            "high": [3.0, 1.0, 2.0, 2.5],
            "low": [3.0, 1.0, 2.0, 2.5],
            "close": [3.0, 1.0, 2.0, 2.5],
            "volume": [1.0, 1.0, 1.0, 1.0],
        }
    )
    out = sort_and_dedup(df)
    assert out["open_time"].tolist() == [0, 60_000, 120_000]
    assert float(out.loc[out["open_time"] == 60_000, "open"].iloc[0]) == 2.5


def test_check_candle_gaps_detects_missing_bars() -> None:
    """Eksik mum aralıkları bulunmalı."""
    df = pd.DataFrame({"open_time": [0, 60_000, 180_000, 240_000]})
    gaps = check_candle_gaps(df, 60_000)
    assert gaps == [(60_000, 180_000)]


def test_check_candle_gaps_empty_when_contiguous() -> None:
    """Kesintisiz seride boşluk yok."""
    df = pd.DataFrame({"open_time": [0, 60_000, 120_000]})
    assert check_candle_gaps(df, 60_000) == []


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://fapi.binance.com/fapi/v1/klines", True),
        ("https://fapi.binance.com/fapi/v1/exchangeInfo", True),
        ("https://www.okx.com/api/v5/market/candles", True),
        ("https://www.okx.com/api/v5/public/instruments", True),
        ("https://api.binance.com/api/v3/klines", False),
        ("https://fapi.binance.com/fapi/v1/order", False),
        ("http://fapi.binance.com/fapi/v1/klines", False),
        ("https://evil.example.com/fapi/v1/klines", False),
        ("https://fapi.binance.com/fapi/v1/account", False),
    ],
)
def test_url_allowlist(url: str, expected: bool) -> None:
    """Yalnızca dört public uç nokta kabul edilir."""
    assert is_url_allowed(url) is expected


def test_url_with_signature_params_rejected() -> None:
    """İmza/api-key içeren sorgular reddedilir."""
    assert not is_url_allowed(
        "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&signature=abc"
    )


def test_to_ms_parsing() -> None:
    """Zaman damgası çevrimi ve ret davranışı."""
    assert to_ms("1700000000000") == 1_700_000_000_000
    assert to_ms(1_700_000_000_000) == 1_700_000_000_000
    with pytest.raises(CandleValidationError):
        to_ms("-5")
    with pytest.raises(CandleValidationError):
        to_ms("abc")
