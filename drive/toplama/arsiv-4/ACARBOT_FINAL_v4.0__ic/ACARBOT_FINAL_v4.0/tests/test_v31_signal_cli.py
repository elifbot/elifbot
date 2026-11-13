"""v3.1 — sinyal eşiği CLI parametreleri testleri (dış v1.3 özelliğinin birleşimi).

Bayrak verilmezse kod varsayılanları DEĞİŞMEZ (birebir geriye uyum).
"""

from __future__ import annotations

import unittest

from app.main import apply_profile, build_parser
from core.config import SuperConfig


def _apply(argv):
    return apply_profile(build_parser().parse_args(argv), SuperConfig())


class SignalCliTests(unittest.TestCase):
    def test_defaults_unchanged_without_flags(self):
        cfg = _apply(["--paper"]).signal
        self.assertEqual(cfg.min_rvol_for_entry, 1.5)
        self.assertEqual(cfg.fade_impulse_pct, 0.35)
        self.assertEqual(cfg.spike_multiplier, 3.0)

    def test_relaxed_thresholds_applied(self):
        cfg = _apply([
            "--paper", "--min-rvol", "1.2",
            "--fade-impulse", "0.25", "--spike-multiplier", "2.5",
        ]).signal
        self.assertEqual(cfg.min_rvol_for_entry, 1.2)
        self.assertEqual(cfg.fade_impulse_pct, 0.25)
        self.assertEqual(cfg.spike_multiplier, 2.5)

    def test_partial_override_keeps_other_defaults(self):
        cfg = _apply(["--paper", "--min-rvol", "1.0"]).signal
        self.assertEqual(cfg.min_rvol_for_entry, 1.0)
        self.assertEqual(cfg.fade_impulse_pct, 0.35)
        self.assertEqual(cfg.spike_multiplier, 3.0)

    def test_works_with_apex_profile(self):
        cfg = _apply(["--paper", "--profile", "apex", "--min-rvol", "1.2"])
        self.assertEqual(cfg.signal.min_rvol_for_entry, 1.2)
        self.assertEqual(cfg.portfolio.max_positions, 0)

    def test_invalid_values_rejected(self):
        for argv in (
            ["--paper", "--min-rvol", "0"],
            ["--paper", "--min-rvol", "-1"],
            ["--paper", "--fade-impulse", "0"],
            ["--paper", "--spike-multiplier", "1"],
            ["--paper", "--spike-multiplier", "0.5"],
        ):
            with self.assertRaises(ValueError, msg=str(argv)):
                _apply(argv)

    def test_backtest_mode_accepts_flags(self):
        # --paper zorunluluğu sys.argv'ye bakar (taban davranış); pytest
        # altında bu yüzden --paper açıkça verilir.
        args = build_parser().parse_args(
            ["--mode", "backtest", "--paper", "--min-rvol", "1.2"]
        )
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.signal.min_rvol_for_entry, 1.2)

    def test_thresholds_reach_backtest_engine_config(self):
        """Aynı eşikler backtest motoruna giden config'te de görünmeli."""
        cfg = _apply(["--paper", "--spike-multiplier", "2.0"])
        self.assertEqual(cfg.signal.spike_multiplier, 2.0)


if __name__ == "__main__":
    unittest.main()
