"""v3.1 — motor seçimi testleri: --motors both/trend/fade (dış v1.4 birleşimi).

Kapalı motor HİÇ DEĞERLENDİRİLMEZ. v3.1'de kapı TEK yerdedir
(SignalPipeline.evaluate) — Executor (canlı) ve BacktestEngine (backtest)
AYNI pipeline'ı kullandığı için kural iki katmanda birden geçerlidir.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.executor import Executor
from app.main import apply_profile, build_parser
from core.config import SuperConfig
from core.pipeline import SignalPipeline
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

    def test_engine_object_shared_between_executor_and_pipeline(self):
        """Executor'daki fade/trend takma adları pipeline'ın TA KENDİSİ —
        böylece kapı tek yerden (pipeline) her iki katmana uygulanır."""
        cfg = _config_for("trend")
        ex = Executor(PaperBroker(cfg, 1_000.0), RiskManager(cfg), cfg)
        self.assertIs(ex.fade, ex.pipeline.fade)
        self.assertIs(ex.trend, ex.pipeline.trend)


class PipelineMotorGateTests(unittest.TestCase):
    def test_trend_only_never_evaluates_fade(self):
        cfg = _config_for("trend")
        pipeline = SignalPipeline(cfg)
        candles = make_candles(flat_series(count=80))
        with patch.object(
            pipeline.fade, "evaluate",
            side_effect=AssertionError("FADE kapalıyken çağrılmamalı"),
        ):
            pipeline.evaluate("okx:BTC-USDT-SWAP", candles)

    def test_fade_only_never_evaluates_trend(self):
        cfg = _config_for("fade")
        pipeline = SignalPipeline(cfg)
        candles = make_candles(flat_series(count=80))
        with patch.object(
            pipeline.trend, "evaluate",
            side_effect=AssertionError("TREND kapalıyken çağrılmamalı"),
        ):
            pipeline.evaluate("okx:BTC-USDT-SWAP", candles)

    def test_both_evaluates_both(self):
        cfg = _config_for("both")
        pipeline = SignalPipeline(cfg)
        candles = make_candles(flat_series(count=80))
        calls = []
        with patch.object(
            pipeline.fade, "evaluate",
            side_effect=lambda ctx: calls.append("fade") or Signal(
                "HOLD", "fade", 0, 0, None, rejection_code="x",
            ),
        ), patch.object(
            pipeline.trend, "evaluate",
            side_effect=lambda ctx: calls.append("trend") or Signal(
                "HOLD", "trend", 0, 0, None, rejection_code="y",
            ),
        ):
            pipeline.evaluate("okx:BTC-USDT-SWAP", candles)
        self.assertEqual(sorted(calls), ["fade", "trend"])

    def test_executor_respects_gate_via_shared_pipeline(self):
        """Canlı yolu: --motors trend ile executor FADE'i hiç çağırmaz."""
        cfg = _config_for("trend")
        ex = Executor(PaperBroker(cfg, 1_000.0), RiskManager(cfg), cfg)
        candles = make_candles(flat_series(count=80))
        ex.update_candles("okx:BTC-USDT-SWAP", candles)
        with patch.object(
            ex.fade, "evaluate",
            side_effect=AssertionError("FADE kapalıyken çağrılmamalı"),
        ):
            ex._evaluate_entry(
                "okx:BTC-USDT-SWAP", candles, candles[-1].timestamp,
            )


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
        trend = Signal(
            "HOLD", "trend", 0.0, 1.0, None, rejection_code="dusuk_hacim",
        )
        result = resolver.resolve(disabled_fade, trend, Regime.RANGE)
        self.assertEqual(result.rejection_code, "dusuk_hacim")


if __name__ == "__main__":
    unittest.main()
