from __future__ import annotations

import abc
from typing import Callable

from ..models import AccountView, EntryPlan, Position, Trade

EventCb = Callable[[str, dict], None]


class Broker(abc.ABC):
    exchange: str
    positions: dict[str, Position]

    @abc.abstractmethod
    def account(self) -> AccountView: ...

    @abc.abstractmethod
    async def place_entry(self, plan: EntryPlan, now: float) -> bool: ...

    @abc.abstractmethod
    async def close_position(self, pos: Position, reason: str, now: float, price: float,
                             detail: list[str] | None = None) -> None: ...

    @abc.abstractmethod
    async def update_stop(self, pos: Position, new_stop: float) -> None: ...

    @abc.abstractmethod
    def unrealized(self, pos: Position, price: float) -> float:
        """Tahmini NET kar/zarar (giris komisyonu + tahmini cikis komisyonu dahil)."""

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self.positions or self.has_pending(symbol)

    def has_pending(self, symbol: str) -> bool:
        return False

    def on_trade(self, trade: Trade) -> None:
        """Paper simulasyon icin: gelen her islemde dolum/stop kontrolu."""

    async def tick(self, now: float) -> None:
        """Periyodik is (bekleyen emir iptali, mutabakat...)."""

    async def startup(self) -> None:
        """Baslangic kontrolleri."""
