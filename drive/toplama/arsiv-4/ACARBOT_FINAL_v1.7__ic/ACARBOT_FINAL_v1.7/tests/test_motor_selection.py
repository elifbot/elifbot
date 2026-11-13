"""Motor seçimi testleri (FINAL v1.4): --motors trend/fade/both.

Kullanıcı isteği (7 Kasım 2026): FADE kapatılıp TREND öne çıkarılacak.
Bu testler kapalı motorun hiç değerlendirilmediğini ve canlı/backtest
katmanlarında aynı kuralın geçerli olduğunu kilitler.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from app.executor import Executor
from app.main import apply_profile, build_parser
from core.config import SuperConfig
from core.risk import RiskManager
from core.strategy import Regime, Signal, SignalResolver
from exec.paper import PaperBroker
from tests.helpers import flat_series, make_candles


def _config_for(motors_arg: str) -> SuperConfig:
    return apply_profile(
        build_parser().parse_args(["--paper", "--motors", motors_arg]),
        SuperConfig(),
    )


class MotorCliTests(unittest.TestCase):
    def test_default_both(self):
        cfg = _config_for("both")
        self.assertEqual(cfg.signal.enabled_motors, ("fade", "trend"))

    def test_trend_only(self):
        cfg = _config_for("trend")
        self.assertEqual(cfg.signal.enabled_motors, ("trend",))

    def test_fade_only(self):
        cfg = _config_for("fade")
        self.assertEqual(cfg.signal.enabled_motors, ("fade",))

    def test_combined_with_thresholds_and_apex(self):
        args = build_parser().parse_args([
            "--paper", "--profile", "apex", "--motors", "trend",
            "--min-rvol", "1.2",
        ])
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.signal.enabled_motors, ("trend",))
        self.assertEqual(cfg.signal.min_rvol_for_entry, 1.2)
        self.assertEqual(cfg.portfolio.max_positions, 0)


class ExecutorMotorGateTests(unittest.TestCase):
    def _executor(self, cfg: SuperConfig) -> Executor:
        broker = PaperBroker(cfg, 1_000.0)
        return Executor(broker, RiskManager(cfg), cfg)

    def test_trend_only_never_evaluates_fade(self):
        cfg = _config_for("trend")
        ex = self._executor(cfg)
        candles = make_candles(flat_series(count=80))
        ex.update_candles("okx:BTC-USDT-SWAP", candles)
        with patch.object(
            ex.fade, "evaluate",
            side_effect=AssertionError("FADE kapalıyken çağrılmamalı"),
        ):
            ex._evaluate_entry("okx:BTC-USDT-SWAP", candles, candles[-1].timestamp)

    def test_fade_only_never_evaluates_trend(self):
        cfg = _config_for("fade")
        ex = self._executor(cfg)
        candles = make_candles(flat_series(count=80))
        ex.update_candles("okx:BTC-USDT-SWAP", candles)
        with patch.object(
            ex.trend, "evaluate",
            side_effect=AssertionError("TREND kapalıyken çağrılmamalı"),
        ):
            ex._evaluate_entry("okx:BTC-USDT-SWAP", candles, candles[-1].timestamp)

    def test_both_evaluates_both(self):
        cfg = _config_for("both")
        ex = self._executor(cfg)
        candles = make_candles(flat_series(count=80))
        ex.update_candles("okx:BTC-USDT-SWAP", candles)
        calls = []
        with patch.object(ex.fade, "evaluate",
                          side_effect=lambda ctx: calls.append("fade") or Signal("HOLD", "fade", 0, 0, None, rejection_code="x")), \
             patch.object(ex.trend, "evaluate",
                          side_effect=lambda ctx: calls.append("trend") or Signal("HOLD", "trend", 0, 0, None, rejection_code="y")):
            ex._evaluate_entry("okx:BTC-USDT-SWAP", candles, candles[-1].timestamp)
        self.assertEqual(sorted(calls), ["fade", "trend"])


class ResolverWithDisabledMotorTests(unittest.TestCase):
    def test_disabled_fade_lets_trend_through(self):
        resolver = SignalResolver(SuperConfig())
        disabled_fade = Signal("HOLD", "fade", 0.0, 0.0, None)
        trend = Signal("LONG", "trend", 0.5, 2.0, 0.01, confidence=0.6)
        result = resolver.resolve(disabled_fade, trend, Regime.TREND_UP)
        self.assertEqual(result.side, "LONG")
        self.assertEqual(result.motor, "trend")

    def test_disabled_fade_holds_in_range(self):
        # TREND'in RANGE rejim filtresi korunur (kalite kuralı)
        resolver = SignalResolver(SuperConfig())
        disabled_fade = Signal("HOLD", "fade", 0.0, 0.0, None)
        trend = Signal("LONG", "trend", 0.5, 2.0, 0.01, confidence=0.6)
        result = resolver.resolve(disabled_fade, trend, Regime.RANGE)
        self.assertEqual(result.side, "HOLD")
        self.assertEqual(result.rejection_code, "rejim_uyumsuz")

    def test_disabled_motor_code_not_masking(self):
        # Kapalı motor red kodu taşımaz → açık motorun kodu görünür
        resolver = SignalResolver(SuperConfig())
        disabled_fade = Signal("HOLD", "fade", 0.0, 0.0, None)
        trend = Signal("HOLD", "trend", 0.0, 1.0, None, rejection_code="dusuk_hacim")
        result = resolver.resolve(disabled_fade, trend, Regime.RANGE)
        self.assertEqual(result.rejection_code, "dusuk_hacim")


if __name__ == "__main__":
    unittest.main()
