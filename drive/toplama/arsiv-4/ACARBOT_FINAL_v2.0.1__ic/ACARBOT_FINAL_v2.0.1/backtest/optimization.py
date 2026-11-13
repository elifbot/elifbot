"""ACARBOT v2.0 — Parametre duyarlılık analizi ve IS/OOS optimizasyonu.

Şartname madde 7 (profesyonel backtest):
  - Parametre hassasiyet analizi: parametre gridindeki her kombinasyon
    ayrı çalıştırılır; kararlılık (kaç kombinasyon kârlı, PnL yayılımı)
    raporlanır. Tek noktada iyi görünen, komşu parametrelerde çöken
    sistem "aşırı uyumlu" sayılır.
  - Out-of-sample kontrolü: veri IS (in-sample) / OOS (out-of-sample)
    diye bölünür; grid IS'te taranır, en iyi parametreler OOS'ta
    doğrulanır. OOS/IS performans oranı düşerse sistem güvenilmezdir.
  - Walk-forward: `backtest.walkforward.walk_forward` (v1.2'den) ile
    birlikte kullanılır: pencere bazlı OOS + bu modülün grid araması.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from backtest.engine import BacktestEngine
from backtest.metrics import MetricBlock, compute_metrics
from core.config import SuperConfig
from infra.market_data.models import Candle


@dataclass
class SensitivityRow:
    params: dict[str, Any]
    net_pnl: float
    trade_count: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float

    def as_dict(self) -> dict:
        return {
            "params": self.params,
            "net_pnl": round(self.net_pnl, 4),
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": (
                None if self.profit_factor == float("inf")
                else round(self.profit_factor, 4)
            ),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
        }


@dataclass
class SensitivityReport:
    rows: list[SensitivityRow] = field(default_factory=list)

    @property
    def profitable_fraction(self) -> float:
        if not self.rows:
            return 0.0
        return sum(1 for r in self.rows if r.net_pnl > 0) / len(self.rows)

    @property
    def best(self) -> SensitivityRow | None:
        if not self.rows:
            return None
        return max(self.rows, key=lambda r: r.net_pnl)

    @property
    def worst(self) -> SensitivityRow | None:
        if not self.rows:
            return None
        return min(self.rows, key=lambda r: r.net_pnl)

    @property
    def robustness_note(self) -> str:
        if not self.rows:
            return "veri yok"
        best = self.best
        worst = self.worst
        if best is None or worst is None:
            return "veri yok"
        if self.profitable_fraction >= 0.8 and worst.net_pnl > -1e-9:
            return "kararlı: komşu parametreler de kârlı"
        if self.profitable_fraction >= 0.5:
            return "orta: sonuçlar parametreye duyarlı"
        return "zayıf: çoğu parametre kâr etmiyor (aşırı uyum riski)"

    def as_dict(self) -> dict:
        return {
            "rows": [r.as_dict() for r in self.rows],
            "profitable_fraction": round(self.profitable_fraction, 3),
            "robustness": self.robustness_note,
        }


# İzin verilen duyarlılık parametreleri (güvenli: yalnızca bu alanlar
# değiştirilir; risk tavanlarına dokunulmaz).
_ALLOWED_PARAMS = {
    "exit.stop_atr_multiple",
    "exit.tp1_r_multiple",
    "exit.trail_atr_multiple",
    "signal.spike_multiplier",
    "signal.min_rvol_for_entry",
    "signal.fade_impulse_pct",
    "signal.regime_adx_trend_threshold",
}


def _apply_param(config: SuperConfig, dotted: str, value: Any) -> SuperConfig:
    group_name, field_name = dotted.split(".", 1)
    if group_name not in {"exit", "signal"}:
        raise ValueError(f"parametre grubu desteklenmiyor: {group_name}")
    group = getattr(config, group_name)
    if not hasattr(group, field_name):
        raise ValueError(f"bilinmeyen parametre: {dotted}")
    return replace(config, **{group_name: replace(group, **{field_name: value})})


def sensitivity_analysis(
    candles_by_symbol: dict[str, list[Candle]],
    param_grid: dict[str, list[Any]],
    base_config: SuperConfig | None = None,
    initial_balance: float = 1_000.0,
) -> SensitivityReport:
    """Grid parametrelerini tarar; her kombinasyon için metrik üretir.

    param_grid örneği: {"exit.stop_atr_multiple": [1.0, 1.5, 2.0]}
    """
    config = base_config or SuperConfig()
    keys = list(param_grid)
    combos: list[dict[str, Any]] = [{}]
    for key in keys:
        if key not in _ALLOWED_PARAMS:
            raise ValueError(f"duyarlılık analizi bu parametreye izin vermiyor: {key}")
        combos = [{**combo, key: value} for combo in combos for value in param_grid[key]]
    report = SensitivityReport()
    for combo in combos:
        run_config = config
        for dotted, value in combo.items():
            run_config = _apply_param(run_config, dotted, value)
        engine = BacktestEngine(config=run_config, initial_balance=initial_balance)
        result = engine.run(candles_by_symbol)
        metrics = compute_metrics(
            list(result.trades), initial_balance, result.final_balance,
            result.equity_curve,
        )
        report.rows.append(SensitivityRow(
            params=dict(combo),
            net_pnl=result.net_pnl,
            trade_count=metrics.trade_count,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
            max_drawdown_pct=metrics.max_drawdown_pct,
        ))
    return report


@dataclass
class OosCheckResult:
    is_metrics: MetricBlock
    oos_metrics: MetricBlock
    best_params: dict[str, Any]
    degradation_ratio: float      # OOS beklenti / IS beklenti (1.0 = aynı)

    @property
    def verdict(self) -> str:
        if self.is_metrics.expectancy_usdt <= 0:
            return "IS kâr etmiyor: parametre araması anlamsız"
        if self.degradation_ratio >= 0.6:
            return "OOS doğruladı: sistem geçmişe aşırı uyumlu görünmüyor"
        if self.degradation_ratio > 0:
            return "OOS zayıf: aşırı uyum şüphesi yüksek"
        return "OOS zararda: sistem reddedilmeli"

    def as_dict(self) -> dict:
        return {
            "best_params": self.best_params,
            "is": self.is_metrics.as_dict(),
            "oos": self.oos_metrics.as_dict(),
            "degradation_ratio": round(self.degradation_ratio, 4),
            "verdict": self.verdict,
        }


def out_of_sample_check(
    candles_by_symbol: dict[str, list[Candle]],
    param_grid: dict[str, list[Any]],
    base_config: SuperConfig | None = None,
    initial_balance: float = 1_000.0,
    is_fraction: float = 0.7,
) -> OosCheckResult:
    """IS'te grid araması, OOS'ta en iyi parametrelerin doğrulanması."""
    if not 0.1 <= is_fraction < 1.0:
        raise ValueError("is_fraction [0.1, 1.0) aralığında olmalı")
    config = base_config or SuperConfig()
    all_ts = sorted({
        c.timestamp for candles in candles_by_symbol.values() for c in candles
    })
    if not all_ts:
        raise ValueError("veri yok")
    split_ts = all_ts[0] + (all_ts[-1] - all_ts[0]) * is_fraction
    is_data = {
        symbol: [c for c in candles if c.timestamp < split_ts]
        for symbol, candles in candles_by_symbol.items()
    }
    oos_data = {
        symbol: [c for c in candles if c.timestamp >= split_ts]
        for symbol, candles in candles_by_symbol.items()
    }
    is_data = {s: c for s, c in is_data.items() if c}
    oos_data = {s: c for s, c in oos_data.items() if c}

    report = sensitivity_analysis(
        is_data, param_grid, config, initial_balance,
    )
    best = report.best
    best_params = best.params if best else {}
    run_config = config
    for dotted, value in best_params.items():
        run_config = _apply_param(run_config, dotted, value)

    is_engine = BacktestEngine(config=run_config, initial_balance=initial_balance)
    is_result = is_engine.run(is_data)
    is_metrics = compute_metrics(
        list(is_result.trades), initial_balance, is_result.final_balance,
        is_result.equity_curve,
    )
    oos_engine = BacktestEngine(config=run_config, initial_balance=initial_balance)
    oos_result = oos_engine.run(oos_data)
    oos_metrics = compute_metrics(
        list(oos_result.trades), initial_balance, oos_result.final_balance,
        oos_result.equity_curve,
    )
    if is_metrics.expectancy_usdt > 0:
        degradation = (
            oos_metrics.expectancy_usdt / is_metrics.expectancy_usdt
        )
    else:
        degradation = 0.0
    return OosCheckResult(
        is_metrics=is_metrics,
        oos_metrics=oos_metrics,
        best_params=best_params,
        degradation_ratio=degradation,
    )
