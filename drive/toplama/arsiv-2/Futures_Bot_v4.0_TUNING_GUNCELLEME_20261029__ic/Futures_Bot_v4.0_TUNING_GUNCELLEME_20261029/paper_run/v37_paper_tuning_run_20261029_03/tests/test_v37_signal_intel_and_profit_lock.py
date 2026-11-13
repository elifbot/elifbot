"""v37 paper sinyal-zenginleştirme ve net kâr koruması regresyonları."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portfolio.paper_futures import LONG, SHORT, PaperPortfolio
from scanner.signal_intel import (
    SignalEnricher,
    combine_mtf,
    flow_confirmation,
    normalize_closed_candles,
)


class _FlowBook:
    def __init__(self, *, buy=2_000.0, sell=500.0, age=100, trades=5):
        self.buy = buy
        self.sell = sell
        self.age = age
        self.trades = trades

    def anlik(self, exchange, symbol, now_ms, window):
        if window == 15:
            buy, sell = self.buy, self.sell
            age, trades = self.age, self.trades
        else:
            buy, sell = self.buy, self.sell
            age, trades = self.age, self.trades
        return SimpleNamespace(
            hazir=(buy + sell) > 0,
            alis_usd=buy,
            satis_usd=sell,
            toplam_usd=buy + sell,
            cvd_usd=buy - sell,
            islem_adedi=trades,
            son_islem_yas_ms=age,
        )


def _binance_candles(asof_ms: int, n: int = 60):
    hour = 3_600_000
    end = (asof_ms // hour) * hour - hour
    start = end - (n - 1) * hour
    rows = []
    for i in range(n):
        ts = start + i * hour
        rows.append([ts, "100", "102", "99", str(100 + i / 100), "1",
                     ts + hour - 1, "0", 1, "0", "0", "0"])
    return rows


def test_normalize_only_latest_continuous_closed_mtf_suffix():
    asof = 120 * 3_600_000
    rows = _binance_candles(asof, 60)
    # Current, not-yet-closed candle must be omitted.
    rows.append([asof, "101", "103", "100", "102", "1",
                 asof + 3_600_000 - 1, "0", 1, "0", "0", "0"])
    frame = normalize_closed_candles("binance", "1h", rows, asof)
    assert len(frame) == 60
    assert int(frame.open_time.iloc[-1]) == asof - 3_600_000


def test_normalize_rejects_conflicting_duplicate_closed_candle():
    asof = 120 * 3_600_000
    rows = _binance_candles(asof, 60)
    conflicting = list(rows[-1])
    conflicting[4] = "101"
    rows.append(conflicting)
    with pytest.raises(ValueError, match="çakışan"):
        normalize_closed_candles("binance", "1h", rows, asof)


def test_normalize_fails_closed_when_last_candle_is_stale_or_gap_exists():
    asof = 120 * 3_600_000
    rows = _binance_candles(asof, 60)
    rows.pop()
    with pytest.raises(ValueError, match="güncel değil"):
        normalize_closed_candles("binance", "1h", rows, asof)


def test_mtf_weighting_allows_neutral_and_blocks_opposing_strong_trend():
    bullish = combine_mtf({"score": 40}, {"score": 60})
    assert bullish["score"] == 51.0
    assert bullish["allow_long"] and not bullish["allow_short"]
    neutral = combine_mtf({"score": 10}, {"score": -5})
    assert neutral["trend"] == "NEUTRAL"
    assert neutral["allow_long"] and neutral["allow_short"]


def test_flow_confirmation_requires_recent_directional_real_taker_cvd():
    good = flow_confirmation(_FlowBook(), "binance", "BTCUSDT", 1_000_000, "LONG")
    assert good.accepted
    assert good.cvd15_usd == 1_500
    assert good.taker_buy_sell_ratio == 4

    opposing = flow_confirmation(
        _FlowBook(buy=500, sell=2_000), "okx", "BTC-USDT-SWAP", 1_000_000, "LONG"
    )
    assert not opposing.accepted
    assert opposing.reason == "cvd_opposes_entry"

    stale = flow_confirmation(
        _FlowBook(age=15_001), "binance", "BTCUSDT", 1_000_000, "LONG"
    )
    assert not stale.accepted
    assert stale.reason == "orderflow_stale_or_empty"


def test_enricher_combines_mtf_funding_oi_and_flow_without_network():
    async def run():
        enricher = SignalEnricher()
        enricher._mtf = AsyncMock(return_value={
            "available": True, "score": 20, "trend": "BULLISH",
            "allow_long": True, "allow_short": False,
            "1h": {"score": 20}, "4h": {"score": 20},
        })
        enricher._derivatives = AsyncMock(return_value={
            "available": True, "funding_rate": 0.0, "oi_usd": 1_000_000,
            "oi_change_pct": None, "oi_signal": "NOTR", "funding_crowding": "DENGELI",
        })
        result = await enricher.evaluate(
            None, exchange="binance", symbol="BTCUSDT", side="LONG",
            ret_pct=0.5, price=100.0, flow_book=_FlowBook(), now_ms=1_000_000,
        )
        assert result["accepted"] is True
        assert result["reasons"] == []

        # Positive funding crowds longs: block a same-direction fade entry, not a short.
        enricher._derivatives = AsyncMock(return_value={
            "available": True, "funding_rate": 0.001, "oi_usd": 1_000_000,
            "oi_change_pct": None, "oi_signal": "NOTR", "funding_crowding": "LONG_KALABALIK",
        })
        blocked = await enricher.evaluate(
            None, exchange="binance", symbol="BTCUSDT", side="LONG",
            ret_pct=0.5, price=100.0, flow_book=_FlowBook(), now_ms=1_000_001,
        )
        enricher._mtf = AsyncMock(return_value={
            "available": True, "score": -20, "trend": "BEARISH",
            "allow_long": False, "allow_short": True,
            "1h": {"score": -20}, "4h": {"score": -20},
        })
        allowed = await enricher.evaluate(
            None, exchange="binance", symbol="BTCUSDT", side="SHORT",
            ret_pct=0.5, price=100.0, flow_book=_FlowBook(buy=500, sell=2_000),
            now_ms=1_000_002,
        )
        assert "funding_crowding_opposes_fade" in blocked["reasons"]
        assert allowed["accepted"] is True

    asyncio.run(run())


def _portfolio():
    return PaperPortfolio(
        5_000, fee_rate=0.0005, max_open_positions=None,
        max_same_direction=None, max_utilisation=1.0, balance_floor=0.0,
    )


def _simulate_stop_fill(pf, pos, side):
    # Match ws_bot: market slippage 0.05%, then stop overshoot 0.10%.
    slip, overshoot = 0.0005, 0.001
    stop = pos.stop_price
    fill = stop * (1 - slip) * (1 - overshoot) if side == LONG else stop * (1 + slip) * (1 + overshoot)
    return pf.close_position(pos.exchange, pos.symbol, fill, now_ms=2, reason="stop_loss")


@pytest.mark.parametrize("side,mark", [(LONG, 100.5), (SHORT, 99.5)])
def test_two_stage_mfe_lock_preserves_net_target_after_costs(side, mark):
    pf = _portfolio()
    opened = pf.open_position(
        "binance", "BTCUSDT", side, 100.0, 500.0, leverage=1.0,
        step_size=0.001, now_ms=1,
    )
    assert opened.ok and opened.position
    pos = opened.position
    pf.mark_price("binance", "BTCUSDT", mark, 2)
    update = pf.update_profit_protection("binance", "BTCUSDT")
    assert update["stage"] == 1
    assert update["mfe_active"] is True
    assert update["mfe_activated"] is True
    assert update["target_net_usdt"] == pytest.approx(1.2)

    rec = _simulate_stop_fill(pf, pos, side)
    assert rec is not None
    assert rec.realized_pnl >= update["target_net_usdt"] - 1e-8


def test_profit_lock_is_monotonic_and_exchange_symbol_scoped():
    pf = _portfolio()
    long = pf.open_position(
        "binance", "BTCUSDT", LONG, 100, 500, leverage=1, step_size=0.001, now_ms=1
    ).position
    short = pf.open_position(
        "okx", "BTC-USDT-SWAP", SHORT, 100, 500, leverage=1, step_size=0.001, now_ms=1
    ).position
    assert long and short

    pf.mark_price("binance", "BTCUSDT", 100.5, 2)
    first = pf.update_profit_protection("binance", "BTCUSDT")
    first_stop = first["stop_price"]
    assert short.mfe_usdt == 0 and short.profit_lock_stage == 0

    pf.mark_price("binance", "BTCUSDT", 100.9, 3)
    second = pf.update_profit_protection("binance", "BTCUSDT")
    assert second["stage"] == 2
    assert second["stop_price"] > first_stop

    pf.mark_price("binance", "BTCUSDT", 100.1, 4)
    third = pf.update_profit_protection("binance", "BTCUSDT")
    assert third["stop_price"] == pytest.approx(second["stop_price"])
    assert long.peak_price == pytest.approx(100.9)
    assert long.mfe_usdt == pytest.approx(4.5)


def test_funding_cost_tightens_but_income_never_loosens_protected_stop():
    pf = _portfolio()
    pos = pf.open_position(
        "binance", "BTCUSDT", LONG, 100, 500, leverage=1, step_size=0.001, now_ms=1
    ).position
    assert pos
    pf.mark_price("binance", "BTCUSDT", 100.5, 2)
    first = pf.update_profit_protection("binance", "BTCUSDT")
    stop_before = first["stop_price"]
    pos.funding_fee = 0.50
    after_cost = pf.update_profit_protection("binance", "BTCUSDT")
    assert after_cost["stop_price"] >= stop_before
    pos.funding_fee = -0.50
    after_income = pf.update_profit_protection("binance", "BTCUSDT")
    assert after_income["stop_price"] >= after_cost["stop_price"]


def test_short_mfe_peak_tracks_favorable_low_not_later_rebound():
    pf = _portfolio()
    pos = pf.open_position(
        "okx", "ETH-USDT-SWAP", SHORT, 100, 500, leverage=1, step_size=0.001, now_ms=1
    ).position
    assert pos
    pf.mark_price("okx", "ETH-USDT-SWAP", 99.0, 2)
    pf.mark_price("okx", "ETH-USDT-SWAP", 99.8, 3)
    assert pos.peak_price == pytest.approx(99.0)
    assert pos.mfe_usdt == pytest.approx(5.0)
