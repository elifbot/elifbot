"""FINAL v1.9 — hacim filtresi: likiditesizlik ≠ veri hatası + log seli düzeltmesi.

Kullanıcı gözlemi: "şüpheli hacimler devam ediyor, sürekli olay akışında var".

Kanıta dayalı teşhis (7 Kasım 2026, canlı OKX verisi):
  * volCcy24h / vol24h oranı ctVal ile TAM eşleşiyor → birim doğru (v1.6 fix sağlam).
  * Şüpheli işaretlenen sembollerin 24s hacmi 20 sn boyunca HİÇ değişmedi
    (NOK, COAI, ZRX, SHIB: 0/15 örnek), BTC ise 9/15 değişti.
  * NOK-USDT-SWAP son 100 dakikanın 78'inde hiç işlem yok.
  → Taban hacim ~0 olduğu için TEK bir normal işlem RVOL'u 100-10000x gösteriyor.
    Bu bir veri hatası değil, LİKİDİTESİZLİK.

Ek kod kusurları:
  * 3 sn pencere boyunca aynı patlama tekrar tekrar olay üretiyordu (aynı RVOL
    değeriyle art arda log) → log seli.
  * Filtre devreye girince tick_volume=0 oluyordu → maker emirleri dolmuyordu.
  * tick_volume olarak 3 sn pencere TOPLAMI veriliyordu → mükerrer hacim sayımı.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from core.spike import SpikeDetector, SpikeEvent
from exec.paper import PaperBroker


def _feed(detector, symbol, price, small_volume, seconds, burst=None):
    """Isınma + taban beslemesi; son saniyede isteğe bağlı patlama."""
    event = None
    for i in range(seconds):
        event = detector.update(symbol, price, small_volume, i * 1000)
    if burst is not None:
        event = detector.update(symbol, price, burst, seconds * 1000)
    return event


class LiquidityClassificationTests(unittest.TestCase):
    def test_illiquid_baseline_is_not_data_error(self):
        """Taban 0.1 USDT/sn → dev RVOL ama 'veri hatası' DEĞİL."""
        det = SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0, min_baseline_notional_per_second=5.0,
        )
        ev = _feed(det, "okx:NOK-USDT-SWAP", 100.0, 0.001, 63, burst=10.0)
        self.assertIsNotNone(ev)
        self.assertGreater(ev.rvol, 100.0)
        self.assertTrue(ev.illiquid)
        self.assertFalse(ev.suspect)
        self.assertLess(ev.baseline_notional_per_second, 5.0)

    def test_liquid_baseline_absurd_rvol_is_suspect(self):
        """Taban 100 USDT/sn ve absürt sapma → gerçek veri şüphesi."""
        det = SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0, min_baseline_notional_per_second=5.0,
        )
        ev = _feed(det, "okx:BTC-USDT-SWAP", 100.0, 1.0, 63, burst=1000.0)
        self.assertIsNotNone(ev)
        self.assertGreater(ev.rvol, 100.0)
        self.assertFalse(ev.illiquid)
        self.assertTrue(ev.suspect)
        self.assertGreater(ev.baseline_notional_per_second, 5.0)

    def test_normal_spike_is_neither(self):
        det = SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0, min_baseline_notional_per_second=5.0,
        )
        ev = _feed(det, "okx:X-USDT-SWAP", 100.0, 1.0, 63, burst=10.0)
        self.assertIsNotNone(ev)
        self.assertGreaterEqual(ev.rvol, 3.0)
        self.assertFalse(ev.illiquid)
        self.assertFalse(ev.suspect)

    def test_default_detector_backward_compatible(self):
        """Likidite tabanı verilmezse eski davranış korunur."""
        det = SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0,
        )
        ev = _feed(det, "okx:NOK-USDT-SWAP", 100.0, 0.001, 63, burst=10.0)
        self.assertIsNotNone(ev)
        self.assertFalse(ev.illiquid)
        self.assertTrue(ev.suspect)

    def test_invalid_liquidity_floor_rejected(self):
        with self.assertRaises(ValueError):
            SpikeDetector(min_baseline_notional_per_second=-1.0)


class BurstCooldownTests(unittest.TestCase):
    def test_same_burst_does_not_reemit_every_second(self):
        """Eski hata: aynı patlama 3 sn boyunca aynı RVOL ile tekrar loglanıyordu."""
        det = SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0, min_baseline_notional_per_second=5.0,
        )
        first = _feed(det, "okx:NOK-USDT-SWAP", 100.0, 0.001, 63, burst=10.0)
        self.assertIsNotNone(first)
        # Hemen sonraki saniyeler: aynı pencere, yeni olay ÜRETİLMEMELİ
        for offset in (64, 65):
            again = det.update("okx:NOK-USDT-SWAP", 100.0, 0.001, offset * 1000)
            self.assertIsNone(again)

    def test_distinct_burst_after_cooldown_emits(self):
        det = SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0, min_baseline_notional_per_second=5.0,
            cooldown_seconds=3,
        )
        _feed(det, "okx:A-USDT-SWAP", 100.0, 0.001, 63, burst=10.0)
        later = None
        for offset in range(64, 75):
            later = det.update("okx:A-USDT-SWAP", 100.0, 10.0, offset * 1000)
            if later is not None:
                break
        self.assertIsNotNone(later)


class ExecutorVolumeFeedTests(unittest.TestCase):
    def _executor(self):
        cfg = SuperConfig()
        ex = Executor(PaperBroker(cfg, 1000.0), RiskManager(cfg), cfg)
        ex.store = None
        ex.broker.process_entry_tick = Mock(return_value=None)
        return ex

    def _filtered_spike(self, illiquid: bool) -> SpikeEvent:
        return SpikeEvent(
            base_volume=999.0, window_seconds=3.0,
            base_volume_per_second=333.0, baseline_per_second=0.001,
            rvol=5000.0, direction=None, price_change_pct=0.0,
            price=100.0, timestamp_ms=2000,
            suspect=not illiquid, illiquid=illiquid,
            baseline_notional_per_second=0.1 if illiquid else 100.0,
        )

    def test_fill_model_gets_real_volume_even_when_filtered(self):
        """Filtre sinyali iptal eder ama GERÇEK hacim dolum modelini besler."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=self._filtered_spike(True))
        ex.process_price_update("okx:NOK-USDT-SWAP", 100.0, 1000,
                                base_volume_24h=100000.0)
        ex.process_price_update("okx:NOK-USDT-SWAP", 100.0, 2000,
                                base_volume_24h=100050.0)
        tick_volume = ex.broker.process_entry_tick.call_args[0][2]
        self.assertEqual(tick_volume, 50.0)

    def test_suspect_spike_also_feeds_real_volume(self):
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=self._filtered_spike(False))
        ex.process_price_update("okx:BTC-USDT-SWAP", 100.0, 1000,
                                base_volume_24h=100000.0)
        ex.process_price_update("okx:BTC-USDT-SWAP", 100.0, 2000,
                                base_volume_24h=100007.0)
        tick_volume = ex.broker.process_entry_tick.call_args[0][2]
        self.assertEqual(tick_volume, 7.0)

    def test_no_double_counting_of_window_volume(self):
        """Tick hacmi tek tick deltası olmalı, 3 sn pencere toplamı değil."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=None)
        ex.process_price_update("okx:A-USDT-SWAP", 100.0, 1000,
                                base_volume_24h=100000.0)
        for i, total in enumerate((100010.0, 100020.0, 100030.0), start=2):
            ex.process_price_update("okx:A-USDT-SWAP", 100.0, i * 1000,
                                    base_volume_24h=total)
            tick_volume = ex.broker.process_entry_tick.call_args[0][2]
            self.assertEqual(tick_volume, 10.0)

    def test_no_volume_data_means_zero_tick_volume(self):
        ex = self._executor()
        ex.process_price_update("okx:A-USDT-SWAP", 100.0, 1000)
        tick_volume = ex.broker.process_entry_tick.call_args[0][2]
        self.assertEqual(tick_volume, 0.0)


class VolumeLogThrottleTests(unittest.TestCase):
    def _executor(self, interval=60.0):
        from dataclasses import replace
        cfg = SuperConfig()
        cfg = replace(cfg, signal=replace(cfg.signal, rvol_log_interval_seconds=interval))
        ex = Executor(PaperBroker(cfg, 1000.0), RiskManager(cfg), cfg)
        ex.store = None
        return ex

    def _spike(self, illiquid=True):
        return SpikeEvent(
            base_volume=10.0, window_seconds=3.0, base_volume_per_second=3.33,
            baseline_per_second=0.001, rvol=3333.0, direction=None,
            price_change_pct=0.0, price=100.0, timestamp_ms=0,
            suspect=not illiquid, illiquid=illiquid,
            baseline_notional_per_second=0.1 if illiquid else 100.0,
        )

    def test_repeated_events_logged_once_per_interval(self):
        ex = self._executor(interval=60.0)
        with self.assertLogs("app.executor", level="INFO") as logs:
            for i in range(50):
                ex._log_volume_filter("okx:NOK-USDT-SWAP", self._spike(), i * 1000)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(ex.low_liquidity_count, 50)
        self.assertEqual(ex.rvol_suspect_count, 0)

    def test_log_after_interval_reports_suppressed_count(self):
        ex = self._executor(interval=60.0)
        with self.assertLogs("app.executor", level="INFO") as logs:
            for i in range(10):
                ex._log_volume_filter("okx:NOK-USDT-SWAP", self._spike(), i * 1000)
            ex._log_volume_filter("okx:NOK-USDT-SWAP", self._spike(), 61_000)
        self.assertEqual(len(logs.records), 2)
        self.assertIn("tekrar bastırıldı", logs.records[-1].getMessage())

    def test_illiquid_is_info_suspect_is_warning(self):
        ex = self._executor()
        with self.assertLogs("app.executor", level="INFO") as logs:
            ex._log_volume_filter("okx:NOK-USDT-SWAP", self._spike(True), 1000)
            ex._log_volume_filter("okx:BTC-USDT-SWAP", self._spike(False), 1000)
        levels = {r.levelname for r in logs.records}
        self.assertIn("INFO", levels)
        self.assertIn("WARNING", levels)
        self.assertNotIn("ERROR", levels)
        self.assertEqual(ex.low_liquidity_count, 1)
        self.assertEqual(ex.rvol_suspect_count, 1)

    def test_different_symbols_throttled_independently(self):
        ex = self._executor(interval=60.0)
        with self.assertLogs("app.executor", level="INFO") as logs:
            ex._log_volume_filter("okx:A-USDT-SWAP", self._spike(), 1000)
            ex._log_volume_filter("okx:B-USDT-SWAP", self._spike(), 1500)
        self.assertEqual(len(logs.records), 2)


class ConfigDefaultsTests(unittest.TestCase):
    def test_liquidity_floor_and_log_interval_defaults(self):
        sig = SuperConfig().signal
        self.assertEqual(sig.spike_min_baseline_notional_per_second, 5.0)
        self.assertEqual(sig.rvol_log_interval_seconds, 60.0)

    def test_executor_wires_liquidity_floor(self):
        ex = Executor(PaperBroker(SuperConfig(), 1000.0), RiskManager(), SuperConfig())
        self.assertEqual(
            ex.spike_detector.min_baseline_notional_per_second, 5.0,
        )


if __name__ == "__main__":
    unittest.main()
