"""v2.0 — Akıllı rejim, MTF ve order flow testleri (şartname 1-3)."""

from __future__ import annotations

import pytest

from core.config import MtfConfig, OrderFlowConfig, SuperConfig
from core.mtf import MtfAnalyzer, resample_closed
from core.orderflow import OrderFlowEngine
from core.regime import MarketRegime, SmartRegimeDetector
from tests.helpers import INTERVAL_MS, START_MS, make_candles
from infra.market_data.models import Candle


def _trend_closes(count: int = 80, start: float = 100.0, drift: float = 0.15):
    closes = []
    price = start
    for _ in range(count):
        closes.append(price)
        price *= 1 + drift / 100.0
    return closes


class TestSmartRegime:
    def test_strong_uptrend_detected(self):
        candles = make_candles(_trend_closes(80, drift=0.4))
        reading = SmartRegimeDetector(SuperConfig()).classify(candles)
        assert reading.regime in (
            MarketRegime.STRONG_TREND_UP, MarketRegime.TREND_UP,
        )
        assert reading.engine_suggestion == "TREND_LONG"
        assert reading.ema20_slope_pct > 0

    def test_strong_downtrend_detected(self):
        closes = _trend_closes(80, start=200.0, drift=-0.4)
        candles = make_candles(closes)
        reading = SmartRegimeDetector(SuperConfig()).classify(candles)
        assert reading.regime in (
            MarketRegime.STRONG_TREND_DOWN, MarketRegime.TREND_DOWN,
        )
        assert reading.engine_suggestion == "TREND_SHORT"

    def test_warmup_returns_uncertain(self):
        candles = make_candles([100.0] * 30)
        reading = SmartRegimeDetector(SuperConfig()).classify(candles)
        assert reading.regime == MarketRegime.UNCERTAIN
        assert reading.engine_suggestion == "WAIT"

    def test_reading_is_transparent(self):
        candles = make_candles(_trend_closes(80))
        reading = SmartRegimeDetector(SuperConfig()).classify(candles)
        data = reading.as_dict()
        assert data["engine"] in {"TREND_LONG", "TREND_SHORT", "FADE",
                                  "SPIKE_CONFIRM", "BLOCK", "WAIT"}
        assert "adx" in data and "structure" in data


class TestMtfResample:
    def test_incomplete_bucket_excluded(self):
        """Eksik mumlar tamamlanmadan değerlendirmeye ALINMAZ (şartname 2)."""
        # 15m hizalı başlangıç: 5 tam kova (15 mum) + 2 mumluk eksik kova
        aligned = (START_MS // (15 * 60_000)) * (15 * 60_000) + 15 * 60_000
        candles = make_candles([100.0] * 17, start_ms=aligned,
                               interval_ms=INTERVAL_MS)
        resampled = resample_closed(candles, "15m")
        assert len(resampled) == 5
        assert all(c.volume > 0 for c in resampled)

    def test_ohlc_aggregation_correct(self):
        aligned = (START_MS // (15 * 60_000)) * (15 * 60_000)
        candles = [
            Candle(aligned + i * INTERVAL_MS, 100 + i, 100 + i + 1,
                   100 + i - 0.5, 100 + i + 0.5, 2.0)
            for i in range(6)  # 2 tam 15m kova + 1 eksik
        ]
        resampled = resample_closed(candles, "15m")
        assert len(resampled) == 2
        first = resampled[0]
        assert first.open == 100.0
        assert first.close == 102.5
        assert first.high == 103.0
        assert first.low == 99.5
        assert first.volume == pytest.approx(6.0)

    def test_bias_needs_enough_bars(self):
        analyzer = MtfAnalyzer(MtfConfig())
        reading = analyzer.analyze_resampled(make_candles([100.0] * 40))
        # 40 adet 5m → 13 tam 15m barı < min_bars → "uygulanmadı"
        bias = reading.biases["15m"]
        assert bias.available is False
        assert "yetersiz" in bias.note

    def test_strong_conflict_blocks(self):
        """5m LONG sinyalinde 15m+1h güçlü SHORT → engel (şartname 2 örneği)."""
        analyzer = MtfAnalyzer(MtfConfig())
        down = make_candles(_trend_closes(60, start=120.0, drift=-0.5),
                            interval_ms=INTERVAL_MS)
        reading = analyzer.analyze_rest({"15m": down, "1h": down})
        block, alignment = analyzer.evaluate_conflict(reading, "LONG")
        assert block == "mtf_uyumsuz"

    def test_no_data_means_no_block(self):
        """Üst TF verisi yoksa görüş yok: engel YOK ('uygulanmadı')."""
        analyzer = MtfAnalyzer(MtfConfig())
        reading = analyzer.analyze_rest({})
        block, _ = analyzer.evaluate_conflict(reading, "LONG")
        assert block is None


def _book(bid_price=100.0, bid_qty=10.0, ask_price=100.2, ask_qty=1.0):
    bids = [(bid_price - i * 0.1, bid_qty) for i in range(5)]
    asks = [(ask_price + i * 0.1, ask_qty) for i in range(5)]
    return bids, asks


class TestOrderFlow:
    def test_imbalance_buy_pressure(self):
        engine = OrderFlowEngine(OrderFlowConfig())
        bids, asks = _book(bid_qty=10.0, ask_qty=1.0)
        snapshot = engine.update_book("X", bids, asks, START_MS)
        assert snapshot.imbalance.available
        assert snapshot.imbalance.value > 0.3
        assert snapshot.imbalance.note == "alici_baskisi"

    def test_big_orders_median_scaled(self):
        """Büyük emir tespiti MEDYANA göre ölçeklenir (mutlak sabit değil)."""
        engine = OrderFlowEngine(OrderFlowConfig())
        bids = [(100.0 - i * 0.1, 10.0 if i == 0 else 0.5) for i in range(5)]
        asks = [(100.2 + i * 0.1, 0.5) for i in range(5)]
        snapshot = engine.update_book("X", bids, asks, START_MS)
        assert snapshot.big_orders.available
        assert snapshot.big_orders.value > 0  # büyük emir bid tarafında

    def test_absorption_detects_stall(self):
        """Duvar + durgun fiyat → emilim şüphesi (vekil ölçüm)."""
        engine = OrderFlowEngine(OrderFlowConfig())
        for i in range(4):
            bids, asks = _book(bid_price=100.0, ask_price=100.2)
            snapshot = engine.update_book(
                "X", bids, asks, START_MS + i * 25_000,
            )
        assert snapshot.absorption.available
        assert "emilim" in snapshot.absorption.note

    def test_cvd_tick_rule(self):
        engine = OrderFlowEngine(OrderFlowConfig())
        price = 100.0
        for i in range(10):
            engine.update_tick("X", price + i * 0.1, 1.0, START_MS + i * 1000)
        component = engine.cvd_component("X")
        assert component.available
        assert component.value > 0.5  # yükselen fiyata hacim → alıcı CVD

    def test_oi_unavailable_when_no_data(self):
        """OI verisi yoksa 'uygulanmadı' — sabit sayı YOK (kullanıcı kuralı)."""
        engine = OrderFlowEngine(OrderFlowConfig())
        oi_comp, squeeze = engine.oi_components("X", 100.0, False)
        assert oi_comp.available is False
        assert squeeze.available is False
        assert "uygulanmadi" in oi_comp.note

    def test_oi_change_and_squeeze(self):
        engine = OrderFlowEngine(OrderFlowConfig())
        for i in range(5):
            engine.update_open_interest("X", 1000.0 * (1 + i * 0.02),
                                        START_MS + i * 60_000)
        oi_comp, squeeze = engine.oi_components("X", 100.0, True)
        assert oi_comp.available
        assert oi_comp.value > 0
        assert squeeze.available and squeeze.value > 0

    def test_sweep_reversal_from_candles(self):
        closes = [100.0] * 20
        candles = make_candles(closes)
        from infra.market_data.models import Candle as C
        # Süpürme mumu: öncesindeki diplerin altına sarkar, üstünde kapanır
        sweep = C(timestamp=candles[-1].timestamp + INTERVAL_MS,
                  open=100.0, high=100.2, low=98.5, close=100.05, volume=10.0)
        candles = candles + [sweep]
        component = OrderFlowEngine.sweep_reversal_component(
            candles, "LONG", lookback=12,
        )
        assert component.available and component.value > 0
        assert "dip" in component.note
