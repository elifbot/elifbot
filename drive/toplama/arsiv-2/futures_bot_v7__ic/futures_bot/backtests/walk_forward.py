"""
backtests/walk_forward.py — Walk-forward doğrulama.

Kural: her test penceresi BAŞLAMADAN önce parametre seti dondurulur.
Bu uygulamada parametre optimizasyonu YAPILMAZ (sabit config); bu nedenle
"eğitim penceresi yalnızca ısınma/bağlam içindir" ve overfitting riski
düşüktür — ancak bu, stratejinin kârlı olduğu anlamına GELMEZ.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import pandas as pd

from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig, WalkForwardPlan
from strategies.base import StrategyBase


@dataclass
class WindowResult:
    """Tek bir walk-forward penceresinin sonucu."""

    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    params_hash: str
    metrics: dict = field(default_factory=dict)


def _params_hash(strategy: StrategyBase, config: BacktestConfig) -> str:
    """Parametre setinin parmak izi (dondurulduğunun kanıtı)."""
    payload = {
        "strategy": strategy.NAME,
        "status": strategy.STATUS,
        "min_rows": strategy.MIN_ROWS,
        "fee": config.fee_rate,
        "leverage": config.leverage,
        "starting_balance": config.starting_balance,
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def run_walk_forward(
    df: pd.DataFrame,
    strategy_factory,
    *,
    train_bars: int = 500,
    test_bars: int = 200,
    config: BacktestConfig | None = None,
) -> list[WindowResult]:
    """
    Walk-forward pencerelerini çalıştırır.

    strategy_factory: her pencere için YENİ strateji örneği üreten çağrılabilir
    (durum paylaşımı olmaması için zorunlu).
    """
    cfg = config or BacktestConfig()
    plan = WalkForwardPlan(train_bars=train_bars, test_bars=test_bars)
    out: list[WindowResult] = []

    for idx, (ts, te, ss, se) in enumerate(plan.windows(len(df))):
        strategy = strategy_factory()
        # Parametre seti test penceresi başlamadan ÖNCE dondurulur.
        frozen = _params_hash(strategy, cfg) if cfg.params_frozen else "DONDURULMADI"
        # Eğitim penceresi yalnızca ısınma bağlamı sağlar (optimizasyon yok).
        test_slice = df.iloc[max(0, te - strategy.MIN_ROWS - 1) : se].reset_index(drop=True)
        engine = SimpleBacktestEngine(strategy, cfg).run(test_slice)
        out.append(
            WindowResult(
                window_index=idx,
                train_start=int(df.iloc[ts]["open_time"]),
                train_end=int(df.iloc[te - 1]["open_time"]) if te - 1 < len(df) else 0,
                test_start=int(df.iloc[ss]["open_time"]) if ss < len(df) else 0,
                test_end=int(df.iloc[se - 1]["open_time"]) if se - 1 < len(df) else 0,
                params_hash=frozen,
                metrics=engine.results(),
            )
        )
    return out
