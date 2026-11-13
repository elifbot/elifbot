"""Ten-vote confluence strategy with explicit regime and data-quality gates.

This module only evaluates closed candles. It never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from core.indicators import (
    adx, atr, bollinger_bands, cci, directional_movement, ema, macd,
    obv, rsi, stochastic, supertrend, vwap,
)
from core.risk import MIN_IMPULSE_PERCENT, MIN_RVOL_FOR_ENTRY
from core.strategy import Signal, measure_impulse_rvol
from infra.market_data.models import Candle


@dataclass(frozen=True)
class Regime:
    name: str
    adx_value: float
    atr_pct: float
    trend_score: float


def classify_regime(candles: Sequence[Candle]) -> Regime:
    """Classify trend/range/volatility from closed candles only."""
    if len(candles) < 40:
        return Regime("WARMUP", 0.0, 0.0, 0.0)
    close = [c.close for c in candles]
    high = [c.high for c in candles]
    low = [c.low for c in candles]
    adx_values = adx(high, low, close, 14)
    atr_values = atr(high, low, close, 14)
    e20, e50 = ema(close, 20)[-1], ema(close, 50)[-1]
    av, tr = adx_values.adx[-1], atr_values[-1]
    if None in (av, tr, e20, e50) or close[-1] <= 0:
        return Regime("WARMUP", 0.0, 0.0, 0.0)
    atr_pct = float(tr) / close[-1] * 100.0
    trend_score = 100.0 * (float(e20) / float(e50) - 1.0)
    if atr_pct >= 5.0:
        name = "EXTREME_VOL"
    elif float(av) < 16.0:
        name = "RANGE"
    elif trend_score >= 0.12:
        name = "TREND_UP"
    elif trend_score <= -0.12:
        name = "TREND_DOWN"
    else:
        name = "TRANSITION"
    return Regime(name, float(av), atr_pct, trend_score)


def candle_integrity(candles: Sequence[Candle], expected_interval_ms: int = 300_000) -> tuple[bool, str]:
    """Reject duplicate, reversed, malformed-time and multi-candle gaps."""
    if len(candles) < 2:
        return False, "INSUFFICIENT_CANDLES"
    previous = None
    for item in candles:
        if item.timestamp < 0 or item.close <= 0 or item.volume < 0:
            return False, "BAD_CANDLE"
        if previous is not None:
            delta = item.timestamp - previous
            if delta <= 0:
                return False, "NON_MONOTONIC_CANDLES"
            if delta > expected_interval_ms * 2:
                return False, "CANDLE_GAP"
        previous = item.timestamp
    return True, "OK"


class EliteConfluenceStrategy:
    """A conservative 10-factor vote model; default threshold is 7/10."""

    def __init__(self, threshold: int = 7, min_adx: float = 18.0,
                 stop_atr_multiple: float = 2.5, max_atr_pct: float = 4.5):
        if not 5 <= threshold <= 10:
            raise ValueError("threshold must be between 5 and 10")
        if min_adx <= 0 or stop_atr_multiple <= 0 or max_atr_pct <= 0:
            raise ValueError("strategy thresholds must be positive")
        self.threshold = threshold
        self.min_adx = min_adx
        self.stop_atr_multiple = stop_atr_multiple
        self.max_atr_pct = max_atr_pct

    def evaluate(self, candles: Sequence[Candle]) -> Signal:
        if len(candles) < 80:
            return Signal("HOLD", 0.0, 0.0, None, "elite", "ELITE_WARMUP")
        ok, reason = candle_integrity(candles)
        if not ok:
            return Signal("HOLD", 0.0, 0.0, None, "elite", reason)

        close = [c.close for c in candles]
        high = [c.high for c in candles]
        low = [c.low for c in candles]
        volume = [c.volume for c in candles]
        price = close[-1]
        impulse, rvol = measure_impulse_rvol(candles)
        if abs(impulse) < MIN_IMPULSE_PERCENT:
            return Signal("HOLD", impulse, rvol, None, "elite", "LOW_IMPULSE")
        if rvol < MIN_RVOL_FOR_ENTRY:
            return Signal("HOLD", impulse, rvol, None, "elite", "LOW_RVOL")

        regime = classify_regime(candles)
        if regime.name in {"WARMUP", "EXTREME_VOL"}:
            return Signal("HOLD", impulse, rvol, None, "elite", regime.name)
        if regime.adx_value < self.min_adx or regime.name == "RANGE":
            return Signal("HOLD", impulse, rvol, None, "elite", "RANGE_MARKET")

        e20, e50 = ema(close, 20)[-1], ema(close, 50)[-1]
        macd_values = macd(close)
        hist = macd_values.histogram
        rsi_values = rsi(close, 14)
        dm = directional_movement(high, low, close, 14)
        stoch = stochastic(high, low, close, 14, 3)
        obv_values = obv(close, volume)
        cci_values = cci(high, low, close, 20)
        st = supertrend(high, low, close, 10, 3.0)
        vw = vwap(high, low, close, volume, 20)
        bb = bollinger_bands(close, 20, 2.0)

        required = (e20, e50, hist[-1], hist[-2], rsi_values[-1],
                    dm.plus_di[-1], dm.minus_di[-1], dm.adx[-1],
                    stoch.percent_k[-1], stoch.percent_d[-1],
                    stoch.percent_k[-2], stoch.percent_d[-2],
                    cci_values[-1], st.direction[-1], vw[-1],
                    bb.upper[-1], bb.lower[-1])
        if any(v is None for v in required):
            return Signal("HOLD", impulse, rvol, None, "elite", "INDICATOR_WARMUP")

        votes = {"ema_alignment": 0, "macd_momentum": 0, "rsi_zone": 0,
                 "adx_direction": 0, "stoch_cross": 0, "obv_flow": 0,
                 "cci_direction": 0, "supertrend": 0, "vwap_position": 0,
                 "bollinger_breakout": 0}
        votes["ema_alignment"] = 1 if e20 > e50 else (-1 if e20 < e50 else 0)
        votes["macd_momentum"] = 1 if hist[-1] > 0 and hist[-1] > hist[-2] else (
            -1 if hist[-1] < 0 and hist[-1] < hist[-2] else 0)
        rv = float(rsi_values[-1])
        votes["rsi_zone"] = 1 if 52 <= rv <= 72 else (-1 if 28 <= rv <= 48 else 0)
        votes["adx_direction"] = 1 if dm.plus_di[-1] > dm.minus_di[-1] and dm.adx[-1] >= self.min_adx else (
            -1 if dm.minus_di[-1] > dm.plus_di[-1] and dm.adx[-1] >= self.min_adx else 0)
        k0, d0 = float(stoch.percent_k[-2]), float(stoch.percent_d[-2])
        k1, d1 = float(stoch.percent_k[-1]), float(stoch.percent_d[-1])
        votes["stoch_cross"] = 1 if k0 <= d0 and k1 > d1 and k1 < 85 else (
            -1 if k0 >= d0 and k1 < d1 and k1 > 15 else 0)
        votes["obv_flow"] = 1 if obv_values[-1] > obv_values[-6] else (
            -1 if obv_values[-1] < obv_values[-6] else 0)
        cv = float(cci_values[-1])
        votes["cci_direction"] = 1 if cv > 50 else (-1 if cv < -50 else 0)
        votes["supertrend"] = int(st.direction[-1])
        votes["vwap_position"] = 1 if price > vw[-1] else -1
        votes["bollinger_breakout"] = 1 if price > bb.upper[-1] else (
            -1 if price < bb.lower[-1] else 0)

        long_votes = sum(v == 1 for v in votes.values())
        short_votes = sum(v == -1 for v in votes.values())
        side = "LONG" if long_votes >= self.threshold else (
            "SHORT" if short_votes >= self.threshold else "HOLD")
        if side == "HOLD":
            return Signal("HOLD", impulse, rvol, None, "elite",
                          f"LOW_CONFLUENCE_L{long_votes}_S{short_votes}")
        if side == "LONG" and regime.name == "TREND_DOWN":
            return Signal("HOLD", impulse, rvol, None, "elite", "HTF_PROXY_BEARISH")
        if side == "SHORT" and regime.name == "TREND_UP":
            return Signal("HOLD", impulse, rvol, None, "elite", "HTF_PROXY_BULLISH")
        atr_values = atr(high, low, close, 14)
        if atr_values[-1] is None or not isfinite(float(atr_values[-1])):
            return Signal("HOLD", impulse, rvol, None, "elite", "ATR_UNAVAILABLE")
        stop_fraction = self.stop_atr_multiple * float(atr_values[-1]) / price
        if stop_fraction <= 0 or stop_fraction >= 0.20:
            return Signal("HOLD", impulse, rvol, None, "elite", "INVALID_STOP_DISTANCE")
        return Signal(side, impulse, rvol, stop_fraction, "elite", None)
