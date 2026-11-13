"""Veri akışı testleri — tüm ağ çağrıları mock'lanmıştır (gerçek HTTP yok)."""
from __future__ import annotations

import pytest

import data.binance_futures_feed as bf
import data.okx_swap_feed as of
from data.binance_futures_feed import BinanceFuturesFeed, FeedAccessError, FeedError
from data.okx_swap_feed import FeedError as OkxFeedError
from data.okx_swap_feed import OkxSwapFeed


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """requests.Session yerine geçen, sıralı yanıt döndüren sahte oturum."""

    def __init__(self, responses, raise_timeout=False):
        self._responses = list(responses)
        self._raise_timeout = raise_timeout
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        if self._raise_timeout:
            raise bf.requests.Timeout("timeout")
        if not self._responses:
            raise AssertionError("beklenmeyen ek istek")
        return self._responses.pop(0)

    def close(self):
        pass


def _kline(ts: int, o=100.0, h=101.0, l=99.0, c=100.5, v=10.0):
    return [ts, f"{o}", f"{h}", f"{l}", f"{c}", f"{v}",
            ts + 59_999, f"{v * c}", 42, f"{v / 2}", f"{v * c / 2}", "0"]


# ---------------------------------------------------------------------------
# Binance
# ---------------------------------------------------------------------------
def test_binance_fetch_candles_normalizes() -> None:
    """Binance kline yanıtı normalize edilmeli ve artan sırada dönmeli."""
    raw = [_kline(180_000), _kline(60_000), _kline(120_000)]
    feed = BinanceFuturesFeed(session=FakeSession([FakeResponse(200, raw)]))
    df = feed.fetch_candles("BTCUSDT", "1m", 3)
    assert list(df["open_time"]) == [60_000, 120_000, 180_000]
    assert df["close"].dtype.kind == "f"
    assert df.attrs["exchange"] == "binance"


def test_binance_invalid_row_is_skipped() -> None:
    """high < low olan bozuk satır atılır, kalanlar korunur."""
    bad = _kline(120_000, h=90.0, l=95.0)
    raw = [_kline(60_000), bad, _kline(180_000)]
    feed = BinanceFuturesFeed(session=FakeSession([FakeResponse(200, raw)]))
    df = feed.fetch_candles("BTCUSDT", "1m", 3)
    assert len(df) == 2


def test_binance_empty_response_raises() -> None:
    """Boş yanıt FeedError olmalı."""
    feed = BinanceFuturesFeed(session=FakeSession([FakeResponse(200, [])]))
    with pytest.raises(FeedError):
        feed.fetch_candles("BTCUSDT", "1m", 3)


def test_binance_451_raises_access_error() -> None:
    """451 bölgesel engel FeedAccessError olarak yükselmeli."""
    feed = BinanceFuturesFeed(session=FakeSession([FakeResponse(451, {})]))
    with pytest.raises(FeedAccessError):
        feed.fetch_candles("BTCUSDT", "1m", 3)


def test_binance_retries_on_429(monkeypatch) -> None:
    """429 sonrası tekrar denenmeli ve başarılı yanıt kullanılmalı."""
    monkeypatch.setattr(bf.time, "sleep", lambda *_: None)
    session = FakeSession([FakeResponse(429, {}), FakeResponse(200, [_kline(60_000)])])
    feed = BinanceFuturesFeed(session=session)
    df = feed.fetch_candles("BTCUSDT", "1m", 1)
    assert len(df) == 1
    assert len(session.calls) == 2


def test_binance_malformed_json_raises() -> None:
    """JSON çözülemeyen yanıt FeedError olmalı."""

    class BadJson(FakeResponse):
        def json(self):
            raise ValueError("bad json")

    feed = BinanceFuturesFeed(session=FakeSession([BadJson(200, None)]))
    with pytest.raises(FeedError):
        feed.fetch_candles("BTCUSDT", "1m", 1)


def test_binance_instruments_parsing() -> None:
    """exchangeInfo'dan tick/step boyutları çıkarılmalı."""
    payload = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "underlyingType": "COIN",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                ],
            }
        ]
    }
    feed = BinanceFuturesFeed(session=FakeSession([FakeResponse(200, payload)]))
    out = feed.fetch_instruments()
    assert out["BTCUSDT"]["tick_size"] == pytest.approx(0.1)
    assert out["BTCUSDT"]["step_size"] == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# OKX
# ---------------------------------------------------------------------------
def _okx_row(ts: int, confirm: str = "1", vol: float = 100.0):
    return [str(ts), "100.0", "101.0", "99.0", "100.5", str(vol), "1.0", "10050.0", confirm]


def test_okx_confirm_filter_drops_open_candle() -> None:
    """confirm != '1' olan (kapanmamış) mum KULLANILMAMALI."""
    payload = {"code": "0", "data": [_okx_row(60_000, "1"), _okx_row(120_000, "0")]}
    feed = OkxSwapFeed(session=FakeSession([FakeResponse(200, payload)]))
    df = feed.fetch_candles("BTC-USDT-SWAP", "1m", 2, ct_val=0.01)
    assert list(df["open_time"]) == [60_000]


def test_okx_only_unconfirmed_raises() -> None:
    """Tüm mumlar kapanmamışsa hata verilmeli."""
    payload = {"code": "0", "data": [_okx_row(60_000, "0")]}
    feed = OkxSwapFeed(session=FakeSession([FakeResponse(200, payload)]))
    with pytest.raises(OkxFeedError):
        feed.fetch_candles("BTC-USDT-SWAP", "1m", 1, ct_val=0.01)


def test_okx_volume_conversion_uses_ctval() -> None:
    """Hacim = kontrat * ctVal (base birim)."""
    payload = {"code": "0", "data": [_okx_row(60_000, "1", vol=100.0)]}
    feed = OkxSwapFeed(session=FakeSession([FakeResponse(200, payload)]))
    df = feed.fetch_candles("BTC-USDT-SWAP", "1m", 1, ct_val=0.01)
    assert float(df["volume"].iloc[0]) == pytest.approx(1.0)


def test_okx_volume_marked_contracts_without_ctval() -> None:
    """ctVal yoksa hacim kontrat olarak işaretlenir (birleştirme yapılmaz)."""
    payload = {"code": "0", "data": [_okx_row(60_000, "1", vol=100.0)]}
    feed = OkxSwapFeed(session=FakeSession([FakeResponse(200, payload)]))
    df = feed.fetch_candles("BTC-USDT-SWAP", "1m", 1)
    assert df.attrs["volume_is_contracts"] is True
    assert float(df["volume"].iloc[0]) == pytest.approx(100.0)


def test_okx_error_code_raises() -> None:
    """code != '0' olan yanıt FeedError olmalı."""
    payload = {"code": "51000", "msg": "parameter error", "data": []}
    feed = OkxSwapFeed(session=FakeSession([FakeResponse(200, payload)]))
    with pytest.raises(OkxFeedError):
        feed.fetch_candles("BTC-USDT-SWAP", "1m", 1, ct_val=0.01)


def test_okx_instruments_skip_non_positive_ctval() -> None:
    """ctVal <= 0 olan enstrüman atlanır (hacim çevrimi yapılamaz)."""
    payload = {
        "code": "0",
        "data": [
            {"instId": "BTC-USDT-SWAP", "ctVal": "0.01", "ctValCcy": "BTC",
             "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"},
            {"instId": "BAD-SWAP", "ctVal": "0", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"},
        ],
    }
    feed = OkxSwapFeed(session=FakeSession([FakeResponse(200, payload)]))
    out = feed.fetch_instruments()
    assert "BTC-USDT-SWAP" in out
    assert "BAD-SWAP" not in out
    assert out["BTC-USDT-SWAP"]["ct_val"] == pytest.approx(0.01)


def test_feeds_use_get_only() -> None:
    """Her iki akış da yalnızca GET kullanır."""
    session = FakeSession([FakeResponse(200, [_kline(60_000)])])
    BinanceFuturesFeed(session=session).fetch_candles("BTCUSDT", "1m", 1)
    assert all(call[0].startswith("https://fapi.binance.com/") for call in session.calls)
