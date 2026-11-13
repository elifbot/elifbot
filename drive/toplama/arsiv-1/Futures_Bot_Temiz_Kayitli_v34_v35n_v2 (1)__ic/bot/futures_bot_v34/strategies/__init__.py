"""Aday stratejiler — hepsi SHADOW durumunda başlar."""
from strategies.base import HOLD, LONG, SHORT, SignalResult, StrategyBase  # noqa: F401
from strategies.mean_reversion import MeanReversionStrategy  # noqa: F401
from strategies.spike_momentum import SpikeMomentumStrategy  # noqa: F401
from strategies.squeeze_breakout import SqueezeBreakoutStrategy  # noqa: F401
from strategies.trend_follower import TrendFollowerStrategy  # noqa: F401


def build_candidates() -> list[StrategyBase]:
    """Her çağrıda YENİ örnekler döndürür (durum paylaşımı yok)."""
    return [
        TrendFollowerStrategy(),
        MeanReversionStrategy(),
        SqueezeBreakoutStrategy(),
        SpikeMomentumStrategy(),
    ]
