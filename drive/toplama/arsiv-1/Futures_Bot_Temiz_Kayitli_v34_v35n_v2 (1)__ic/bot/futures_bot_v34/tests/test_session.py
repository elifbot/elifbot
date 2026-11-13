"""Oturum / CLI entegrasyon testleri (ağ erişimi yok)."""
from __future__ import annotations

import pandas as pd
import pytest

import config
from logger.trade_logger import TradeLogger
from main import (
    TradingSession,
    load_replay_csv,
    parse_pairs,
)
from portfolio.paper_futures import PaperPortfolio
from tests.conftest import make_ohlcv


def _session(tmp_path, minutes: int = 60) -> TradingSession:
    pf = PaperPortfolio(config.STARTING_BALANCE_USDT, fee_rate=config.TAKER_FEE_RATE)
    logger = TradeLogger(str(tmp_path / "trades.csv"))
    return TradingSession(pf, logger, session_minutes=minutes)


def test_parse_pairs_defaults_to_config() -> None:
    """Boş spec, config'deki pair listesini döndürür."""
    assert parse_pairs("") == list(config.EXCHANGE_SYMBOL_PAIRS)


def test_parse_pairs_custom() -> None:
    """'borsa:sembol' listesi çözülür."""
    assert parse_pairs("binance:BTCUSDT, okx:ETH-USDT-SWAP") == [
        ("binance", "BTCUSDT"),
        ("okx", "ETH-USDT-SWAP"),
    ]


def test_parse_pairs_invalid() -> None:
    """Eksik ayırıcı hata verir."""
    with pytest.raises(ValueError):
        parse_pairs("BTCUSDT")


def test_each_pair_has_isolated_strategies(tmp_path) -> None:
    """Her (exchange, symbol) kendi aday örneklerini alır."""
    s = _session(tmp_path)
    a = s.strategies_for(("binance", "BTCUSDT"))
    b = s.strategies_for(("okx", "BTC-USDT-SWAP"))
    assert a is not b
    assert all(x is not y for x, y in zip(a, b))


def test_entries_blocked_in_last_minutes(tmp_path) -> None:
    """Son 7 dakikada yeni giriş izni verilmez."""
    s = _session(tmp_path, minutes=60)
    started = 1_000.0
    assert s.entries_allowed(started, started + 10 * 60)
    assert not s.entries_allowed(started, started + 55 * 60)


def test_on_window_processes_closed_candles(tmp_path) -> None:
    """on_window kapanmış mum penceresiyle çalışır ve hata vermez."""
    s = _session(tmp_path)
    df = make_ohlcv(300)
    now_ms = int(df.iloc[-1]["close_time"])
    events = s.on_window("binance", "BTCUSDT", df, now_ms)
    assert isinstance(events, list)
    assert ("binance", "BTCUSDT") in s.last_windows


def test_finish_closes_all_positions(tmp_path) -> None:
    """Oturum sonunda tüm pozisyonlar kapanır ve kayıt üretilir."""
    s = _session(tmp_path)
    df = make_ohlcv(300)
    now_ms = int(df.iloc[-1]["close_time"])
    s.on_window("binance", "BTCUSDT", df, now_ms, allow_entries=True)
    # Pozisyon açılmış olabilir veya olmayabilir; açıksa kapanmalı.
    opened = len(s.portfolio.positions)
    s.finish(now_ms)
    assert len(s.portfolio.positions) == 0
    if opened:
        assert len(s.portfolio.closed_trades) >= 1


def test_session_rejects_invalid_minutes(tmp_path) -> None:
    """no_entry_minutes > session_minutes hata verir."""
    with pytest.raises(ValueError):
        _session(tmp_path, minutes=5)


def test_load_replay_csv_missing_columns(tmp_path) -> None:
    """Eksik kolonlu CSV reddedilir."""
    path = tmp_path / "bad.csv"
    pd.DataFrame({"open_time": [0], "open": [1.0]}).to_csv(path, index=False)
    with pytest.raises(ValueError):
        load_replay_csv(str(path))


def test_load_replay_csv_adds_close_time(tmp_path) -> None:
    """Replay CSV'sine close_time eklenir ve sıralanır."""
    path = tmp_path / "ok.csv"
    make_ohlcv(5)[["open_time", "open", "high", "low", "close", "volume"]].iloc[::-1].to_csv(
        path, index=False
    )
    df = load_replay_csv(str(path))
    assert list(df["open_time"]) == sorted(df["open_time"])
    assert "close_time" in df.columns
