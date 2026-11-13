"""kasa1000_cross profili: cross marj + 20 pozisyon, risk tavanları korunur."""

from __future__ import annotations

import unittest

from app.main import apply_profile, build_parser
from core.config import SuperConfig


def _cfg(*extra: str) -> SuperConfig:
    args = build_parser().parse_args(["--paper", "--profile", "kasa1000_cross", *extra])
    return apply_profile(args, SuperConfig())


class KasaCrossProfileTests(unittest.TestCase):
    def test_cross_margin_and_position_count(self):
        cfg = _cfg()
        self.assertEqual(cfg.v2.margin.mode, "cross")
        self.assertEqual(cfg.portfolio.max_positions, 20)

    def test_per_position_spec_kept(self):
        acc = _cfg().account
        self.assertEqual(acc.margin_per_position, 50.0)
        self.assertEqual(acc.leverage, 10.0)
        self.assertEqual(acc.max_notional_per_position, 500.0)
        self.assertEqual(acc.max_loss_per_position, 25.0)

    def test_kill_switch_and_daily_brake_kept(self):
        p = _cfg().portfolio
        self.assertEqual(p.daily_soft_loss, 100.0)
        self.assertEqual(p.daily_hard_loss, 150.0)

    def test_caps_scaled_not_removed(self):
        p = _cfg().portfolio
        self.assertEqual(p.gross_notional_cap, 20 * 500.0)
        self.assertEqual(p.total_open_risk_cap, 20 * 25.0)
        self.assertGreater(p.net_directional_notional_cap, 0.0)
        self.assertLess(p.net_directional_notional_cap, p.gross_notional_cap)

    def test_cli_margin_mode_still_overrides(self):
        self.assertEqual(_cfg("--margin-mode", "isolated").v2.margin.mode, "isolated")

    def test_plain_kasa1000_unchanged(self):
        args = build_parser().parse_args(["--paper", "--profile", "kasa1000"])
        cfg = apply_profile(args, SuperConfig())
        self.assertEqual(cfg.portfolio.max_positions, 6)
        self.assertEqual(cfg.v2.margin.mode, SuperConfig().v2.margin.mode)


if __name__ == "__main__":
    unittest.main()
