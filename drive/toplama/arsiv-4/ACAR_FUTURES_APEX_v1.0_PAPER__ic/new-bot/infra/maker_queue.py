"""Conservative maker-limit queue approximation for PAPER research only.

It is not an exchange matching engine: public trades do not reveal exact queue
priority. Queue-ahead is therefore estimated from displayed depth and fills
are participation-capped. No live order API exists in this project.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from math import isfinite


class OrderState(str, Enum):
    NEW="NEW"
    OPEN="OPEN"
    PARTIALLY_FILLED="PARTIALLY_FILLED"
    FILLED="FILLED"
    CANCELED="CANCELED"
    EXPIRED="EXPIRED"
    REJECTED="REJECTED"


@dataclass
class MakerOrder:
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: float
    remaining: float
    queue_ahead: float
    filled: float = 0.0
    state: OrderState = OrderState.NEW
    created_ms: int = 0
    updated_ms: int = 0
    reason: str = ""


class MakerQueueSimulator:
    def __init__(self, participation_rate: float = 0.10):
        if not isfinite(participation_rate) or not 0 < participation_rate <= 1:
            raise ValueError("participation_rate must be in (0, 1]")
        self.participation_rate=participation_rate
        self.orders: dict[str,MakerOrder]={}

    def submit(self, order_id: str, symbol: str, side: str, price: float,
               quantity: float, best_bid: float, best_ask: float,
               displayed_queue_ahead: float, timestamp_ms: int) -> MakerOrder:
        if order_id in self.orders:
            raise ValueError("duplicate order_id")
        if side not in {"BUY","SELL"}:
            raise ValueError("side must be BUY or SELL")
        vals=(price,quantity,best_bid,best_ask,displayed_queue_ahead)
        if any(not isfinite(v) for v in vals) or min(price,quantity,best_bid,best_ask) <= 0 or displayed_queue_ahead < 0:
            raise ValueError("invalid order/book values")
        if best_bid >= best_ask:
            raise ValueError("crossed or locked book")
        order=MakerOrder(order_id,symbol,side,price,quantity,quantity,
                         displayed_queue_ahead,created_ms=timestamp_ms,
                         updated_ms=timestamp_ms)
        crosses=(side=="BUY" and price >= best_ask) or (side=="SELL" and price <= best_bid)
        if crosses:
            order.state=OrderState.REJECTED
            order.reason="POST_ONLY_WOULD_TAKE"
        elif (side=="BUY" and price > best_bid) or (side=="SELL" and price < best_ask):
            # Price improvement inside spread is allowed only if still non-crossing.
            order.state=OrderState.OPEN
        else:
            order.state=OrderState.OPEN
        self.orders[order_id]=order
        return order

    def on_trade(self, symbol: str, aggressor_side: str, price: float,
                 quantity: float, timestamp_ms: int) -> list[MakerOrder]:
        if aggressor_side not in {"BUY","SELL"}:
            raise ValueError("aggressor_side must be BUY or SELL")
        if not isfinite(price) or not isfinite(quantity) or price <= 0 or quantity <= 0:
            return []
        changed=[]
        for order in self.orders.values():
            if order.symbol != symbol or order.state not in {OrderState.OPEN,OrderState.PARTIALLY_FILLED}:
                continue
            # A resting bid is hit by aggressive sells; a resting ask by aggressive buys.
            eligible=(order.side=="BUY" and aggressor_side=="SELL" and price <= order.price) or (
                order.side=="SELL" and aggressor_side=="BUY" and price >= order.price)
            if not eligible:
                continue
            order.updated_ms=timestamp_ms
            flow=quantity*self.participation_rate
            ahead=min(order.queue_ahead,flow)
            order.queue_ahead-=ahead
            available=max(0.0,flow-ahead)
            fill=min(order.remaining,available)
            if fill > 0:
                order.filled+=fill
                order.remaining-=fill
                order.state=OrderState.FILLED if order.remaining <= 1e-12 else OrderState.PARTIALLY_FILLED
            changed.append(order)
        return changed

    def cancel(self, order_id: str, timestamp_ms: int) -> MakerOrder:
        order=self.orders[order_id]
        if order.state in {OrderState.OPEN,OrderState.PARTIALLY_FILLED}:
            order.state=OrderState.CANCELED
            order.updated_ms=timestamp_ms
        return order

    def expire(self, order_id: str, timestamp_ms: int) -> MakerOrder:
        order=self.orders[order_id]
        if order.state in {OrderState.OPEN,OrderState.PARTIALLY_FILLED}:
            order.state=OrderState.EXPIRED
            order.updated_ms=timestamp_ms
        return order
