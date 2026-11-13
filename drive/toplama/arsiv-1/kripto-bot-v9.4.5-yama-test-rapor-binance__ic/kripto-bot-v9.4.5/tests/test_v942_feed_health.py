"""v9.4.2: Binance WS yönlendirmesi ve trade-tape kör noktası regresyon testleri (bağımlılıksız)."""
import pytest

from src.feed_health import (
    binance_futures_single_stream_url,
    binance_futures_stream_category,
    binance_futures_ws_url,
    venue_feed_status,
)


def test_aggtrade_goes_to_market_and_bookticker_to_public():
    assert binance_futures_ws_url("aggTrade", "btcusdt@aggTrade").startswith("wss://fstream.binance.com/market/stream?streams=")
    assert binance_futures_ws_url("bookTicker", "btcusdt@bookTicker").startswith("wss://fstream.binance.com/public/stream?streams=")


def test_legacy_urls_are_never_produced():
    for suffix in ("aggTrade", "bookTicker"):
        url = binance_futures_ws_url(suffix, "x")
        assert "fstream.binance.com/stream" not in url and "fstream.binance.com/ws" not in url


def test_scanner_all_tickers_stream_is_market():
    assert binance_futures_single_stream_url("!ticker@arr") == "wss://fstream.binance.com/market/ws/!ticker@arr"


def test_unknown_stream_fails_loudly_instead_of_silently_going_quiet():
    with pytest.raises(ValueError):
        binance_futures_stream_category("somethingNew")


def test_fresh_bbo_without_trade_tape_is_NOT_healthy():
    """v9.4.1 kusuru: BBO var, aggTrade 0 -> eski kod healthy=true diyordu."""
    now = 10_000.0
    st = {"last_bbo_ts": now - 0.1, "last_trade_ts": 0.0, "ticks": 0}
    r = venue_feed_status(st, now, started_at=now - 900)
    assert r["bbo_healthy"] and not r["trade_tape_healthy"] and not r["healthy"]
    assert r["alarms"] == ["TRADE_TAPE_ABSENT"]


def test_stale_tape_after_ticks_is_reported_as_stale():
    now = 10_000.0
    st = {"last_bbo_ts": now - 1, "last_trade_ts": now - 120, "ticks": 500}
    r = venue_feed_status(st, now, started_at=now - 900)
    assert r["alarms"] == ["TRADE_TAPE_STALE"] and not r["healthy"]


def test_both_feeds_fresh_is_healthy():
    now = 10_000.0
    r = venue_feed_status({"last_bbo_ts": now - 1, "last_trade_ts": now - 2, "ticks": 5}, now, started_at=now - 900)
    assert r["healthy"] and r["alarms"] == []


def test_warmup_grace_does_not_alarm_immediately():
    now = 10_000.0
    r = venue_feed_status({"last_bbo_ts": 0.0, "last_trade_ts": 0.0}, now, started_at=now - 10)
    assert r["alarms"] == []


def test_stale_bbo_alarms():
    now = 10_000.0
    r = venue_feed_status({"last_bbo_ts": now - 100, "last_trade_ts": now - 1, "ticks": 9}, now, started_at=now - 900)
    assert "BBO_STALE" in r["alarms"] and not r["healthy"]
