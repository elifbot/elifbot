"""Conservative two-motor simulator on historical closed 5m candles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.risk import RiskManager
from core.symbols import is_blacklisted
from core.strategy import FadeStrategy, TrendMomentumStrategy, measure_impulse_rvol
from infra.market_data.models import Candle
from infra.paper import PaperBroker


@dataclass(frozen=True)
class BacktestResult:
    initial_balance: float
    final_balance: float
    trades: tuple[dict[str, object], ...]

    @property
    def net_pnl(self) -> float:
        return self.final_balance - self.initial_balance

    @property
    def trade_count(self) -> int:
        return sum(item.get("type") == "CLOSE" for item in self.trades)

    @property
    def win_rate(self) -> float:
        closes = [item for item in self.trades if item.get("type") == "CLOSE"]
        if not closes:
            return 0.0
        return sum(float(item["pnl"]) > 0 for item in closes) / len(closes)


class BacktestEngine:
    def __init__(
        self,
        strategy: FadeStrategy | None = None,
        trend_strategy: TrendMomentumStrategy | None = None,
        risk: RiskManager | None = None,
        initial_balance: float = 1_000.0,
    ) -> None:
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        self.strategy = strategy or FadeStrategy()
        self.trend_strategy = trend_strategy or TrendMomentumStrategy()
        self.risk = risk or RiskManager()
        self.initial_balance = initial_balance

    def run(self, symbol: str, candles_5m: Sequence[Candle]) -> BacktestResult:
        broker = PaperBroker(self.initial_balance)
        if is_blacklisted(symbol):
            return BacktestResult(self.initial_balance, self.initial_balance, ())
        history: list[Candle] = []

        for candle in candles_5m:
            current_history = [*history, candle]
            momentum = (
                measure_impulse_rvol(current_history)
                if len(current_history) >= 23 else (None, None)
            )
            if symbol in broker.portfolio.positions:
                broker.check_exit(
                    symbol, candle.high, candle.low, candle.close, candle.timestamp,
                    impulse_pct=momentum[0], rvol=momentum[1],
                )
            elif history:
                fade_signal = self.strategy.evaluate(history)
                trend_signal = self.trend_strategy.evaluate(history)
                if (
                    fade_signal.side != "HOLD"
                    and trend_signal.side != "HOLD"
                    and fade_signal.side != trend_signal.side
                ):
                    signal = None
                elif fade_signal.side != "HOLD":
                    signal = fade_signal
                else:
                    signal = trend_signal
                if signal is not None and signal.side != "HOLD" and signal.stop_distance_fraction is not None:
                    plan = self.risk.plan(
                        broker.portfolio.balance,
                        candle.open,
                        signal.stop_distance_fraction,
                        signal.side,
                    )
                    broker.open_position(symbol, plan, candle.timestamp, "post_only")
                    broker.portfolio.positions[symbol].motor = signal.motor
                    broker.trades[-1]["motor"] = signal.motor
                    broker.check_exit(
                        symbol, candle.high, candle.low, candle.close, candle.timestamp,
                        impulse_pct=momentum[0], rvol=momentum[1],
                    )
            history.append(candle)

        if symbol in broker.portfolio.positions and candles_5m:
            last = candles_5m[-1]
            broker.close_position(symbol, last.close, "end_of_backtest", last.timestamp)
        return BacktestResult(
            self.initial_balance, broker.portfolio.balance, tuple(broker.trades)
        )
