import pytest

from src.exit_rules import apply_supertrend_trailing
from src.risk import Position, RiskManager


def _position(side="LONG"):
    return Position(
        symbol="BTC/USDT:USDT",
        side=side,
        entry=100.0,
        qty=5.0,
        stop=92.0 if side == "LONG" else 108.0,
        leverage=10,
        margin_usdt=50.0,
        entry_fee_usdt=0.10,
        exit_fee_pct=0.05,
        net_breakeven_enabled=True,
    )


def _net_at(pos, price):
    direction = 1.0 if pos.side == "LONG" else -1.0
    gross = direction * (price - pos.entry) * pos.qty
    exit_fee = price * pos.qty * pos.exit_fee_pct / 100.0
    return gross - pos.entry_fee_usdt - exit_fee + pos.funding_usdt


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_net_breakeven_covers_actual_entry_and_estimated_exit_fee(side):
    risk = RiskManager()
    pos = _position(side)
    breakeven = risk.net_breakeven_price(pos)
    assert _net_at(pos, breakeven) == pytest.approx(0.0, abs=1e-10)
    assert breakeven > pos.entry if side == "LONG" else breakeven < pos.entry

    pos.funding_usdt = 0.05
    funded = risk.net_breakeven_price(pos)
    assert _net_at(pos, funded) == pytest.approx(0.0, abs=1e-10)
    assert funded < breakeven if side == "LONG" else funded > breakeven


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_net_buffer_does_not_move_trailing_activation_earlier(side):
    risk = RiskManager(trail_pct=5.0)
    pos = _position(side)
    initial = pos.stop
    early_price = 100.05 if side == "LONG" else 99.95
    result = risk.update(pos, early_price)
    assert result["action"] == "hold"
    assert pos.stop == initial

    activation_price = 106.0 if side == "LONG" else 94.0
    risk.update(pos, activation_price)
    floor = risk.net_breakeven_price(pos)
    if side == "LONG":
        assert pos.stop >= floor > pos.entry
    else:
        assert pos.stop <= floor < pos.entry


def test_mfe_mae_and_supertrend_respect_net_floor():
    risk = RiskManager(trail_pct=5.0)
    pos = _position("LONG")
    risk.update(pos, 99.0)
    risk.update(pos, 101.0)
    risk.update(pos, 100.0)
    assert pos.mfe_usdt == pytest.approx(5.0)
    assert pos.mae_usdt == pytest.approx(-5.0)

    floor = risk.net_breakeven_price(pos)
    assert not apply_supertrend_trailing(
        pos, 101.0, {"direction": 1, "value": 100.01}, risk
    )
    assert apply_supertrend_trailing(
        pos, 101.0, {"direction": 1, "value": floor + 0.01}, risk
    )
    assert pos.stop == pytest.approx(floor + 0.01)
