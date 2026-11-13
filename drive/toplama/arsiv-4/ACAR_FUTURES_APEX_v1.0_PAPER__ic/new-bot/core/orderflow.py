"""Bounded order-flow features from observed public trades and book snapshots.

Missing inputs stay unavailable; this module never substitutes zero for missing data.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from math import isfinite
import time


@dataclass(frozen=True)
class FlowSnapshot:
    available: bool
    trade_count: int
    buy_notional: float | None
    sell_notional: float | None
    cvd: float | None
    taker_buy_sell_ratio: float | None
    weighted_obi: float | None
    book_age_sec: float | None


class OrderFlowAnalyzer:
    def __init__(self, window_seconds: int = 300, max_trades: int = 20000):
        if window_seconds < 1 or max_trades < 10:
            raise ValueError("invalid order-flow window or capacity")
        self.window_seconds=window_seconds
        self.trades=deque(maxlen=max_trades)
        self.book: tuple[float,float,float] | None=None

    def add_trade(self, price: float, quantity: float, aggressor_side: str,
                  timestamp: float | None = None) -> None:
        ts=float(timestamp if timestamp is not None else time.time())
        if not all(isfinite(v) for v in (price,quantity,ts)) or price <= 0 or quantity <= 0:
            raise ValueError("trade values must be positive and finite")
        if aggressor_side not in {"BUY","SELL"}:
            raise ValueError("aggressor_side must be BUY or SELL")
        signed=price*quantity*(1 if aggressor_side=="BUY" else -1)
        self.trades.append((ts,signed,price*quantity))
        self._prune(ts)

    def update_book(self, bids, asks, timestamp: float | None = None,
                    depth: int = 20) -> None:
        ts=float(timestamp if timestamp is not None else time.time())
        bid_levels=list(bids)[:depth]
        ask_levels=list(asks)[:depth]
        if not bid_levels or not ask_levels:
            self.book=None
            return
        bid=ask=0.0
        for price,qty in bid_levels:
            if not all(isfinite(float(v)) for v in (price,qty)) or price <= 0 or qty < 0:
                raise ValueError("invalid bid level")
            bid += float(price)*float(qty)
        for price,qty in ask_levels:
            if not all(isfinite(float(v)) for v in (price,qty)) or price <= 0 or qty < 0:
                raise ValueError("invalid ask level")
            ask += float(price)*float(qty)
        if bid+ask <= 0:
            self.book=None
            return
        self.book=(bid,ask,ts)

    def _prune(self, now: float) -> None:
        cutoff=now-self.window_seconds
        while self.trades and self.trades[0][0] < cutoff:
            self.trades.popleft()

    def snapshot(self, now: float | None = None, max_book_age_sec: float = 10.0) -> FlowSnapshot:
        current=float(now if now is not None else time.time())
        self._prune(current)
        if not self.trades:
            return FlowSnapshot(False,0,None,None,None,None,None,None)
        buy=sum(notional for ts,signed,notional in self.trades if signed > 0)
        sell=sum(notional for ts,signed,notional in self.trades if signed < 0)
        cvd=sum(signed for ts,signed,notional in self.trades)
        ratio=buy/sell if sell > 0 else None
        obi=None
        age=None
        if self.book is not None:
            bid,ask,book_ts=self.book
            age=max(0.0,current-book_ts)
            if age <= max_book_age_sec and bid+ask > 0:
                obi=(bid-ask)/(bid+ask)
        return FlowSnapshot(True,len(self.trades),buy,sell,cvd,ratio,obi,age)
