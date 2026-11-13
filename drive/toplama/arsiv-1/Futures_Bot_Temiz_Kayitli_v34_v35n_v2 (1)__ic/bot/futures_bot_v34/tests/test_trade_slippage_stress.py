"""CSV işlem kaydı kayma duyarlılığı testleri."""
from __future__ import annotations

import pytest

from scripts.trade_slippage_stress import stress_trade_rows


def _row() -> dict[str, str]:
    return {
        "side": "LONG", "qty_base": "5", "entry_price": "100",
        "exit_price": "101", "entry_fee": "0.25", "exit_fee": "0.2525",
        "funding_fee": "bilinmiyor",
    }


def test_zero_slippage_reproduces_reference_net() -> None:
    out = stress_trade_rows([_row()], 0)
    assert out["net_pnl"] == pytest.approx(4.4975)
    assert out["funding"] == "bilinmiyor"


def test_adverse_slippage_reduces_net_and_recomputes_fees() -> None:
    base = stress_trade_rows([_row()], 0)
    stressed = stress_trade_rows([_row()], 20)
    assert stressed["net_pnl"] < base["net_pnl"]
    assert stressed["fees"] > 0
    assert stressed["trades"] == 1


def test_numeric_funding_is_included_once() -> None:
    row = _row(); row["funding_fee"] = "0.1"
    out = stress_trade_rows([row], 0)
    assert out["net_pnl"] == pytest.approx(4.3975)
    assert out["funding"] == "funding dahil"
