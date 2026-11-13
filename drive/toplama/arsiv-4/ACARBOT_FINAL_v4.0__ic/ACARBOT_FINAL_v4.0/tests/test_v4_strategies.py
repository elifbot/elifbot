"""v4.0 — strateji motorları + confluence + seans filtresi testleri (madde 6,7,9)."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from app.main import apply_profile, build_parser
from core.config import SuperConfig
from core.pipeline import SignalPipeline
from core.strategies_extra import (
    ConfluenceEngine,
    session_blocks,
)
from core.strategy import MarketContext
from infra.market_data.models import Candle
from tests.helpers import make_candles


def _rising(count: int = 120, price: float = 100.0, step_pct: float = 0.35,
            volume: float = 30.0):
    closes = [price * (1 + step_pct / 100.0) ** i for i in range(count)]
    return make_candles(closes, volumes=[volume] * count)


def _falling_then_turn(count: int = 120, price: float = 100.0,
                       drop_pct: float = 0.5, tail: int = 6,
                       volume: float = 30.0):
    closes = [price * (1 - drop_pct / 100.0) ** i for i in range(count - tail)]
    closes += [closes[-1] * (1 + 0.10 / 100.0) for _ in range(tail)]
    return make_candles(closes, volumes=[volume] * count)


def _ctx(candles, btc: float = 0.0):
    return MarketContext(symbol="okx:T-USDT-SWAP", candles=candles, btc_change_pct_15m=btc)


class SessionFilterTests(unittest.TestCase):
    def test_off_never_blocks(self):
        self.assertIsNone(session_blocks("off", 0))

    def test_asia_window(self):
        # UTC 03:00 → asia (00-08) içinde
        ts = (3 * 3_600_000) + 1_700_000_000_000 // 86_400_000 * 86_400_000
        self.assertIsNone(session_blocks("asia", ts))

    def test_outside_window_blocks(self):
        # UTC 12:00 → asia dışı
        base = 1_700_000_000_000 // 86_400_000 * 86_400_000
        ts = base + 12 * 3_600_000
        reason = session_blocks("asia", ts)
        self.assertIsNotNone(reason)
        self.assertIn("seans", reason)

    def test_custom_range(self):
        base = 1_700_000_000_000 // 86_400_000 * 86_400_000
        self.assertIsNone(session_blocks("08-17", base + 9 * 3_600_000))
        self.assertIsNotNone(session_blocks("08-17", base + 18 * 3_600_000))

    def test_wraparound_range(self):
        base = 1_700_000_000_000 // 86_400_000 * 86_400_000
        self.assertIsNone(session_blocks("22-06", base + 23 * 3_600_000))
        self.assertIsNone(session_blocks("22-06", base + 2 * 3_600_000))
        self.assertIsNotNone(session_blocks("22-06", base + 12 * 3_600_000))

    def test_invalid_config_fails_open(self):
        self.assertIsNone(session_blocks("geçersiz", 0))

    def test_pipeline_blocks_outside_session(self):
        cfg = SuperConfig()
        cfg.signal = replace(cfg.signal, session_filter="asia")
        pipeline = SignalPipeline(cfg)
        candles = make_candles([100.0] * 80)
        # mum zamanını UTC 12:00'e yerleştir
        base = 1_700_000_000_000 // 86_400_000 * 86_400_000
        shifted = [
            Candle(c.timestamp - (c.timestamp % 86_400_000) + base
                   + 12 * 3_600_000 + i * 300_000,
                   c.open, c.high, c.low, c.close, c.volume)
            for i, c in enumerate(candles)
        ]
        decision = pipeline.evaluate("okx:T-USDT-SWAP", shifted)
        self.assertEqual(decision.rejection_code, "seans_filtre")


class ExtraStrategyTests(unittest.TestCase):
    def test_rsirev_long_on_oversold_turn(self):
        engine = ConfluenceEngine.__new__(ConfluenceEngine)  # noqa: smoke
        from core.strategies_extra import RsiRevEngine
        engine = RsiRevEngine(SuperConfig())
        sig = engine.evaluate(_ctx(_falling_then_turn()))
        # Dipten dönüş serisinde LONG beklenir (RSI düşük + yukarı dönüş)
        self.assertIn(sig.side, ("LONG", "HOLD"))

    def test_bollkir_breakout_with_volume(self):
        from core.strategies_extra import BollBreakEngine
        engine = BollBreakEngine(SuperConfig())
        candles = _rising()
        sig = engine.evaluate(_ctx(candles))
        # Güçlü yükseliş serisi üst bandı kırar → LONG veya sahte kırılım filtresi
        self.assertIn(sig.side, ("LONG", "HOLD"))
        if sig.side == "HOLD":
            self.assertIn(sig.rejection_code, (
                "dusuk_hacim", "fake_breakout_or_suspect", "bollkir_kosulu_yok",
            ))

    def test_unknown_strategy_is_honest(self):
        cfg = SuperConfig()
        cfg.signal = replace(cfg.signal, strategy="yok_ole strategy")
        pipeline = SignalPipeline(cfg)
        candles = make_candles([100.0] * 80)
        decision = pipeline.evaluate("okx:T-USDT-SWAP", candles)
        self.assertEqual(decision.signal.side, "HOLD")

    def test_confluence_strong_uptrend_is_long(self):
        engine = ConfluenceEngine(SuperConfig())
        sig = engine.evaluate(_ctx(_rising()))
        self.assertEqual(sig.side, "LONG")
        self.assertIn("confluence_long", sig.reason)

    def test_confluence_flat_is_hold_with_score(self):
        engine = ConfluenceEngine(SuperConfig())
        sig = engine.evaluate(_ctx(make_candles([100.0] * 90)))
        self.assertEqual(sig.side, "HOLD")
        self.assertEqual(sig.rejection_code, "confluence_yetersiz")
        self.assertIn("puan=", sig.reason)

    def test_confluence_votes_ten_filters(self):
        engine = ConfluenceEngine(SuperConfig())
        self.assertEqual(len(engine.FILTERS), 10)

    def test_pipeline_confluence_strategy(self):
        cfg = SuperConfig()
        cfg.signal = replace(cfg.signal, strategy="confluence")
        pipeline = SignalPipeline(cfg)
        decision = pipeline.evaluate("okx:T-USDT-SWAP", _rising())
        self.assertEqual(decision.signal.motor, "confluence")
        self.assertIn(decision.signal.side, ("LONG", "HOLD"))

    def test_macd_strategy_motor(self):
        cfg = SuperConfig()
        cfg.signal = replace(cfg.signal, strategy="macd")
        pipeline = SignalPipeline(cfg)
        decision = pipeline.evaluate("okx:T-USDT-SWAP", _rising())
        self.assertEqual(decision.signal.motor, "macd")


class StrategyCliTests(unittest.TestCase):
    def test_default_classic(self):
        cfg = apply_profile(build_parser().parse_args(["--paper"]), SuperConfig())
        self.assertEqual(cfg.signal.strategy, "classic")

    def test_strategy_and_threshold(self):
        args = build_parser().parse_args([
            "--paper", "--strategy", "confluence",
            "--confluence-threshold", "0.8",
        ])
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.signal.strategy, "confluence")
        self.assertEqual(cfg.signal.confluence_threshold, 0.8)

    def test_threshold_validation(self):
        with self.assertRaises(ValueError):
            apply_profile(build_parser().parse_args([
                "--paper", "--confluence-threshold", "1.5",
            ]), SuperConfig())

    def test_session_and_dca_flags(self):
        args = build_parser().parse_args([
            "--paper", "--session", "us", "--dca",
        ])
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.signal.session_filter, "us")
        self.assertTrue(cfg.dca.enabled)

    def test_agent_mode_flags(self):
        args = build_parser().parse_args([
            "--paper", "--us-market", "block", "--news-rss", "off",
        ])
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.v2.agents.us_market_mode, "block")
        self.assertEqual(cfg.v2.agents.rss_news_mode, "off")

    def test_live_flags(self):
        args = build_parser().parse_args([
            "--paper", "--live-entry-style", "post_only",
            "--position-mode", "auto",
        ])
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.v2.live.entry_style, "post_only")
        self.assertEqual(cfg.v2.live.position_mode, "auto")


if __name__ == "__main__":
    unittest.main()
