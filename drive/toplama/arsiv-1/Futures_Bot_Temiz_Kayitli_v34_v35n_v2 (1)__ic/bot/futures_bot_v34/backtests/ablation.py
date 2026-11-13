"""
backtests/ablation.py — Gösterge ailesi ablasyon analizi.

Yöntem: bir aile devre dışı bırakıldığında o ailenin koşulları "gerekli"
olmaktan çıkar; diğer her şey sabit kalır. Aynı veri üzerinde temel çizgiyle
karşılaştırma yapılır.

UYARI: Bu bir nedensellik kanıtı değildir; tek bir veri seti üzerinde
yapılan karşılaştırmadır. Küçük örneklemde farklar gürültü olabilir.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig


@dataclass
class AblationResult:
    """Aile bazlı ablasyon sonucu."""

    family: str          # "BASE" = hiçbir aile devre dışı değil
    trades: int
    realized_pnl: float
    win_rate: float
    profit_factor: float | None
    delta_pnl: float = 0.0


def run_ablation(
    df: pd.DataFrame,
    strategy_factory,
    *,
    families: tuple[str, ...] = ("A", "B", "C", "D"),
    config: BacktestConfig | None = None,
) -> list[AblationResult]:
    """Temel çizgi + her aile için tek tek devre dışı bırakma çalıştırır."""
    cfg = config or BacktestConfig()
    results: list[AblationResult] = []

    baseline_engine = SimpleBacktestEngine(strategy_factory(), cfg).run(df)
    base = baseline_engine.results()
    results.append(
        AblationResult(
            family="BASE",
            trades=base["trades"],
            realized_pnl=base["realized_pnl"],
            win_rate=base["win_rate"],
            profit_factor=base["profit_factor"],
        )
    )

    for fam in families:
        strat = strategy_factory()
        strat.disabled_families = {fam}
        res = SimpleBacktestEngine(strat, cfg).run(df).results()
        results.append(
            AblationResult(
                family=fam,
                trades=res["trades"],
                realized_pnl=res["realized_pnl"],
                win_rate=res["win_rate"],
                profit_factor=res["profit_factor"],
                delta_pnl=round(res["realized_pnl"] - base["realized_pnl"], 6),
            )
        )
    return results
