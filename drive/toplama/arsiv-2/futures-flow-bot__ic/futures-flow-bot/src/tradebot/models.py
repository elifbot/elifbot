from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> "Side":
        return Side.SHORT if self is Side.LONG else Side.LONG


@dataclass(slots=True)
class Trade:
    """Borsadan gelen tek islem (normalize). usd = notional (fiyat x miktar)."""
    exchange: str
    symbol: str        # ccxt formati: "BTC/USDT:USDT"
    ts: float          # saniye (epoch)
    price: float
    usd: float
    taker_buy: bool    # True: alici agresif (piyasa alim)


@dataclass
class Signal:
    exchange: str
    symbol: str
    side: Side
    score: int
    price: float
    ts: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class EntryPlan:
    signal: Signal
    price: float
    notional: float
    margin: float
    leverage: int
    stop_dist: float
    stop_price: float

    @property
    def exchange(self) -> str:
        return self.signal.exchange

    @property
    def symbol(self) -> str:
        return self.signal.symbol

    @property
    def side(self) -> Side:
        return self.signal.side


@dataclass
class Position:
    exchange: str
    symbol: str
    side: Side
    entry_price: float
    qty: float                 # coin miktari
    notional: float
    margin: float
    stop_price: float
    opened_ts: float
    entry_fee: float = 0.0
    entry_reasons: list[str] = field(default_factory=list)
    score: int = 0
    peak_pnl: float = 0.0
    breakeven_done: bool = False
    stop_order_id: str | None = None
    order_amount: float = 0.0  # borsa birimi (live)


@dataclass
class AccountView:
    equity: float
    available: float
    open_positions: int
    pending: int
    realized_today: float = 0.0
