"""FINAL v1.8 — işlem başı 25 USDT HEDEF net risk testleri.

Kullanıcı kararı: "evet hepsini 25 yap".
Eski davranış: 500 USDT nominal tavanı dar stoplarda riski ~3-5 USDT'ye
düşürüyordu. v1.8: nominal tavanı varsayılan kapalı, her yeni işlem
25 USDT net riske (ücret + kayma + funding tamponu) göre boyutlanır.
Teminat dinamik: notional / kaldıraç. Teminat yetmezse giriş AÇILMAZ;
risk sessizce küçültülmez.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.main import apply_profile, build_parser
from core.config import SuperConfig
from core.portfolio import Portfolio
from core.risk import RiskManager
from exec.paper import PaperBroker


def _risk() -> RiskManager:
    return RiskManager(SuperConfig())


def _apex_risk() -> RiskManager:
    args = build_parser().parse_args(["--paper", "--profile", "apex"])
    return RiskManager(apply_profile(args, SuperConfig()))


class TestTargetRiskSizing:
    def test_default_config_targets_25_and_disables_notional_cap(self):
        cfg = SuperConfig()
        assert cfg.account.max_loss_per_position == 25.0
        assert cfg.account.max_notional_per_position == 0.0
        assert cfg.account.margin_per_position == 0.0
        assert cfg.account.leverage == 10.0

    @pytest.mark.parametrize("stop_frac", [0.003, 0.004, 0.0077, 0.015, 0.025])
    def test_long_and_short_target_25_across_stop_widths(self, stop_frac):
        risk = _risk()
        for side in ("LONG", "SHORT"):
            plan = risk.plan(100.0, stop_frac, side)
            assert plan.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)
            assert plan.margin == pytest.approx(plan.notional / 10.0)
            assert plan.notional > 0

    def test_tight_stop_no_longer_clipped_to_500(self):
        plan = _risk().plan(100.0, 0.003, "LONG")
        # 25 / (0.003 + 0.0015 + 0.0001) ≈ 5434.78
        assert plan.notional == pytest.approx(5434.782608695652, rel=1e-9)
        assert plan.notional > 500.0
        assert plan.margin == pytest.approx(543.4782608695652, rel=1e-9)

    def test_ftt_like_short_targets_25(self):
        risk = _risk()
        plan = risk.plan(0.2288, 0.0077, "SHORT")
        expected_notional = 25.0 / (0.0077 + 0.0015 + 0.0001)
        assert plan.notional == pytest.approx(expected_notional, rel=1e-9)
        assert plan.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)
        assert plan.stop_loss == pytest.approx(0.2288 * 1.0077)

    def test_funding_buffer_scales_with_notional(self):
        risk = _risk()
        plan = risk.plan(100.0, 0.004, "LONG")
        assert plan.estimated_funding_buffer == pytest.approx(plan.notional * 0.0001)
        assert plan.net_risk_at_stop == pytest.approx(
            plan.notional * (0.004 + 0.0015) + plan.estimated_funding_buffer
        )

    def test_funding_disabled_removes_buffer(self):
        cfg = SuperConfig()
        cfg = replace(cfg, funding=replace(cfg.funding, enabled=False))
        plan = RiskManager(cfg).plan(100.0, 0.004, "LONG")
        assert plan.estimated_funding_buffer == 0.0
        assert plan.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)

    def test_legacy_positive_notional_cap_still_binds(self):
        cfg = SuperConfig()
        cfg = replace(cfg, account=replace(cfg.account, max_notional_per_position=500.0))
        plan = RiskManager(cfg).plan(100.0, 0.003, "LONG")
        assert plan.notional == 500.0
        assert plan.net_risk_at_stop < 25.0

    def test_invalid_config_rejected(self):
        cfg = SuperConfig()
        with pytest.raises(ValueError):
            RiskManager(replace(cfg, account=replace(cfg.account, max_loss_per_position=0.0)))
        with pytest.raises(ValueError):
            RiskManager(replace(cfg, account=replace(cfg.account, max_notional_per_position=-1.0)))
        with pytest.raises(ValueError):
            RiskManager(replace(cfg, account=replace(cfg.account, leverage=0.0)))


class TestDynamicMarginAndReservations:
    def test_margin_sufficiency_uses_dynamic_notional(self):
        risk = _apex_risk()
        plan = risk.plan(100.0, 0.003, "LONG")  # margin ≈ 543.48
        portfolio = Portfolio(1_000.0)
        decision = risk.check_portfolio(
            portfolio, "okx:NEW-USDT-SWAP", "LONG", plan.notional,
            plan.net_risk_at_stop, {}, 0.0,
        )
        assert decision.allowed, decision.reason

        small = Portfolio(500.0)
        decision = risk.check_portfolio(
            small, "okx:NEW-USDT-SWAP", "LONG", plan.notional,
            plan.net_risk_at_stop, {}, 0.0,
        )
        assert not decision.allowed
        assert decision.reason == "INSUFFICIENT_FUNDS"

    def test_reserved_pending_margin_blocks_overcommit(self):
        risk = _apex_risk()
        plan = risk.plan(100.0, 0.003, "LONG")
        portfolio = Portfolio(1_000.0)
        reserved = plan.margin * (1.0 + risk.config.account.maker_fee_rate)
        decision = risk.check_portfolio(
            portfolio, "okx:NEW-USDT-SWAP", "LONG", plan.notional,
            plan.net_risk_at_stop, {}, 0.0, reserved_margin=reserved,
        )
        assert not decision.allowed
        assert decision.reason == "INSUFFICIENT_FUNDS"

    def test_broker_reserved_margin_sums_active_orders(self):
        cfg = SuperConfig()
        broker = PaperBroker(cfg, 10_000.0)
        risk = RiskManager(cfg)
        plan = risk.plan(100.0, 0.004, "LONG")
        order = broker.place_entry("okx:A-USDT-SWAP", plan, now_ms=0)
        broker.bind_plan(order, plan, "trend")
        expected = plan.margin * (1.0 + cfg.account.maker_fee_rate)
        assert broker.reserved_margin() == pytest.approx(expected)
        broker.cancel_pending_entries(1_000, reason="test")
        assert broker.reserved_margin() == pytest.approx(0.0)

    def test_open_event_reports_notional_margin_and_net_risk(self):
        cfg = SuperConfig()
        broker = PaperBroker(cfg, 10_000.0)
        risk = RiskManager(cfg)
        plan = risk.plan(100.0, 0.004, "LONG")
        order = broker.place_entry("okx:A-USDT-SWAP", plan, now_ms=0, baseline_per_second=1.0)
        broker.bind_plan(order, plan, "trend")
        broker.process_entry_tick("okx:A-USDT-SWAP", 99.0, 10.0, 1_000)
        opens = [t for t in broker.trades if t["type"] == "OPEN"]
        assert opens
        op = opens[0]
        assert op["net_risk"] == pytest.approx(25.0, abs=1e-6)
        assert op["notional"] == pytest.approx(op["quantity"] * op["price"])
        assert op["margin"] == pytest.approx(op["notional"] / 10.0)
        position = broker.portfolio.positions["okx:A-USDT-SWAP"]
        assert position.initial_net_risk == pytest.approx(25.0, abs=1e-6)

    def test_emergency_net_loss_threshold_remains_25(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        assert broker.max_loss_per_position == 25.0
