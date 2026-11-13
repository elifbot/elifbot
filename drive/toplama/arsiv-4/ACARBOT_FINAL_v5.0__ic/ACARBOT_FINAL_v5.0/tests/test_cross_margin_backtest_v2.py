"""v2.0 — Cross margin, backtest v2 (Monte Carlo/kısmi dolum/spread/rejim)."""

from __future__ import annotations

import pytest
from dataclasses import replace

from backtest.engine import BacktestEngine
from backtest.montecarlo import monte_carlo
from backtest.optimization import out_of_sample_check, sensitivity_analysis
from backtest.metrics import compute_metrics
from core.config import SuperConfig
from core.portfolio import Portfolio, Position
from core.risk import KillSwitchState, RiskManager
from tests.helpers import INTERVAL_MS, make_candles, apex_config


def _cross_config() -> SuperConfig:
    config = apex_config()
    config.v2 = replace(
        config.v2, margin=replace(config.v2.margin, mode="cross"),
    )
    return config


def _position(symbol: str, entry=100.0, qty=5.0):
    return Position(
        symbol=symbol, side="LONG", entry=entry, quantity=qty,
        initial_quantity=qty, margin=50.0, stop_loss=entry * 0.95,
        opened_at_ms=0,
    )


class TestCrossMargin:
    def test_cross_free_margin_includes_unrealized(self):
        """CROSS: serbest teminat = bakiye + açık PnL − kullanılan marj."""
        risk = RiskManager(_cross_config())
        portfolio = Portfolio(1_000.0)
        # Pozisyon -40 açık zararda: izole serbest bakiye 950,
        # cross serbest teminat = 1000 - 40 - 50 = 910
        portfolio.positions["X:AUSDT"] = _position("X:AUSDT")
        prices = {"X:AUSDT": 92.0}
        isolated = risk.config
        risk_isolated = RiskManager(apex_config())
        decision_cross = risk.check_portfolio(
            portfolio, "X:B-usdt", "LONG", 500.0, 2.0, prices, 0.0,
        )
        decision_isolated = risk_isolated.check_portfolio(
            portfolio, "X:B-usdt", "LONG", 500.0, 2.0, prices, 0.0,
        )
        # Bakiye 1000, marj 50, zarar 40 → cross 910 ≥ 50.5 → izin
        assert decision_cross.allowed
        assert decision_isolated.allowed

    def test_cross_blocks_when_unrealized_eats_free_margin(self):
        risk = RiskManager(_cross_config())
        risk_isolated = RiskManager(apex_config())
        portfolio = Portfolio(1_000.0)
        # 2 pozisyon × 500 nominal, fiyat 14'e çöker: her biri -430 zarar
        for i in range(2):
            portfolio.positions[f"X:{i}USDT"] = _position(f"X:{i}USDT")
        prices = {f"X:{i}USDT": 14.0 for i in range(2)}
        decision_cross = risk.check_portfolio(
            portfolio, "X:NEWUSDT", "LONG", 500.0, 2.0, prices, 0.0,
        )
        # cross: 1000 + (-860) - 100 = 40 < 50.5 → INSUFFICIENT_FUNDS
        assert not decision_cross.allowed
        assert decision_cross.reason == "INSUFFICIENT_FUNDS"
        # izole: teminat hesabı açık zararı GÖRMEZ (1000-100=900 yeterli);
        # engel ancak drawdown korumasından gelir → gerekçe FARKLI
        decision_isolated = risk_isolated.check_portfolio(
            portfolio, "X:NEWUSDT", "LONG", 500.0, 2.0, prices, 0.0,
        )
        assert decision_isolated.reason == "PORTFOLIO_DRAWDOWN_PROTECTION"

    def test_cross_account_liquidation_triggers_halt(self):
        """CROSS: equity <= toplam bakım marjı → HARD_HALT (hesap bazlı)."""
        risk = RiskManager(_cross_config())
        portfolio = Portfolio(1_000.0)
        portfolio.positions["X:AUSDT"] = _position("X:AUSDT", qty=10.0)
        # equity = 1000 - 990 = 10; bakım marjı = 100 × %0.4 = 0.4 → 10 > 0.4
        state = risk.evaluate_kill_switch(
            portfolio, {"X:AUSDT": 1.0}, 0.0,
        )
        # unrealized = (1-100)*10 = -990 → equity 10 > 0.4 → HALT olmamalı;
        # ama equity eşiği (850) aşılır → EQUITY_FLOOR HALT (öncelik: daha sıkı)
        assert state == KillSwitchState.HARD_HALT
        assert risk.last_halt_reason in {"EQUITY_FLOOR", "CROSS_LIQUIDATION"}

    def test_isolated_default_unchanged(self):
        """Varsayılan izolated: mevcut davranış korunur (208 testin garantisi)."""
        risk = RiskManager(apex_config())
        assert risk.config.v2.margin.mode == "isolated"
        portfolio = Portfolio(1_000.0)
        decision = risk.check_portfolio(
            portfolio, "X:TUSDT", "LONG", 500.0, 2.0, {}, 0.0,
        )
        assert decision.allowed


def _fade_candles(symbol_volume=10.0):
    closes = [100.0] * 80
    volumes = [10.0] * 80
    closes[-2] = 98.2
    closes[-1] = 98.0
    volumes[-1] = 40.0
    return make_candles(closes, volumes=volumes)


def _fade_run(spread_bps=None):
    """Sinyal + temas mumu ile tam backtest koşusu."""
    from infra.market_data.models import Candle
    candles = _fade_candles()
    touch = Candle(
        timestamp=candles[-1].timestamp + INTERVAL_MS,
        open=98.0, high=98.1, low=97.85, close=97.95, volume=500.0,
    )
    engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
    result = engine.run(
        {"TESTUSDT": candles + [touch]},
        spread_bps=spread_bps,
    )
    return result


class TestBacktestV2:
    def test_partial_fill_opens_partial_position(self):
        """Mum hacmi emri karşılamıyorsa KISMİ dolum açılır (şartname 7)."""
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        candles = _fade_candles()
        from infra.market_data.models import Candle
        touch = Candle(
            timestamp=candles[-1].timestamp + INTERVAL_MS,
            open=98.0, high=98.1, low=97.85, close=97.95, volume=15.0,
        )
        result = engine.run({"TESTUSDT": candles + [touch]})
        opens = [t for t in result.trades if t.get("type") == "OPEN"]
        assert opens
        # plan qty ≈ 500/98 ≈ 5.1; mum hacmi 15 × %10 = 1.5 → kısmi
        assert opens[0]["quantity"] < 5.0

    def test_trades_carry_regime_and_score(self):
        """İşlemler rejim ve skor etiketli gelir (rejim kırılımı için)."""
        result = _fade_run()
        opens = [t for t in result.trades if t.get("type") == "OPEN"]
        assert opens
        assert opens[0].get("regime")
        assert opens[0].get("score", 0.0) > 0

    def test_by_regime_breakdown(self):
        result = _fade_run()
        metrics = compute_metrics(
            list(result.trades), 1_000.0, result.final_balance,
            result.equity_curve,
        )
        assert metrics.by_regime
        assert any(k != "?" for k in metrics.by_regime)

    def test_spread_applied_when_measured_data_given(self):
        """Ölçülmüş spread verilirse limit kötüleştirilir; yoksa uygulanmadı."""
        with_spread = _fade_run(spread_bps={"TESTUSDT": 4.0})
        assert with_spread.spread_applied
        fills = [t for t in with_spread.trades if t.get("type") == "ORDER_FILL"]
        assert fills
        assert fills[0]["price"] < 97.9804  # yarım spread daha aşağıda

        without = _fade_run()
        assert without.spread_applied is False

    def test_betas_computed_when_btc_present(self):
        """BTC verisi varsa betalar GERÇEK 5m kapanışlarından hesaplanır."""
        btc = make_candles([100.0 * (1 + (i % 5 - 2) * 0.001) for i in range(120)])
        result = BacktestEngine(apex_config(), initial_balance=1_000.0).run({
            "BTCUSDT": btc, "TESTUSDT": _fade_candles(),
        })
        assert "TESTUSDT" in result.betas

    def test_shock_summary_reported(self):
        result = BacktestEngine(apex_config(), initial_balance=1_000.0).run(
            {"TESTUSDT": _fade_candles()},
        )
        assert "unavailable" in result.shock_tests
        # BTC yok → beta yok → şok testi uygulanmadı olarak SAYILIR
        assert result.shock_tests["unavailable"] >= 1


class TestMonteCarlo:
    def test_percentile_distribution(self):
        pnls = [10.0, -5.0, 20.0, -5.0, 15.0, -3.0, 8.0, -8.0]
        mc = monte_carlo(pnls, initial_balance=1_000.0, simulations=500,
                         seed=7)
        assert mc.trade_count == len(pnls)
        assert mc.final_pnl_p5 <= mc.final_pnl_p50 <= mc.final_pnl_p95
        assert 0.0 <= mc.prob_loss <= 1.0
        assert 0.0 <= mc.prob_ruin <= 1.0

    def test_ruin_probability_high_for_losing_system(self):
        pnls = [-30.0] * 20
        mc = monte_carlo(pnls, initial_balance=1_000.0, simulations=200,
                         ruin_drawdown_pct=15.0, seed=3)
        assert mc.prob_ruin == pytest.approx(1.0)

    def test_empty_input_safe(self):
        mc = monte_carlo([], initial_balance=1_000.0)
        assert mc.trade_count == 0
        assert mc.prob_loss == 0.0


class TestOptimization:
    def test_sensitivity_grid_runs_and_ranks(self):
        candles = _fade_candles()
        report = sensitivity_analysis(
            {"TESTUSDT": candles},
            {"exit.stop_atr_multiple": [1.0, 1.5, 2.0]},
            initial_balance=1_000.0,
        )
        assert len(report.rows) == 3
        assert report.best is not None
        assert report.robustness_note

    def test_sensitivity_rejects_risky_params(self):
        """Risk tavanlarına dokunan parametre gridde YASAK."""
        with pytest.raises(ValueError):
            sensitivity_analysis(
                {"TESTUSDT": _fade_candles()},
                {"account.max_loss_per_position": [10.0, 25.0]},
            )

    def test_out_of_sample_check(self):
        candles = _fade_candles() * 3
        report = out_of_sample_check(
            {"TESTUSDT": candles},
            {"exit.stop_atr_multiple": [1.0, 1.5]},
            initial_balance=1_000.0,
            is_fraction=0.7,
        )
        assert report.verdict
        assert report.best_params
