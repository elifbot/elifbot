from abc import ABC, abstractmethod
from typing import Dict, Any

class ExchangeAdapter(ABC):
    name = 'base'

    @abstractmethod
    async def get_balance(self) -> float: ...

    @abstractmethod
    async def set_cross_leverage(self, symbol: str, leverage: int): ...

    @abstractmethod
    async def place_maker_entry(self, symbol: str, side: str, qty: float, price: float, client_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def place_protective_exit(self, symbol: str, side: str, qty: float, stop: float, target: float, client_id: str): ...

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str): ...

    @abstractmethod
    async def close_position(self, symbol: str, side: str, qty: float): ...
