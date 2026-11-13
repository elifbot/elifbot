"""Reporting-only helpers; never turn unknown equity into a risk decision."""
from __future__ import annotations
import math

class UnknownEquity(RuntimeError):
    """A current price required to evaluate unrealized PnL is unavailable."""

def safe_unrealized(executor):
    """Return (None, False) only for the explicitly identified quote failure.

    Other exceptions propagate: financial errors must not be silenced. This is
    a reporting helper, not a bypass for account, margin or risk checks.
    """
    try:
        value=float(executor.total_unrealized_usdt())
    except UnknownEquity:
        return None,False
    if not math.isfinite(value):
        raise ValueError('nonfinite unrealized PnL')
    return value,True

def equity_or_none(balance, unreal):
    return None if unreal is None else float(balance)+float(unreal)

def money_or_unknown(value, *, signed=False, digits=2):
    if value is None:
        return 'bilinmiyor'
    return '$'+format(float(value),f'{"+" if signed else ""},.{digits}f')
