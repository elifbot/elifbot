"""v5.2 — SERTLEŞTİRME TESTLERİ.

Kapsanan kullanıcı tespitleri:
  1. "1m yol" etiketi gerçek kapsamayı yansıtmıyordu
  2. Hüküm mantığı negatif walk-forward sonucunu gizliyordu
  3. Rapor hataları: WF satırı liste basıyor, "ölçülmüş" etiketi yanlış,
     --bounds / --compare-no-costs kapalı
  4. Ölçüm tabanı ince
  5. Sürüm/paketleme tutarlılığı
  6. Dinamik risk ölçekleme (yeni)

Ek olarak bu sürümde bulunan 4. hata:
  7. walk_forward() cost_model / intrabar aktarmıyordu
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app import __version__
from backtest.costs import CostModel
from backtest.verdict import (
    DEFAULT_MIN_WF_TRADES,
    EDGE_CANDIDATE,
    EDGE_RISK_DRIFT,
    INSUFFICIENT_SAMPLE,
    INVALID_OPTIMISTIC,
    NO_EDGE,
    decide,
)
from core.risk_scaling import RiskBudget, RiskScaler, RiskScalingConfig
from infra.market_data.models import Candle

BASE_MS = 1_699_999_800_000  # 5m hizalı


def _wf(windows=6, profitable=0, trades=61, net=-433.6379, worst=-102.1114):
    """Walk-forward sözlüğü — v5.1 raporundaki gerçek şekil."""
    per = trades // max(1, windows)
    rows = [
        {
            "index": i + 1, "start_ts": BASE_MS + i * 1_000_000,
            "end_ts": BASE_MS + (i + 1) * 1_000_000,
            "net_pnl": net / windows, "trades": per,
            "win_rate": 0.2, "max_dd_pct": 8.9,
            "profitable": i < profitable,
        }
        for i in range(windows)
    ]
    return {
        "windows": rows, "profitable_windows": profitable,
        "total_windows": windows, "total_net_pnl": net,
        "worst_window_net_pnl": worst,
    }


def _primary(count=5, net=-87.111, breaches=1, dd_rejections=1117):
    return {
        "label": "birincil", "trade_count": count, "net_pnl": net,
        "path_source": "synthetic_adverse_first",
        "monte_carlo": {"prob_loss": 0.996},
        "risk_audit": {
            "breach_count": breaches, "max_realized_over_target": 1.346,
            "breach_ratio_threshold": 1.3, "losing_trades": 4,
            "mean_realized_over_target": 1.0988,
            "max_stop_overshoot_ratio": 0.7755,
        },
        "intrabar": {
            "real_1m_bars": 0, "synthetic_bars": 30,
            "real_coverage_ratio": 0.0,
        },
        "rejection_counts": {
            "dusuk_hacim": 126652,
            "PORTFOLIO_DRAWDOWN_PROTECTION": dd_rejections,
        },
        "walk_forward": _wf(),
    }


# =====================================================================
# 2) HÜKÜM MANTIĞI — walk-forward öncelikli
# =====================================================================

class TestVerdictWalkForwardPriority:
    def test_v51_bug_replay_no_edge_not_insufficient(self):
        """Kullanıcının bildirdiği senaryonun BİREBİR tekrarı.

        v5.1: birincil 5 işlem -> "örneklem yetersiz" diyordu.
        v5.2: WF 61 işlem / 0-6 kârlı / -433.64 -> "KENAR YOK".
        """
        verdict = decide([_primary()], min_trades=200)
        assert verdict.code == NO_EDGE
        assert verdict.severity == "red"
        assert "KENAR YOK" in verdict.headline
        assert "örneklem yetersiz" not in verdict.headline.lower()

    def test_wf_evidence_in_verdict(self):
        verdict = decide([_primary()], min_trades=200)
        wf = verdict.evidence["walk_forward"]
        assert wf["total_trades"] >= DEFAULT_MIN_WF_TRADES
        assert wf["profitable_windows"] == 0
        assert wf["total_net_pnl"] == pytest.approx(-433.6379)

    def test_truncation_is_reported_as_loss_not_uncertainty(self):
        verdict = decide([_primary()], min_trades=200)
        trunc = verdict.evidence["sample_truncation"]
        assert trunc["drawdown_rejections"] == 1117
        assert trunc["truncated"] is True
        assert any("KESİLMİŞ" in r for r in verdict.reasons)

    def test_zero_coverage_is_disclosed(self):
        verdict = decide([_primary()], min_trades=200)
        assert verdict.evidence["real_1m_coverage_ratio"] == 0.0
        assert any("DOĞRULANMADI" in r for r in verdict.reasons)

    def test_profitable_window_blocks_wf_no_edge(self):
        """Bir pencere kârlıysa WF kuralı tetiklenmez."""
        block = _primary()
        block["walk_forward"] = _wf(profitable=1)
        verdict = decide([block], min_trades=200)
        assert verdict.code == INSUFFICIENT_SAMPLE

    def test_positive_wf_blocks_no_edge(self):
        block = _primary()
        block["walk_forward"] = _wf(net=250.0, profitable=4)
        verdict = decide([block], min_trades=200)
        assert verdict.code == INSUFFICIENT_SAMPLE

    def test_thin_wf_falls_through_to_sample_rule(self):
        block = _primary()
        block["walk_forward"] = _wf(trades=6, net=-10.0)
        verdict = decide([block], min_trades=200)
        assert verdict.code == INSUFFICIENT_SAMPLE

    def test_insufficient_warns_about_negative_wf(self):
        block = _primary()
        block["walk_forward"] = _wf(trades=6, net=-10.0)
        verdict = decide([block], min_trades=200)
        assert any("NEGATİF" in r for r in verdict.reasons)

    def test_min_trades_source_all_counts_wf(self):
        block = _primary(count=180, net=150.0)
        block["monte_carlo"] = {"prob_loss": 0.2}
        block["walk_forward"] = _wf(trades=60, net=100.0, profitable=4)
        # 180 + 60 = 240 >= 200 -> örneklem yeterli, kârlı, aşım var
        verdict = decide([block], min_trades=200, min_trades_source="all")
        assert verdict.code == EDGE_RISK_DRIFT

    def test_min_trades_source_primary_legacy(self):
        block = _primary(count=180, net=150.0)
        block["walk_forward"] = _wf(trades=60, net=100.0, profitable=4)
        verdict = decide([block], min_trades=200, min_trades_source="primary")
        assert verdict.code == INSUFFICIENT_SAMPLE

    def test_disabled_costs_override_everything(self):
        verdict = decide(
            [_primary()], min_trades=200,
            cost_model={"enabled": False, "optimistic_warning": True},
        )
        assert verdict.code == INVALID_OPTIMISTIC
        assert verdict.severity == "invalid"

    def test_edge_candidate_requires_positive_everything(self):
        block = _primary(count=300, net=150.0, breaches=0)
        block["monte_carlo"] = {"prob_loss": 0.2}
        block["walk_forward"] = _wf(trades=300, net=400.0, profitable=5)
        block["intrabar"]["real_coverage_ratio"] = 1.0
        verdict = decide([block], min_trades=200)
        assert verdict.code == EDGE_CANDIDATE

    def test_no_edge_with_enough_primary_trades(self):
        block = _primary(count=300, net=-50.0, breaches=0)
        block["walk_forward"] = {}
        assert decide([block], min_trades=200).code == NO_EDGE

    def test_empty_runs_is_safe(self):
        assert decide([], min_trades=200).code == INSUFFICIENT_SAMPLE

    def test_render_has_no_python_repr(self):
        text = decide([_primary()], min_trades=200).render()
        assert "[{" not in text
        assert "dict_keys" not in text

    def test_verdict_is_json_serialisable(self):
        payload = decide([_primary()], min_trades=200).as_dict()
        assert json.loads(json.dumps(payload))["code"] == NO_EDGE

    def test_wf_taken_from_first_block_that_has_it(self):
        empty = _primary()
        empty["walk_forward"] = {}
        verdict = decide([empty, _primary()], min_trades=200)
        assert verdict.code == NO_EDGE


# =====================================================================
# 6) DİNAMİK RİSK ÖLÇEKLEME
# =====================================================================

class TestRiskScalingConfig:
    def test_defaults_are_conservative(self):
        cfg = RiskScalingConfig()
        assert cfg.enabled is True
        assert cfg.min_risk_usdt == pytest.approx(2.5)
        assert cfg.max_risk_usdt == 0.0  # yukarı ölçekleme yok

    @pytest.mark.parametrize("kwargs", [
        {"min_risk_usdt": 0.0},
        {"max_risk_usdt": -1.0},
        {"max_risk_usdt": 1.0, "min_risk_usdt": 5.0},
        {"drawdown_floor_pct": 1.0, "drawdown_start_pct": 2.0},
        {"loss_streak_step": 0.0},
        {"loss_streak_floor": 1.5},
        {"expectancy_r_floor": 0.1},
        {"max_cost_fraction_of_risk": 0.9, "hard_cost_fraction_of_risk": 0.5},
        {"recovery_wins": 0},
        {"recovery_step": 2.0},
    ])
    def test_invalid_config_rejected(self, kwargs):
        with pytest.raises(ValueError):
            RiskScalingConfig(**kwargs)


class TestRiskScalerComponents:
    def test_drawdown_ladder_monotonic(self):
        scaler = RiskScaler()
        values = [scaler.drawdown_scale(d) for d in (0, 1, 2, 4, 6, 8, 10)]
        assert values == sorted(values, reverse=True)
        assert values[0] == 1.0
        assert values[-1] == 0.0

    def test_drawdown_start_is_free(self):
        scaler = RiskScaler(RiskScalingConfig(drawdown_start_pct=2.0))
        assert scaler.drawdown_scale(2.0) == 1.0
        assert scaler.drawdown_scale(2.01) < 1.0

    def test_first_losses_are_free_then_shrink(self):
        scaler = RiskScaler()
        assert scaler.streak_scale() == 1.0
        scaler.observe(-10.0, 25.0)
        assert scaler.streak_scale() == 1.0
        scaler.observe(-10.0, 25.0)
        assert scaler.streak_scale() == 1.0  # ilk 2 bedava
        scaler.observe(-10.0, 25.0)
        assert scaler.streak_scale() == pytest.approx(0.85)

    def test_streak_floor_respected(self):
        scaler = RiskScaler()
        for _ in range(50):
            scaler.observe(-10.0, 25.0)
        assert scaler.streak_scale() == pytest.approx(0.25)

    def test_expectancy_needs_min_trades(self):
        scaler = RiskScaler(RiskScalingConfig(expectancy_min_trades=20))
        for _ in range(19):
            scaler.observe(-25.0, 25.0)
        assert scaler.expectancy_scale() == 1.0
        scaler.observe(-25.0, 25.0)
        assert scaler.expectancy_scale() == 0.0  # mean R = -1

    def test_expectancy_positive_is_neutral(self):
        scaler = RiskScaler(RiskScalingConfig(expectancy_min_trades=5))
        for _ in range(10):
            scaler.observe(25.0, 25.0)
        assert scaler.expectancy_scale() == 1.0

    def test_cost_hard_block(self):
        scaler = RiskScaler()
        # maliyet stopun 2 katı -> pay %66.7 > %60 sert eşik
        budget = scaler.budget(25.0, cost_rate=0.02, stop_fraction=0.01)
        assert budget.blocked is True
        assert budget.block_reason == "MALIYET_BUTCESI_ASIMI"
        assert budget.budget_usdt == 0.0
        assert scaler.blocked_count == 1

    def test_cost_soft_scale(self):
        scaler = RiskScaler()
        # pay = 0.0045 / 0.0145 = %31 -> eşik altı, ölçek 1
        assert scaler.cost_scale(0.0045, 0.010)[0] == 1.0
        # pay = 0.007/0.017 = %41 -> %35-%60 arası, kısmi ölçek
        scale, blocked = scaler.cost_scale(0.007, 0.010)
        assert blocked is False
        assert 0.0 < scale < 1.0

    def test_doge_like_cost_is_blocked(self):
        """Ölçülen DOGE maliyeti (~46 bps) dar stopta işlemi reddetmeli."""
        scaler = RiskScaler()
        budget = scaler.budget(25.0, cost_rate=0.0046, stop_fraction=0.003)
        assert budget.blocked is True

    def test_never_scales_up(self):
        scaler = RiskScaler()
        for _ in range(30):
            scaler.observe(50.0, 25.0)
        budget = scaler.budget(25.0)
        assert budget.budget_usdt <= 25.0

    def test_floor_respected_when_opted_in(self):
        """Tabana YÜKSELTME ancak açıkça istenirse (İYİMSER)."""
        scaler = RiskScaler(RiskScalingConfig(below_floor_action="floor_up"))
        budget = scaler.budget(25.0, drawdown_pct=50.0)
        assert budget.budget_usdt == pytest.approx(2.5)

    def test_below_floor_blocks_by_default(self):
        """v5.4: ölçekleyici tabanın altını istediyse işlem AÇILMAZ.

        Eski davranış 0,039 USDT isteyen adaya 2,50 USDT veriyordu (64x).
        Bu, 'asla yukarı ölçeklenmez' garantisini sessizce deliyordu.
        """
        scaler = RiskScaler()
        budget = scaler.budget(25.0, drawdown_pct=50.0)
        assert budget.blocked is True
        assert budget.block_reason == "OLCEK_TABAN_ALTINDA"
        assert budget.budget_usdt == 0.0
        assert scaler.stats()["below_floor_blocks"] == 1

    def test_no_binding_when_nothing_binds(self):
        """v5.4: hiçbir bileşen kısmıyorsa bağlayıcı 'none'.

        Eski kod min() ile sözlüğün ilk anahtarını ('drawdown') seçiyor,
        taze hesapta 'drawdown bağladı' diye YANLIŞ raporluyordu.
        """
        scaler = RiskScaler()
        budget = scaler.budget(25.0)
        assert budget.scale == 1.0
        assert budget.binding == "none"
        assert "drawdown" not in scaler.stats()["binding_counts"]

    def test_explicit_ceiling(self):
        scaler = RiskScaler(RiskScalingConfig(max_risk_usdt=5.0))
        assert scaler.budget(25.0).budget_usdt == pytest.approx(5.0)

    def test_recovery_hysteresis(self):
        cfg = RiskScalingConfig(recovery_wins=3, recovery_step=0.10)
        scaler = RiskScaler(cfg)
        for _ in range(6):
            scaler.observe(-10.0, 25.0)
        low = scaler.recovery_cap
        scaler.observe(10.0, 25.0)
        assert scaler.recovery_cap == low  # tek kazanç yetmez
        scaler.observe(10.0, 25.0)
        scaler.observe(10.0, 25.0)
        assert scaler.recovery_cap > low

    def test_disabled_is_passthrough(self):
        scaler = RiskScaler(RiskScalingConfig(enabled=False))
        budget = scaler.budget(25.0, drawdown_pct=99.0, cost_rate=0.9,
                               stop_fraction=0.001)
        assert budget.budget_usdt == 25.0
        assert budget.blocked is False

    def test_binding_component_is_reported(self):
        scaler = RiskScaler()
        budget = scaler.budget(25.0, drawdown_pct=5.0)
        assert budget.binding == "drawdown"
        assert "drawdown" in budget.components

    def test_deterministic(self):
        def run():
            scaler = RiskScaler()
            out = []
            for pnl in (-10, -10, -10, 20, -5, -5, 30, 30, 30):
                scaler.observe(float(pnl), 25.0)
                out.append(round(scaler.budget(25.0, drawdown_pct=3.0).budget_usdt, 6))
            return out
        assert run() == run()

    def test_invalid_base_rejected(self):
        with pytest.raises(ValueError):
            RiskScaler().budget(0.0)

    def test_stats_shape(self):
        scaler = RiskScaler()
        scaler.budget(25.0)
        stats = scaler.stats()
        assert stats["budgets_issued"] == 1
        assert stats["enabled"] is True
        assert json.loads(json.dumps(stats))

    def test_budget_as_dict_roundtrip(self):
        budget = RiskBudget(25.0, 12.5, 0.5, {"drawdown": 0.5}, "drawdown")
        assert json.loads(json.dumps(budget.as_dict()))["scale"] == 0.5

    def test_nan_pnl_ignored(self):
        scaler = RiskScaler()
        scaler.observe(float("nan"), 25.0)
        assert scaler.trade_count == 0


class TestRiskScalingIntegration:
    def test_risk_plan_honours_budget(self):
        from core.risk import RiskManager

        risk = RiskManager()
        full = risk.plan(100.0, 0.02, "LONG")
        small = risk.plan(100.0, 0.02, "LONG", risk_budget=5.0)
        assert full.net_risk_at_stop == pytest.approx(25.0)
        assert small.net_risk_at_stop == pytest.approx(5.0)
        assert small.notional < full.notional

    def test_paper_grid_align_does_not_override_budget(self):
        """v5.2'de bulunan hata: ızgara hizalaması bütçeyi eziyordu."""
        from core.risk import RiskManager
        from exec.paper import PaperBroker
        from exec.orders import Order, OrderSide, OrderType

        broker = PaperBroker()
        broker.tick_sizes["okx:X-USDT-SWAP"] = 0.01
        plan = RiskManager().plan(100.0, 0.02, "LONG", risk_budget=5.0)
        order = Order(
            symbol="okx:X-USDT-SWAP", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT, quantity=plan.quantity,
            limit_price=100.0, created_ms=BASE_MS, ttl_ms=60_000,
        )
        broker.bind_plan(order, plan, "trend", risk_budget=5.0)
        aligned = broker._plan_for_order[order.id]
        assert aligned.net_risk_at_stop <= 5.0 + 1e-6

    def test_engine_shrinks_target_risk_after_losses(self):
        from backtest.engine import BacktestEngine
        from backtest.regression_gate import build_fixture, canonical_config

        base = canonical_config()
        cfg = replace(
            base,
            portfolio=replace(
                base.portfolio, portfolio_drawdown_pct=90.0,
                daily_soft_loss=1e9, daily_hard_loss=1e9,
            ),
        )
        candles = build_fixture()
        from tests.helpers import legacy_ttl

        off = legacy_ttl(BacktestEngine(
            replace(cfg, risk_scaling=RiskScalingConfig(enabled=False)),
            initial_balance=1_000.0,
        )).run(candles, cost_model=CostModel())
        on = legacy_ttl(BacktestEngine(
            replace(cfg, risk_scaling=RiskScalingConfig(
                drawdown_start_pct=0.5, drawdown_floor_pct=50.0,
                below_floor_action="floor_up",
            )),
            initial_balance=1_000.0,
        )).run(candles, cost_model=CostModel())

        def targets(result):
            return [
                float(t.get("target_net_risk") or 0.0)
                for t in result.trades if t.get("type") == "CLOSE"
            ]

        off_targets, on_targets = targets(off), targets(on)
        assert len(on_targets) >= 4
        assert max(on_targets) <= max(off_targets) + 1e-6
        assert min(on_targets) < max(on_targets) - 1.0  # fiilen küçüldü
        assert on.risk_scaling["budgets_issued"] > 0
        assert on.risk_scaling["min_scale_seen"] < 1.0
        assert off.risk_scaling["budgets_issued"] == 0

    def test_engine_reports_cost_block_rejections(self):
        from backtest.engine import BacktestEngine
        from backtest.regression_gate import build_fixture, canonical_config

        cfg = replace(
            canonical_config(),
            risk_scaling=RiskScalingConfig(
                hard_cost_fraction_of_risk=0.02,
                max_cost_fraction_of_risk=0.01,
            ),
        )
        result = BacktestEngine(cfg, initial_balance=1_000.0).run(
            build_fixture(), cost_model=CostModel(),
        )
        assert result.rejection_counts.get("MALIYET_BUTCESI_ASIMI", 0) > 0
        assert result.trade_count == 0


# =====================================================================
# 1) HEDEFLİ 1m + DÜRÜST ETİKET
# =====================================================================

class TestTargetedFineData:
    def test_trade_windows_floors_and_pads(self):
        from tools.validate_strategy import trade_windows

        trades = [
            {"type": "ORDER_FILL", "symbol": "okx:X", "timestamp": BASE_MS + 123_000},
            {"type": "CLOSE", "symbol": "okx:X", "timestamp": BASE_MS + 900_000},
        ]
        spans = trade_windows(trades, pad_bars=1)
        start, end = spans["okx:X"][0]
        assert start % 300_000 == 0
        assert end % 300_000 == 0
        assert start <= BASE_MS
        assert end >= BASE_MS + 900_000

    def test_trade_windows_covers_holding_period(self):
        from tools.validate_strategy import trade_windows

        trades = [
            {"type": "ORDER_FILL", "symbol": "s", "timestamp": BASE_MS},
            {"type": "CLOSE", "symbol": "s", "timestamp": BASE_MS + 3_600_000},
        ]
        start, end = trade_windows(trades)["s"][0]
        assert end - start >= 3_600_000

    def test_open_position_uses_last_timestamp(self):
        from tools.validate_strategy import trade_windows

        trades = [
            {"type": "ORDER_FILL", "symbol": "s", "timestamp": BASE_MS},
            {"type": "ORDER_FILL", "symbol": "z", "timestamp": BASE_MS + 600_000},
        ]
        assert "s" in trade_windows(trades)

    def test_merge_windows(self):
        from tools.download_history import merge_windows

        assert merge_windows([(0, 10), (5, 20), (30, 40)]) == [(0, 20), (30, 40)]
        assert merge_windows([]) == []
        assert merge_windows([(100, 200)], pad_ms=50) == [(50, 250)]

    def test_fetch_okx_range_filters_bounds(self, monkeypatch):
        import tools.download_history as dh

        calls = []

        def fake_get(url):
            calls.append(url)
            # 100 bar, end_ms'ten geriye
            top = BASE_MS + 6_000_000
            return {"data": [
                [str(top - i * 60_000), "1", "2", "0.5", "1.5", "10"]
                for i in range(100)
            ]}

        monkeypatch.setattr(dh, "_get", fake_get)
        start = BASE_MS + 5_000_000
        end = BASE_MS + 5_600_000
        rows = dh.fetch_okx_range("X-USDT-SWAP", start, end, "1m")
        assert rows
        assert all(start <= r[0] < end for r in rows)

    def test_fetch_okx_range_empty_when_reversed(self):
        from tools.download_history import fetch_okx_range

        assert fetch_okx_range("X", BASE_MS + 100, BASE_MS, "1m") == []

    def test_fetch_okx_windows_respects_request_cap(self, monkeypatch):
        import tools.download_history as dh

        monkeypatch.setattr(
            dh, "fetch_okx_range",
            lambda *a, **k: [(BASE_MS, 1.0, 2.0, 0.5, 1.5, 10.0)],
        )
        rows, used, truncated = dh.fetch_okx_windows(
            "X", [(BASE_MS, BASE_MS + 60_000_000)], max_requests=1,
        )
        assert truncated is True

    def test_path_label_honest_at_zero_coverage(self):
        from tools.validate_strategy import _path_label

        label = _path_label("birincil", {"real_coverage_ratio": 0.0}, True)
        assert "1m YOK" in label
        assert "gerçek 1m yol" not in label

    def test_path_label_partial_coverage(self):
        from tools.validate_strategy import _path_label

        label = _path_label("birincil", {"real_coverage_ratio": 0.42}, True)
        assert "karma yol" in label
        assert "42.0" in label

    def test_path_label_full_coverage(self):
        from tools.validate_strategy import _path_label

        assert "gerçek 1m yol" in _path_label(
            "birincil", {"real_coverage_ratio": 1.0}, True,
        )

    def test_path_label_marks_costless(self):
        from tools.validate_strategy import _path_label

        assert "MALİYETSİZ" in _path_label(
            "x", {"real_coverage_ratio": 1.0}, False,
        )

    def test_refine_skips_covered_windows(self, tmp_path):
        from tools.validate_strategy import refine_fine_data

        class Result:
            trades = (
                {"type": "ORDER_FILL", "symbol": "okx:X", "timestamp": BASE_MS},
                {"type": "CLOSE", "symbol": "okx:X", "timestamp": BASE_MS + 600_000},
            )

        stats = {
            "targeted_windows": 0, "requests": 0, "fine_bars_gained": 0,
            "empty_windows": 0, "failures": 0, "truncated": False,
            "unsupported_exchange_skips": 0,
        }
        requested = {"okx:X": [(BASE_MS - 300_000, BASE_MS + 1_200_000)]}
        fine, changed = refine_fine_data(
            "okx", {}, {}, Result(), tmp_path, 0.0, requested, 100, stats,
        )
        assert changed is False
        assert stats["requests"] == 0

    def test_refine_non_okx_is_skipped(self, tmp_path):
        from tools.validate_strategy import refine_fine_data

        class Result:
            trades = (
                {"type": "ORDER_FILL", "symbol": "binance:X", "timestamp": BASE_MS},
                {"type": "CLOSE", "symbol": "binance:X", "timestamp": BASE_MS + 600_000},
            )

        stats = {
            "targeted_windows": 0, "requests": 0, "fine_bars_gained": 0,
            "empty_windows": 0, "failures": 0, "truncated": False,
            "unsupported_exchange_skips": 0,
        }
        _, changed = refine_fine_data(
            "binance", {}, {}, Result(), tmp_path, 0.0, {}, 100, stats,
        )
        assert changed is False
        assert stats["unsupported_exchange_skips"] == 1

    def test_refine_records_failures(self, tmp_path, monkeypatch):
        import tools.validate_strategy as vs

        def boom(*a, **k):
            raise RuntimeError("451")

        monkeypatch.setattr(vs, "fetch_okx_windows", boom)

        class Result:
            trades = (
                {"type": "ORDER_FILL", "symbol": "okx:X", "timestamp": BASE_MS},
                {"type": "CLOSE", "symbol": "okx:X", "timestamp": BASE_MS + 600_000},
            )

        stats = {
            "targeted_windows": 0, "requests": 0, "fine_bars_gained": 0,
            "empty_windows": 0, "failures": 0, "truncated": False,
            "unsupported_exchange_skips": 0,
        }
        _, changed = vs.refine_fine_data(
            "okx", {}, {}, Result(), tmp_path, 0.0, {}, 100, stats,
        )
        assert changed is False
        assert stats["failures"] == 1

    def test_two_pass_raises_real_coverage(self):
        """Sentetik koşuda 1m kapsaması 0; işlem barlarına 1m verilince artar."""
        from backtest.intrabar import IntrabarPath

        coarse = Candle(
            timestamp=BASE_MS, open=100.0, high=103.0, low=97.0,
            close=101.0, volume=1000.0,
        )
        empty = IntrabarPath()
        empty.steps("s", coarse)
        assert empty.stats.real_bars == 0

        fine = [
            Candle(
                timestamp=BASE_MS + i * 60_000, open=100.0,
                high=103.0 if i == 2 else 101.0,
                low=97.0 if i == 1 else 99.0,
                close=100.5, volume=200.0,
            )
            for i in range(5)
        ]
        loaded = IntrabarPath(fine_by_symbol={"s": fine})
        steps, source = loaded.steps("s", coarse)
        assert source == "real_1m"
        assert len(steps) == 5
        assert loaded.stats.as_dict()["real_coverage_ratio"] == 1.0

    def test_targeted_cache_roundtrip(self, tmp_path):
        from tools.download_history import write_csv
        from tools.validate_strategy import load_targeted_cache

        cache = tmp_path / "fine_targeted"
        cache.mkdir()
        write_csv(cache / "OKX_XUSDTSWAP_1m_targeted.csv",
                  [(BASE_MS, 1.0, 2.0, 0.5, 1.5, 10.0)])
        loaded = load_targeted_cache(tmp_path, ["okx:X-USDT-SWAP"])
        assert "okx:X-USDT-SWAP" in loaded
        assert len(loaded["okx:X-USDT-SWAP"]) == 1


# =====================================================================
# 3) RAPOR HATALARI
# =====================================================================

class TestReportFixes:
    def test_json_safe_strips_nested_infinity(self):
        from tools.validate_strategy import json_safe

        payload = {"by_symbol": {"X": {"profit_factor": float("inf")}},
                   "list": [float("nan"), 1.5], "ok": 2.0}
        cleaned = json_safe(payload)
        assert cleaned["by_symbol"]["X"]["profit_factor"] == 0.0
        assert cleaned["list"][0] == 0.0
        text = json.dumps(cleaned, allow_nan=False)
        assert "Infinity" not in text and "NaN" not in text

    def test_walk_forward_line_prints_count_not_list(self):
        from tools.validate_strategy import build_markdown

        block = _primary()
        block["metrics"] = {"win_rate": 0.2, "profit_factor": 0.0075,
                            "max_drawdown_usdt": 87.1, "by_regime": {}}
        report = {
            "version": __version__, "generated_at": "now",
            "dataset": {"exchange": "okx", "symbols": 6, "days": 90,
                        "total_bars": 155520, "fine_days": 0, "fine_bars": 0,
                        "fine_mode": "targeted", "fine_symbols": 0},
            "profile": "apex", "target_net_risk": 25.0,
            "cost_summary": "test", "cost_model": CostModel().as_dict(),
            "runs": [block], "verdict": "hüküm",
            "verdict_detail": {"code": NO_EDGE, "severity": "red"},
        }
        md = build_markdown(report)
        assert "0/6 pencere kârlı" in md
        assert "[{" not in md
        assert "| Pencere | İşlem |" in md

    def test_bounds_interval_section(self):
        from tools.validate_strategy import build_markdown

        block = _primary()
        block["metrics"] = {"by_regime": {}}
        report = {
            "version": __version__, "generated_at": "now",
            "dataset": {"exchange": "okx", "symbols": 6, "days": 90,
                        "total_bars": 1, "fine_days": 0, "fine_bars": 0,
                        "fine_mode": "targeted", "fine_symbols": 0},
            "profile": "apex", "target_net_risk": 25.0,
            "cost_summary": "t", "cost_model": CostModel().as_dict(),
            "runs": [block], "verdict": "v",
            "bounds_interval": {
                "adverse_net_pnl": -100.0, "adverse_trades": 5,
                "favorable_net_pnl": 20.0, "favorable_trades": 6,
                "width_usdt": 120.0, "spans_zero": True,
            },
            "optimism_gap": {
                "with_costs_net_pnl": -87.0, "with_costs_trades": 5,
                "without_costs_net_pnl": -40.0, "without_costs_trades": 5,
                "delta_net_pnl": 47.0,
            },
        }
        md = build_markdown(report)
        assert "Sentetik sınır aralığı" in md
        assert "İyimserlik farkı" in md
        assert "Aralık sıfırı KAPSIYOR" in md
        assert "47.0000" in md

    def test_defaults_on_for_bounds_and_compare(self):
        import argparse

        from tools.validate_strategy import main

        # Bayrak varsayılanlarını ayrıştırıcı üzerinden doğrula
        captured = {}
        real_parse = argparse.ArgumentParser.parse_args

        def spy(self, argv=None, namespace=None):
            ns = real_parse(self, argv, namespace)
            if hasattr(ns, "bounds"):
                captured["bounds"] = ns.bounds
                captured["compare"] = ns.compare_no_costs
                captured["fine_mode"] = ns.fine_mode
                captured["fine_days"] = ns.fine_days
            raise SystemExit(0)

        argparse.ArgumentParser.parse_args = spy
        try:
            with pytest.raises(SystemExit):
                main([])
        finally:
            argparse.ArgumentParser.parse_args = real_parse
        assert captured["bounds"] is True
        assert captured["compare"] is True
        assert captured["fine_mode"] == "targeted"
        assert captured["fine_days"] == 0

    def test_no_bounds_flag_still_works(self):
        import argparse

        from tools.validate_strategy import main

        captured = {}
        real_parse = argparse.ArgumentParser.parse_args

        def spy(self, argv=None, namespace=None):
            ns = real_parse(self, argv, namespace)
            if hasattr(ns, "bounds"):
                captured["bounds"] = ns.bounds
                captured["compare"] = ns.compare_no_costs
            raise SystemExit(0)

        argparse.ArgumentParser.parse_args = spy
        try:
            with pytest.raises(SystemExit):
                main(["--no-bounds", "--no-compare-no-costs"])
        finally:
            argparse.ArgumentParser.parse_args = real_parse
        assert captured["bounds"] is False
        assert captured["compare"] is False


class TestCostProvenance:
    def test_unmeasured_exchange_labelled_as_assumption(self):
        costs = CostModel(
            measured_spread_bps={"okx:BTC-USDT-SWAP": 0.01},
            measured_symbols=1, source="measured",
        )
        text = costs.summary_text()
        assert "binance: VARSAYIM (ÖLÇÜLMEDİ)" in text
        assert "okx: 1 sembol ÖLÇÜLDÜ" in text

    def test_measured_exchanges_set(self):
        costs = CostModel(
            measured_slippage_bps={"okx:X": 1.0, "binance:Y": 2.0},
            measured_symbols=2, source="measured",
        )
        assert costs.measured_exchanges() == {"okx", "binance"}

    def test_symbol_provenance(self):
        costs = CostModel(
            measured_slippage_bps={"okx:X": 1.0},
            measured_symbols=1, source="measured",
        )
        assert costs.symbol_provenance("okx:X") == "measured"
        assert costs.symbol_provenance("okx:Y") == "default"
        assert CostModel.disabled().symbol_provenance("okx:X") == "disabled"

    def test_coverage_report(self):
        costs = CostModel(
            measured_slippage_bps={"okx:X": 1.0},
            measured_symbols=1, source="measured",
        )
        cov = costs.coverage(["okx:X", "okx:Y", "binance:Z"])
        assert cov["dataset_symbols"] == 3
        assert cov["measured_symbols"] == 1
        assert cov["coverage_ratio"] == pytest.approx(0.3333)
        assert "binance:Z" in cov["unmeasured_symbols"]

    def test_summary_appends_dataset_coverage(self):
        costs = CostModel(
            measured_slippage_bps={"okx:X": 1.0},
            measured_symbols=1, source="measured",
        )
        text = costs.summary_text(["okx:X", "binance:Z"])
        assert "VERİ KÜMESİ KAPSAMASI 1/2" in text
        assert "ÖLÇÜLMEYEN: binance:Z" in text

    def test_exchange_provenance_in_dict(self):
        costs = CostModel(
            measured_slippage_bps={"okx:X": 1.0},
            measured_symbols=1, source="measured",
        )
        prov = costs.as_dict()["exchange_provenance"]
        assert prov["okx"]["source"] == "measured_symbols"
        assert prov["binance"]["source"] == "default_assumption"
        assert prov["binance"]["measured_symbol_count"] == 0

    def test_disabled_summary_is_explicit(self):
        assert "KAPALI" in CostModel.disabled().summary_text()


# =====================================================================
# 7) WALK-FORWARD MALİYET AKTARIMI (bu sürümde bulunan hata)
# =====================================================================

class TestWalkForwardCostPropagation:
    def test_walk_forward_accepts_cost_model(self):
        import inspect

        from backtest.walkforward import walk_forward

        params = inspect.signature(walk_forward).parameters
        assert "cost_model" in params
        assert "intrabar" in params
        assert "tick_sizes" in params

    def test_windows_use_given_cost_model(self):
        from backtest.walkforward import walk_forward
        from core.config import SuperConfig

        candles = {
            "okx:X": [
                Candle(
                    timestamp=BASE_MS + i * 300_000, open=100.0 + i * 0.01,
                    high=100.5 + i * 0.01, low=99.5 + i * 0.01,
                    close=100.2 + i * 0.01, volume=1_000.0,
                )
                for i in range(400)
            ],
        }
        costs = CostModel(
            measured_slippage_bps={"okx:X": 7.5},
            measured_symbols=1, source="measured",
        )
        report = walk_forward(
            candles, windows=2, config=SuperConfig(),
            initial_balance=1_000.0, cost_model=costs,
        )
        assert len(report.windows) == 2
        for window in report.windows:
            assert window.result.cost_model["source"] == "measured"
            assert window.result.cost_model["measured_slippage_bps"]["okx:X"] == 7.5

    def test_window_intrabar_stats_not_shared(self):
        from backtest.intrabar import IntrabarPath
        from backtest.walkforward import walk_forward
        from core.config import SuperConfig

        candles = {
            "okx:X": [
                Candle(
                    timestamp=BASE_MS + i * 300_000, open=100.0,
                    high=101.0, low=99.0, close=100.0, volume=1_000.0,
                )
                for i in range(400)
            ],
        }
        shared = IntrabarPath(synthetic_order="adverse_first")
        walk_forward(
            candles, windows=4, config=SuperConfig(),
            initial_balance=1_000.0, intrabar=shared,
        )
        # Paylaşılan nesnenin sayacı şişmemeli (her pencere kendi modeli)
        assert shared.stats.synthetic_bars == 0


# =====================================================================
# 4) ÖLÇÜM TABANI
# =====================================================================

class TestMeasurementQuality:
    def test_percentile_math(self):
        from tools.measure_costs import _pct

        assert _pct([], 75) is None
        assert _pct([5.0], 75) == 5.0
        assert _pct([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
        assert _pct([1.0, 2.0, 3.0, 4.0], 75) == pytest.approx(3.25)
        assert _pct([1.0, 2.0, 3.0, 4.0], 100) == 4.0

    def test_thin_base_is_flagged(self):
        from tools.measure_costs import grade_measurement

        details = {f"s{i}": {"samples": 4, "window_seconds": 1.2}
                   for i in range(6)}
        quality = grade_measurement(details, rounds=1, samples=4)
        assert quality["grade"] == "thin"
        assert quality["reasons"]

    def test_adequate_base(self):
        from tools.measure_costs import grade_measurement

        details = {f"s{i}": {"samples": 24, "window_seconds": 150.0}
                   for i in range(10)}
        quality = grade_measurement(details, rounds=4, samples=6)
        assert quality["grade"] == "adequate"

    def test_empty_details(self):
        from tools.measure_costs import grade_measurement

        assert grade_measurement({}, 4, 6)["grade"] == "none"

    def test_caveat_present(self):
        from tools.measure_costs import grade_measurement

        quality = grade_measurement({"a": {"samples": 24, "window_seconds": 200.0}}, 4, 6)
        assert "küçük coinlerde" in quality["caveat"]

    def test_measure_symbol_uses_percentile(self, monkeypatch):
        import tools.measure_costs as mc

        books = [
            ([(99.9, 100.0)], [(100.1, 100.0)], 100),
            ([(99.0, 100.0)], [(101.0, 100.0)], 200),
            ([(99.5, 100.0)], [(100.5, 100.0)], 150),
        ]
        seq = iter(books * 4)
        monkeypatch.setattr(mc, "fetch_book", lambda *a, **k: next(seq))
        monkeypatch.setattr(mc.time, "sleep", lambda *_: None)
        result = mc.measure_symbol(
            "okx", "X", samples=3, notional=100.0, pause=0.0,
            percentile=100.0, rounds=2, round_gap=0.0,
        )
        assert result is not None
        assert result["samples"] == 6
        assert result["rounds"] == 2
        assert result["percentile"] == 100.0
        # p100 = en kötü spread
        worst = (101.0 - 99.0) / 100.0 * 10_000.0
        assert result["spread_bps"] == pytest.approx(worst, abs=1e-3)
        assert result["spread_stats"]["p50"] <= result["spread_stats"]["max"]

    def test_measure_symbol_records_window(self, monkeypatch):
        import tools.measure_costs as mc

        monkeypatch.setattr(
            mc, "fetch_book",
            lambda *a, **k: ([(99.9, 100.0)], [(100.1, 100.0)], 120),
        )
        monkeypatch.setattr(mc.time, "sleep", lambda *_: None)
        result = mc.measure_symbol(
            "okx", "X", samples=2, notional=100.0, pause=0.0, rounds=2,
        )
        assert result["first_sample_at"] and result["last_sample_at"]
        assert "window_seconds" in result


# =====================================================================
# 5) SÜRÜM TUTARLILIĞI
# =====================================================================

class TestVersionConsistency:
    def test_version_matches_shipped_changelog(self):
        """Sürüm sabit kodlanmaz: changelog dosya adı tek kaynaktan türetilir."""
        from pathlib import Path

        from tools.package_release import short_version

        root = Path(__file__).resolve().parents[1]
        short = short_version(__version__)
        assert (root / f"DEGISIKLIKLER_FINAL_v{short}.md").exists(), (
            f"v{short} değişiklik günlüğü eksik"
        )

    def test_reference_version_matches_when_present(self):
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "docs" / "backtest_referans.json"
        if not path.exists():
            pytest.skip("referans dosyası yok")
        reference = json.loads(path.read_text(encoding="utf-8"))
        assert reference["version"] == __version__

    def test_changelog_for_this_version_exists(self):
        from pathlib import Path

        from tools.package_release import short_version

        root = Path(__file__).resolve().parents[1]
        short = short_version(__version__)
        path = root / f"DEGISIKLIKLER_FINAL_v{short}.md"
        assert path.exists(), f"v{short} değişiklik günlüğü eksik"
        assert short in path.read_text(encoding="utf-8")

    def test_changelogs_are_not_duplicates(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        if not (root / "DEGISIKLIKLER_FINAL_v5.1.md").exists():
            pytest.skip("v6.1 temiz paket: tarihsel değişiklik belgeleri çıkarıldı")
        v51 = (root / "DEGISIKLIKLER_FINAL_v5.1.md").read_text(encoding="utf-8")
        v52 = (root / "DEGISIKLIKLER_FINAL_v5.2.md").read_text(encoding="utf-8")
        assert v51 != v52


# =====================================================================
# RAPOR TUTARLILIK KAPISI (v5.2)
# =====================================================================

class TestReportConsistencyGate:
    def _report(self, **overrides):
        from backtest.verdict import decide

        runs = [_primary()]
        detail = decide(runs, min_trades=200)
        report = {
            "version": __version__,
            "runs": runs,
            "cost_model": CostModel().as_dict(),
            "dataset": {"symbol_list": ["okx:X"]},
            "verdict_detail": detail.as_dict(),
            "bounds_interval": {"spans_zero": False},
            "optimism_gap": {"delta_net_pnl": 10.0},
        }
        report.update(overrides)
        return report

    def test_consistent_report_passes(self):
        from backtest.regression_gate import check_report_consistency

        gate = check_report_consistency(self._report())
        assert gate.ok, gate.failures

    def test_tampered_verdict_is_caught(self):
        """Hükmü elle 'örneklem yetersiz' yaparsak kapı kırmızı olur."""
        from backtest.regression_gate import check_report_consistency

        report = self._report()
        report["verdict_detail"]["code"] = INSUFFICIENT_SAMPLE
        gate = check_report_consistency(report)
        assert not gate.ok
        assert any("HÜKÜM TUTARSIZ" in f for f in gate.failures)

    def test_legacy_report_without_structured_verdict_fails(self):
        from backtest.regression_gate import check_report_consistency

        report = self._report()
        del report["verdict_detail"]
        gate = check_report_consistency(report)
        assert not gate.ok

    def test_false_1m_label_is_caught(self):
        from backtest.regression_gate import check_report_consistency

        report = self._report()
        report["runs"][0]["label"] = "birincil (gerçek 1m yol)"
        report["runs"][0]["intrabar"]["real_coverage_ratio"] = 0.0
        gate = check_report_consistency(report)
        assert any("ETİKET YALANI" in f for f in gate.failures)

    def test_zero_coverage_warns(self):
        from backtest.regression_gate import check_report_consistency

        gate = check_report_consistency(self._report())
        assert any("DOĞRULANMADI" in w for w in gate.warnings)

    def test_windows_must_be_list(self):
        from backtest.regression_gate import check_report_consistency

        report = self._report()
        report["runs"][0]["walk_forward"]["windows"] = "bozuk"
        gate = check_report_consistency(report)
        assert not gate.ok

    def test_total_windows_must_be_int(self):
        from backtest.regression_gate import check_report_consistency

        report = self._report()
        report["runs"][0]["walk_forward"]["total_windows"] = [{"a": 1}]
        gate = check_report_consistency(report)
        assert not gate.ok

    def test_missing_bounds_warns(self):
        from backtest.regression_gate import check_report_consistency

        gate = check_report_consistency(self._report(bounds_interval={}))
        assert any("--bounds" in w for w in gate.warnings)

    def test_missing_optimism_gap_warns(self):
        from backtest.regression_gate import check_report_consistency

        gate = check_report_consistency(self._report(optimism_gap={}))
        assert any("--compare-no-costs" in w for w in gate.warnings)

    def test_thin_measurement_warns(self):
        from backtest.regression_gate import check_report_consistency

        gate = check_report_consistency(
            self._report(cost_quality={"grade": "thin"}),
        )
        assert any("İNCE" in w for w in gate.warnings)

    def test_unmeasured_symbols_warn(self):
        from backtest.regression_gate import check_report_consistency

        costs = CostModel(
            measured_slippage_bps={"okx:Y": 1.0},
            measured_symbols=1, source="measured",
        )
        gate = check_report_consistency(self._report(cost_model=costs.as_dict()))
        assert any("ölçülmedi" in w for w in gate.warnings)

    def test_empty_report_fails(self):
        from backtest.regression_gate import check_report_consistency

        assert not check_report_consistency({}).ok

    def test_no_runs_fails(self):
        from backtest.regression_gate import check_report_consistency

        assert not check_report_consistency({"runs": []}).ok

    def test_shipped_v51_report_is_rejected(self):
        """Paketteki eski v5.1 raporu kapıdan GEÇMEMELİ."""
        from pathlib import Path

        from backtest.regression_gate import check_report_consistency

        path = Path(__file__).resolve().parents[1] / "docs" / "dogrulama_v5.1.json"
        if not path.exists():
            pytest.skip("v5.1 raporu yok")
        report = json.loads(path.read_text(encoding="utf-8"))
        assert not check_report_consistency(report).ok


# =====================================================================
# 5) SÜRÜM TUTARLI PAKETLEME
# =====================================================================

class TestPackageRelease:
    def test_short_version(self):
        from tools.package_release import short_version

        assert short_version("5.2-final") == "5.2"
        assert short_version("5.10-final") == "5.10"
        assert short_version("5.2.1-final") == "5.2.1"

    def test_bad_version_rejected(self):
        from tools.package_release import short_version

        with pytest.raises(ValueError):
            short_version("final")

    def test_previous_short(self):
        from tools.package_release import _previous_short

        assert _previous_short("5.2") == "5.1"
        assert _previous_short("5.0") is None

    def test_excludes_caches_and_data(self, tmp_path):
        import tools.package_release as pr

        root = tmp_path
        (root / "app").mkdir()
        good = root / "app" / "main.py"
        good.write_text("x = 1", encoding="utf-8")
        bad_dir = root / "__pycache__"
        bad_dir.mkdir()
        (bad_dir / "main.pyc").write_text("x", encoding="utf-8")
        data = root / "data" / "validation"
        data.mkdir(parents=True)
        (data / "BTC_5m.csv").write_text("x", encoding="utf-8")
        (root / "bot.log").write_text("x", encoding="utf-8")
        (root / "state.sqlite3").write_text("x", encoding="utf-8")

        original = pr.ROOT
        pr.ROOT = root
        try:
            assert pr._included(good) is True
            assert pr._included(bad_dir / "main.pyc") is False
            assert pr._included(data / "BTC_5m.csv") is False
            assert pr._included(root / "bot.log") is False
            assert pr._included(root / "state.sqlite3") is False
        finally:
            pr.ROOT = original

    def test_consistency_passes_on_shipped_tree(self):
        from pathlib import Path

        from tools.package_release import check_consistency

        root = Path(__file__).resolve().parents[1]
        if not (root / "docs" / "backtest_referans.json").exists():
            pytest.skip("Referans yok: eski yeşil kapı iddiası atlanır; yayın kapısı kırmızı kalır")
        errors, _ = check_consistency()
        assert not errors, errors

    def test_unversioned_changelog_is_rejected(self, tmp_path, monkeypatch):
        import tools.package_release as pr

        (tmp_path / "DEGISIKLIKLER_FINAL.md").write_text("eski", encoding="utf-8")
        monkeypatch.setattr(pr, "ROOT", tmp_path)
        errors, _ = pr.check_consistency()
        assert any("Sürümsüz" in e for e in errors)

    def test_zip_name_derives_from_version(self, tmp_path, monkeypatch):
        import tools.package_release as pr

        root = tmp_path / "src"
        root.mkdir()
        (root / "app").mkdir()
        (root / "app" / "main.py").write_text("x = 1", encoding="utf-8")
        monkeypatch.setattr(pr, "ROOT", root)
        out = tmp_path / "out"
        target, manifest = pr.build(out)
        expected = f"ACARBOT_FINAL_v{pr.short_version(__version__)}.zip"
        assert target.name == expected
        assert manifest["root_dir"] == expected[:-4]
        assert manifest["version"] == __version__
        assert manifest["file_count"] == 1
        assert len(manifest["sha256"]) == 64
        import zipfile

        with zipfile.ZipFile(target) as zf:
            assert all(n.startswith(manifest["root_dir"] + "/") for n in zf.namelist())

    def test_duplicate_changelog_is_rejected(self, tmp_path, monkeypatch):
        import tools.package_release as pr

        short = pr.short_version(__version__)
        prev = pr._previous_short(short)
        body = f"# v{short} degisiklikler\n"
        (tmp_path / f"DEGISIKLIKLER_FINAL_v{short}.md").write_text(body, encoding="utf-8")
        (tmp_path / f"DEGISIKLIKLER_FINAL_v{prev}.md").write_text(body, encoding="utf-8")
        monkeypatch.setattr(pr, "ROOT", tmp_path)
        errors, _ = pr.check_consistency()
        assert any("BİREBİR AYNI" in e for e in errors)

    def test_stale_reference_is_rejected(self, tmp_path, monkeypatch):
        import tools.package_release as pr

        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "backtest_referans.json").write_text(
            json.dumps({"version": "0.0-final"}), encoding="utf-8",
        )
        monkeypatch.setattr(pr, "ROOT", tmp_path)
        errors, _ = pr.check_consistency()
        assert any("Referans bayat" in e for e in errors)

    def test_non_strict_json_is_rejected(self, tmp_path, monkeypatch):
        import tools.package_release as pr

        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "bozuk.json").write_text('{"pf": Infinity}', encoding="utf-8")
        monkeypatch.setattr(pr, "ROOT", tmp_path)
        errors, _ = pr.check_consistency()
        assert any("katı JSON değil" in e for e in errors)

    def test_changelog_index_exists(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        index = root / "DEGISIKLIKLER.md"
        if not index.exists():
            pytest.skip("v6.1 temiz paket: tarihsel değişiklik dizini çıkarıldı")
        text = index.read_text(encoding="utf-8")
        assert "v5.2" in text
        assert "package_release" in text


# ======================================================================
# v5.2 — CANLI OTURUM RAPORU: risk ölçekleme kanıtı
# ======================================================================

class TestLiveRiskScalingReport:
    """Ölçekleyici canlıda 'yazılmış ama etkisiz' kalmasın.

    v5.0'da ajanlar backtest'te etkisizdi. Aynı sınıf hata ölçekleyicide
    de olabilirdi: bütçe hesaplanır, _align_plan_to_grid onu sabit
    tavanla ezer. Bu yüzden 'bütçe üretildi' ile 'bütçe pozisyona
    yansıdı' AYRI ölçülür.
    """

    @staticmethod
    def _executor(
        scaler=None, base: float = 25.0, enabled: bool = True,
    ):
        from types import SimpleNamespace
        return SimpleNamespace(
            risk_scaler=scaler,
            config=SimpleNamespace(
                account=SimpleNamespace(max_loss_per_position=base),
                risk_scaling=SimpleNamespace(enabled=enabled),
            ),
        )

    @staticmethod
    def _opens(*risks: float) -> list[dict]:
        return [
            {"type": "OPEN", "symbol": f"okx:S{i}", "net_risk": r}
            for i, r in enumerate(risks)
        ]

    def test_block_importable(self):
        from app.main import _risk_scaling_block
        assert callable(_risk_scaling_block)

    def test_no_scaler_is_disabled_not_crash(self):
        from app.main import _risk_scaling_block
        out = _risk_scaling_block(self._executor(scaler=None), [])
        assert out["enabled"] is False
        assert out["opened_positions"] == 0

    def test_no_positions_is_unobserved_not_ineffective(self):
        """Hiç işlem açılmadıysa 'etkisiz' DENMEMELİ — gözlenemedi."""
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        out = _risk_scaling_block(self._executor(sc), [])
        assert out["live_effective"] is None
        assert out["opened_positions"] == 0

    def test_budgets_without_position_flagged(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        for _ in range(5):
            sc.budget(25.0, drawdown_pct=1.0, cost_rate=0.001,
                      stop_fraction=0.015)
        out = _risk_scaling_block(self._executor(sc), [])
        assert out["budgets_issued"] == 5
        assert out["budgets_issued_but_no_position"] is True
        assert out["live_effective"] is None

    def test_scaled_down_position_proves_effective(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        out = _risk_scaling_block(self._executor(sc), self._opens(6.25, 25.0))
        assert out["scaled_down_positions"] == 1
        assert out["scaled_up_positions"] == 0
        assert out["live_effective"] is True
        assert out["never_scaled_up"] is True
        assert out["observed_min_net_risk"] == 6.25

    def test_scaled_up_position_is_violation(self):
        """Bütçe aşıldıysa rapor 'etkin' DEMEMELİ, ihlal bildirmeli."""
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        out = _risk_scaling_block(self._executor(sc), self._opens(30.0))
        assert out["scaled_up_positions"] == 1
        assert out["never_scaled_up"] is False
        assert out["live_effective"] is False

    def test_all_at_base_is_inconclusive(self):
        """Ölçek 1.0'da kalmış olabilir → kanıt yok, ihlal de yok."""
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        out = _risk_scaling_block(self._executor(sc), self._opens(25.0, 25.0))
        assert out["scaled_down_positions"] == 0
        assert out["live_effective"] is None
        assert out["never_scaled_up"] is True

    def test_close_events_do_not_count_as_positions(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        trades = [{"type": "CLOSE", "net_risk": 5.0, "pnl": -5.0}]
        out = _risk_scaling_block(self._executor(sc), trades)
        assert out["opened_positions"] == 0

    def test_missing_net_risk_is_skipped(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        trades = [{"type": "OPEN", "symbol": "x"}] + self._opens(10.0)
        out = _risk_scaling_block(self._executor(sc), trades)
        assert out["opened_positions"] == 1

    def test_stats_fields_present(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        sc.budget(25.0, drawdown_pct=9.0, cost_rate=0.001,
                  stop_fraction=0.015)
        out = _risk_scaling_block(self._executor(sc), self._opens(2.5))
        for key in (
            "budgets_issued", "blocked_count", "binding_counts",
            "mean_scale", "min_scale_seen", "min_risk_usdt",
            "base_risk_usdt", "live_effective",
        ):
            assert key in out, key
        assert out["min_risk_usdt"] == 2.5
        assert out["base_risk_usdt"] == 25.0

    def test_blocked_count_surfaces(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        # Sert kapı: pay = cost/(stop+cost) >= 0.60 → cost >= 1.5 x stop
        # 90 bps maliyet / %0.5 stop = 0.0090/0.0140 = %64.3 → RET
        sc.budget(25.0, drawdown_pct=0.0, cost_rate=0.0090,
                  stop_fraction=0.005)
        out = _risk_scaling_block(self._executor(sc), [])
        assert out["blocked_count"] == 1

    def test_soft_cost_zone_scales_but_does_not_block(self):
        """DOGE gerçek ölçümü: 45 bps / %0.5 stop = %47 → yumuşak bölge.

        Bu sınır önemli: sert kapı sanıp işlemi tamamen kesmek, ölçülmüş
        DOGE maliyetini yanlış yorumlamak olur.
        """
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        b = sc.budget(25.0, drawdown_pct=0.0, cost_rate=0.0045,
                      stop_fraction=0.005)
        assert b.blocked is False
        assert 0.0 < b.scale < 1.0
        out = _risk_scaling_block(self._executor(sc), [])
        assert out["blocked_count"] == 0
        assert out["budgets_issued"] == 1

    def test_zero_base_does_not_divide_or_flag(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        out = _risk_scaling_block(
            self._executor(sc, base=0.0), self._opens(25.0),
        )
        assert out["scaled_up_positions"] == 0
        assert out["scaled_down_positions"] == 0

    def test_tolerance_absorbs_grid_rounding(self):
        """Izgara hizalaması kuruş farkı yaratır; bu ihlal sayılmamalı."""
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
        out = _risk_scaling_block(self._executor(sc), self._opens(25.001))
        assert out["scaled_up_positions"] == 0
        assert out["never_scaled_up"] is True

    def test_session_report_contains_risk_scaling(self):
        """Blok gerçekten rapor sözlüğüne bağlı mı (unutulmasın)."""
        import inspect
        from app import main as m
        src = inspect.getsource(m.write_session_report)
        assert '"risk_scaling": _risk_scaling_block(' in src


# ======================================================================
# v5.2 — CANLI/BACKTEST MALİYET EŞİTLİĞİ
# ======================================================================

class TestLiveCostParity:
    """Ölçülmüş maliyet yalnız backtest'te değil, canlıda da kullanılmalı.

    Bulunan sapma: CostModel backtest'e yükleniyordu ama PaperBroker
    config.account'un düz oranlarını (15 bps) kullanıyordu. DOGE'nin
    ölçülen ~45 bps'si canlıda görünmüyordu → canlı backtest'ten
    iyimserdi ve iki yol karşılaştırılamıyordu.
    """

    @staticmethod
    def _model():
        from backtest.costs import ExchangeCosts
        return CostModel(
            by_exchange={"okx": ExchangeCosts()},
            measured_spread_bps={"okx:DOGE-USDT-SWAP": 1.406},
            measured_slippage_bps={"okx:DOGE-USDT-SWAP": 22.823},
            measured_exit_slippage_bps={"okx:DOGE-USDT-SWAP": 25.101},
            source="test",
        )

    def test_round_trip_rate_matches_definition(self):
        m = self._model()
        maker, taker = m.fee_rates("okx:DOGE-USDT-SWAP")
        expected = maker + taker + 22.823 / 10_000 + 25.101 / 10_000
        assert m.round_trip_rate("okx:DOGE-USDT-SWAP") == pytest.approx(expected)

    def test_measured_doge_cost_exceeds_flat_default(self):
        """Sapmanın büyüklüğü: ölçülen DOGE, düz varsayılandan kat kat pahalı."""
        m = self._model()
        flat = 0.0002 + 0.0005 + 0.0005 + 0.0003   # 15 bps
        assert m.round_trip_rate("okx:DOGE-USDT-SWAP") > flat * 3

    def test_disabled_model_is_zero(self):
        from dataclasses import replace as dc_replace
        m = dc_replace(self._model(), enabled=False)
        assert m.round_trip_rate("okx:DOGE-USDT-SWAP") == 0.0

    def test_fee_rates_public(self):
        m = self._model()
        maker, taker = m.fee_rates("okx:BTC-USDT-SWAP")
        assert maker == 0.0002 and taker == 0.0005

    def test_broker_default_unchanged_without_measurement(self):
        from exec.paper import PaperBroker
        b = PaperBroker()
        assert b.cost_of("okx:DOGE-USDT-SWAP", "stop_slippage_rate") == 0.0005

    def test_broker_uses_measured_after_set(self):
        from exec.paper import PaperBroker
        b = PaperBroker()
        b.set_symbol_costs("okx:DOGE-USDT-SWAP", stop_slippage_rate=0.0025101)
        assert b.cost_of("okx:DOGE-USDT-SWAP", "stop_slippage_rate") == 0.0025101
        # ölçülmeyen sembol varsayılanda kalır
        assert b.cost_of("okx:BTC-USDT-SWAP", "stop_slippage_rate") == 0.0005

    def test_broker_partial_override_keeps_other_defaults(self):
        from exec.paper import PaperBroker
        b = PaperBroker()
        b.set_symbol_costs("okx:X", taker_fee_rate=0.0009)
        assert b.cost_of("okx:X", "taker_fee_rate") == 0.0009
        assert b.cost_of("okx:X", "maker_fee_rate") == 0.0002

    def test_broker_rejects_negative_and_nonfinite(self):
        from exec.paper import PaperBroker
        b = PaperBroker()
        for bad in (-0.001, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                b.set_symbol_costs("okx:X", stop_slippage_rate=bad)

    def test_exit_cost_rate_sums_three_components(self):
        from exec.paper import PaperBroker
        b = PaperBroker()
        b.set_symbol_costs(
            "okx:X", taker_fee_rate=0.001,
            stop_slippage_rate=0.002, extra_slippage_rate=0.003,
        )
        assert b.exit_cost_rate("okx:X") == pytest.approx(0.006)
        assert b.exit_cost_rate("okx:X", extra=False) == pytest.approx(0.003)

    def test_provenance_lists_measured_symbols(self):
        from exec.paper import PaperBroker
        b = PaperBroker()
        b.set_symbol_costs("okx:DOGE-USDT-SWAP", stop_slippage_rate=0.0025)
        prov = b.cost_provenance()
        assert prov["measured_count"] == 1
        assert prov["measured_symbols"] == ["okx:DOGE-USDT-SWAP"]
        assert prov["defaults"]["stop_slippage_rate"] == 0.0005

    def test_measured_cost_makes_stop_exit_worse(self):
        """Uçtan uca: aynı stop, ölçülen maliyetle DAHA KÖTÜ net PnL.

        Bu test sapmanın gerçek etkisini ölçer — sadece oran karşılaştırması
        değil, kapanış kaydının pnl'i.
        """
        from core.portfolio import Position
        from exec.paper import PaperBroker

        def _close(slip: float) -> dict:
            b = PaperBroker(initial_balance=1_000.0)
            b.set_symbol_costs("okx:X", stop_slippage_rate=slip)
            b.portfolio.positions["okx:X"] = Position(
                symbol="okx:X", side="LONG", entry=100.0, quantity=10.0,
                initial_quantity=10.0, margin=100.0, stop_loss=99.0,
                opened_at_ms=0,
            )
            return b.close_position_market("okx:X", 99.0, "stop_loss", 1_000)

        cheap = _close(0.0005)        # config varsayılanı: 5 bps
        measured = _close(0.0025101)  # ölçülen DOGE çıkışı: 25,1 bps
        assert cheap["pnl"] > measured["pnl"]
        # 10 adet x 100 USDT x (25,1-5) bps ≈ 2,01 USDT daha kötü
        assert cheap["pnl"] - measured["pnl"] == pytest.approx(2.01, abs=0.05)
        assert measured["slippage"] > cheap["slippage"]

    def test_apply_without_path_labels_assumption(self):
        from types import SimpleNamespace
        from app.main import _apply_measured_costs
        ex = SimpleNamespace(broker=None, tick_sizes={})
        out = _apply_measured_costs(ex, None)
        assert out["loaded"] is False
        assert "VARSAYIM" in out["label"]
        assert ex.cost_model is None

    def test_apply_with_path_binds_broker_and_executor(self, tmp_path):
        from types import SimpleNamespace
        from app.main import _apply_measured_costs
        from exec.paper import PaperBroker
        path = tmp_path / "costs.json"
        self._model().save(path)
        b = PaperBroker()
        ex = SimpleNamespace(
            broker=b, tick_sizes={"okx:DOGE-USDT-SWAP": 0.00001},
        )
        out = _apply_measured_costs(ex, str(path))
        assert out["loaded"] is True
        assert out["applied_symbols"] == 1
        assert ex.cost_model is not None
        assert b.cost_of("okx:DOGE-USDT-SWAP", "stop_slippage_rate") \
            == pytest.approx(25.101 / 10_000)

    def test_cli_has_costs_flag(self):
        from app.main import build_parser
        import sys as _sys
        old = _sys.argv
        _sys.argv = ["prog", "--paper"]
        try:
            ns = build_parser().parse_args(["--paper", "--costs", "x.json"])
            assert ns.costs == "x.json"
        finally:
            _sys.argv = old

    def test_session_report_contains_cost_model(self):
        import inspect
        from app import main as m
        assert '"cost_model": {' in inspect.getsource(m.write_session_report)

    def test_executor_gate_uses_model_when_present(self):
        import inspect
        from app import executor as ex
        src = inspect.getsource(ex.Executor)
        assert "_model.round_trip_rate(symbol)" in src


# ======================================================================
# v5.2 — TERS SEÇİLİM: ölçülür, gizlenmez
# ======================================================================

class TestAdverseSelectionHonesty:
    """15 dk canlı testte bulundu: GNO SHORT, hold_ms=0, −31,37 USDT.

    İlk tepki "dolum anında stop ötesini iptal et" oldu. YANLIŞTI:
    test_adverse_selection_gap_fills_then_stops bu davranışın KASITLI
    olduğunu belgeliyor ("eski kod kaybı gizliyordu"). İptal etmek
    simülatörü iyimser yapar. Doğru çözüm: ÖLÇMEK, varsayılanı
    gerçekçi bırakmak, iptali açıkça İYİMSER diye etiketlemek.
    """

    @staticmethod
    def _broker(cancel: bool = False):
        from dataclasses import replace as dc_replace
        from core.config import SuperConfig
        from exec.paper import PaperBroker
        cfg = SuperConfig()
        cfg.exit = dc_replace(
            cfg.exit, cancel_on_stop_breach_at_fill=cancel,
        )
        return PaperBroker(cfg, 1_000.0)

    @staticmethod
    def _place(b, stop_fraction=0.004):
        from core.risk import RiskManager
        risk = RiskManager(b.config)
        plan = risk.plan(100.0, stop_fraction, "LONG")
        order = b.place_entry("X:TEST", plan, now_ms=0, baseline_per_second=1.0)
        b.bind_plan(order, plan, "fade")
        return order, plan

    def test_default_policy_is_realistic(self):
        from core.config import SuperConfig
        assert SuperConfig().exit.cancel_on_stop_breach_at_fill is False

    def test_beyond_stop_still_fills_by_default(self):
        """Gerçekçi varsayılan: stop ötesi dolum ENGELLENMEZ."""
        b = self._broker(cancel=False)
        _, plan = self._place(b)
        assert plan.stop_loss == pytest.approx(99.6)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        assert "X:TEST" in b.portfolio.positions
        assert b.stale_fill_cancels == 0

    def test_beyond_stop_is_counted(self):
        b = self._broker(cancel=False)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        assert b.adverse_selection_fills == 1

    def test_normal_fill_not_counted_as_adverse(self):
        """Stopun ÜSTÜNDE dolum ters seçilim değildir."""
        b = self._broker(cancel=False)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.90, 10.0, 1_000)
        assert "X:TEST" in b.portfolio.positions
        assert b.adverse_selection_fills == 0

    def test_optimistic_policy_cancels_and_counts(self):
        b = self._broker(cancel=True)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        assert "X:TEST" not in b.portfolio.positions
        assert b.stale_fill_cancels == 1
        assert b.adverse_selection_fills == 1
        reasons = [
            t.get("reason") for t in b.trades
            if t.get("type") == "ORDER_CANCELED"
        ]
        assert "DOLUM_ANI_STOP_IHLALI" in reasons

    def test_optimistic_policy_does_not_block_good_fill(self):
        b = self._broker(cancel=True)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.90, 10.0, 1_000)
        assert "X:TEST" in b.portfolio.positions
        assert b.stale_fill_cancels == 0

    def test_short_side_symmetry(self):
        from core.risk import RiskManager
        b = self._broker(cancel=False)
        risk = RiskManager(b.config)
        plan = risk.plan(100.0, 0.004, "SHORT")
        order = b.place_entry("X:S", plan, now_ms=0, baseline_per_second=1.0)
        b.bind_plan(order, plan, "trend")
        # SHORT stopu yukarıda; fiyat stopun ÜSTÜNDE → ters seçilim
        b.process_entry_tick("X:S", plan.stop_loss + 0.5, 10.0, 1_000)
        assert b.adverse_selection_fills == 1

    def test_partial_fill_not_canceled(self):
        """Kısmen dolmuş emirde pozisyon var; iptal muhasebe bozar."""
        b = self._broker(cancel=True)
        order, plan = self._place(b)
        order.filled_quantity = order.quantity * 0.2
        assert b._stale_fill_blocks(order, plan, 99.0) is False
        assert b.stale_fill_cancels == 0

    def test_zero_stop_is_ignored(self):
        from dataclasses import replace as dc_replace
        b = self._broker(cancel=True)
        order, plan = self._place(b)
        assert b._stale_fill_blocks(
            order, dc_replace(plan, stop_loss=0.0), 99.0,
        ) is False

    def test_nonfinite_price_is_ignored(self):
        b = self._broker(cancel=True)
        order, plan = self._place(b)
        assert b._stale_fill_blocks(order, plan, float("nan")) is False
        assert b._stale_fill_blocks(order, plan, 0.0) is False

    def test_counter_not_double_counted_per_tick(self):
        """Aynı emir ikinci tick'te yeniden sayılmamalı (pozisyon açıldı)."""
        b = self._broker(cancel=False)
        self._place(b)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        b.process_entry_tick("X:TEST", 99.0, 10.0, 2_000)
        assert b.adverse_selection_fills == 1

    def test_session_report_has_adverse_selection(self):
        import inspect
        from app import main as m
        src = inspect.getsource(m.write_session_report)
        assert '"adverse_selection": {' in src
        assert '"born_dead_closes"' in src
        assert '"optimistic_stale_cancel"' in src

    def test_report_policy_labels_optimism(self):
        import inspect
        from app import main as m
        src = inspect.getsource(m.write_session_report)
        assert "İYİMSER" in src and "GERÇEKÇİ" in src


# ======================================================================
# v5.2 — KAPI ATIF ANALİZİ: "bu kapı bizi kârdan etti mi?"
# ======================================================================

def _wave_closes(n: int = 400, base: float = 100.0) -> list[float]:
    """Sinyal üretecek kadar hareketli, deterministik seri."""
    import math
    return [
        base * (1.0 + 0.02 * math.sin(i / 7.0) + 0.006 * math.sin(i / 2.3))
        for i in range(n)
    ]


class TestGateAttribution:
    """Reddedilen adayların karşı-olgusal ölçümü.

    Kullanıcı sorusu: maliyet kapısı / hacim kapısı / dolmayan emir
    bizi kârdan mı etti? Cevap ölçümle verilmeli, varsayımla değil.
    """

    def test_probe_default_off(self):
        """Üretim davranışı değişmemeli."""
        from backtest.engine import BacktestEngine
        assert BacktestEngine().gate_probe is None

    def test_probe_records_only_formed_signals(self):
        """Sinyali oluşmayan bar kaydedilmemeli (yön yok)."""
        from backtest.engine import BacktestEngine
        from tests.helpers import make_candles
        eng = BacktestEngine()
        eng.gate_probe = []
        eng.run({"okx:TEST": make_candles(_wave_closes(300))})
        for rec in eng.gate_probe:
            assert rec["side"] in ("LONG", "SHORT")
            assert 0 < rec["stop_fraction"] < 1
            assert rec["reason"] is not None

    def test_probe_reason_is_labelled(self):
        from backtest.engine import BacktestEngine
        from tests.helpers import make_candles
        eng = BacktestEngine()
        eng.gate_probe = []
        eng.run({"okx:TEST": make_candles(_wave_closes(400))})
        assert all(r["reason"] for r in eng.gate_probe)

    def test_probe_does_not_change_result(self):
        """İzleme açık/kapalı AYNI sonucu vermeli (yan etki yok)."""
        from backtest.engine import BacktestEngine
        from tests.helpers import make_candles
        data = {"okx:TEST": make_candles(_wave_closes(400))}
        a = BacktestEngine().run(data)
        eng = BacktestEngine()
        eng.gate_probe = []
        b = eng.run(data)
        assert a.net_pnl == b.net_pnl
        assert a.trade_count == b.trade_count

    def test_simulate_candidate_returns_pnl(self):
        from tools.gate_attribution import _simulate_candidate
        from tools.validate_strategy import _profile_config
        from tests.helpers import make_candles
        cfg = _profile_config("apex", None)
        fwd = make_candles(_wave_closes(60))
        cand = {
            "symbol": "okx:TEST", "ts_ms": fwd[0].timestamp - 300_000,
            "side": "LONG", "entry_ref": 100.0,
            "stop_fraction": 0.015, "motor": "trend",
        }
        out = _simulate_candidate(cand, fwd, cfg, None, 25.0)
        assert out is not None
        assert "net_pnl" in out and "outcome" in out

    def test_simulate_rejects_invalid_input(self):
        from tools.gate_attribution import _simulate_candidate
        from tools.validate_strategy import _profile_config
        from tests.helpers import make_candles
        cfg = _profile_config("apex", None)
        fwd = make_candles(_wave_closes(10))
        base = {"symbol": "okx:T", "ts_ms": 0, "side": "LONG",
                "entry_ref": 100.0, "stop_fraction": 0.015}
        assert _simulate_candidate({**base, "entry_ref": 0.0}, fwd, cfg, None, 25.0) is None
        assert _simulate_candidate({**base, "stop_fraction": 0.0}, fwd, cfg, None, 25.0) is None
        assert _simulate_candidate(base, [], cfg, None, 25.0) is None

    def test_agg_labels_saving_gate(self):
        from tools.gate_attribution import _agg
        rows = [{"sim": {"net_pnl": -10.0, "outcome": "stop_loss"}},
                {"sim": {"net_pnl": -5.0, "outcome": "stop_loss"}},
                {"sim": {"net_pnl": 3.0, "outcome": "trailing_stop"}}]
        out = _agg(rows)
        assert out["hipotetik_net_usdt"] == -12.0
        assert out["hukum"] == "KAPI BIZI ZARARDAN KURTARDI"
        assert out["kazanan"] == 1 and out["kaybeden"] == 2

    def test_agg_labels_costly_gate(self):
        from tools.gate_attribution import _agg
        rows = [{"sim": {"net_pnl": 20.0, "outcome": "trailing_stop"}},
                {"sim": {"net_pnl": -5.0, "outcome": "stop_loss"}}]
        out = _agg(rows)
        assert out["hipotetik_net_usdt"] == 15.0
        assert out["hukum"] == "KAPI BIZI KÂRDAN ETTI"

    def test_agg_excludes_unfilled(self):
        from tools.gate_attribution import _agg
        rows = [{"sim": {"net_pnl": 0.0, "outcome": "DOLMADI"}},
                {"sim": {"net_pnl": -5.0, "outcome": "stop_loss"}}]
        out = _agg(rows)
        assert out["simule_edilen"] == 1
        assert out["dolmayan"] == 1
        assert out["hipotetik_net_usdt"] == -5.0

    def test_agg_empty_is_safe(self):
        from tools.gate_attribution import _agg
        out = _agg([])
        assert out["aday"] == 0
        assert out["hukum"] == "ETKISIZ"

    def test_fill_price_is_limit_not_tick(self):
        """Karşı-olgusal simülasyon girişte AVANTAJ sağlamamalı.

        Tetik fiyatı limitin ötesine itiliyor; dolum LİMİTTEN olmalı.
        Aksi hâlde 'kapı bizi kârdan etti' sonucu yapay olarak şişer.
        """
        from core.config import SuperConfig
        from core.risk import RiskManager
        from exec.paper import PaperBroker
        cfg = SuperConfig()
        b = PaperBroker(cfg, 1_000.0)
        plan = RiskManager(cfg).plan(100.0, 0.015, "LONG", motor="trend")
        order = b.place_entry("X:T", plan, now_ms=0, baseline_per_second=1e12)
        b.bind_plan(order, plan, "trend")
        aligned = b._plan_for_order[order.id]
        b.process_entry_tick("X:T", aligned.entry * 0.999, 1e12, 1_000)
        pos = b.portfolio.positions["X:T"]
        assert pos.entry == order.limit_price

    def test_ablation_variants_are_single_variable(self):
        """Her varyant TEMEL'den yalnız ilgili alanda ayrılmalı."""
        from tools.ablate_gates import _variants
        from tools.validate_strategy import _profile_config
        base = _profile_config("apex", None)
        names = [n for n, _, _ in _variants(base)]
        assert names[0] == "TEMEL"
        assert len(set(names)) == len(names)
        for name, _, cfg in _variants(base):
            if name == "TEMEL":
                assert cfg == base

    def test_ablation_includes_all_three_user_questions(self):
        from tools.ablate_gates import _variants
        from tools.validate_strategy import _profile_config
        names = {n for n, _, _ in _variants(_profile_config("apex", None))}
        assert any("MALIYET" in n for n in names)
        assert any("HACIM" in n for n in names)
        assert any("MAKER" in n for n in names)
        assert any(n.startswith("RR_") for n in names)


class TestShadowStopAwareness:
    """Gölge izleyici artık stop-farkındalıklı.

    Eski ölçüm "ufuklardan en iyi getiri > 0 ise kazanırdı" diyordu.
    Bu YANLIŞ: fiyat önce stopu vurup sonra dönebilir. Gerçek soru
    "stop önce mi, hedef önce mi?"
    """

    @staticmethod
    def _tracker():
        from core.gates import ShadowSignalTracker
        return ShadowSignalTracker()

    def test_stop_first_then_recovery_is_still_a_loss(self):
        """Kritik vaka: fiyat stopu vurup SONRA yükseliyor.

        Eski ölçüm bunu 'kazanırdı' sayıyordu. Gerçekte işlem stopla
        kapanırdı ve sonraki yükseliş bizi ilgilendirmez.
        """
        t = self._tracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "LONG", "MALIYET_BUTCESI_ASIMI",
                               100.0, 0.01, base)
        t.on_price("X:A", 98.0, base + 60_000)      # stop (−%2 < −%1)
        t.on_price("X:A", 110.0, base + 121 * 60_000)  # sonra +%10
        assert rec.first_exit == "STOP"
        s = t.summary()["by_reason"]["MALIYET_BUTCESI_ASIMI"]
        assert s["once_stop"] == 1
        assert s["once_hedef"] == 0

    def test_target_first_is_recorded(self):
        t = self._tracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "LONG", "COST", 100.0, 0.01, base)
        t.on_price("X:A", 101.5, base + 60_000)
        assert rec.first_exit == "HEDEF"

    def test_short_side_stop_direction(self):
        t = self._tracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "SHORT", "COST", 100.0, 0.01, base)
        t.on_price("X:A", 102.0, base + 60_000)     # SHORT için aleyhte
        assert rec.first_exit == "STOP"

    def test_first_exit_never_flips(self):
        t = self._tracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "LONG", "COST", 100.0, 0.01, base)
        t.on_price("X:A", 98.0, base + 60_000)
        t.on_price("X:A", 105.0, base + 120_000)
        assert rec.first_exit == "STOP"

    def test_mfe_mae_tracked(self):
        t = self._tracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "LONG", "COST", 100.0, 0.05, base)
        t.on_price("X:A", 103.0, base + 60_000)
        t.on_price("X:A", 97.0, base + 120_000)
        assert rec.mfe_pct == pytest.approx(3.0)
        assert rec.mae_pct == pytest.approx(-3.0)

    def test_zero_stop_fraction_leaves_exit_undecided(self):
        t = self._tracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "LONG", "COST", 100.0, 0.0, base)
        t.on_price("X:A", 90.0, base + 60_000)
        assert rec.first_exit is None

    def test_cost_gate_rejection_is_shadow_recorded(self):
        """Maliyet kapısı reddi artık karşı-olgusal izleniyor."""
        import inspect
        from app.executor import Executor
        src = inspect.getsource(Executor)
        idx = src.index("if budget.blocked:")
        block = src[idx:idx + 900]
        assert "_record_shadow" in block

    def test_summary_has_no_optimistic_best_horizon(self):
        t = self._tracker()
        base = 1_700_000_000_000
        t.record_blocked("X:A", "LONG", "COST", 100.0, 0.01, base)
        t.on_price("X:A", 100.5, base + 121 * 60_000)
        s = t.summary()["by_reason"]["COST"]
        assert "avg_best_return_pct" not in s
        assert "ort_son_getiri_pct" in s


class TestShadowShortHorizons:
    """v5.3: 15 dk oturumda gölge verisi üretilebilmeli."""

    def test_short_horizons_present(self):
        from core.gates import ShadowSignalTracker
        t = ShadowSignalTracker()
        assert 1 in t.horizons and 5 in t.horizons and 15 in t.horizons

    def test_one_minute_horizon_matures_in_short_session(self):
        from core.gates import ShadowSignalTracker
        t = ShadowSignalTracker()
        base = 1_700_000_000_000
        rec = t.record_blocked("X:A", "LONG", "MALIYET_BUTCESI_ASIMI",
                               100.0, 0.01, base)
        t.on_price("X:A", 100.5, base + 61_000)
        assert "1" in rec.returns
        s = t.summary()["by_reason"]["MALIYET_BUTCESI_ASIMI"]
        assert s["olgunlasan_ufuk_dakika"] == 1
        assert s["ort_son_getiri_pct"] == pytest.approx(0.5)

    def test_summary_uses_longest_available_not_fixed_120(self):
        from core.gates import ShadowSignalTracker
        t = ShadowSignalTracker()
        base = 1_700_000_000_000
        t.record_blocked("X:A", "LONG", "COST", 100.0, 0.05, base)
        t.on_price("X:A", 101.0, base + 61_000)       # 1 dk
        t.on_price("X:A", 102.0, base + 301_000)      # 5 dk
        s = t.summary()["by_reason"]["COST"]
        assert s["olgunlasan_ufuk_dakika"] == 5
        assert s["ort_son_getiri_pct"] == pytest.approx(2.0)

    def test_no_data_is_safe(self):
        from core.gates import ShadowSignalTracker
        t = ShadowSignalTracker()
        t.record_blocked("X:A", "LONG", "COST", 100.0, 0.01, 0)
        s = t.summary()["by_reason"]["COST"]
        assert s["olgunlasan_ufuk_dakika"] == 0
        assert s["ort_son_getiri_pct"] == 0.0


# =====================================================================
# v5.4 — TTL DÜRÜSTLÜĞÜ: 45 sn 5m mumda çözülemez
# =====================================================================

class TestTTLHonesty:
    def test_ttl_reads_live_config_single_source(self):
        """TTL canlı config'ten okunur; sabit 300000 DEĞİL."""
        from dataclasses import replace as dreplace

        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        cfg = apex_config()
        cfg = dreplace(cfg, exit=dreplace(cfg.exit, order_ttl_seconds=45.0))
        engine = BacktestEngine(cfg, initial_balance=1_000.0)
        assert engine._limit_ttl_ms() == 45_000

    def test_legacy_mode_restores_bar_window(self):
        """legacy_bar opt-in'i eski pencereyi TAM olarak geri verir."""
        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        engine.ttl_model = "legacy_bar"
        assert engine._limit_ttl_ms() == engine.base_config.data.timeframe_ms

    def test_default_model_is_honest(self):
        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        assert engine.ttl_model == "fine_window"

    def test_unresolved_ttl_does_not_fill(self):
        """İnce veri yoksa 45 sn çözülemez → dolum YOK (muhafazakâr)."""
        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from infra.market_data.models import Candle
        from tests.helpers import apex_config

        setup = _fade_setup_candles_v54("TESTUSDT")
        touch = Candle(
            timestamp=setup[-1].timestamp + 300_000,
            open=98.0, high=98.1, low=97.85, close=97.95, volume=500.0,
        )
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        result = engine.run(
            {"TESTUSDT": setup + [touch]}, cost_model=CostModel.disabled(),
        )
        assert result.fill_optimism["ttl_model"] == "fine_window"
        assert not [t for t in result.trades if t["type"] == "ORDER_FILL"], (
            "1m yolu olmadan 45 sn çözülemez; dolum olmamalı"
        )

    def test_one_minute_path_allows_fill_within_window(self):
        """1m alt yol varsa TTL penceresindeki dokunuş dolar."""
        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from infra.market_data.models import Candle
        from tests.helpers import apex_config

        setup = _fade_setup_candles_v54("TESTUSDT")
        base_ts = setup[-1].timestamp + 300_000
        # IntrabarPath kovaları 5m IZGARASINA göre kurar; setup damgaları
        # hizalı değil. İnce mumlar kovaya göre üretilmeli.
        bucket = base_ts - (base_ts % 300_000)
        fine = [
            Candle(
                timestamp=bucket + i * 60_000,
                open=98.0, high=98.1,
                # TTL penceresine düşen alt mumda limana dokunuluyor
                low=(
                    97.85
                    if (bucket + i * 60_000) < base_ts + 45_000
                    and (bucket + (i + 1) * 60_000) > base_ts
                    else 97.95
                ),
                close=97.95, volume=100.0,
            )
            for i in range(5)
        ]
        coarse = Candle(
            timestamp=base_ts, open=98.0, high=98.1, low=97.85,
            close=97.95, volume=500.0,
        )
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        result = engine.run(
            {"TESTUSDT": setup + [coarse]},
            cost_model=CostModel.disabled(),
            fine_candles_by_symbol={"TESTUSDT": fine},
        )
        assert result.fill_optimism["ttl_1m_cozulen_aday"] >= 1
        assert [t for t in result.trades if t["type"] == "ORDER_FILL"]

    def test_fill_optimism_reports_resolution(self):
        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        result = engine.run(
            {"TESTUSDT": _fade_setup_candles_v54("TESTUSDT")},
            cost_model=CostModel.disabled(),
        )
        fo = result.fill_optimism
        assert fo["ttl_ms"] == 45_000
        assert "ttl_cozunurluk" in fo
        assert "cozulmez" in fo["ttl_cozunurluk"] or "1m" in fo["ttl_cozunurluk"]


def _fade_setup_candles_v54(symbol: str):
    """v5.4 TTL testleri için fade kurulumu (test_backtest ile aynı desen)."""
    from tests.test_backtest import _fade_setup_candles

    return _fade_setup_candles(symbol)


# =====================================================================
# v5.4 — GÖLGE: n<30 yön iddiası yasak
# =====================================================================

class TestShadowSampleGuard:
    def test_small_sample_forbids_directional_claim(self):
        from core.gates import MIN_DIRECTIONAL_N, ShadowSignalTracker

        tracker = ShadowSignalTracker()
        summary = tracker.summary()
        assert summary["min_yon_orneklemi"] == MIN_DIRECTIONAL_N

    def test_guard_fields_present_per_reason(self):
        from core.gates import ShadowSignalTracker

        tracker = ShadowSignalTracker()
        tracker.record_blocked(
            symbol="okx:X-USDT-SWAP", side="LONG",
            reason="MALIYET_BUTCESI_ASIMI", entry_ref=100.0,
            stop_fraction=0.01, ts_ms=1_699_999_800_000,
        )
        tracker.on_price("okx:X-USDT-SWAP", 98.5, 1_699_999_800_000 + 60_000)
        out = tracker.summary()["by_reason"]["MALIYET_BUTCESI_ASIMI"]
        assert out["yön_iddiasi_gecerli"] is False
        assert "YASAK" in out["yön_notu"]


# =====================================================================
# v5.4 — GİRİŞ KENARI TESTİ: kapısız, simetrik, permütasyon
# =====================================================================

class TestEntryEdgeTool:
    def _c(self, ts, high, low, close):
        from infra.market_data.models import Candle

        return Candle(
            timestamp=ts, open=close, high=high, low=low,
            close=close, volume=10.0,
        )

    def test_symmetric_target_hit(self):
        from tools.entry_edge import symmetric_path

        fwd = [self._c(1, 102.0, 99.5, 101.5)]
        out = symmetric_path("LONG", 100.0, 1.0, fwd, 10)
        assert out["kotumser"]["r"] == 1.0
        assert out["kotumser"]["exit"] == "target"

    def test_symmetric_stop_hit(self):
        from tools.entry_edge import symmetric_path

        fwd = [self._c(1, 100.5, 98.0, 99.0)]
        out = symmetric_path("LONG", 100.0, 1.0, fwd, 10)
        assert out["kotumser"]["r"] == -1.0
        assert out["kotumser"]["exit"] == "stop"

    def test_ambiguous_bar_gives_two_bounds(self):
        """Aynı mumda hem stop hem hedef: sıra BİLİNMEZ, iki sınır."""
        from tools.entry_edge import symmetric_path

        fwd = [self._c(1, 102.0, 98.0, 100.0)]
        out = symmetric_path("LONG", 100.0, 1.0, fwd, 10)
        assert out["ambiguous"] is True
        assert out["kotumser"]["r"] == -1.0
        assert out["iyimser"]["r"] == 1.0

    def test_short_side_is_mirrored(self):
        from tools.entry_edge import symmetric_path

        fwd = [self._c(1, 100.5, 98.0, 99.0)]
        out = symmetric_path("SHORT", 100.0, 1.0, fwd, 10)
        assert out["kotumser"]["r"] == 1.0

    def test_horizon_exit_when_neither_touched(self):
        from tools.entry_edge import symmetric_path

        fwd = [self._c(i, 100.4, 99.6, 100.2) for i in range(1, 4)]
        out = symmetric_path("LONG", 100.0, 1.0, fwd, 3)
        assert out["kotumser"]["exit"] == "horizon"
        assert out["kotumser"]["r"] == pytest.approx(0.2)

    def test_horizon_at_matches_reference(self):
        import numpy as np

        from tools.entry_edge import horizon_at, horizon_return

        fwd = [
            self._c(i, 100.0 + i + 0.5, 99.5, 100.0 + i)
            for i in range(1, 6)
        ]
        closes = np.asarray([100.0] + [c.close for c in fwd])
        ref = horizon_return("LONG", 100.0, 1.0, fwd, 3)
        got = horizon_at(closes, 0, 1.0, 0.01, 3)
        assert got == pytest.approx(ref)

    def test_mean_se_confidence_interval(self):
        from tools.entry_edge import mean_se

        st = mean_se([1.0, -1.0, 1.0, -1.0])
        assert st["n"] == 4
        assert st["mean"] == 0.0
        assert st["ci_low"] < 0 < st["ci_high"]

    def test_permutation_p_value_high_when_null_beats(self):
        from tools.entry_edge import permutation_test

        out = permutation_test(0.0, [1.0, 2.0, 3.0])
        assert out["p"] == pytest.approx(1.0)

    def test_permutation_p_value_low_when_observed_wins(self):
        from tools.entry_edge import permutation_test

        # p = (better+1)/(n+1): 3 permütasyonda en küçük p 0.25'tir.
        # Anlamlılık için yeterli permütasyon sayısı gerekir.
        out = permutation_test(10.0, [0.0, 0.1, -0.1] * 40)
        assert out["n_perm"] == 120
        assert out["p"] < 0.05

    def test_empty_inputs_are_safe(self):
        from tools.entry_edge import mean_se, permutation_test, symmetric_path

        assert mean_se([])["n"] == 0
        assert permutation_test(0.0, [])["p"] is None
        assert symmetric_path("LONG", 100.0, 0.0, [], 5) is None


# =====================================================================
# v5.4 — HEDEFLİ 1m KİLİTLENMESİ: aday pencereleri
# =====================================================================

class TestCandidateWindows:
    def test_candidate_windows_cover_entry_bar(self):
        from tools.validate_strategy import candidate_windows

        probe = [{"symbol": "okx:X-USDT-SWAP", "ts_ms": 1_700_000_100_000}]
        spans = candidate_windows(probe)
        assert "okx:X-USDT-SWAP" in spans
        lo, hi = spans["okx:X-USDT-SWAP"][0]
        assert lo % 300_000 == 0
        assert hi - lo == 2 * 300_000

    def test_empty_probe_is_safe(self):
        from tools.validate_strategy import candidate_windows

        assert candidate_windows(None) == {}
        assert candidate_windows([]) == {}

    def test_invalid_rows_skipped(self):
        from tools.validate_strategy import candidate_windows

        probe = [
            {"symbol": "", "ts_ms": 1_700_000_000_000},
            {"symbol": "okx:X-USDT-SWAP", "ts_ms": 0},
            {"symbol": "okx:Y-USDT-SWAP", "ts_ms": 1_700_000_000_000},
        ]
        spans = candidate_windows(probe)
        assert list(spans) == ["okx:Y-USDT-SWAP"]

    def test_result_carries_probe_field(self):
        """BacktestResult aday evrenini taşımalı (indirme bunu kullanır)."""
        import dataclasses

        from backtest.engine import BacktestResult

        names = {f.name for f in dataclasses.fields(BacktestResult)}
        assert "gate_probe" in names

    def test_no_deadlock_when_zero_trades(self):
        """İşlem 0 olsa bile adaylar hedeflenir → 1m indirmesi tetiklenir.

        v5.4'te bulunan kilitlenme: dürüst TTL 1m ister, indirici yalnız
        işlem olan yere 1m çekerdi → 1m yok → dolum yok → işlem yok.
        """
        from tools.validate_strategy import candidate_windows, trade_windows

        trades = []
        probe = [{"symbol": "okx:X-USDT-SWAP", "ts_ms": 1_700_000_000_000}]
        assert trade_windows(trades) == {}
        assert candidate_windows(probe), "aday pencereleri boş olmamalı"


# =====================================================================
# v5.4 — GECİKME ÖLÇEĞİ: kaba bar farkı 0 iken dolum bloklanmamalı
# =====================================================================

class TestLatencyScaleMismatch:
    """v5.4'te bulunan ve düzeltilen hata.

    created_ms mum KAPANIŞINA alınınca kaba bar farkı tam 0 olur.
    Eski gecikme karşılaştırması `0 < 350ms` → True → HER dolum
    bloklanıyordu; sonuç 0 işlem. Gecikme alt mum ölçeğinde uygulanmalı.
    """

    def _setup(self):
        from infra.market_data.models import Candle
        from tests.test_backtest import _fade_setup_candles

        setup = _fade_setup_candles("TESTUSDT")
        base_ts = setup[-1].timestamp + 300_000
        bucket = base_ts - (base_ts % 300_000)
        fine = [
            Candle(
                timestamp=bucket + i * 60_000, open=98.0, high=98.1,
                low=(
                    97.85
                    if (bucket + i * 60_000) < base_ts + 45_000
                    and (bucket + (i + 1) * 60_000) > base_ts
                    else 97.95
                ),
                close=97.95, volume=100.0,
            )
            for i in range(5)
        ]
        coarse = Candle(
            timestamp=base_ts, open=98.0, high=98.1, low=97.85,
            close=97.95, volume=500.0,
        )
        return setup, coarse, fine

    def test_sub_bar_latency_does_not_block_everything(self):
        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        setup, coarse, fine = self._setup()
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        result = engine.run(
            {"TESTUSDT": setup + [coarse]},
            cost_model=CostModel(),  # gecikme 350ms > 0
            fine_candles_by_symbol={"TESTUSDT": fine},
        )
        assert result.fill_optimism["ttl_1m_cozulen_aday"] >= 1
        assert [t for t in result.trades if t["type"] == "ORDER_FILL"], (
            "350ms gecikme 60s alt mumu bütünüyle bloklamamalı"
        )

    def test_latency_larger_than_step_still_blocks(self):
        """Gecikme alt mum aralığından BÜYÜKSE blok geçerli kalmalı."""
        from dataclasses import replace as dreplace

        from backtest.costs import CostModel
        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        setup, coarse, fine = self._setup()
        cfg = apex_config()
        cfg = dreplace(
            cfg, data=dreplace(cfg.data, bt_latency_ms=600_000),
        )
        engine = BacktestEngine(cfg, initial_balance=1_000.0)
        result = engine.run(
            {"TESTUSDT": setup + [coarse]},
            cost_model=CostModel.disabled(),
            fine_candles_by_symbol={"TESTUSDT": fine},
        )
        assert not [t for t in result.trades if t["type"] == "ORDER_FILL"]


# =====================================================================
# v5.4 — SINIR ARALIĞI: ölçüm yokluğu "sıfır sonuç" DEĞİLDİR
# =====================================================================

class TestBoundsUncomputable:
    def test_uncomputable_bounds_flagged_not_zero(self):
        """Dürüst TTL sentetik yolda çözemez → sınır HESAPLANAMAZ.

        İki sınırın da 0 işlem vermesi 'aralık sıfırı kapsıyor' diye
        raporlanmamalı; bu bir sonuç değil ölçüm yokluğudur.
        """
        import copy
        import json
        from pathlib import Path

        from backtest.regression_gate import check_report_consistency

        root = Path(__file__).resolve().parents[1]
        path = root / "docs" / "dogrulama_v5.4.json"
        if not path.exists():
            pytest.skip("v5.4 doğrulama raporu yok")
        report = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
        report["bounds_interval"] = {
            "hesaplanabilir": False,
            "adverse_trades": 0, "favorable_trades": 0,
            "spans_zero": None,
        }
        res = check_report_consistency(report)
        text = " ".join(res.warnings)
        assert "HESAPLANAMADI" in text
        assert "sıfırı kapsıyor" not in text

    def test_computable_bounds_still_report_span(self):
        import copy
        import json
        from pathlib import Path

        from backtest.regression_gate import check_report_consistency

        root = Path(__file__).resolve().parents[1]
        path = root / "docs" / "dogrulama_v5.4.json"
        if not path.exists():
            pytest.skip("v5.4 doğrulama raporu yok")
        report = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
        report["bounds_interval"] = {
            "hesaplanabilir": True,
            "adverse_net_pnl": -5.0, "favorable_net_pnl": 5.0,
            "adverse_trades": 3, "favorable_trades": 3,
            "spans_zero": True,
        }
        res = check_report_consistency(report)
        assert "sıfırı kapsıyor" in " ".join(res.warnings)
