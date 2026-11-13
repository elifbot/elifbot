"""Gecikme ve kayma stres modeli regresyon testleri."""
from __future__ import annotations

import pandas as pd
import pytest

from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig
from backtests.execution import ExecutionModel
from backtests.stress import StressScenario, run_execution_stress
from strategies.base import SignalResult, StrategyBase


class AlwaysLong(StrategyBase):
    NAME = "test_always_long"
    MIN_ROWS = 1

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        return SignalResult("LONG", self.NAME, "test")


def _df() -> pd.DataFrame:
    return pd.DataFrame({
        "open_time": [0, 60_000, 120_000, 180_000],
        "open": [100.0, 100.0, 102.0, 104.0],
        "high": [101.0, 103.0, 105.0, 106.0],
        "low": [99.0, 99.0, 101.0, 103.0],
        "close": [100.0, 101.0, 103.0, 105.0],
        "volume": [1.0, 1.0, 1.0, 1.0],
    })


def test_directional_slippage_and_cap() -> None:
    model = ExecutionModel(
        fixed_slippage_bps=10,
        atr_slippage_fraction=0.10,
        max_slippage_bps=20,
    )
    # 10 bps sabit + 10 bps ATR = 20 bps; LONG giriş pahalı, çıkış düşük.
    assert model.execution_price(100, "LONG", is_entry=True, atr=1) == pytest.approx(100.2)
    assert model.execution_price(100, "LONG", is_entry=False, atr=1) == pytest.approx(99.8)
    # SHORT için tam tersi; kayma iki yönde de aleyhtedir.
    assert model.execution_price(100, "SHORT", is_entry=True, atr=1) == pytest.approx(99.8)
    assert model.execution_price(100, "SHORT", is_entry=False, atr=1) == pytest.approx(100.2)


def test_zero_stress_preserves_raw_price() -> None:
    model = ExecutionModel()
    assert model.execution_price(100, "LONG", is_entry=True) == 100
    assert model.execution_price(100, "SHORT", is_entry=False) == 100


def test_immediate_entry_applies_slippage() -> None:
    engine = SimpleBacktestEngine(
        AlwaysLong(), BacktestConfig(fee_rate=0, slippage_bps=100),
    )
    df = _df()
    engine.feed(df.iloc[0].to_dict()); engine.step()
    engine.feed(df.iloc[1].to_dict()); engine.step()
    pos = engine.portfolio.positions[(AlwaysLong.NAME, "BACKTEST")]
    assert pos.entry_price == pytest.approx(102.01)  # ikinci close 101 + %1


def test_latency_defers_to_next_available_candle_open() -> None:
    engine = SimpleBacktestEngine(
        AlwaysLong(), BacktestConfig(fee_rate=0, latency_ms=600),
    )
    df = _df()
    engine.feed(df.iloc[0].to_dict()); engine.step()
    engine.feed(df.iloc[1].to_dict()); engine.step()
    assert not engine.portfolio.positions
    assert engine._pending_entry is not None
    engine.feed(df.iloc[2].to_dict()); engine.step()
    pos = engine.portfolio.positions[(AlwaysLong.NAME, "BACKTEST")]
    assert pos.entry_price == pytest.approx(102.0)  # üçüncü mumun açılışı
    assert engine._pending_entry is None


def test_stress_runner_isolates_scenarios() -> None:
    out = run_execution_stress(
        _df(), AlwaysLong,
        base_config=BacktestConfig(fee_rate=0),
        scenarios=(
            StressScenario("base"),
            StressScenario("stress", latency_ms=600, slippage_bps=20),
        ),
    )
    assert [r["scenario"] for r in out] == ["base", "stress"]
    assert out[0]["metrics"]["execution"]["slippage_bps"] == 0
    assert out[1]["metrics"]["execution"]["slippage_bps"] == 20
    assert out[1]["metrics"]["execution"]["latency_ms"] == 600


def test_negative_execution_parameters_rejected() -> None:
    with pytest.raises(ValueError):
        ExecutionModel(fixed_slippage_bps=-1)
    with pytest.raises(ValueError):
        ExecutionModel(latency_ms=-1)
