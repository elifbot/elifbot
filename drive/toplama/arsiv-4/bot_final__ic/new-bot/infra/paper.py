"""Local-only broker with maker-only entries and simulated reduce-only exits."""

from __future__ import annotations

import logging
from math import isfinite
import time

from core.portfolio import Portfolio, Position
from core.risk import (
    MAX_LOSS_PER_POS,
    KÂR_KİLİTLEME_ESİĞİ,
    TRAILING_ACTIVATION_USDT,
    TRAILING_DISTANCE_PERCENT,
    InsufficientFunds,
    TradePlan,
)
from core.strategy import MINIMUM_RVOL

logger = logging.getLogger(__name__)


class PaperBroker:
    def __init__(
        self,
        initial_balance: float = 10_000.0,
        maker_fee_rate: float = 0.0002,
        taker_fee_rate: float = 0.0004,
        stop_slippage_rate: float = 0.0005,
        funding_buffer_usdt: float = 0.01,
    ) -> None:
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        if any(rate < 0 or rate >= 1 for rate in (
            maker_fee_rate, taker_fee_rate, stop_slippage_rate
        )):
            raise ValueError("fee and slippage rates must be in [0, 1)")
        if not isfinite(funding_buffer_usdt) or funding_buffer_usdt < 0:
            raise ValueError("funding_buffer_usdt must be finite and non-negative")
        self.portfolio = Portfolio(initial_balance)
        self.maker_fee_rate = maker_fee_rate
        self.taker_fee_rate = taker_fee_rate
        self.stop_slippage_rate = stop_slippage_rate
        self.funding_buffer_usdt = funding_buffer_usdt
        self.trades: list[dict[str, object]] = []
        self.mode = "paper"

    def open_position(
        self,
        symbol: str,
        plan: TradePlan,
        timestamp: int | None = None,
        order_type: str = "post_only",
    ) -> Position:
        if order_type != "post_only":
            raise ValueError("entries must be post-only maker orders")
        if plan.side not in {"LONG", "SHORT"}:
            raise ValueError("position side must be LONG or SHORT")
        if symbol in self.portfolio.positions:
            raise ValueError(f"position already open for {symbol}")
        available = self.portfolio.balance - self.portfolio.used_margin
        fee = plan.notional * self.maker_fee_rate
        required = plan.margin + fee + self.funding_buffer_usdt
        if required > available:
            raise InsufficientFunds(
                f"INSUFFICIENT_FUNDS: available={available:.8f}, "
                f"required={required:.8f}"
            )
        self.portfolio.balance -= fee
        opened_at = timestamp or int(time.time() * 1000)
        position = Position(
            symbol=symbol,
            side=plan.side,
            entry=plan.entry,
            quantity=plan.quantity,
            margin=plan.margin,
            stop_loss=plan.stop_loss,
            opened_at=opened_at,
            entry_fee=fee,
            last_checked_timestamp=opened_at,
            best_price=plan.entry,
        )
        self.portfolio.positions[symbol] = position
        self.trades.append({
            "type": "OPEN", "symbol": symbol, "side": plan.side,
            "price": plan.entry, "quantity": plan.quantity, "fee": fee,
            "timestamp": opened_at, "mode": "paper",
            "order_type": "post_only", "post_only": True, "reduce_only": False,
            "limit_price": plan.entry,
        })
        return position

    def close_position(
        self,
        symbol: str,
        price: float,
        reason: str = "signal",
        timestamp: int | None = None,
    ) -> dict[str, object]:
        if price <= 0:
            raise ValueError("price must be positive")
        position = self.portfolio.positions.get(symbol)
        if position is None:
            raise ValueError(f"no paper position is open for {symbol}")

        slippage = (
            price * self.stop_slippage_rate
            if reason in {
                "stop_loss", "position_loss_stop", "trailing_stop", "time_stop"
            }
            else 0.0
        )
        fill_price = price - slippage if position.side == "LONG" else price + slippage
        exit_fee = fill_price * position.quantity * self.taker_fee_rate
        direction = 1.0 if position.side == "LONG" else -1.0
        gross_pnl = direction * (fill_price - position.entry) * position.quantity
        net_pnl = gross_pnl - position.entry_fee - exit_fee
        del self.portfolio.positions[symbol]
        self.portfolio.balance += gross_pnl - exit_fee
        trade = {
            "type": "CLOSE", "symbol": symbol, "side": position.side,
            "entry": position.entry,
            "trigger_price": price, "price": fill_price,
            "quantity": position.quantity, "gross_pnl": gross_pnl,
            "entry_fee": position.entry_fee, "fee": exit_fee,
            "slippage": slippage, "pnl": net_pnl, "reason": reason,
            "timestamp": timestamp or int(time.time() * 1000), "mode": "paper",
            "execution_type": (
                "stop_market"
                if reason in {"stop_loss", "position_loss_stop", "trailing_stop"}
                else "market"
            ),
            "reduce_only": True,
        }
        self.trades.append(trade)
        return trade

    def check_exit(
        self,
        symbol: str,
        high: float,
        low: float,
        close: float | None = None,
        timestamp: int | None = None,
        impulse_pct: float | None = None,
        rvol: float | None = None,
        reference_price: float | None = None,
    ) -> dict[str, object] | None:
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return None
        if reference_price is not None:
            if not isfinite(reference_price) or reference_price <= 0:
                raise ValueError("reference price must be positive and finite")
            high = low = close = reference_price
        current_close = close if close is not None else (high + low) / 2.0
        if min(high, low, current_close) <= 0 or high < low:
            raise ValueError("invalid exit candle")
        direction = 1 if position.side == "LONG" else -1
        unrealized_pnl = direction * (current_close - position.entry) * position.quantity
        if unrealized_pnl <= -MAX_LOSS_PER_POS:
            trade = self.close_position(
                symbol, current_close, "position_loss_stop", timestamp
            )
            logger.warning(
                "STOP LOSS TETİKLENDİ: [%s] %.0f USDT zarar ile kapatıldı",
                symbol,
                MAX_LOSS_PER_POS,
            )
            return trade
        # If both levels are touched in one bar, the conservative stop wins.
        stop_reason = "trailing_stop" if position.trailing_active else "stop_loss"
        if position.side == "LONG" and low <= position.stop_loss:
            if position.trailing_active:
                return self._close_trailing_position(
                    symbol, position.stop_loss, timestamp
                )
            return self.close_position(symbol, position.stop_loss, stop_reason, timestamp)
        if position.side == "SHORT" and high >= position.stop_loss:
            if position.trailing_active:
                return self._close_trailing_position(
                    symbol, position.stop_loss, timestamp
                )
            return self.close_position(symbol, position.stop_loss, stop_reason, timestamp)

        if timestamp is not None and timestamp > position.last_checked_timestamp:
            position.bars_held += 1
            position.last_checked_timestamp = timestamp

        favorable_price = high if position.side == "LONG" else low
        favorable_pnl = direction * (
            favorable_price - position.entry
        ) * position.quantity
        if not position.trailing_active and favorable_pnl >= TRAILING_ACTIVATION_USDT:
            position.trailing_active = True
            position.best_price = favorable_price
            position.stop_loss = self._percentage_trailing_stop(position, favorable_price)
            logger.info(
                "YÜZDESEL TRAILING STOP AKTİF: [%s] en iyi fiyat=%.8f stop=%.8f",
                symbol, favorable_price, position.stop_loss,
            )
        elif position.trailing_active:
            best_price = position.best_price or position.entry
            if position.side == "LONG":
                position.best_price = max(best_price, favorable_price)
                trailing_stop = self._percentage_trailing_stop(
                    position, position.best_price
                )
                position.stop_loss = max(position.stop_loss, trailing_stop)
            else:
                position.best_price = min(best_price, favorable_price)
                trailing_stop = self._percentage_trailing_stop(
                    position, position.best_price
                )
                position.stop_loss = min(position.stop_loss, trailing_stop)

        stop_touched = (
            low <= position.stop_loss
            if position.side == "LONG"
            else high >= position.stop_loss
        )
        if stop_touched and position.trailing_active:
            return self._close_trailing_position(symbol, position.stop_loss, timestamp)

        if impulse_pct is not None and rvol is not None:
            momentum_continues = (
                impulse_pct > 0 if position.side == "LONG" else impulse_pct < 0
            ) and rvol >= MINIMUM_RVOL
            if unrealized_pnl >= KÂR_KİLİTLEME_ESİĞİ and momentum_continues:
                if not position.profit_lock_active:
                    position.profit_lock_active = True
                    logger.info("MOMENTUM DEVAM EDİYOR - POZİSYON AÇIK TUTULUYOR")
            elif not momentum_continues:
                trade = self.close_position(
                    symbol, current_close, "momentum_end", timestamp
                )
                if unrealized_pnl > 0:
                    logger.info("MOMENTUM BİTTİ - KÂR İLE KAPATILDI")
                else:
                    logger.info("MOMENTUM BİTTİ - POZİSYON KAPATILDI")
                return trade

        estimated_net_pnl = (
            (1 if position.side == "LONG" else -1)
            * (current_close - position.entry) * position.quantity
            - position.entry_fee
            - current_close * position.quantity
            * (self.taker_fee_rate + self.stop_slippage_rate)
        )
        if position.bars_held >= 6 and estimated_net_pnl <= 0:
            return self.close_position(symbol, current_close, "time_stop", timestamp)
        return None

    @staticmethod
    def _percentage_trailing_stop(position: Position, best_price: float) -> float:
        distance = TRAILING_DISTANCE_PERCENT / 100.0
        if position.side == "LONG":
            return best_price * (1 - distance)
        return best_price * (1 + distance)

    def _close_trailing_position(
        self, symbol: str, price: float, timestamp: int | None
    ) -> dict[str, object]:
        logger.info(
            "YÜZDESEL TRAILING STOP TETİKLENDİ: [%s] %%%g düşüş ile kapatıldı",
            symbol,
            TRAILING_DISTANCE_PERCENT,
        )
        return self.close_position(symbol, price, "trailing_stop", timestamp)

    def mark_to_market(self, prices: dict[str, float]) -> float:
        return self.portfolio.equity(prices)
