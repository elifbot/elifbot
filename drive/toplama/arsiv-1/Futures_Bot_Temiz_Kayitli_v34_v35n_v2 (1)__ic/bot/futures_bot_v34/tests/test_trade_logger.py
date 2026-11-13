"""CSV kayıt testleri — allowlist ve funding etiketi."""
from __future__ import annotations

import csv
import os

from logger.trade_logger import FIELDS, FUNDING_UNKNOWN, TradeLogger
from portfolio.paper_futures import LONG, PaperPortfolio


def _record():
    pf = PaperPortfolio(2_000.0, fee_rate=0.0005)
    pf.open_position("binance", "BTCUSDT", LONG, 100.0, 500.0, leverage=1.0,
                     step_size=1.0, now_ms=1)
    rec = pf.close_position("binance", "BTCUSDT", 101.0, now_ms=2)
    assert rec is not None
    return rec


def test_allowlist_is_fixed() -> None:
    """Alan listesi sabit ve funding alanı içermeli."""
    assert "funding_fee" in FIELDS
    assert "reason" in FIELDS
    for forbidden in ("api_key", "secret", "authorization", "url", "headers"):
        assert forbidden not in FIELDS


def test_logger_writes_header_once(tmp_path) -> None:
    """Başlık yalnızca bir kez yazılır."""
    path = str(tmp_path / "trades.csv")
    logger = TradeLogger(path)
    logger.log_trades([_record()])
    logger.log_trades([_record()])
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == list(FIELDS)
    assert len(rows) == 3  # başlık + 2 satır


def test_funding_column_is_unknown_not_zero(tmp_path) -> None:
    """funding_fee kolonu 'bilinmiyor' yazılır; sayısal 0 gibi sunulmaz."""
    path = str(tmp_path / "trades.csv")
    TradeLogger(path).log_trades([_record()])
    rows = TradeLogger.read_rows(path)
    assert rows[0]["funding_fee"] == FUNDING_UNKNOWN
    assert rows[0]["funding_fee"] != "0.0"


def test_only_allowlisted_columns_written(tmp_path) -> None:
    """CSV başlığı tam olarak allowlist ile eşleşir."""
    path = str(tmp_path / "trades.csv")
    TradeLogger(path).log_trades([_record()])
    with open(path, newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert set(header) == set(FIELDS)


def test_csv_contains_no_absolute_paths_or_http(tmp_path) -> None:
    """CSV'de mutlak yol veya URL bulunmamalı."""
    path = str(tmp_path / "trades.csv")
    TradeLogger(path).log_trades([_record()])
    content = open(path, encoding="utf-8").read()
    assert "http" not in content
    assert os.path.abspath(str(tmp_path)) not in content
