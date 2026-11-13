"""Yorum 1-B/C/G ve Yorum 2-4/7 — net zarar tavanı, portföy riski,
funding, likidasyon ve kill switch testleri.
"""

import pytest

from core.config import SuperConfig
from core.portfolio import (
    Portfolio,
    compute_funding_payment,
    compute_liquidation_price,
    next_funding_timestamp_ms,
)
from core.risk import (
    KillSwitchState,
    RiskManager,
    TradePlan,
)


@pytest.fixture
def config():
    return SuperConfig()


@pytest.fixture
def risk(config):
    return RiskManager(config)


class TestNetRiskSizing:
    def test_net_risk_at_stop_includes_costs(self, risk):
        """Net risk = stop mesafesi + ücretler + kayma + funding tamponu (Y2-4)."""
        plan = risk.plan(100.0, 0.004, "LONG")
        acc = risk.config.account
        expected = plan.notional * (
            0.004 + acc.maker_fee_rate + acc.taker_fee_rate
            + acc.stop_slippage_rate + acc.extra_slippage_rate
        ) + plan.estimated_funding_buffer
        assert plan.net_risk_at_stop == pytest.approx(expected, rel=1e-6)
        # v5.0: hedef net risk TAM olarak 25 USDT (nominal tavan kırpması yok)
        assert plan.net_risk_at_stop == pytest.approx(
            acc.max_loss_per_position, abs=1e-9,
        )

    def test_wide_stop_shrinks_notional(self, risk):
        """v5.0: geniş stop → nominal küçülür ama net risk 25'te sabit kalır."""
        wide = risk.plan(100.0, 0.06, "LONG")
        tight = risk.plan(100.0, 0.003, "LONG")
        assert wide.notional < tight.notional
        assert wide.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)

    def test_tight_stop_no_longer_clipped_to_500(self, risk):
        """v5.0 (v1.8 kuralı): 500 nominal tavanı KAPALI.

        Eski davranış dar stoplarda riski ~2-3 USDT'ye kırıyordu; kullanıcı
        kararı 'hepsini 25 yap'. Artık dar stop = büyük nominal = 25 USDT risk.
        """
        plan = risk.plan(100.0, 0.0035, "LONG")
        assert plan.notional == pytest.approx(25.0 / (0.0035 + 0.0016), rel=1e-9)
        assert plan.notional > 500.0
        assert plan.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)
        assert plan.margin == pytest.approx(plan.notional / 10.0)

    def test_short_side_mirrors_stop_and_liq(self, risk):
        plan = risk.plan(100.0, 0.004, "SHORT")
        assert plan.stop_loss == pytest.approx(100.4)
        assert plan.liquidation_price > 100.0

    def test_invalid_inputs_rejected(self, risk):
        with pytest.raises(ValueError):
            risk.plan(-1.0, 0.01, "LONG")
        with pytest.raises(ValueError):
            risk.plan(100.0, 1.5, "LONG")
        with pytest.raises(ValueError):
            risk.plan(100.0, 0.01, "FLAT")


class TestPortfolioChecks:
    def _filled_portfolio(self):
        portfolio = Portfolio(1_000.0)
        return portfolio

    def test_max_positions_cap(self, risk, config):
        portfolio = Portfolio(10_000.0)
        prices = {}
        from core.portfolio import Position
        for i in range(config.portfolio.max_positions):
            symbol = f"X:{i}USDT"
            prices[symbol] = 100.0
            portfolio.positions[symbol] = Position(
                symbol=symbol, side="LONG", entry=100.0, quantity=5.0,
                initial_quantity=5.0, margin=50.0, stop_loss=95.0,
                opened_at_ms=0,
            )
        decision = risk.check_portfolio(
            portfolio, "X:NEWUSDT", "LONG", 500.0, 2.0, prices, 0.0,
        )
        assert not decision.allowed
        assert decision.reason == "MAX_POSITIONS_REACHED"

    def test_correlation_group_cap(self, risk):
        """BTC + ETH aynı grupta; üçüncü major engellenir (Y1-G)."""
        portfolio = Portfolio(10_000.0)
        from core.portfolio import Position
        portfolio.positions["binance:BTCUSDT"] = Position(
            symbol="binance:BTCUSDT", side="LONG", entry=100.0, quantity=1.0,
            initial_quantity=1.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        portfolio.positions["binance:ETHUSDT"] = Position(
            symbol="binance:ETHUSDT", side="LONG", entry=100.0, quantity=1.0,
            initial_quantity=1.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        decision = risk.check_portfolio(
            portfolio, "binance:BCHUSDT", "LONG", 500.0, 2.0,
            {"binance:BTCUSDT": 100.0, "binance:ETHUSDT": 100.0}, 0.0,
        )
        assert not decision.allowed
        assert decision.reason and decision.reason.startswith("CORRELATION_GROUP_CAP")

    def test_gross_notional_cap(self, risk, config):
        portfolio = Portfolio(10_000.0)
        from core.portfolio import Position
        symbol = "X:AAAUSDT"
        portfolio.positions[symbol] = Position(
            symbol=symbol, side="LONG", entry=100.0,
            quantity=config.portfolio.gross_notional_cap / 100.0 - 1.0,
            initial_quantity=1.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        decision = risk.check_portfolio(
            portfolio, "X:BBBUSDT", "LONG", 500.0, 2.0, {symbol: 100.0}, 0.0,
        )
        assert not decision.allowed
        assert decision.reason == "GROSS_NOTIONAL_CAP"

    def test_total_open_risk_cap(self, risk, config):
        portfolio = Portfolio(10_000.0)
        from core.portfolio import Position
        symbol = "X:AAAUSDT"
        portfolio.positions[symbol] = Position(
            symbol=symbol, side="LONG", entry=100.0, quantity=1.0,
            initial_quantity=1.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
            initial_net_risk=config.portfolio.total_open_risk_cap - 1.0,
        )
        decision = risk.check_portfolio(
            portfolio, "X:BBBUSDT", "LONG", 500.0, 5.0, {symbol: 100.0}, 0.0,
        )
        assert not decision.allowed
        assert decision.reason == "TOTAL_OPEN_RISK_CAP"

    def test_daily_soft_loss_blocks_entries(self, risk):
        portfolio = Portfolio(1_000.0)
        decision = risk.check_portfolio(
            portfolio, "X:TESTUSDT", "LONG", 500.0, 2.0, {}, -101.0,
        )
        assert not decision.allowed
        assert decision.reason == "DAILY_SOFT_LOSS_LIMIT"

    def test_daily_hard_loss_blocks_and_flattens(self, risk):
        portfolio = Portfolio(1_000.0)
        decision = risk.check_portfolio(
            portfolio, "X:TESTUSDT", "LONG", 500.0, 2.0, {}, -151.0,
        )
        assert not decision.allowed
        assert decision.reason == "DAILY_HARD_LOSS_KILL_SWITCH"

    def test_portfolio_drawdown_protection(self, risk, config):
        portfolio = Portfolio(1_000.0)
        portfolio.equity_peak = 1_200.0
        prices = {}
        from core.portfolio import Position
        # equity ≈ 1.000 - 110 → tepeye göre ~%25 düşüş
        portfolio.positions["X:LOSUSDT"] = Position(
            symbol="X:LOSUSDT", side="LONG", entry=100.0, quantity=4.4,
            initial_quantity=4.4, margin=50.0, stop_loss=90.0, opened_at_ms=0,
        )
        decision = risk.check_portfolio(
            portfolio, "X:NEWUSDT", "LONG", 500.0, 2.0,
            {"X:LOSUSDT": 75.0}, 0.0,
        )
        assert not decision.allowed
        assert decision.reason == "PORTFOLIO_DRAWDOWN_PROTECTION"


class TestKillSwitch:
    def test_soft_stop_transition(self, risk):
        portfolio = Portfolio(1_000.0)
        state = risk.evaluate_kill_switch(portfolio, {}, -110.0)
        assert state == KillSwitchState.SOFT_STOP
        assert risk.kill_switch_state == KillSwitchState.SOFT_STOP

    def test_hard_halt_transition(self, risk):
        portfolio = Portfolio(1_000.0)
        state = risk.evaluate_kill_switch(portfolio, {}, -160.0)
        assert state == KillSwitchState.HARD_HALT

    def test_recovery_only_on_new_day(self, risk):
        portfolio = Portfolio(1_000.0)
        risk.evaluate_kill_switch(portfolio, {}, -110.0)
        risk.reset_daily()
        assert risk.kill_switch_state == KillSwitchState.NORMAL

    def test_hard_halt_not_reset_by_default(self, risk):
        portfolio = Portfolio(1_000.0)
        risk.evaluate_kill_switch(portfolio, {}, -200.0)
        risk.reset_daily()
        assert risk.kill_switch_state == KillSwitchState.HARD_HALT
        risk.reset_daily(hard_too=True)
        assert risk.kill_switch_state == KillSwitchState.NORMAL


class TestFunding:
    def test_long_pays_positive_rate(self):
        payment = compute_funding_payment(500.0, 0.0001, "LONG")
        assert payment == pytest.approx(0.05)

    def test_short_receives_positive_rate(self):
        payment = compute_funding_payment(500.0, 0.0001, "SHORT")
        assert payment == pytest.approx(-0.05)

    def test_negative_rate_reverses(self):
        assert compute_funding_payment(500.0, -0.0001, "LONG") < 0
        assert compute_funding_payment(500.0, -0.0001, "SHORT") > 0

    def test_next_funding_boundary(self):
        # 07:59:59 UTC → 08:00; 08:00:00 → 16:00
        eight_hours = 8 * 3_600_000
        base = 1_700_000_000_000  # 08:00 UTC civarı değil ama bölen tutarlı
        nxt = next_funding_timestamp_ms(base)
        assert (nxt - base) > 0
        assert nxt % eight_hours == 0

    def test_apply_funding_if_due(self, risk):
        """8 saat sınırı geçildiğinde ödeme uygulanır (Y1-C)."""
        from core.portfolio import Position
        position = Position(
            symbol="X:T", side="LONG", entry=100.0, quantity=5.0,
            initial_quantity=5.0, margin=50.0, stop_loss=99.0,
            opened_at_ms=0,
        )
        payment = risk.apply_funding_if_due(
            position, 100.0, now_ms=8 * 3_600_000 + 1_000, funding_rate=0.0001,
        )
        assert payment is not None
        assert payment == pytest.approx(0.05)  # 500 notional x 0.0001
        assert position.funding_paid == pytest.approx(0.05)

    def test_no_double_funding_same_period(self, risk):
        from core.portfolio import Position
        position = Position(
            symbol="X:T", side="LONG", entry=100.0, quantity=5.0,
            initial_quantity=5.0, margin=50.0, stop_loss=99.0,
            opened_at_ms=0,
        )
        first = risk.apply_funding_if_due(position, 100.0, 8 * 3_600_000 + 1)
        second = risk.apply_funding_if_due(position, 100.0, 8 * 3_600_000 + 2)
        assert first is not None
        assert second is None

    def test_funding_before_open_ignored(self, risk):
        from core.portfolio import Position
        opened = 3 * 3_600_000
        position = Position(
            symbol="X:T", side="LONG", entry=100.0, quantity=5.0,
            initial_quantity=5.0, margin=50.0, stop_loss=99.0,
            opened_at_ms=opened,
        )
        payment = risk.apply_funding_if_due(position, 100.0, 4 * 3_600_000)
        assert payment is None  # pozisyon 0. dönemden önce açıldı sayılır


class TestLiquidation:
    def test_liquidation_price_long(self, config):
        liq = compute_liquidation_price(100.0, "LONG", 10.0, config.funding)
        # 100 * (1 - 0.1 + 0.005 + 0.0125) = 91.75
        assert liq == pytest.approx(91.75, rel=1e-3)

    def test_liquidation_price_short(self, config):
        liq = compute_liquidation_price(100.0, "SHORT", 10.0, config.funding)
        assert liq == pytest.approx(108.25, rel=1e-3)

    def test_liquidation_trigger(self, risk):
        from core.portfolio import Position
        position = Position(
            symbol="X:T", side="LONG", entry=100.0, quantity=5.0,
            initial_quantity=5.0, margin=50.0, stop_loss=99.0,
            opened_at_ms=0, liquidation_price=91.75,
        )
        assert risk.check_liquidation(position, 91.0) is True
        assert risk.check_liquidation(position, 95.0) is False

    def test_margin_warning(self, risk):
        from core.portfolio import Position
        position = Position(
            symbol="X:T", side="LONG", entry=100.0, quantity=5.0,
            initial_quantity=5.0, margin=50.0, stop_loss=99.0,
            opened_at_ms=0, liquidation_price=91.75,
        )
        # Zarar 45 → teminatın %90'ı → uyarı
        assert risk.margin_warning(position, 91.0) is True
        # Zarar 10 → %20 → uyarı yok
        assert risk.margin_warning(position, 98.0) is False
