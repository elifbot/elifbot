"""v9.4 shared, volatility-scaled protection. Fixed $50 margin / 10x unchanged.

A tactical stop is deliberately tighter than the retained 8% emergency ceiling.
All functions are pure and used by both event backtest and live paper risk.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class AdaptivePolicy:
    stop_atr: float = 1.8
    min_stop_pct: float = 0.35
    max_stop_pct: float = 1.20
    trail_atr: float = 2.0
    activation_r: float = 1.5
    profit_floor_r: float = 0.25
    total_risk_fraction: float = 0.02
    directional_risk_fraction: float = 0.015
    cooldown_bars: int = 3
    max_spread_pct: float = 0.05
    max_entry_drift_atr: float = 0.50

    def risk_distance(self, entry: float, atr: float) -> float:
        if not all(math.isfinite(x) and x > 0 for x in (entry,atr)):
            raise ValueError('invalid entry/ATR')
        distance=max(atr*self.stop_atr,entry*self.min_stop_pct/100)
        if distance/entry*100 > self.max_stop_pct:
            raise ValueError('volatility exceeds tactical risk budget')
        return distance

    def initial_stop(self,side,entry,atr):
        d=self.risk_distance(entry,atr)
        return entry-d if side=='LONG' else entry+d

    def ratchet(self, *, side, entry, qty, atr, mfe_usdt, old_stop, mark, fees_usdt):
        if qty<=0 or atr<=0 or mark<=0:return old_stop
        risk=self.risk_distance(entry,atr)
        if mfe_usdt < self.activation_r*risk*qty:return old_stop
        # Leave at least 2 ATR of noise room, rather than locking a fixed 65-80% of every tiny wick.
        locked=max(fees_usdt+0.15, self.profit_floor_r*risk*qty, mfe_usdt-self.trail_atr*atr*qty)
        sign=1 if side=='LONG' else -1
        candidate=entry+sign*locked/qty
        # A newly placed protective stop must be on the protective side of current mark.
        candidate=min(candidate,mark*(1-1e-6)) if side=='LONG' else max(candidate,mark*(1+1e-6))
        return max(old_stop,candidate) if side=='LONG' else min(old_stop,candidate)
