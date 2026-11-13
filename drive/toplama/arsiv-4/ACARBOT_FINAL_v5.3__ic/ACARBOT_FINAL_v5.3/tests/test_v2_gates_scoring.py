"""v2.0 — Skorlama, uzmanlar/Hakem, giriş kapıları ve equity eşiği testleri.

Şartname hedefleri:
  - Ağırlıklar: 20/15/20/15/15/10/5 (toplam 100); <70 işlem yok.
  - Veri gelmeyen bileşen "uygulanmadı" → paydadan düşülür.
  - Piyasa Hakemi veto; motor ağırlıkları kapanan işlemlerden uyarlanır
    (canlıda kendi kendine parametre değiştirme YOK).
  - Equity eşiği -%15 → HARD_HALT + pozisyonlar kapatılır.
  - BTC şok testi + beta ayarlı yön tavanı (gerçek betalar).
  - Giriş hızı 3/dk (gerçek girişler), yeniden giriş beklemesi 15 dk.
"""

from __future__ import annotations

import pytest

from core.config import RiskGateConfig, SuperConfig
from core.experts import (
    ExpertPerformanceTracker,
    ExpertVote,
    MarketJudge,
    MomentumHunter,
    ReversalHunter,
)
from core.gates import (
    EntryRateLimiter,
    ReentryCooldown,
    ShadowSignalTracker,
    exit_kind_for,
)
from core.portfolio import Portfolio, Position
from core.portfolio_risk import (
    BetaEstimator,
    BtcShockTester,
    base_asset_of,
    beta_adjusted_directional_notional,
)
from core.risk import KillSwitchState, RiskManager
from core.scoring import SignalScorer
from core.regime import SmartRegimeDetector
from tests.helpers import make_candles


class TestScoring:
    def _regime(self, candles):
        return SmartRegimeDetector(SuperConfig()).classify(candles)

    def test_weights_sum_to_100(self):
        cfg = SuperConfig().v2.scoring
        assert cfg.total_weight == pytest.approx(100.0)

    def test_missing_components_excluded_not_faked(self):
        """Veri yoksa bileşen 'uygulanmadı'; sabit puan YAZILMAZ."""
        scorer = SignalScorer(SuperConfig())
        candles = make_candles([100.0] * 80)
        score = scorer.score(
            "LONG", self._regime(candles), 3.0, candles,
        )
        names = {c.name for c in score.components}
        assert "orderflow" in names
        of = next(c for c in score.components if c.name == "orderflow")
        assert of.available is False
        assert score.available_fraction < 1.0

    def test_full_data_scores_on_100_scale(self):
        """Tüm veri geldiğinde ağırlık toplamı 100'dür (gerçek ölçek)."""
        from core.mtf import MtfAnalyzer
        from core.orderflow import OrderFlowEngine
        from core.config import OrderFlowConfig
        scorer = SignalScorer(SuperConfig())
        candles = make_candles([100.0] * 620)
        mtf = MtfAnalyzer().analyze_resampled(candles)
        engine = OrderFlowEngine(OrderFlowConfig())
        base = 1_700_000_000_000
        for i in range(3):
            bids = [(100.0 - j * 0.1, 5.0) for j in range(5)]
            asks = [(100.2 + j * 0.1, 5.0) for j in range(5)]
            engine.update_book("X", bids, asks, base + i * 25_000)
        for i in range(8):
            engine.update_tick("X", 100.0 + i * 0.05, 1.0, base + i * 1_000)
        for i in range(4):
            engine.update_open_interest("X", 1000.0 + i, base + i * 60_000)
        snapshot = engine.snapshot_for("X", candles, "LONG")
        score = scorer.score(
            "LONG", self._regime(candles), 3.0, candles,
            mtf=mtf, orderflow=snapshot,
        )
        assert score.available_weight == pytest.approx(100.0)
        assert 0.0 <= score.total <= 100.0

    def test_weak_score_blocks(self):
        """Kötü uyum + düşük hacim → 70 altı → işlem yok."""
        scorer = SignalScorer(SuperConfig())
        candles = make_candles([100.0] * 80)
        score = scorer.score(
            "SHORT", self._regime(candles), 0.2, candles,
        )
        assert score.total < 70.0
        assert score.tradeable is False
        assert score.grade == "WEAK"

    def test_grade_boundaries(self):
        scorer = SignalScorer(SuperConfig())
        candles = make_candles([100.0] * 80)
        regime = self._regime(candles)
        strong = scorer.score("LONG", regime, 4.0, candles)
        assert strong.grade in {"STRONG", "VERY_STRONG", "NORMAL"}


class TestExpertsAndJury:
    def test_momentum_hunter_detects_pump(self):
        closes = [100.0] * 60
        closes[-2] = 101.5
        closes[-1] = 101.9
        volumes = [10.0] * 60
        volumes[-1] = 40.0
        candles = make_candles(closes, volumes=volumes)
        vote = MomentumHunter().evaluate(candles)
        assert vote.side == "LONG"

    def test_reversal_hunter_extreme(self):
        closes = [100.0 - i * 0.5 for i in range(40)]  # sert düşüş → RSI düşük
        candles = make_candles(closes)
        vote = ReversalHunter(SuperConfig().v2.experts).evaluate(candles)
        # Sert düşüş sonrası dönüş mumu yoksa oy NONE, RSI eşik çalışır
        assert vote.side in {"NONE", "LONG"}

    def test_jury_veto_on_overwhelming_opposition(self):
        judge = MarketJudge(SuperConfig())
        votes = [
            ExpertVote("trend_hunter", "SHORT", 1.0),
            ExpertVote("momentum_hunter", "SHORT", 1.0),
            ExpertVote("reversal_hunter", "SHORT", 1.0),
            ExpertVote("liquidity_hunter", "SHORT", 1.0),
        ]
        decision = judge.judge("LONG", 0.2, votes)
        assert decision.side == "HOLD"
        assert decision.vetoed

    def test_jury_no_veto_on_base_support(self):
        judge = MarketJudge(SuperConfig())
        votes = [
            ExpertVote("trend_hunter", "LONG", 0.8),
            ExpertVote("momentum_hunter", "NONE", 0.0),
        ]
        decision = judge.judge("LONG", 0.8, votes)
        assert decision.side == "LONG"
        assert not decision.vetoed

    def test_performance_weight_adapts_within_bounds(self):
        """Başarısız motorun ağırlığı düşer; canlı otomatik parametre YOK."""
        cfg = SuperConfig().v2.experts
        tracker = ExpertPerformanceTracker(cfg)
        for _ in range(cfg.perf_min_trades):
            tracker.record("momentum_hunter", -1.0)
        weight = tracker.weight_of("momentum_hunter")
        assert cfg.min_weight <= weight < 1.0
        for _ in range(cfg.perf_min_trades):
            tracker.record("trend_hunter", 1.5)
        assert tracker.weight_of("trend_hunter") > 1.0
        assert tracker.weight_of("trend_hunter") <= cfg.max_weight


class TestEntryRateLimiter:
    def test_allows_three_per_minute(self):
        limiter = EntryRateLimiter(RiskGateConfig(entry_rate_per_min=3))
        base = 1_700_000_000_000
        assert limiter.allow(base)
        limiter.record(base)
        limiter.record(base + 1_000)
        limiter.record(base + 2_000)
        assert not limiter.allow(base + 3_000)

    def test_window_resets_after_60s(self):
        limiter = EntryRateLimiter(RiskGateConfig(entry_rate_per_min=3))
        base = 1_700_000_000_000
        for i in range(3):
            limiter.record(base + i)
        assert not limiter.allow(base + 5_000)
        assert limiter.allow(base + 61_000)

    def test_deferred_sorted_by_score(self):
        limiter = EntryRateLimiter(RiskGateConfig())
        base = 1_700_000_000_000
        limiter.defer("A", "LONG", 60.0, base)
        limiter.defer("B", "SHORT", 85.0, base)
        limiter.defer("C", "LONG", 92.0, base)
        order = [c.symbol for c in limiter.flush(base + 1_000)]
        assert order == ["C", "B", "A"]

    def test_deferred_ttl_expiry(self):
        limiter = EntryRateLimiter(RiskGateConfig(deferred_entry_ttl_s=90.0))
        base = 1_700_000_000_000
        limiter.defer("A", "LONG", 90.0, base)
        assert limiter.flush(base + 91_000) == []
        assert limiter.deferred_expired == 1


class TestReentryCooldown:
    def test_hard_exit_blocks_15_minutes(self):
        cooldown = ReentryCooldown(RiskGateConfig())
        base = 1_700_000_000_000
        cooldown.record_exit("X", base, "stop_loss")
        assert cooldown.blocked("X", base + 5 * 60_000) is not None
        assert cooldown.blocked("X", base + 15 * 60_000 + 1) is None

    def test_soft_exit_blocks_5_minutes(self):
        cooldown = ReentryCooldown(RiskGateConfig())
        base = 1_700_000_000_000
        cooldown.record_exit("X", base, "trailing_stop")
        assert cooldown.blocked("X", base + 4 * 60_000) is not None
        assert cooldown.blocked("X", base + 5 * 60_000 + 1) is None

    def test_other_exits_do_not_block(self):
        cooldown = ReentryCooldown(RiskGateConfig())
        cooldown.record_exit("X", 0, "kill_switch_hard")
        assert cooldown.blocked("X", 1) is None
        assert exit_kind_for("end_of_backtest") == "none"


class TestEquityFloor:
    def test_floor_triggers_hard_halt_and_flattens(self):
        """Equity başlangıçın -%15'ine inince HARD_HALT (şartname A-2)."""
        config = SuperConfig()
        risk = RiskManager(config)
        portfolio = Portfolio(1_000.0)
        portfolio.positions["X:LOSUSDT"] = Position(
            symbol="X:LOSUSDT", side="LONG", entry=100.0, quantity=10.0,
            initial_quantity=10.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        # unrealized = (84-100)*10 = -160 → equity 840 <= 850
        state = risk.evaluate_kill_switch(portfolio, {"X:LOSUSDT": 84.0}, 0.0)
        assert state == KillSwitchState.HARD_HALT
        assert risk.last_halt_reason == "EQUITY_FLOOR"

    def test_floor_above_threshold_is_normal(self):
        risk = RiskManager(SuperConfig())
        portfolio = Portfolio(1_000.0)
        portfolio.positions["X:OKUSDT"] = Position(
            symbol="X:OKUSDT", side="LONG", entry=100.0, quantity=1.0,
            initial_quantity=1.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        state = risk.evaluate_kill_switch(portfolio, {"X:OKUSDT": 99.0}, 0.0)
        assert state == KillSwitchState.NORMAL

    def test_floor_active_even_in_apex(self):
        """Equity eşiği APEX profilinde de geçerlidir (zorunlu risk)."""
        from dataclasses import replace
        config = SuperConfig()
        config.portfolio = replace(
            config.portfolio, max_positions=0, daily_soft_loss=0.0,
            daily_hard_loss=0.0,
        )
        risk = RiskManager(config)
        portfolio = Portfolio(1_000.0)
        portfolio.positions["X:LOSUSDT"] = Position(
            symbol="X:LOSUSDT", side="LONG", entry=100.0, quantity=10.0,
            initial_quantity=10.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        state = risk.evaluate_kill_switch(portfolio, {"X:LOSUSDT": 80.0}, 0.0)
        assert state == KillSwitchState.HARD_HALT


class TestBetaAndShock:
    def _beta_inputs(self, factor=2.0, count=80):
        """BTC dönüşümlü ±%1; sembol factor katı → beta ≈ factor."""
        btc = [100.0]
        sym = [100.0]
        for i in range(count):
            change = 0.01 if i % 2 == 0 else -0.01
            btc.append(btc[-1] * (1 + change))
            sym.append(sym[-1] * (1 + change * factor))
        return sym, btc

    def test_beta_from_real_returns(self):
        estimator = BetaEstimator(RiskGateConfig(beta_min_returns=50))
        sym, btc = self._beta_inputs(factor=2.0)
        beta = estimator.beta(sym, btc)
        assert beta is not None
        assert beta == pytest.approx(2.0, rel=0.35)

    def test_beta_unavailable_reported_not_faked(self):
        estimator = BetaEstimator(RiskGateConfig(beta_min_returns=50))
        beta = estimator.beta([100.0, 101.0, 100.5], [100.0, 100.5, 101.0])
        assert beta is None  # "uygulanmadi"

    def test_shock_test_blocks_over_cap(self):
        tester = BtcShockTester(RiskGateConfig())
        portfolio = Portfolio(1_000.0)
        portfolio.positions["X:AUSDT"] = Position(
            symbol="X:AUSDT", side="LONG", entry=100.0, quantity=10.0,
            initial_quantity=10.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        portfolio.positions["X:BUSDT"] = Position(
            symbol="X:BUSDT", side="LONG", entry=100.0, quantity=10.0,
            initial_quantity=10.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        prices = {"X:AUSDT": 100.0, "X:BUSDT": 100.0}
        result = tester.evaluate(
            positions=portfolio.positions, prices=prices,
            planned_symbol=None, planned_side=None, planned_notional=0.0,
            planned_beta=None,
            betas={"A": 5.0, "B": 5.0},   # 2 × 1000 × 5 × 3% = 300 > 150
            equity=1_000.0,
        )
        assert result.available and result.blocked
        assert result.worst_loss == pytest.approx(300.0, rel=1e-6)

    def test_shock_test_unavailable_without_beta(self):
        """Beta yoksa şok testi 'uygulanmadı' — engel de sabit varsayım da yok."""
        tester = BtcShockTester(RiskGateConfig())
        result = tester.evaluate(
            positions={}, prices={}, planned_symbol="X:NEWUSDT",
            planned_side="LONG", planned_notional=500.0, planned_beta=None,
            betas={}, equity=1_000.0,
        )
        assert result.available is False
        assert result.reason == "beta_uygulanmadi"

    def test_beta_adjusted_directional(self):
        portfolio = Portfolio(1_000.0)
        portfolio.positions["X:AUSDT"] = Position(
            symbol="X:AUSDT", side="LONG", entry=100.0, quantity=5.0,
            initial_quantity=5.0, margin=50.0, stop_loss=95.0, opened_at_ms=0,
        )
        total = beta_adjusted_directional_notional(
            portfolio.positions, {"X:AUSDT": 100.0},
            None, None, 0.0, None, {"A": 2.0},
        )
        assert total == pytest.approx(1000.0)  # 500 × beta 2

    def test_base_asset_extraction(self):
        assert base_asset_of("binance:BTCUSDT") == "BTC"
        assert base_asset_of("okx:BTC-USDT-SWAP") == "BTC"
        assert base_asset_of("X:1000PEPEUSDT") == "1000PEPE"


class TestShadowSignals:
    def test_blocked_entry_tracked_30_60_120(self):
        tracker = ShadowSignalTracker()
        base = 1_700_000_000_000
        record = tracker.record_blocked(
            "X:AUSDT", "LONG", "NEWS_GUARD", 100.0, 0.004, base,
        )
        assert record is not None
        tracker.on_price("X:AUSDT", 101.0, base + 31 * 60_000)
        tracker.on_price("X:AUSDT", 102.0, base + 61 * 60_000)
        tracker.on_price("X:AUSDT", 103.0, base + 121 * 60_000)
        assert record.returns["30"] == pytest.approx(1.0)
        assert record.returns["60"] == pytest.approx(2.0)
        assert record.returns["120"] == pytest.approx(3.0)
        assert record.matured

    def test_short_side_returns_direction_adjusted(self):
        tracker = ShadowSignalTracker()
        base = 1_700_000_000_000
        record = tracker.record_blocked(
            "X:AUSDT", "SHORT", "SWEEP_GUARD", 100.0, 0.004, base,
        )
        tracker.on_price("X:AUSDT", 98.0, base + 31 * 60_000)
        assert record.returns["30"] == pytest.approx(2.0)  # SHORT için kâr

    def test_summary_counts_first_touch_not_best_horizon(self):
        """v5.2: `would_have_won` kaldırıldı — ufukların EN İYİSİNİ
        seçiyordu (ileriye bakıp kiraz toplama). Yerine İLK TEMAS:
        stop önce mi vurdu, hedef önce mi?
        """
        tracker = ShadowSignalTracker()
        base = 1_700_000_000_000
        tracker.record_blocked("X:AUSDT", "LONG", "NEWS_GUARD", 100.0, 0.004, base)
        tracker.on_price("X:AUSDT", 102.0, base + 121 * 60_000)
        summary = tracker.summary()
        news = summary["by_reason"]["NEWS_GUARD"]
        assert news["blocked"] == 1
        assert news["once_hedef"] == 1
        assert news["once_stop"] == 0
        assert news["hedef_orani"] == 1.0
        assert "would_have_won" not in news
