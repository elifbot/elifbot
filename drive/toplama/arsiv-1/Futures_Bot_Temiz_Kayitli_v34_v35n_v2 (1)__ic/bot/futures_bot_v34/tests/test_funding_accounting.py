"""Olay bazlı funding muhasebesi testleri."""
from __future__ import annotations

import pytest

from logger.trade_logger import TradeLogger
from portfolio.paper_futures import LONG, SHORT, PaperPortfolio


def _open(pf: PaperPortfolio, side: str):
    result = pf.open_position(
        "binance", "BTCUSDT", side, 100.0, 100.0,
        leverage=1.0, step_size=1.0, now_ms=1,
    )
    assert result.ok
    return result.position


def test_long_positive_funding_is_cost_and_not_double_counted() -> None:
    pf = PaperPortfolio(1_000.0, fee_rate=0.0005)
    pos = _open(pf, LONG)
    before = pf.balance
    fee = pf.apply_funding("binance", "BTCUSDT", 0.001, 100.0, now_ms=2)
    assert fee == pytest.approx(0.1)
    assert pf.balance == pytest.approx(before - 0.1)
    rec = pf.close_position("binance", "BTCUSDT", 101.0, now_ms=3)
    assert rec is not None
    assert rec.funding_fee == pytest.approx(0.1)
    assert rec.funding_label == "funding dahil / olay bazlı"
    assert rec.realized_pnl == pytest.approx(1 - pos.entry_fee - rec.exit_fee - 0.1)
    # Açılış öncesi 1000; tüm bakiye değişimi net PnL'e eşit, funding iki kez düşmez.
    assert pf.balance - 1_000.0 == pytest.approx(rec.realized_pnl)


def test_short_positive_funding_is_income() -> None:
    pf = PaperPortfolio(1_000.0, fee_rate=0.0005)
    _open(pf, SHORT)
    fee = pf.apply_funding("binance", "BTCUSDT", 0.001, 100.0, now_ms=2)
    assert fee == pytest.approx(-0.1)
    rec = pf.close_position("binance", "BTCUSDT", 100.0, now_ms=3)
    assert rec is not None
    assert rec.realized_pnl == pytest.approx(-rec.entry_fee - rec.exit_fee + 0.1)
    assert pf.balance - 1_000.0 == pytest.approx(rec.realized_pnl)


def test_multiple_funding_events_accumulate() -> None:
    pf = PaperPortfolio(1_000.0, fee_rate=0.0005)
    _open(pf, LONG)
    pf.apply_funding("binance", "BTCUSDT", 0.001, 100.0)
    pf.apply_funding("binance", "BTCUSDT", -0.0005, 100.0)
    rec = pf.close_position("binance", "BTCUSDT", 100.0)
    assert rec is not None
    assert rec.funding_fee == pytest.approx(0.05)


def test_unknown_funding_remains_text_and_known_funding_is_numeric(tmp_path) -> None:
    path = tmp_path / "trades.csv"
    pf = PaperPortfolio(1_000.0, fee_rate=0.0005)
    _open(pf, LONG)
    rec_unknown = pf.close_position("binance", "BTCUSDT", 100.0)
    assert rec_unknown is not None
    logger = TradeLogger(str(path))
    logger.log_trades([rec_unknown])
    assert logger.read_rows(str(path))[0]["funding_fee"] == "bilinmiyor"

    _open(pf, LONG)
    pf.apply_funding("binance", "BTCUSDT", 0.001, 100.0)
    rec_known = pf.close_position("binance", "BTCUSDT", 100.0)
    assert rec_known is not None
    logger.log_trades([rec_known])
    assert float(logger.read_rows(str(path))[1]["funding_fee"]) == pytest.approx(0.1)


def test_funding_requires_open_position_and_valid_inputs() -> None:
    pf = PaperPortfolio(1_000.0)
    assert pf.apply_funding("binance", "NONE", 0.001, 100.0) is None
    _open(pf, LONG)
    with pytest.raises(ValueError):
        pf.apply_funding("binance", "BTCUSDT", float("nan"), 100.0)
    with pytest.raises(ValueError):
        pf.apply_funding("binance", "BTCUSDT", 0.001, 0.0)
