"""Walk-forward analizi (Y1-D).

Veriyi k bitişik pencereye böler; her pencerede ayrı simülasyon koşturur
ve pencere bazlı OOS (test) istatistikleri üretir. Böylece tek dönemlik
şansın değil, farklı piyasa rejimlerindeki davranışın raporu çıkar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backtest.engine import BacktestEngine, BacktestResult
from backtest.metrics import MetricBlock, compute_metrics
from infra.market_data.models import Candle


@dataclass
class WalkForwardWindow:
    index: int
    start_ts: int
    end_ts: int
    result: BacktestResult
    metrics: MetricBlock

    @property
    def is_profitable(self) -> bool:
        return self.result.net_pnl > 0


@dataclass
class WalkForwardReport:
    windows: list[WalkForwardWindow] = field(default_factory=list)

    @property
    def profitable_windows(self) -> int:
        return sum(1 for w in self.windows if w.is_profitable)

    @property
    def total_net_pnl(self) -> float:
        return sum(w.result.net_pnl for w in self.windows)

    @property
    def worst_window(self) -> WalkForwardWindow | None:
        if not self.windows:
            return None
        return min(self.windows, key=lambda w: w.result.net_pnl)

    def as_dict(self) -> dict:
        return {
            "windows": [
                {
                    "index": w.index,
                    "start_ts": w.start_ts,
                    "end_ts": w.end_ts,
                    "net_pnl": round(w.result.net_pnl, 4),
                    "trades": w.result.trade_count,
                    "win_rate": round(w.metrics.win_rate, 4),
                    "max_dd_pct": round(w.metrics.max_drawdown_pct, 4),
                    "profitable": w.is_profitable,
                }
                for w in self.windows
            ],
            "profitable_windows": self.profitable_windows,
            "total_windows": len(self.windows),
            "total_net_pnl": round(self.total_net_pnl, 4),
            "worst_window_net_pnl": (
                round(self.worst_window.result.net_pnl, 4)
                if self.worst_window else 0.0
            ),
        }


def walk_forward(
    candles_by_symbol: dict[str, list[Candle]],
    windows: int = 4,
    config=None,
    initial_balance: float = 1_000.0,
    max_positions: int | None = None,
    funding_rates: dict[str, list[tuple[int, float]]] | None = None,
    btc_symbol: str = "BTCUSDT",
) -> WalkForwardReport:
    """Zaman ekseninde k eşit pencereye böler ve ayrı ayrı test eder."""
    if windows < 1:
        raise ValueError("pencere sayısı >= 1 olmalı")
    engine = BacktestEngine(
        config=config,
        initial_balance=initial_balance,
        max_positions=max_positions,
    )
    all_ts = sorted({
        c.timestamp
        for candles in candles_by_symbol.values()
        for c in candles
    })
    if not all_ts:
        return WalkForwardReport()
    span = (all_ts[-1] - all_ts[0] + 1) / windows
    report = WalkForwardReport()
    for index in range(windows):
        start = all_ts[0] + index * span
        end = start + span
        sliced = {
            symbol: [
                c for c in candles if start <= c.timestamp < end
            ]
            for symbol, candles in candles_by_symbol.items()
        }
        sliced = {s: c for s, c in sliced.items() if c}
        if not sliced:
            continue
        result = engine.run(
            sliced, funding_rates=funding_rates, btc_symbol=btc_symbol,
        )
        metrics = compute_metrics(
            list(result.trades),
            initial_balance,
            result.final_balance,
            result.equity_curve,
        )
        report.windows.append(WalkForwardWindow(
            index=index + 1,
            start_ts=int(start),
            end_ts=int(end),
            result=result,
            metrics=metrics,
        ))
    return report
