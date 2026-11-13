"""Yorum 2, madde 1 — RVOL birim hatası düzeltmesi testleri.

Eski hata: 1 saniyelik sentetik mum hacmi, 5 dakikalık mum ortalamasıyla
kıyaslanıyordu → 3x patlama RVOL ≈ 0.01 veriyor, 1.5 eşiği ≈ 450x patlama
istiyordu. Yeni SpikeDetector pay/payda aynı ölçekte tutar.
"""

import pytest

from core.spike import SpikeDetector, candle_rvol, estimate_secondly_base_volume


class TestSpikeDetectorUnits:
    def test_three_x_burst_gives_rvol_three_not_point_zero_one(self):
        """3x hacim patlaması RVOL ≈ 3 vermeli (0.01 değil!)."""
        detector = SpikeDetector(multiplier=3.0, lookback_seconds=60,
                                 window_seconds=1)
        # 60 saniye taban: her saniye 1.0 baz hacim, fiyat sabit 100
        ts = 1_700_000_000_000
        for second in range(60):
            detector.update("TESTUSDT", 100.0, 1.0, ts + second * 1000)
        # 61. saniyede 3.0 baz hacim → 3x patlama
        event = detector.update("TESTUSDT", 100.0, 3.0, ts + 60_000)
        assert event is not None
        assert 2.5 < event.rvol < 3.5, f"RVOL beklenen ~3, gelen {event.rvol}"

    def test_normal_volume_produces_no_event(self):
        detector = SpikeDetector(multiplier=3.0, lookback_seconds=60,
                                 window_seconds=1)
        ts = 1_700_000_000_000
        for second in range(61):
            detector.update("TESTUSDT", 100.0, 1.0, ts + second * 1000)
        # Son 61 güncelleme ile ısındı; normal hacim olay üretmez
        assert detector.update("TESTUSDT", 100.0, 1.5, ts + 61_000) is None

    def test_direction_long_on_price_increase(self):
        detector = SpikeDetector(multiplier=3.0, lookback_seconds=60,
                                 window_seconds=1, direction_seconds=5)
        ts = 1_700_000_000_000
        for second in range(60):
            detector.update("TESTUSDT", 100.0, 1.0, ts + second * 1000)
        event = detector.update(
            "TESTUSDT", 100.5, 4.0, ts + 60_000,
        )
        assert event is not None
        assert event.direction == "LONG"
        assert event.price_change_pct > 0

    def test_direction_short_on_price_decrease(self):
        detector = SpikeDetector(multiplier=3.0, lookback_seconds=60,
                                 window_seconds=1, direction_seconds=5)
        ts = 1_700_000_000_000
        for second in range(60):
            detector.update("TESTUSDT", 100.0, 1.0, ts + second * 1000)
        event = detector.update("TESTUSDT", 99.0, 4.0, ts + 60_000)
        assert event is not None
        assert event.direction == "SHORT"

    def test_window_of_three_seconds_aggregates(self):
        detector = SpikeDetector(multiplier=2.0, lookback_seconds=30,
                                 window_seconds=3)
        ts = 1_700_000_000_000
        for second in range(30):
            detector.update("TESTUSDT", 100.0, 1.0, ts + second * 1000)
        # 3 saniyelik pencerede toplam 15 (saniyede 5) → 5x
        event = detector.update("TESTUSDT", 100.0, 5.0, ts + 30_000)
        event2 = detector.update("TESTUSDT", 100.0, 5.0, ts + 31_000)
        event3 = detector.update("TESTUSDT", 100.0, 5.0, ts + 32_000)
        final = event3 or event2 or event
        assert final is not None
        assert 4.0 < final.rvol < 6.0

    def test_sanity_cap_marks_suspect(self):
        """Aşırı büyük RVOL (birim hatası işareti) suspect olarak işaretlenir."""
        detector = SpikeDetector(multiplier=3.0, lookback_seconds=30,
                                 window_seconds=1, sanity_cap=50.0)
        ts = 1_700_000_000_000
        for second in range(30):
            detector.update("TESTUSDT", 100.0, 1.0, ts + second * 1000)
        event = detector.update("TESTUSDT", 100.0, 500.0, ts + 30_000)
        assert event is not None
        assert event.suspect is True
        assert event.rvol > 50.0


class TestCandleRvol:
    def test_same_unit_candle_rvol(self):
        """Mum RVOL'u aynı periyot mumlarla kıyaslar — birim hatası imkânsız."""
        volumes = [10.0] * 20 + [30.0]  # son mum 3x
        assert candle_rvol(volumes, lookback=20) == pytest.approx(3.0, rel=0.01)

    def test_candle_rvol_insufficient_history(self):
        assert candle_rvol([10.0] * 5, lookback=20) == 0.0


class TestVolumeUnitValidation:
    def test_binance_base_volume_passthrough(self):
        """Binance: quote delta / fiyat = baz hacim (çarpan 1)."""
        base = estimate_secondly_base_volume(500.0, 100.0, contract_size=1.0)
        assert base == pytest.approx(5.0)

    def test_okx_contract_size_conversion(self):
        """OKX: kontrat bazlı hacim sözleşme büyüklüğüyle çarpılmalı."""
        base = estimate_secondly_base_volume(500.0, 100.0, contract_size=0.01)
        assert base == pytest.approx(0.05)

    def test_negative_delta_rejected(self):
        with pytest.raises(ValueError):
            estimate_secondly_base_volume(-1.0, 100.0)

    def test_bad_price_rejected(self):
        with pytest.raises(ValueError):
            estimate_secondly_base_volume(10.0, 0.0)
