"""Yorum 2, madde 2 — yön çelişkisi düzeltmesi ve Yorum 1-E filtre testleri.

Eski hata: canlıda SHORT hiç açılamıyor; LONG için "5s yükseliş + 10dk düşüş
+ yükselen trend" gibi neredeyse imkânsız bileşim gerekiyordu.
Yeni tasarım: her motor LONG ve SHORT üretebilir; spike yalnız tetikleyicidir.
"""


import pytest

from core.config import SuperConfig
from core.strategy import (
    BtcDirectionFilter,
    FadeEngine,
    FakeBreakoutFilter,
    MarketContext,
    Regime,
    RegimeDetector,
    SignalResolver,
    TrendEngine,
)
from tests.helpers import (
    dip_series,
    flat_series,
    make_candles,
    pump_series,
)


def _ctx(closes, volumes, btc_change=0.0):
    candles = make_candles(closes, volumes=volumes)
    return MarketContext(
        symbol="TESTUSDT", candles=candles, spike=None,
        btc_change_pct_15m=btc_change,
    )


class TestFadeDirections:
    def test_fade_long_on_dip_with_volume(self):
        """10 dk düşüş + hacim → FADE LONG (eskiden de vardı)."""
        closes, volumes = dip_series(dip_pct=1.5)
        signal = FadeEngine(SuperConfig()).evaluate(_ctx(closes, volumes))
        assert signal.side == "LONG"
        assert signal.motor == "fade"
        assert 0 < signal.stop_distance_fraction < 1

    def test_fade_short_on_pump_with_volume(self):
        """10 dk yükseliş + hacim → FADE SHORT (YENİ: canlıda SHORT mümkün)."""
        closes, volumes = pump_series(pump_pct=1.5)
        signal = FadeEngine(SuperConfig()).evaluate(_ctx(closes, volumes))
        assert signal.side == "SHORT"
        assert signal.motor == "fade"
        assert 0 < signal.stop_distance_fraction < 1

    def test_fade_rejects_low_volume(self):
        closes, volumes = dip_series(dip_pct=1.5, spike_volume=10.5)
        signal = FadeEngine(SuperConfig()).evaluate(_ctx(closes, volumes))
        assert signal.side == "HOLD"
        assert signal.rejection_code == "dusuk_hacim"

    def test_fade_long_rejects_falling_knife(self):
        """Son kapanış önceki mumun düşüğünün altındaysa bıçak yakalanmaz."""
        closes, volumes = dip_series(dip_pct=3.0)
        candles = make_candles(closes, volumes=volumes)
        # Son mumu hızlı düşüşe çevir: kapanış önceki düşüğün altında
        from infra.market_data.models import Candle
        last = candles[-1]
        prev = candles[-2]
        knife_close = prev.low * 0.98
        knife = Candle(
            timestamp=last.timestamp,
            open=prev.close, high=prev.close * 1.001,
            low=knife_close * 0.999, close=knife_close,
            volume=last.volume,
        )
        ctx = MarketContext(
            symbol="TESTUSDT", candles=candles[:-1] + [knife], spike=None,
            btc_change_pct_15m=0.0,
        )
        signal = FadeEngine(SuperConfig()).evaluate(ctx)
        if signal.side == "LONG":
            pytest.fail("düşen bıçak koruması LONG üretti")
        # ya HOLD ya da red kodu beklenir
        assert signal.rejection_code in {
            "dusen_bicak", "fake_breakout_or_suspect", "fade_kosulu_yok",
            "guclu_trend_fade_kapali",
        }

    def test_fade_short_rejects_rising_knife(self):
        """Son kapanış önceki mumun üstüğünün üstündeyse pump devam ediyor."""
        closes, volumes = pump_series(pump_pct=3.0)
        candles = make_candles(closes, volumes=volumes)
        from infra.market_data.models import Candle
        last = candles[-1]
        prev = candles[-2]
        knife_close = prev.high * 1.02
        knife = Candle(
            timestamp=last.timestamp,
            open=prev.close, low=prev.low * 0.999,
            high=knife_close * 1.001, close=knife_close,
            volume=last.volume,
        )
        ctx = MarketContext(
            symbol="TESTUSDT", candles=candles[:-1] + [knife], spike=None,
            btc_change_pct_15m=0.0,
        )
        signal = FadeEngine(SuperConfig()).evaluate(ctx)
        if signal.side == "SHORT":
            pytest.fail("yükselen bıçak koruması SHORT üretti")

    def test_fade_blocked_when_btc_crashing_against_long(self):
        closes, volumes = dip_series(dip_pct=1.5)
        ctx = _ctx(closes, volumes, btc_change=-1.0)  # BTC %1 düşüş
        signal = FadeEngine(SuperConfig()).evaluate(ctx)
        assert signal.side == "HOLD"
        assert signal.rejection_code == "btc_tersi"

    def test_fade_short_blocked_when_btc_pumping(self):
        closes, volumes = pump_series(pump_pct=1.5)
        ctx = _ctx(closes, volumes, btc_change=1.0)  # BTC %1 yükseliş
        signal = FadeEngine(SuperConfig()).evaluate(ctx)
        assert signal.side == "HOLD"
        assert signal.rejection_code == "btc_tersi"


class TestTrendDirections:
    def _trend_candles(self, direction: str):
        count = 80
        step = 0.15 if direction == "up" else -0.15
        base = [100.0 + step * i for i in range(count - 3)]
        # Geri çekilme: son 3 mumdan biri EMA20'ye değmeli
        volumes = [10.0] * count
        closes = base + [base[-1], base[-1] - step * 3, base[-1] - step * 2]
        volumes[-1] = 30.0  # RVOL tetikleyicisi
        return closes, volumes

    def test_trend_long_with_pullback(self):
        closes, volumes = self._trend_candles("up")
        signal = TrendEngine(SuperConfig()).evaluate(_ctx(closes, volumes))
        if signal.side != "HOLD":
            assert signal.side == "LONG"
        # Geri çekilme mumları trend yönünü bozmuyor; HOLD ise red kodu anlamlı
        else:
            assert signal.rejection_code in {
                "trend_onayi_yok", "geri_cekilme_yok", "fake_breakout_or_suspect",
            }

    def test_trend_short_with_pullback(self):
        closes, volumes = self._trend_candles("down")
        signal = TrendEngine(SuperConfig()).evaluate(_ctx(closes, volumes))
        if signal.side != "HOLD":
            assert signal.side == "SHORT"

    def test_trend_never_long_without_ema_alignment(self):
        closes = [100.0 + (i % 7) * 0.2 for i in range(80)]
        volumes = [10.0] * 80
        volumes[-1] = 30.0
        signal = TrendEngine(SuperConfig()).evaluate(_ctx(closes, volumes))
        assert signal.side != "LONG"


class TestFilters:
    def test_fake_breakout_rejects_huge_wick(self):
        from infra.market_data.models import Candle
        # Anlamlı gövde (%3) + daha uzun fitil → paniğe dayalı kırılım
        wicky = Candle(
            timestamp=0, open=100.0, high=105.0, low=99.9,
            close=103.0, volume=50.0,
        )
        candles = make_candles(flat_series())[:-1] + [wicky]
        assert FakeBreakoutFilter().allows(candles, rvol=2.0) is False

    def test_fake_breakout_allows_normal_quiet_candle(self):
        from infra.market_data.models import Candle
        quiet = Candle(
            timestamp=0, open=100.0, high=100.2, low=99.8,
            close=100.1, volume=50.0,
        )
        candles = make_candles(flat_series())[:-1] + [quiet]
        assert FakeBreakoutFilter().allows(candles, rvol=2.0) is True

    def test_fake_breakout_rejects_absurd_rvol(self):
        candles = make_candles(flat_series())
        assert FakeBreakoutFilter().allows(candles, rvol=999.0) is False

    def test_btc_filter_allows_aligned_direction(self):
        assert BtcDirectionFilter().allows("SHORT", btc_change_pct_15m=-1.0)
        assert BtcDirectionFilter().allows("LONG", btc_change_pct_15m=1.0)

    def test_btc_filter_blocks_against(self):
        assert not BtcDirectionFilter().allows("LONG", btc_change_pct_15m=-1.0)
        assert not BtcDirectionFilter().allows("SHORT", btc_change_pct_15m=1.0)

    def test_regime_classifier_returns_something_valid(self):
        closes, volumes = dip_series(count=80)
        candles = make_candles(closes, volumes=volumes)
        assert RegimeDetector().classify(candles) in set(Regime)


class TestResolver:
    def test_both_engines_same_side_boosts_confidence(self):
        from core.strategy import Signal
        fade = Signal("SHORT", "fade", 1.5, 3.0, 0.004, confidence=0.5)
        trend = Signal("SHORT", "trend", 0.0, 3.0, 0.006, confidence=0.4)
        resolved = SignalResolver().resolve(fade, trend, Regime.RANGE)
        assert resolved.side == "SHORT"
        assert resolved.motor == "fade+trend"
        assert resolved.confidence == pytest.approx(0.9)

    def test_conflict_in_range_prefers_fade(self):
        from core.strategy import Signal
        fade = Signal("LONG", "fade", -1.5, 3.0, 0.004, confidence=0.6)
        trend = Signal("SHORT", "trend", 0.0, 3.0, 0.006, confidence=0.6)
        resolved = SignalResolver().resolve(fade, trend, Regime.RANGE)
        assert resolved.side == "LONG"

    def test_conflict_in_trend_prefers_trend(self):
        from core.strategy import Signal
        fade = Signal("LONG", "fade", -1.5, 3.0, 0.004, confidence=0.6)
        trend = Signal("SHORT", "trend", 0.0, 3.0, 0.006, confidence=0.6)
        resolved = SignalResolver().resolve(fade, trend, Regime.TREND_DOWN)
        assert resolved.side == "SHORT"

    def test_fade_in_strong_trend_requires_confidence(self):
        from core.strategy import Signal
        weak_fade = Signal("LONG", "fade", -1.5, 1.6, 0.004, confidence=0.3)
        hold_trend = Signal("HOLD", "trend", 0.0, 0.0, None,
                            rejection_code="trend_onayi_yok")
        resolved = SignalResolver().resolve(weak_fade, hold_trend, Regime.TREND_UP)
        assert resolved.side == "HOLD"
        assert resolved.rejection_code == "rejim_uyumsuz"
