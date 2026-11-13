"""Funding and liquidation estimates used as conservative entry vetoes.

These are screening estimates, not exchange liquidation-price replicas.
"""
from __future__ import annotations
from math import isfinite


def estimate_funding_cost(notional_usdt: float, funding_rate: float,
                          intervals: int = 1) -> float:
    if not isfinite(notional_usdt) or notional_usdt < 0:
        raise ValueError("notional must be finite and non-negative")
    if not isfinite(funding_rate):
        raise ValueError("funding rate must be finite")
    if isinstance(intervals,bool) or intervals < 0:
        raise ValueError("intervals must be a non-negative integer")
    return abs(notional_usdt * funding_rate * intervals)


def estimated_liquidation_price(entry: float, leverage: float, side: str,
                                maintenance_margin_rate: float = 0.005) -> float:
    """Isolated-margin first-order estimate; exchange-specific tiers differ."""
    vals=(entry,leverage,maintenance_margin_rate)
    if any(not isfinite(v) for v in vals) or entry <= 0 or leverage <= 0:
        raise ValueError("entry and leverage must be positive finite values")
    if not 0 <= maintenance_margin_rate < 1/leverage:
        raise ValueError("maintenance margin must be below initial margin")
    if side.upper()=="LONG":
        return entry*(1.0-1.0/leverage+maintenance_margin_rate)
    if side.upper()=="SHORT":
        return entry*(1.0+1.0/leverage-maintenance_margin_rate)
    raise ValueError("side must be LONG or SHORT")


def stop_is_before_liquidation(entry: float, stop: float, liquidation: float,
                               side: str, safety_buffer_pct: float = 0.5) -> bool:
    if any(not isfinite(v) for v in (entry,stop,liquidation,safety_buffer_pct)):
        return False
    if entry <= 0 or stop <= 0 or liquidation <= 0 or safety_buffer_pct < 0:
        return False
    buffer=entry*safety_buffer_pct/100.0
    if side.upper()=="LONG":
        return stop > liquidation + buffer and stop < entry
    if side.upper()=="SHORT":
        return stop < liquidation - buffer and stop > entry
    return False
