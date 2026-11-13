"""APEX v1.1 profili testleri: sınırsız pozisyon + günlük fren yok.

Kullanıcı tercihi (7 Kasım 2026): APEX v1.1'in sınırsız pozisyon ve günlük
frensiz davranışı FINAL'e profil olarak geri eklendi. Bu testler profilin
risk katmanında gerçekten uygulandığını ve guarded varsayılanın
bozulmadığını doğrular.
"""

from __future__ import annotations

import unittest

from app.main import apply_profile, build_parser
from core.config import SuperConfig
from core.portfolio import Portfolio, Position
from core.risk import KillSwitchState, RiskManager


def _apex_config() -> SuperConfig:
    args = build_parser().parse_args(["--paper", "--profile", "apex"])
    return apply_profile(args, SuperConfig())


def _position(symbol: str, entry: float = 100.0) -> Position:
    return Position(
        symbol=symbol, side="LONG", entry=entry, quantity=5.0,
        initial_quantity=5.0, margin=50.0, stop_loss=entry * 0.985,
        opened_at_ms=1_700_000_000_000, initial_net_risk=10.0,
    )


def _fill(portfolio: Portfolio, count: int) -> None:
    # Not: free_balance = balance - used_margin; teminat pozisyonlardan
    # hesaplanır, balance ayrıca düşülmez (gerçek açılış akışıyla aynı).
    for i in range(count):
        portfolio.positions[f"okx:COIN{i}-USDT-SWAP"] = _position(f"COIN{i}")


class ApexProfileConfigTests(unittest.TestCase):
    def test_apex_profile_disables_limits(self):
        cfg = _apex_config().portfolio
        self.assertEqual(cfg.max_positions, 0)
        self.assertEqual(cfg.max_positions_per_group, 0)
        self.assertEqual(cfg.daily_soft_loss, 0.0)
        self.assertEqual(cfg.daily_hard_loss, 0.0)
        self.assertEqual(cfg.gross_notional_cap, 0.0)
        self.assertEqual(cfg.net_directional_notional_cap, 0.0)
        self.assertEqual(cfg.total_open_risk_cap, 0.0)
        self.assertEqual(cfg.max_group_notional, 0.0)

    def test_apex_keeps_per_position_risk_and_drawdown(self):
        cfg = _apex_config()
        self.assertEqual(cfg.account.max_loss_per_position, 25.0)
        self.assertGreater(cfg.portfolio.portfolio_drawdown_pct, 0.0)

    def test_guarded_default_unchanged(self):
        args = build_parser().parse_args(["--paper"])
        cfg = apply_profile(args, SuperConfig()).portfolio
        self.assertEqual(cfg.max_positions, 6)
        self.assertEqual(cfg.daily_soft_loss, 100.0)
        self.assertEqual(cfg.daily_hard_loss, 150.0)

    def test_cli_overrides_profile(self):
        args = build_parser().parse_args(
            ["--paper", "--profile", "apex", "--max-positions", "3"]
        )
        cfg = apply_profile(args, SuperConfig()).portfolio
        self.assertEqual(cfg.max_positions, 3)
        self.assertEqual(cfg.daily_soft_loss, 0.0)  # profil korunur

    def test_no_daily_brake_flag_standalone(self):
        args = build_parser().parse_args(["--paper", "--no-daily-brake"])
        cfg = apply_profile(args, SuperConfig()).portfolio
        self.assertEqual(cfg.daily_soft_loss, 0.0)
        self.assertEqual(cfg.daily_hard_loss, 0.0)
        self.assertEqual(cfg.max_positions, 6)  # sadece fren kapanır

    def test_zero_max_positions_means_unlimited(self):
        args = build_parser().parse_args(["--paper", "--max-positions", "0"])
        cfg = apply_profile(args, SuperConfig()).portfolio
        self.assertEqual(cfg.max_positions, 0)

    def test_negative_max_positions_rejected(self):
        args = build_parser().parse_args(["--paper", "--max-positions", "-2"])
        with self.assertRaises(ValueError):
            apply_profile(args, SuperConfig())

    def test_guard_flags(self):
        args = build_parser().parse_args(
            ["--paper", "--no-news-guard", "--no-sweep-guard",
             "--news-buffer-minutes", "45"]
        )
        cfg = apply_profile(args, SuperConfig())
        self.assertFalse(cfg.news.enabled)
        self.assertFalse(cfg.sweep.enabled)
        self.assertEqual(cfg.news.buffer_minutes, 45.0)


class ApexRiskBehaviourTests(unittest.TestCase):
    def test_more_than_six_positions_allowed(self):
        risk = RiskManager(_apex_config())
        portfolio = Portfolio(1_000.0)
        _fill(portfolio, 8)  # guarded olsaydı 6'da dururdu
        decision = risk.check_portfolio(
            portfolio, "okx:NEW-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=0.0,
        )
        self.assertTrue(decision.allowed, decision.reason)

    def test_balance_is_the_natural_limit(self):
        risk = RiskManager(_apex_config())
        portfolio = Portfolio(1_000.0)
        _fill(portfolio, 19)  # 19 x 50 = 950 teminat bağlandı
        decision = risk.check_portfolio(
            portfolio, "okx:NEW-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=0.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "INSUFFICIENT_FUNDS")

    def test_daily_loss_does_not_gate_entries(self):
        risk = RiskManager(_apex_config())
        portfolio = Portfolio(1_000.0)
        decision = risk.check_portfolio(
            portfolio, "okx:BTC-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=-500.0, daily_unrealized_pnl=-100.0,
        )
        self.assertTrue(decision.allowed, decision.reason)

    def test_kill_switch_not_triggered_by_daily_loss(self):
        risk = RiskManager(_apex_config())
        portfolio = Portfolio(1_000.0)
        state = risk.evaluate_kill_switch(portfolio, {}, daily_realized_pnl=-900.0)
        self.assertEqual(state, KillSwitchState.NORMAL)

    def test_guarded_still_blocks_daily_loss(self):
        risk = RiskManager(SuperConfig())
        portfolio = Portfolio(1_000.0)
        decision = risk.check_portfolio(
            portfolio, "okx:BTC-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=-120.0,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("DAILY", decision.reason)

    def test_guarded_still_caps_positions(self):
        risk = RiskManager(SuperConfig())
        portfolio = Portfolio(10_000.0)
        _fill(portfolio, 6)
        decision = risk.check_portfolio(
            portfolio, "okx:NEW-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=0.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "MAX_POSITIONS_REACHED")

    def test_same_group_unlimited_in_apex(self):
        risk = RiskManager(_apex_config())
        portfolio = Portfolio(10_000.0)
        # majors grubundan 3 pozisyon (guarded'da grup tavanı 2)
        for sym in ("BTC", "ETH", "BCH"):
            portfolio.positions[f"okx:{sym}-USDT-SWAP"] = _position(sym)
        decision = risk.check_portfolio(
            portfolio, "okx:BTC-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=0.0,
        )
        # BTC zaten açık → executor seviyesinde engellenir; risk katmanı
        # grup nedeniyle engellememeli (sembol yeni olsun diye XRP değil majors)
        portfolio.positions.pop("okx:BTC-USDT-SWAP")
        decision = risk.check_portfolio(
            portfolio, "okx:BTC-USDT-SWAP", "LONG", 500.0, 10.0,
            {}, daily_realized_pnl=0.0,
        )
        self.assertTrue(decision.allowed, decision.reason)


if __name__ == "__main__":
    unittest.main()
