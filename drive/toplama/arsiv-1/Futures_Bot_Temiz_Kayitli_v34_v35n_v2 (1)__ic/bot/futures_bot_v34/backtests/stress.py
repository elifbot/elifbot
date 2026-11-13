"""Aynı veri üzerinde tekrarlanabilir gecikme/kayma stres matrisi.

Canlı ``ws_bot`` spike/fade stratejisi bu motora bağlı değildir; sonuçlar yalnızca
verilen ``strategy_factory`` stratejisi içindir. Bu ayrım raporlarda korunmalıdır.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import pandas as pd

from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig


@dataclass(frozen=True)
class StressScenario:
    name: str
    latency_ms: int = 0
    slippage_bps: float = 0.0
    slippage_atr_fraction: float = 0.0
    max_slippage_bps: float | None = None


DEFAULT_SCENARIOS = (
    StressScenario("baseline"),
    StressScenario("latency_600ms", latency_ms=600),
    StressScenario("slippage_5bps", slippage_bps=5),
    StressScenario("slippage_10bps", slippage_bps=10),
    StressScenario("latency_600ms_slippage_10bps", latency_ms=600, slippage_bps=10),
    StressScenario("latency_600ms_slippage_20bps", latency_ms=600, slippage_bps=20),
    StressScenario(
        "dynamic_atr_5pct_cap_20bps",
        latency_ms=600,
        slippage_bps=2,
        slippage_atr_fraction=0.05,
        max_slippage_bps=20,
    ),
)


def run_execution_stress(
    df: pd.DataFrame,
    strategy_factory,
    *,
    base_config: BacktestConfig | None = None,
    scenarios=DEFAULT_SCENARIOS,
) -> list[dict]:
    """Her senaryoda temiz strateji ve temiz portföy ile backtest çalıştırır."""
    cfg = base_config or BacktestConfig()
    out: list[dict] = []
    for scenario in scenarios:
        scenario_cfg = replace(
            cfg,
            latency_ms=scenario.latency_ms,
            slippage_bps=scenario.slippage_bps,
            slippage_atr_fraction=scenario.slippage_atr_fraction,
            max_slippage_bps=scenario.max_slippage_bps,
        )
        engine = SimpleBacktestEngine(strategy_factory(), scenario_cfg).run(df)
        metrics = engine.results()
        out.append({
            "scenario": scenario.name,
            "assumptions": asdict(scenario),
            "metrics": metrics,
        })
    return out


__all__ = ["StressScenario", "DEFAULT_SCENARIOS", "run_execution_stress"]
