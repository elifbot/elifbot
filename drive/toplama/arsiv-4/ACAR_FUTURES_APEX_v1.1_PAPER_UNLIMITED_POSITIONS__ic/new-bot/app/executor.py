"""Two-motor signal execution through a local paper broker."""

from __future__ import annotations

import logging
from math import isfinite

from core.portfolio import Position
from core.risk import (
    DailyLossLimitReached,
    InsufficientFunds,
    MIN_IMPULSE_PERCENT,
    MIN_RVOL_FOR_ENTRY,
    MaxPositionsReached,
    RiskManager,
)
from core.symbols import base_asset, is_blacklisted
from core.elite_strategy import EliteConfluenceStrategy
from core.strategy import (
    FadeStrategy,
    Signal,
    TrendMomentumStrategy,
    measure_impulse_rvol,
)
from infra.exchanges.base import OrderBook, Ticker
from infra.market_data.models import Candle
from infra.paper import PaperBroker
from state.store import StateStore

logger = logging.getLogger(__name__)


class Executor:
    def __init__(
        self,
        broker: PaperBroker,
        strategy: FadeStrategy | None = None,
        trend_strategy: TrendMomentumStrategy | None = None,
        risk: RiskManager | None = None,
        store: StateStore | None = None,
        strategy_mode: str = 'classic',
        elite_strategy: EliteConfluenceStrategy | None = None,
    ) -> None:
        if broker.mode != "paper":
            raise ValueError("Executor accepts only a paper broker")
        self.broker = broker
        self.strategy = strategy or FadeStrategy()
        self.trend_strategy = trend_strategy or TrendMomentumStrategy()
        self.risk = risk or RiskManager()
        self.store = store
        if strategy_mode not in {'classic', 'elite'}:
            raise ValueError('strategy_mode must be classic or elite')
        self.strategy_mode = strategy_mode
        self.elite_strategy = elite_strategy or EliteConfluenceStrategy()
        self._last_signal_timestamp: dict[str, int] = {}
        self._latest_prices: dict[str, float] = {}
        self._latest_tickers: dict[str, Ticker] = {}
        self._restore()

    def _snapshot(self) -> dict[str, object]:
        portfolio = self.broker.portfolio
        return {
            "mode": "paper",
            "balance": portfolio.balance,
            "initial_balance": portfolio.initial_balance,
            "last_signal_timestamp": self._last_signal_timestamp,
            "positions": {
                symbol: {
                    "side": position.side, "entry": position.entry,
                    "quantity": position.quantity, "margin": position.margin,
                    "stop_loss": position.stop_loss,
                    "opened_at": position.opened_at, "entry_fee": position.entry_fee,
                    "bars_held": position.bars_held,
                    "last_checked_timestamp": position.last_checked_timestamp,
                    "motor": position.motor,
                    "trailing_active": position.trailing_active,
                    "best_price": position.best_price,
                    "profit_lock_active": position.profit_lock_active,
                }
                for symbol, position in portfolio.positions.items()
            },
        }

    def _restore(self) -> None:
        if self.store is None:
            return
        saved = self.store.load_state()
        if saved is None:
            return
        if saved.get("mode") != "paper":
            raise ValueError("refusing to restore non-paper state")
        balance = float(saved["balance"])
        initial_balance = float(saved.get("initial_balance", self.broker.portfolio.initial_balance))
        if not isfinite(balance) or balance < 0:
            raise ValueError("stored balance cannot be negative")
        if not isfinite(initial_balance) or initial_balance <= 0:
            raise ValueError("stored initial balance is invalid")
        self.broker.portfolio.balance = balance
        self.broker.portfolio.initial_balance = initial_balance
        timestamps = saved.get("last_signal_timestamp", {})
        if not isinstance(timestamps, dict):
            raise ValueError("stored signal timestamps must be an object")
        self._last_signal_timestamp = {
            str(symbol): int(timestamp) for symbol, timestamp in timestamps.items()
        }
        positions = saved.get("positions", {})
        if not isinstance(positions, dict):
            raise ValueError("stored positions must be an object")
        for symbol, raw in positions.items():
            if not isinstance(raw, dict) or raw.get("side") not in {"LONG", "SHORT"}:
                raise ValueError("stored position has invalid side")
            position = Position(
                symbol=symbol,
                side=str(raw["side"]),
                entry=float(raw["entry"]),
                quantity=float(raw["quantity"]),
                margin=float(raw["margin"]),
                stop_loss=float(raw["stop_loss"]),
                opened_at=int(raw["opened_at"]),
                entry_fee=float(raw.get("entry_fee", 0.0)),
                bars_held=int(raw.get("bars_held", 0)),
                last_checked_timestamp=int(raw.get("last_checked_timestamp", 0)),
                motor=str(raw.get("motor", "fade")),
                trailing_active=raw.get("trailing_active", False),
                best_price=(
                    None if raw.get("best_price") is None
                    else float(raw["best_price"])
                ),
                profit_lock_active=raw.get("profit_lock_active", False),
            )
            if not isinstance(position.trailing_active, bool):
                raise ValueError("stored trailing state must be a boolean")
            if not isinstance(position.profit_lock_active, bool):
                raise ValueError("stored profit-lock state must be a boolean")
            if (
                not all(isfinite(value) for value in (
                    position.entry, position.quantity, position.margin,
                    position.stop_loss, position.entry_fee,
                ))
                or min(position.entry, position.quantity, position.margin,
                       position.stop_loss) <= 0
                or position.entry_fee < 0
                or position.bars_held < 0
                or (
                    position.best_price is not None
                    and (
                        not isfinite(position.best_price)
                        or position.best_price <= 0
                    )
                )
            ):
                raise ValueError("stored position contains invalid non-positive values")
            self.broker.portfolio.positions[symbol] = position
            self._latest_prices[symbol] = position.entry

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save_state(self._snapshot())

    def _record_trade(self, trade: dict[str, object]) -> None:
        if self.store is not None:
            self.store.append_trade(trade)

    def latest_ticker(self, symbol: str) -> Ticker | None:
        return self._latest_tickers.get(symbol)

    def manage_position(
        self,
        symbol: str,
        candles_5m: list[Candle],
        reference_ticker: Ticker | None = None,
        verification_candle: Candle | None = None,
    ) -> dict[str, object] | None:
        if not candles_5m:
            raise ValueError("5m candles cannot be empty")
        if symbol not in self.broker.portfolio.positions:
            return None
        latest = candles_5m[-1]
        if reference_ticker is None:
            reference_ticker = self._latest_tickers.get(symbol)
        if reference_ticker is not None:
            expected_symbol = symbol.rsplit(":", 1)[-1].upper()
            if (
                reference_ticker.symbol.upper() != expected_symbol
                or not isfinite(reference_ticker.last_price)
                or reference_ticker.last_price <= 0
                or reference_ticker.timestamp_ms < 0
            ):
                logger.error(
                    "HATALI FİYAT VERİSİ REDDEDİLDİ: [%s] "
                    "ticker_symbol=%s",
                    symbol,
                    reference_ticker.symbol,
                )
                self._persist()
                return None
            if (
                verification_candle is not None
                and verification_candle.timestamp // 300_000
                == reference_ticker.timestamp_ms // 300_000
                and not (
                    verification_candle.low
                    <= reference_ticker.last_price
                    <= verification_candle.high
                )
            ):
                logger.error(
                    "HATALI FİYAT VERİSİ REDDEDİLDİ: [%s] "
                    "ticker=%.12g candle_range=[%.12g, %.12g]",
                    symbol,
                    reference_ticker.last_price,
                    verification_candle.low,
                    verification_candle.high,
                )
                self._persist()
                return None
        impulse_pct, rvol = measure_impulse_rvol(candles_5m)
        trade = self.broker.check_exit(
            symbol,
            latest.high,
            latest.low,
            latest.close,
            latest.timestamp,
            impulse_pct=impulse_pct, rvol=rvol,
            reference_price=(
                reference_ticker.last_price
                if reference_ticker is not None else None
            ),
        )
        if trade is not None:
            self._last_signal_timestamp[symbol] = latest.timestamp
            self._record_trade(trade)
        self._persist()
        return trade

    def process(
        self,
        symbol: str,
        candles_5m: list[Candle],
        tick_size: float = 0.0,
        signal_override: Signal | None = None,
        market_price: float | None = None,
        reference_ticker: Ticker | None = None,
        order_book: OrderBook | None = None,
    ) -> Signal:
        if not candles_5m:
            raise ValueError("5m candles cannot be empty")
        if not isfinite(tick_size) or tick_size < 0:
            raise ValueError("tick_size must be finite and non-negative")
        if market_price is not None and (
            not isfinite(market_price) or market_price <= 0
        ):
            raise ValueError("market_price must be positive and finite")
        latest = candles_5m[-1]
        execution_price = market_price if market_price is not None else latest.close
        self._latest_prices[symbol] = execution_price
        position = self.broker.portfolio.positions.get(symbol)
        if position is not None:
            impulse_pct, rvol = measure_impulse_rvol(candles_5m)
            trade = self.manage_position(
                symbol, candles_5m, reference_ticker=reference_ticker
            )
            if trade is not None:
                return Signal("HOLD", 0.0, 0.0, None)
            current_position = self.broker.portfolio.positions.get(symbol)
            if current_position is not None:
                return Signal(
                    "HOLD", impulse_pct, rvol, None, current_position.motor
                )

        if is_blacklisted(symbol):
            return Signal("HOLD", 0.0, 0.0, None)
        if self._last_signal_timestamp.get(symbol) == latest.timestamp:
            return Signal("HOLD", 0.0, 0.0, None)

        underlying = base_asset(symbol)
        other_position = next(
            (
                key for key in self.broker.portfolio.positions
                if key != symbol and base_asset(key) == underlying
            ),
            None,
        )
        if other_position is not None:
            position_symbol = other_position
            impulse_pct, rvol = measure_impulse_rvol(candles_5m)
            trade = self.broker.check_exit(
                position_symbol,
                latest.high,
                latest.low,
                latest.close,
                latest.timestamp,
                impulse_pct=impulse_pct,
                rvol=rvol,
            )
            if trade is not None:
                self._record_trade(trade)
                self._last_signal_timestamp[position_symbol] = latest.timestamp
            self._last_signal_timestamp[symbol] = latest.timestamp
            self._persist()
            return Signal("HOLD", 0.0, 0.0, None, "conflict")

        if signal_override is None:
            impulse_pct, rvol = measure_impulse_rvol(candles_5m)
            if abs(impulse_pct) < MIN_IMPULSE_PERCENT:
                self._persist()
                return Signal(
                    "HOLD", impulse_pct, rvol, None, "risk",
                    "dusuk_momentum",
                )
            if rvol < MIN_RVOL_FOR_ENTRY:
                self._persist()
                return Signal(
                    "HOLD", impulse_pct, rvol, None, "risk",
                    "dusuk_hacim",
                )
            if self.strategy_mode == "elite":
                elite_signal = self.elite_strategy.evaluate(candles_5m)
                fade_signal = Signal("HOLD", impulse_pct, rvol, None, "fade")
                trend_signal = elite_signal
            else:
                fade_signal = self.strategy.evaluate(candles_5m)
                trend_signal = self.trend_strategy.evaluate(candles_5m)
        else:
            impulse_pct = signal_override.impulse_pct
            rvol = signal_override.rvol
            fade_signal = Signal("HOLD", impulse_pct, rvol, None, "fade")
            trend_signal = signal_override
        self._last_signal_timestamp[symbol] = latest.timestamp
        if signal_override is not None:
            signal = signal_override
        elif fade_signal.side != "HOLD" and trend_signal.side != "HOLD":
            if fade_signal.side != trend_signal.side:
                self._persist()
                return Signal("HOLD", 0.0, 0.0, None, "conflict")
            signal = fade_signal
        else:
            signal = fade_signal if fade_signal.side != "HOLD" else trend_signal
        if signal.side == "HOLD" and fade_signal.side == "HOLD":
            signal = (
                trend_signal
                if trend_signal.rejection_code
                else fade_signal
            )
        signal = Signal(
            signal.side,
            impulse_pct,
            rvol,
            signal.stop_distance_fraction,
            signal.motor,
            signal.rejection_code,
        )

        if position is not None:
            self._persist()
            return Signal(
                "HOLD", signal.impulse_pct, signal.rvol, None,
                signal.motor, "POSITION_ALREADY_OPEN",
            )
        if signal.side == "HOLD":
            self._persist()
            return signal
        if signal.stop_distance_fraction is None:
            self._persist()
            return Signal(
                "HOLD", signal.impulse_pct, signal.rvol, None,
                signal.motor, "INVALID_SIGNAL",
            )

        try:
            # No daily loss circuit breaker: only per-position risk controls remain.
            free_balance = (
                self.broker.portfolio.balance - self.broker.portfolio.used_margin
            )
            required_balance = self.risk.required_balance_per_position
            if free_balance < required_balance:
                raise InsufficientFunds(
                    f"INSUFFICIENT_FUNDS: available={free_balance:.8f}, "
                    f"required={required_balance:.8f}"
                )
            equity = self.broker.mark_to_market(self._latest_prices)
            self.risk.ensure_position_capacity(
                len(self.broker.portfolio.positions), equity
            )
            if tick_size <= 0:
                tick_size = execution_price * 0.0005
            entry_price = (
                execution_price - tick_size
                if signal.side == "LONG"
                else execution_price + tick_size
            )
            plan = self.risk.plan(
                free_balance,
                entry_price,
                signal.stop_distance_fraction,
                signal.side,
                open_positions=len(self.broker.portfolio.positions),
                equity=equity,
            )
            if is_blacklisted(underlying):
                return Signal("HOLD", 0.0, 0.0, None)
            self.broker.open_position(
                symbol,
                plan,
                latest.timestamp,
                order_type="post_only",
                order_book=order_book,
            )
            self.broker.portfolio.positions[symbol].motor = signal.motor
            self.broker.trades[-1]["motor"] = signal.motor
            self._record_trade(self.broker.trades[-1])
            self._persist()
        except MaxPositionsReached:
            self._persist()
            logger.info("MAX_POSITIONS_REACHED: skipping paper entry for %s", symbol)
            return Signal(
                side="HOLD",
                impulse_pct=signal.impulse_pct,
                rvol=signal.rvol,
                stop_distance_fraction=None,
                motor=signal.motor,
                rejection_code=MaxPositionsReached.code,
            )
        except InsufficientFunds:
            self._persist()
            logger.warning("insufficient balance: skipping paper entry for %s", symbol)
            return Signal(
                side="HOLD",
                impulse_pct=signal.impulse_pct,
                rvol=signal.rvol,
                stop_distance_fraction=None,
                motor=signal.motor,
                rejection_code=InsufficientFunds.code,
            )
        return signal

    def process_tick(
        self,
        symbol: str,
        price: float,
        timestamp_ms: int,
        ticker_symbol: str | None = None,
    ) -> dict[str, object] | None:
        if not isfinite(price) or price <= 0 or timestamp_ms < 0:
            raise ValueError("tick price and timestamp are invalid")
        self._latest_prices[symbol] = price
        self._latest_tickers[symbol] = Ticker(
            ticker_symbol or symbol.rsplit(":", 1)[-1],
            0.0,
            price,
            timestamp_ms,
        )
        if symbol not in self.broker.portfolio.positions:
            return None
        candle_timestamp = timestamp_ms - timestamp_ms % (5 * 60_000)
        trade = self.broker.check_exit(
            symbol,
            high=price,
            low=price,
            close=price,
            timestamp=candle_timestamp,
        )
        if trade is not None:
            self._record_trade(trade)
        self._persist()
        return trade

    def close(self, symbol: str, price: float, reason: str = "manual") -> dict[str, object]:
        trade = self.broker.close_position(symbol, price, reason)
        self._record_trade(trade)
        self._persist()
        return trade
