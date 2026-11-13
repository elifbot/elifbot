"""
backtests/engine.py — Mum-mum ilerleyen, lookahead korumalı paper backtest motoru.

Tasarım kuralları:
  * Mumlar motora TEK TEK verilir (feed), karar yalnızca o ana kadarki
    pencereden üretilir.
  * Stratejiye verilen pencere, karar anından SONRAKİ hiçbir mumu içermez;
    ihlal edilirse LookaheadError fırlatılır.
  * Muhasebe, canlı paper oturumuyla AYNI PaperPortfolio sınıfını kullanır.
  * Parametreler pencere başında dondurulur (params_frozen).
  * `USES_DYNAMIC_FLOW_EXIT = True` olan stratejilerde kanonik $50 marj, %8.0 (-$40)
    acil güvenlik stopu ve dinamik akım/dalga çıkış motoru (`evaluate_exit`) birebir çalışır.
"""
from __future__ import annotations

import pandas as pd

from backtests.engine_interface import (
    BacktestConfig,
    BacktestEngine,
    LookaheadError,
)
from backtests.execution import ExecutionModel
from portfolio.paper_futures import PaperPortfolio
from reports.pnl_report import PnLReport
from strategies.base import HOLD, StrategyBase

STOP_ATR_MULT = 2.0
TAKE_PROFIT_ATR_MULT = 4.0
DEFAULT_WINDOW = 300


class SimpleBacktestEngine(BacktestEngine):
    """Tek sembol, tek strateji üzerinde çalışan nedensel backtest motoru."""

    def __init__(
        self,
        strategy: StrategyBase,
        config: BacktestConfig | None = None,
        *,
        window: int = DEFAULT_WINDOW,
        margin: float = 50.0,
    ) -> None:
        super().__init__(config or BacktestConfig())
        self.strategy = strategy
        self.window = max(int(window), strategy.MIN_ROWS + 1)
        strat_margin = getattr(strategy, "CANONICAL_MARGIN_USDT", None)
        self.margin = float(strat_margin if strat_margin is not None and margin == 50.0 else margin)
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
        """Tüm DataFrame'i mum-mum besler (`taker_buy_quote` gibi gerçek akış alanlarını korur)."""
        base_cols = ["open_time", "open", "high", "low", "close", "volume"]
        extra_cols = [c for c in ("taker_buy_quote", "trades_count") if c in df.columns]
        cols = base_cols + extra_cols
        for _, row in df[cols].iterrows():
            self.feed({c: row[c] for c in cols})
            self.step()
        return self

    # -- tek adım ----------------------------------------------------------
    def step(self) -> None:
        if len(self._history) < self.strategy.MIN_ROWS + 1:
            return

        window = pd.DataFrame(self._history[-self.window :])
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
                    key,
                    pending["signal"],
                    float(last["open"]),
                    pending["atr"],
                    ts,
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

    def _open_from_signal(
        self,
        key,
        side: str,
        raw_price: float,
        atr: float | None,
        ts: int,
    ) -> None:
        price = self.execution.execution_price(
            raw_price,
            side,
            is_entry=True,
            atr=atr,
        )
        stop = tp = None
        if getattr(self.strategy, "USES_DYNAMIC_FLOW_EXIT", False):
            stop_pct = float(getattr(self.strategy, "HARD_STOP_PCT", 8.0))
            if side == "LONG":
                stop = price * (1.0 - stop_pct / 100.0)
            else:
                stop = price * (1.0 + stop_pct / 100.0)
            tp = None
        elif atr:
            if side == "LONG":
                stop, tp = price - STOP_ATR_MULT * atr, price + TAKE_PROFIT_ATR_MULT * atr
            else:
                stop, tp = price + STOP_ATR_MULT * atr, price - TAKE_PROFIT_ATR_MULT * atr

        self.portfolio.open_position(
            key[0],
            key[1],
            side,
            price,
            self.margin,
            leverage=self.config.leverage,
            step_size=0.0001,
            now_ms=ts,
            stop_price=stop,
            take_profit_price=tp,
        )

    def _maybe_exit(
        self,
        pos,
        last: pd.Series,
        price: float,
        ts: int,
        window: pd.DataFrame,
    ) -> None:
        high, low = float(last["high"]), float(last["low"])
        atr = self._atr(window)

        outcome = PaperPortfolio.resolve_same_candle(
            high=high,
            low=low,
            stop=pos.stop_price if pos.stop_price is not None else (-1e18 if pos.side == "LONG" else 1e18),
            target=pos.take_profit_price if pos.take_profit_price is not None else (1e18 if pos.side == "LONG" else -1e18),
            side=pos.side,
        )
        if outcome == "STOP" and pos.stop_price:
            fill = self.execution.execution_price(
                min(pos.stop_price, float(last["open"])) if pos.side == "LONG" else max(pos.stop_price, float(last["open"])),
                pos.side,
                is_entry=False,
                atr=atr,
            )
            in_profit_lock = (
                (pos.side == "LONG" and pos.stop_price > pos.entry_price)
                or (pos.side == "SHORT" and pos.stop_price < pos.entry_price)
            )
            self.portfolio.close_position(
                pos.exchange,
                pos.symbol,
                fill,
                now_ms=ts,
                reason="PROFIT_LOCK_STOP" if in_profit_lock else "STOP_LOSS",
            )
            return
        if outcome == "TAKE_PROFIT" and pos.take_profit_price:
            fill = self.execution.execution_price(
                pos.take_profit_price,
                pos.side,
                is_entry=False,
                atr=atr,
            )
            self.portfolio.close_position(
                pos.exchange,
                pos.symbol,
                fill,
                now_ms=ts,
                reason="TAKE_PROFIT",
            )
            return

        fav_px = high if pos.side == "LONG" else low
        pos.mfe_usdt = max(float(getattr(pos, "mfe_usdt", 0.0)), float(pos.unrealised_pnl(fav_px)))

        if getattr(self.strategy, "USES_DYNAMIC_FLOW_EXIT", False) and hasattr(
            self.strategy, "evaluate_exit"
        ):
            exit_dec = self.strategy.evaluate_exit(
                window,
                pos,
                price=price,
                now_ms=ts,
                fee_rate=float(self.config.fee_rate),
            )
            if isinstance(exit_dec, dict) and bool(exit_dec.get("should_exit", False)):
                fill = self.execution.execution_price(
                    price,
                    pos.side,
                    is_entry=False,
                    atr=atr,
                )
                self.portfolio.close_position(
                    pos.exchange,
                    pos.symbol,
                    fill,
                    now_ms=ts,
                    reason=str(exit_dec.get("exit_kind") or "FLOW_EXIT"),
                )
                return

            # Mum kapanışı sonrası t+1 barı için nedensel (causal) kâr-kilidi stop güncellemesi:
            self._ratchet_dynamic_stop_after_bar(pos, close_px=price)

    def _ratchet_dynamic_stop_after_bar(self, pos, close_px: float) -> None:
        """Canlı `RiskManager.update` ile birebir aynı 3-kademeli MFE kâr kilidini
        t mumu kapandıktan sonra t+1 mumu için nedensel olarak kurar (look-ahead sıfır)."""
        mfe = float(getattr(pos, "mfe_usdt", 0.0))
        qty = float(getattr(pos, "qty_base", 0.0))
        if mfe < 1.55 or qty <= 0 or close_px <= 0:
            return
        notional = float(pos.entry_price) * qty
        roundtrip_fee = notional * float(self.config.fee_rate) * 2.0
        if mfe >= 8.0:
            locked_usd = mfe * 0.80
        elif mfe >= 4.5:
            locked_usd = mfe * 0.72
        elif mfe >= 2.2:
            locked_usd = mfe * 0.65
        else:
            locked_usd = max(roundtrip_fee + 0.25, 0.55)

        if pos.side == "LONG":
            cand_stop = float(pos.entry_price) + (locked_usd / qty)
            # Yalnızca mevcut kapanış fiyatının altındaysa geçerli bir STOP emri konabilir
            cand_stop = min(cand_stop, close_px * 0.9992)
            if cand_stop > float(pos.entry_price) and (pos.stop_price is None or cand_stop > pos.stop_price):
                pos.stop_price = cand_stop
        else:
            cand_stop = float(pos.entry_price) - (locked_usd / qty)
            cand_stop = max(cand_stop, close_px * 1.0008)
            if cand_stop < float(pos.entry_price) and (pos.stop_price is None or cand_stop < pos.stop_price):
                pos.stop_price = cand_stop

    @staticmethod
    def _atr(window: pd.DataFrame) -> float | None:
        try:
            if len(window) < 15:
                return None
            high = window["high"].astype(float)
            low = window["low"].astype(float)
            close = window["close"].astype(float)
            prev_close = close.shift(1)
            tr = pd.concat(
                [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
                axis=1,
            ).max(axis=1)
            atr = tr.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()
            v = atr.iloc[-1]
            return None if pd.isna(v) else float(v)
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    # -- sonuç -------------------------------------------------------------
    def results(self) -> dict:
        if self.portfolio.positions and self._last_price > 0:
            final_prices = {
                k: (
                    self.execution.execution_price(
                        self._last_price,
                        pos.side,
                        is_entry=False,
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
