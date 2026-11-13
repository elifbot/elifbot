"""
backtests/engine.py — Mum-mum ilerleyen, lookahead korumalı paper backtest motoru.

Tasarım kuralları:
  * Mumlar motora TEK TEK verilir (feed), karar yalnızca o ana kadarki
    pencereden üretilir.
  * Stratejiye verilen pencere, karar anından SONRAKİ hiçbir mumu içermez;
    ihlal edilirse LookaheadError fırlatılır.
  * Muhasebe, canlı paper oturumuyla AYNI PaperPortfolio sınıfını kullanır.
  * Parametreler pencere başında dondurulur (params_frozen).
"""
from __future__ import annotations

import pandas as pd

from backtests.engine_interface import (
    BacktestConfig,
    BacktestEngine,
    LookaheadError,
)
from portfolio.paper_futures import PaperPortfolio
from reports.pnl_report import PnLReport
from strategies.base import HOLD, StrategyBase
from backtests.execution import ExecutionModel

STOP_ATR_MULT = 2.0
TAKE_PROFIT_ATR_MULT = 4.0
DEFAULT_WINDOW = 300


class SimpleBacktestEngine(BacktestEngine):
    """Tek sembol, tek strateji üzerinde çalışan basit backtest motoru."""

    def __init__(
        self,
        strategy: StrategyBase,
        config: BacktestConfig | None = None,
        *,
        window: int = DEFAULT_WINDOW,
        margin: float = 100.0,
    ) -> None:
        super().__init__(config or BacktestConfig())
        self.strategy = strategy
        self.window = max(int(window), strategy.MIN_ROWS + 1)
        self.margin = float(margin)
        self.portfolio = PaperPortfolio(
            self.config.starting_balance,
            fee_rate=self.config.fee_rate,
        )
        self.execution = ExecutionModel(
            latency_ms=self.config.latency_ms,
            fixed_slippage_bps=self.config.slippage_bps,
            atr_slippage_fraction=self.config.slippage_atr_fraction,
            max_slippage_bps=self.config.max_slippage_bps,
        )
        self._pending_entry: dict | None = None
        self._last_price = 0.0
        self._last_ts = 0
        self.lookahead_checks = 0

    # -- besleme -----------------------------------------------------------
    def feed(self, candle: dict) -> None:  # noqa: D401
        super().feed(candle)

    def run(self, df: pd.DataFrame) -> "SimpleBacktestEngine":
        """Tüm DataFrame'i mum-mum besler."""
        cols = ["open_time", "open", "high", "low", "close", "volume"]
        for _, row in df[cols].iterrows():
            self.feed({c: row[c] for c in cols})
            self.step()
        return self

    # -- tek adım ----------------------------------------------------------
    def step(self) -> None:
        hist = self.history
        if len(hist) < self.strategy.MIN_ROWS + 1:
            return

        window = hist.iloc[-self.window :].reset_index(drop=True)
        decision_ts = int(window.iloc[-1]["open_time"])

        # Lookahead koruması: pencere karar anını aşamaz.
        self._assert_no_lookahead(window, decision_ts)
        self.lookahead_checks += 1

        last = window.iloc[-1]
        price = float(last["close"])
        ts = int(last["open_time"])
        key = (self.strategy.NAME, "BACKTEST")

        # Son fiyatı her mumda güncelle; kapanış raporu giriş fiyatında kalmasın.
        self._last_price, self._last_ts = price, ts

        if key in self.portfolio.positions:
            self.portfolio.mark_price(key[0], key[1], price, ts)
            pos = self.portfolio.positions[key]
            self._maybe_exit(pos, last, price, ts, window)
            return

        if self._pending_entry is not None:
            pending = self._pending_entry
            if ts >= pending["execute_after_ts"]:
                self._pending_entry = None
                self._open_from_signal(
                    key, pending["signal"], float(last["open"]),
                    pending["atr"], ts,
                )
            # Bekleyen emir varken yeni sinyal üstüne yazılmaz.
            return

        res = self.strategy.evaluate(window)
        if res.signal == HOLD:
            return

        atr = self._atr(window)
        if self.config.latency_ms > 0:
            self._pending_entry = {
                "signal": res.signal,
                "atr": atr,
                "execute_after_ts": ts + self.config.latency_ms,
            }
            return
        self._open_from_signal(key, res.signal, price, atr, ts)

    def _open_from_signal(self, key, side: str, raw_price: float,
                          atr: float | None, ts: int) -> None:
        price = self.execution.execution_price(
            raw_price, side, is_entry=True, atr=atr,
        )
        stop = tp = None
        if atr:
            if side == "LONG":
                stop, tp = price - STOP_ATR_MULT * atr, price + TAKE_PROFIT_ATR_MULT * atr
            else:
                stop, tp = price + STOP_ATR_MULT * atr, price - TAKE_PROFIT_ATR_MULT * atr

        self.portfolio.open_position(
            key[0], key[1], side, price, self.margin,
            leverage=self.config.leverage, step_size=0.0001, now_ms=ts,
            stop_price=stop, take_profit_price=tp,
        )

    def _maybe_exit(self, pos, last: pd.Series, price: float, ts: int,
                    window: pd.DataFrame) -> None:
        high, low = float(last["high"]), float(last["low"])
        atr = self._atr(window)
        outcome = PaperPortfolio.resolve_same_candle(
            high=high, low=low,
            stop=pos.stop_price if pos.stop_price is not None else -1e18,
            target=pos.take_profit_price if pos.take_profit_price is not None else 1e18,
            side=pos.side,
        )
        if outcome == "STOP" and pos.stop_price:
            fill = self.execution.execution_price(
                pos.stop_price, pos.side, is_entry=False, atr=atr,
            )
            self.portfolio.close_position(pos.exchange, pos.symbol, fill,
                                          now_ms=ts, reason="STOP_LOSS")
        elif outcome == "TAKE_PROFIT" and pos.take_profit_price:
            fill = self.execution.execution_price(
                pos.take_profit_price, pos.side, is_entry=False, atr=atr,
            )
            self.portfolio.close_position(pos.exchange, pos.symbol, fill,
                                          now_ms=ts, reason="TAKE_PROFIT")

    @staticmethod
    def _atr(window: pd.DataFrame) -> float | None:
        from indicators.core import atr_wilder

        try:
            atr = atr_wilder(window, 14)
            v = atr.iloc[-1]
            return None if pd.isna(v) else float(v)
        except (KeyError, IndexError, TypeError, ValueError):
            # Bozuk/eksik pencere: ATR yok sayılır, stop/hedef konmaz.
            return None

    # -- sonuç -------------------------------------------------------------
    def results(self) -> dict:
        # Açık kalan pozisyonlar son fiyattan kapatılır (rapor tutarlılığı).
        if self.portfolio.positions and self._last_price > 0:
            final_prices = {
                k: (
                    self.execution.execution_price(
                        self._last_price, pos.side, is_entry=False,
                    ),
                    self._last_ts,
                )
                for k, pos in self.portfolio.positions.items()
            }
            self.portfolio.close_all(final_prices, reason="backtest_end")
        report = PnLReport(
            trades=list(self.portfolio.closed_trades),
            starting_balance=self.portfolio.starting_balance,
            ending_balance=self.portfolio.balance,
        )
        pf = report.profit_factor
        return {
            "strategy": self.strategy.NAME,
            "bars": len(self._history),
            "trades": report.closed_count,
            "realized_pnl": round(report.total_realized, 6),
            "win_rate": round(report.win_rate, 4),
            "profit_factor": None if pf is None else round(min(pf, 999.0), 4),
            "max_drawdown": round(report.max_drawdown(), 6),
            "ending_balance": round(report.ending_balance, 6),
            "sharpe": report.sharpe(),
            "lookahead_checks": self.lookahead_checks,
            "funding": "bilinmiyor",
            "execution": {
                "latency_ms": self.config.latency_ms,
                "slippage_bps": self.config.slippage_bps,
                "slippage_atr_fraction": self.config.slippage_atr_fraction,
                "max_slippage_bps": self.config.max_slippage_bps,
            },
            "unfilled_pending_entry": self._pending_entry is not None,
        }


__all__ = ["SimpleBacktestEngine", "LookaheadError"]
