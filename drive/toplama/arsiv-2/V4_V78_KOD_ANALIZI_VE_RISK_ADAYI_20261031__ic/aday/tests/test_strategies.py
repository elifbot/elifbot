"""Aday strateji testleri — SHADOW durumu, izolasyon, sinyal sözleşmesi."""
from __future__ import annotations

import pandas as pd
import pytest

from strategies import build_candidates
from strategies.base import HOLD, SignalResult
from strategies.mean_reversion import MeanReversionStrategy
from strategies.spike_momentum import SpikeMomentumStrategy
from strategies.squeeze_breakout import SqueezeBreakoutStrategy
from strategies.trend_follower import TrendFollowerStrategy


@pytest.mark.parametrize(
    "cls",
    [TrendFollowerStrategy, MeanReversionStrategy, SqueezeBreakoutStrategy, SpikeMomentumStrategy],
)
def test_all_candidates_are_shadow(cls) -> None:
    """Tüm adaylar SHADOW durumunda başlar; ACTIVE'e sessizce terfi etmez."""
    assert cls.STATUS == "SHADOW"
    assert cls().STATUS == "SHADOW"


def test_candidates_have_distinct_state_objects() -> None:
    """Her örnek kendi durum sözlüğüne sahip (paylaşılan mutable state yok)."""
    a = TrendFollowerStrategy()
    b = TrendFollowerStrategy()
    assert a._state is not b._state
    a.evaluate(pd.DataFrame())
    assert a.evaluations == 1
    assert b.evaluations == 0


def test_build_candidates_returns_fresh_instances() -> None:
    """Her çağrı yeni örnekler üretir."""
    first = build_candidates()
    second = build_candidates()
    assert len(first) == 4
    assert all(x is not y for x, y in zip(first, second))


def test_insufficient_data_returns_hold() -> None:
    """Yetersiz satırda HOLD ve açıklama döner."""
    df = pd.DataFrame(
        {
            "open_time": [1, 2, 3],
            "open": [1.0, 1.0, 1.0],
            "high": [2.0, 2.0, 2.0],
            "low": [0.5, 0.5, 0.5],
            "close": [1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    for strat in build_candidates():
        res = strat.evaluate(df)
        assert res.signal == HOLD
        assert res.notes


def test_signal_result_contract(ohlcv: pd.DataFrame) -> None:
    """SignalResult zorunlu alanları doldurulmuş olmalı."""
    res = TrendFollowerStrategy().evaluate(ohlcv)
    assert isinstance(res, SignalResult)
    assert res.signal in ("LONG", "SHORT", HOLD)
    assert res.strategy_name == "trend_follower_A"
    assert res.data_timestamp == int(ohlcv.iloc[-1]["open_time"])
    assert res.contributor_log, "katkı logu boş olmamalı"
    for entry in res.contributor_log:
        assert set(entry) == {"name", "value", "vote", "family"}


def test_families_reported(ohlcv: pd.DataFrame) -> None:
    """Kullanılan aileler raporlanır; F ailesi (veri yok) hiçbir adayda yok."""
    for strat in build_candidates():
        res = strat.evaluate(ohlcv)
        assert res.active_families
        assert "F" not in res.active_families


def test_trend_follower_uptrend_bullish_or_hold(uptrend: pd.DataFrame) -> None:
    """Kesintisiz yükselişte SHORT sinyali üretilmemeli."""
    res = TrendFollowerStrategy().evaluate(uptrend)
    assert res.signal in ("LONG", HOLD)


def test_trend_follower_downtrend_never_long(downtrend: pd.DataFrame) -> None:
    """Kesintisiz düşüşte LONG sinyali üretilmemeli."""
    res = TrendFollowerStrategy().evaluate(downtrend)
    assert res.signal in ("SHORT", HOLD)


def test_strategy_does_not_mutate_input(ohlcv: pd.DataFrame) -> None:
    """Strateji girdi DataFrame'ini değiştirmemeli."""
    before = ohlcv.copy()
    TrendFollowerStrategy().evaluate(ohlcv)
    pd.testing.assert_frame_equal(before, ohlcv)


def test_evaluation_is_deterministic(ohlcv: pd.DataFrame) -> None:
    """Aynı veri -> aynı sinyal (rastgelelik yok)."""
    s1 = TrendFollowerStrategy().evaluate(ohlcv)
    s2 = TrendFollowerStrategy().evaluate(ohlcv)
    assert s1.signal == s2.signal
    assert s1.contributor_log == s2.contributor_log


def test_trend_follower_downtrend_supertrend_line_allows_short(downtrend: pd.DataFrame) -> None:
    """SHORT uses Supertrend price, not the +1/-1 direction flag."""
    from indicators.core import add_core_indicators
    last = add_core_indicators(downtrend).iloc[-1]
    assert last["close"] > 0
    assert last["st_trend"] == -1
    assert last["close"] < last["supertrend"]
    assert TrendFollowerStrategy().evaluate(downtrend).signal == "SHORT"


def test_trend_follower_uptrend_supertrend_line_allows_long(uptrend: pd.DataFrame) -> None:
    from indicators.core import add_core_indicators
    last = add_core_indicators(uptrend).iloc[-1]
    assert last["st_trend"] == 1
    assert last["close"] > last["supertrend"]
    assert TrendFollowerStrategy().evaluate(uptrend).signal == "LONG"


def test_trend_follower_supertrend_report_is_direction_not_price(downtrend: pd.DataFrame) -> None:
    res = TrendFollowerStrategy().evaluate(downtrend)
    st = next(x for x in res.contributor_log if x["name"] == "supertrend")
    assert st["value"] == -1 and st["vote"] == "SHORT"


@pytest.mark.parametrize("line", [float("nan"), "equal"])
def test_trend_follower_missing_or_equal_line_stays_hold(downtrend: pd.DataFrame, monkeypatch, line) -> None:
    import strategies.trend_follower as tf
    real = tf.add_core_indicators
    def controlled(frame):
        out = real(frame)
        out.loc[out.index[-1], "supertrend"] = out.iloc[-1]["close"] if line == "equal" else line
        return out
    monkeypatch.setattr(tf, "add_core_indicators", controlled)
    assert tf.TrendFollowerStrategy().evaluate(downtrend).signal == HOLD
