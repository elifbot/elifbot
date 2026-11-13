"""Small in-memory view of the paper account and its open positions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    side: str
    entry: float
    quantity: float
    margin: float
    stop_loss: float
    opened_at: int
    entry_fee: float = 0.0
    bars_held: int = 0
    last_checked_timestamp: int = 0
    motor: str = "fade"
    trailing_active: bool = False
    best_price: float | None = None
    profit_lock_active: bool = False


class Portfolio:
    def __init__(self, initial_balance: float = 1_000.0) -> None:
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.positions: dict[str, Position] = {}

    @property
    def used_margin(self) -> float:
        return sum(position.margin for position in self.positions.values())

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        total = 0.0
        for symbol, position in self.positions.items():
            price = prices.get(symbol, position.entry)
            sign = 1 if position.side == "LONG" else -1
            total += sign * (price - position.entry) * position.quantity
        return total

    def equity(self, prices: dict[str, float] | None = None) -> float:
        return self.balance + self.unrealized_pnl(prices or {})
