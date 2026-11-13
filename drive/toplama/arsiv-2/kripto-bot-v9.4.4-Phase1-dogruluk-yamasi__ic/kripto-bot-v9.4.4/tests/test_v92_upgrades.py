"""Kripto Bot v9.2 — Denetim Bulguları, Gerçekçi Maker Kuyruğu, 10-Ajan Çapraz Teftiş,
Akım-Takip Çıkışı, Brüt/Net Edge Ayrımı ve Operasyonel Kurtarma Test Paketi."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pytest

from backtests.ablation import run_ablation
from backtests.engine_interface import BacktestConfig
from backtests.stress import DEFAULT_SCENARIOS, run_execution_stress
from backtests.walk_forward import run_walk_forward
from src.circuit_breaker import CircuitBreaker
from src.config import (
    CANONICAL_CONFIG_PATH,
    ConfigError,
    IMMUTABLE_HARD_CAPS,
    enforce_hard_risk_caps,
    load_config,
)
from src.counterfactual import CounterfactualTracker
from src.edge_analytics import compute_edge_separation_report
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.flow_exit_manager import FlowTrendExitManager
from src.maker_queue_sim import RealisticMakerQueueSimulator
from src.risk import RiskManager, position_limits_for_mode
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.ten_agent_debate import TenAgentMutualAuditCouncil
from src.unified_engine import UnifiedTradingEngine, check_funding_settlement_proximity
from strategies.v92_flow_strategy import V92CanonicalFlowStrategy


class _SilentAlerter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, msg: str, **_kw) -> bool:
        self.messages.append(msg)
        return True

    def __call__(self, msg: str):
        return self.send(msg)


def _trend_ohlcv(n: int = 200, start: float = 100.0, drift: float = 0.28) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    px = start
    ts0 = 1_760_000_000_000
    for i in range(n):
        nxt = max(1.0, px + drift + float(rng.normal(0.0, 0.08)))
        hi = max(px, nxt) + 0.18
        lo = min(px, nxt) - 0.15
        vol = 180_000.0 + i * 2_500.0
        rows.append([ts0 + i * 300_000, px, hi, lo, nxt, vol])
        px = nxt
    return pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])


def test_canonical_v92_vault_sizing_stop_and_cross_unlimited():
    """$1,000 kasa, $50×10x=$500 büyüklük, -$40 (%80 marj = %8.0 fiyat) stop, Cross ve sınırsız işlem."""
    cfg = load_config(CANONICAL_CONFIG_PATH)
    assert cfg["version"] == "9.4.4"
    assert float(cfg["paper"]["bakiye"]) == 1000.0
    assert cfg["risk"]["marj_modu"] == "cross"
    assert cfg["boyutlandirma"]["mod"] == "sabit_usdt"
    assert float(cfg["boyutlandirma"]["sabit_marj_usdt"]) == 50.0
    assert int(cfg["boyutlandirma"]["kaldirac"]) == 10
    assert cfg["islem_plani"]["aktif"] is False

    limits = position_limits_for_mode(cfg["risk"], "paper")
    assert limits["max_positions"] >= 1000

    sizer = PositionSizer(
        base_risk_pct=4.0,
        atr_mult=1.25,
        kelly_on=False,
        kelly_fraction=0.5,
        kelly_min_risk=0.25,
        kelly_max_risk=1.5,
        kelly_min_trades=20,
        stats_path="/tmp/v92_test_kelly.json",
        mode="sabit_usdt",
        capital_pct=5.0,
        leverage=10,
        fixed_margin_usdt=50.0,
    )
    risk = RiskManager(
        stop_loss_pct=8.0,
        stop_model="marj",
        margin_stop_fraction=0.80,
        margin_stop_liq_buffer=0.85,
        lock_trigger_pct=2.5,
        lock_level_pct=1.2,
        trail_pct=1.5,
        risk_per_trade_pct=4.0,
        max_positions=1000,
        daily_max_loss_pct=20.0,
        capital_pct_per_entry=5.0,
        leverage=10,
        margin_mode="cross",
        cross_max_margin_pct=98.0,
        cross_min_free_usdt=0.0,
        max_total_margin_pct=98.0,
    )
    entry_px = 100.0
    stop_long = risk.initial_stop("LONG", entry_px, leverage=10)
    stop_short = risk.initial_stop("SHORT", entry_px, leverage=10)
    assert pytest.approx(stop_long, rel=1e-4) == 92.0  # -$40 zarar / $500 notional = -%8.0
    assert pytest.approx(stop_short, rel=1e-4) == 108.0

    qty, info = sizer.size(1000.0, entry_px, stop_long)
    assert pytest.approx(qty) == 5.0  # 5 * $100 = $500 notional ($50 marj × 10x)
    assert pytest.approx(info["margin_usdt"]) == 50.0
    assert pytest.approx(info["notional"]) == 500.0
    assert pytest.approx((entry_px - stop_long) * qty) == 40.0  # Tam $40 stop zararı!


def test_immutable_enforce_hard_risk_caps_cannot_be_bypassed_by_json():
    """JSON içindeki sert_risk_tavanlari yükseltilse dahi IMMUTABLE_HARD_CAPS aşımına izin vermez."""
    cfg = load_config(CANONICAL_CONFIG_PATH)
    assert IMMUTABLE_HARD_CAPS["max_leverage"] == 10

    tampered = copy.deepcopy(cfg)
    tampered["sert_risk_tavanlari"]["maksimum_kaldirac_tavani"] = 50
    tampered["genel"]["kaldıraç"] = 25
    with pytest.raises(ConfigError, match="sabitlenmiş tavanı"):
        enforce_hard_risk_caps(tampered)

    tampered_stop = copy.deepcopy(cfg)
    tampered_stop["sert_risk_tavanlari"]["maks_marj_zarar_orani"] = 0.99
    tampered_stop["risk"]["marj_zarar_orani"] = 0.92
    with pytest.raises(ConfigError, match="marj_zarar_orani"):
        enforce_hard_risk_caps(tampered_stop)


def test_realistic_maker_queue_simulator_expiry_and_trade_through_fill():
    """Pasif maker emir sabit tahtada ASLA dolmaz; yalnız fiyat katedince veya kuyruk tükenince dolar."""

    async def _run():
        sim = RealisticMakerQueueSimulator()
        # 1) Sabit tahta -> zaman aşımıyla iptal (expired_unfilled) ve kaçan fiyat (adverse selection) kaydı
        o_exp = sim.register_order(
            exchange="binance",
            symbol="SOL/USDT",
            side="buy",
            qty=2.0,
            bid=150.00,
            ask=150.05,
            timeout_sec=0.06,
            minute_qv_usdt=60_000.0,
        )
        res_exp = await sim.await_fill_or_expire(o_exp, current_mid_fn=lambda: 150.35)
        assert res_exp.status == "expired_unfilled"
        assert res_exp.filled_qty == 0.0

        # 2) Satıcı agresif emri bid seviyesini deldiğinde -> gerçek pasif maker dolumu
        o_fill = sim.register_order(
            exchange="binance",
            symbol="SOL/USDT",
            side="buy",
            qty=2.0,
            bid=150.00,
            ask=150.05,
            timeout_sec=1.0,
            minute_qv_usdt=30_000.0,
        )

        async def _feed_cross():
            await asyncio.sleep(0.02)
            sim.on_trade("binance", "SOL/USDT", price=149.98, qty=0.5, is_buyer_maker=True)

        asyncio.create_task(_feed_cross())
        res_fill = await sim.await_fill_or_expire(o_fill)
        assert res_fill.status == "filled"
        assert res_fill.filled_qty == 2.0
        assert res_fill.limit_price == 150.00
        st = sim.summary()
        assert st["submitted"] == 2
        assert st["filled"] == 1
        assert st["expired_unfilled"] == 1
        assert st["avg_unfilled_runaway_bps"] > 10.0

    asyncio.run(_run())


def test_exchange_manager_paper_maker_queue_prevents_instant_fill():
    """gercekci_maker_kuyruk=True iken karşı işlem gelmezse execute_entry qty=0 döndürür."""

    async def _run():
        cfg = load_config(CANONICAL_CONFIG_PATH)
        cfg["paper"]["gercekci_maker_kuyruk"] = True
        broker = ExchangeManager(cfg)
        broker.smart_maker_execution = True
        broker.update_live_bbo("binance", "BTC/USDT", 70_000.0, 70_001.0)
        fill = await broker.execute_entry(
            "BTC/USDT", "buy", 0.01, price_hint=70_000.5, prefer_maker=True, timeout=0.06, exchange="binance"
        )
        assert fill["qty"] == 0.0
        assert fill["status"] == "expired_unfilled"
        assert len(broker.paper.trades) == 0
        await broker.close()

    asyncio.run(_run())


def test_edge_separation_report_bootstrap_ci_and_r_multiples():
    """Brüt beklenti, komisyon yükü (bps), R-çarpanları ve deterministik Bootstrap %95 CI doğrulaması."""
    sample_trades = [
        {"margin_usdt": 50.0, "leverage": 10, "gross_pnl": 3.20, "fee_usdt": 0.35, "pnl_usdt": 2.85},
        {"margin_usdt": 50.0, "leverage": 10, "gross_pnl": -1.40, "fee_usdt": 0.35, "pnl_usdt": -1.75},
        {"margin_usdt": 50.0, "leverage": 10, "gross_pnl": 4.80, "fee_usdt": 0.20, "pnl_usdt": 4.60},
        {"margin_usdt": 50.0, "leverage": 10, "gross_pnl": 0.25, "fee_usdt": 0.45, "pnl_usdt": -0.20},
    ]
    rep = compute_edge_separation_report(sample_trades, starting_balance=1000.0, one_r_usdt=40.0)
    assert rep["trade_count"] == 4
    assert rep["low_sample_warning"] is True
    assert pytest.approx(rep["gross_total_usdt"], rel=1e-4) == 6.85
    assert pytest.approx(rep["fees_total_usdt"], rel=1e-4) == 1.35
    assert pytest.approx(rep["net_total_usdt"], rel=1e-4) == 5.50
    assert rep["fee_cost_bps"] > 0
    ci = rep["bootstrap_95_ci_net_per_trade_usdt"]
    assert ci[0] <= rep["post_fee_expectancy_usdt"] <= ci[1]


def test_ten_agent_mutual_audit_three_round_peer_critique():
    """10 müfettiş ajan aynı görev üzerinde 3 turda birbirini denetler; gürültüyü reddedip temiz akımı onaylar."""
    council = TenAgentMutualAuditCouncil(min_consensus_votes=7, min_expected_gross_fee_mult=3.5)

    good = council.evaluate_entry(
        {
            "symbol": "ETH/USDT",
            "side": "LONG",
            "ind_score": 44.0,
            "flow_score": 52.0,
            "combined_score": 48.0,
            "rvol": 1.65,
            "atr_pct": 0.65,
            "spread_pct": 0.01,
            "choppiness_14": 42.0,
            "mtf_aligned": True,
            "vwap_atr_z": 0.85,
            "spot_perp_basis_bps": 4.0,
        }
    )
    assert good["approved"] is True
    assert len(good["round2_votes"]) == 10
    assert good["consensus_votes"] >= 7

    noisy = council.evaluate_entry(
        {
            "symbol": "DOGE/USDT",
            "side": "LONG",
            "ind_score": 12.0,
            "flow_score": -24.0,
            "combined_score": -6.0,
            "rvol": 0.65,
            "atr_pct": 0.06,
            "spread_pct": 0.08,
            "choppiness_14": 68.0,
            "mtf_aligned": False,
            "vwap_atr_z": 3.4,
            "spot_perp_basis_bps": 32.0,
        }
    )
    assert noisy["approved"] is False
    assert noisy["consensus_votes"] < 7


def test_flow_exit_manager_holds_inflow_and_exits_on_reversal():
    """LONG pozisyon para girişi sürerken 135sn geçse bile tutulur; satış başlayınca kapatılır."""
    mgr = FlowTrendExitManager(min_reversal_profit_usdt=1.0)

    hold = mgr.evaluate_open_position(
        side="LONG",
        gross_pnl_usdt=3.20,
        mfe_usdt=3.40,
        roundtrip_fee_usdt=0.20,
        age_sec=240.0,
        ind_score=32.0,
        flow_score=38.0,
        combined_score=35.0,
        flow_snap={"buy_usdt": 15_000.0, "sell_usdt": 4_000.0, "cvd_60s": 11_000.0},
    )
    assert hold["should_exit"] is False

    rev = mgr.evaluate_open_position(
        side="LONG",
        gross_pnl_usdt=2.10,
        mfe_usdt=3.40,
        roundtrip_fee_usdt=0.20,
        age_sec=265.0,
        ind_score=-20.0,
        flow_score=-31.0,
        combined_score=-25.0,
        flow_snap={"buy_usdt": 3_000.0, "sell_usdt": 14_000.0, "cvd_60s": -11_000.0},
    )
    assert rev["should_exit"] is True
    assert "SATIŞA GEÇTİ" in rev["reason"]


def test_funding_proximity_and_counterfactual_tracker():
    """8 saatlik uzlaşmaya <12dk kala aleyhte fonlama engellenir; lehte fonlama serbest bırakılır."""
    near_08_utc = 8 * 3600 - 300
    adverse_long = check_funding_settlement_proximity("LONG", funding_rate=0.0005, now_ts=near_08_utc)
    assert adverse_long["allowed"] is False

    favorable_short = check_funding_settlement_proximity("SHORT", funding_rate=0.0005, now_ts=near_08_utc)
    assert favorable_short["allowed"] is True

    cf = CounterfactualTracker()
    cf.record_blocked_signal(
        gate="macro_regime_gate", symbol="BTC/USDT", side="LONG", price=70_000.0, reason="choppy", now_ts=1000.0
    )
    cf.on_price_update("BTC/USDT", 69_650.0, now_ts=1310.0)
    cf.record_shadow_legacy_time_cut(
        position_id="SOL/USDT:1000",
        symbol="SOL/USDT",
        side="SHORT",
        entry_price=150.0,
        shadow_cut_price=150.25,
        qty=3.0,
        entry_fee_usdt=0.09,
        age_sec=140.0,
        now_ts=1140.0,
    )
    cf.resolve_shadow_cut_on_close(
        position_id="SOL/USDT:1000", actual_net_pnl_usdt=2.40, exit_reason="FLOW_REVERSAL_PROFIT"
    )
    snap = cf.summary()
    assert snap["gate_asymmetry_and_forward_returns"]["macro_regime_gate"]["blocked_long"] == 1
    assert snap["gate_asymmetry_and_forward_returns"]["macro_regime_gate"]["blocked_signal_5m_signed_bps"] < 0
    assert snap["shadow_135s_cut_comparison"]["net_advantage_of_holding_usdt"] > 3.0


def test_restart_open_position_recovery_and_operational_alarms(tmp_path: Path):
    """Süreç yeniden başlatıldığında SQLite'daki açık pozisyon ve stop emri eksiksiz devralınır."""

    async def _run():
        cfg = load_config(CANONICAL_CONFIG_PATH)
        cfg["paper"]["gercekci_maker_kuyruk"] = False
        db_file = tmp_path / "restart_test.db"

        store1 = StateStore(db_file)
        broker1 = ExchangeManager(cfg)
        broker1.update_live_bbo("binance", "ETH/USDT", 2500.0, 2500.2)
        risk1 = RiskManager(
            stop_loss_pct=8.0,
            stop_model="marj",
            margin_stop_fraction=0.80,
            margin_stop_liq_buffer=0.85,
            lock_trigger_pct=2.5,
            lock_level_pct=1.2,
            trail_pct=1.5,
            risk_per_trade_pct=4.0,
            max_positions=1000,
            daily_max_loss_pct=20.0,
            capital_pct_per_entry=5.0,
            leverage=10,
            margin_mode="cross",
            cross_max_margin_pct=98.0,
            cross_min_free_usdt=0.0,
            max_total_margin_pct=98.0,
            state_store=store1,
        )
        sizer1 = PositionSizer(
            4.0, 1.25, False, 0.5, 0.25, 1.5, 20, tmp_path / "k.json",
            mode="sabit_usdt", capital_pct=5.0, leverage=10, fixed_margin_usdt=50.0,
        )
        strat = Strategy(0.52, 0.48, 0.0, 20.0, -20.0, 14.0, True)
        ex1 = Executor(
            broker1, risk1, strat, sizer1, _SilentAlerter(), 10, "maker", 1.0, False,
            state_store=store1, circuit_breaker=CircuitBreaker(state_store=store1),
            trade_plan_cfg={"aktif": False},
        )
        ex1.reconcile_and_unlock_paper_state(owner_id="kripto-bot-v92-main")
        await ex1.on_price_tick("ETH/USDT", 2500.1, exchange="binance")
        await ex1.on_signal(
            "ETH/USDT", 2500.1, {"signal": "LONG", "total": 35.0, "ind": 30.0}, 40.0, False,
            entry_context={"exchange": "binance", "preferred_exchange": "binance"},
        )
        assert "ETH/USDT" in ex1.positions
        saved_stop = ex1.positions["ETH/USDT"].stop
        await broker1.close()

        store2 = StateStore(db_file)
        broker2 = ExchangeManager(cfg)
        ex2 = Executor(
            broker2, risk1, strat, sizer1, _SilentAlerter(), 10, "maker", 1.0, False,
            state_store=store2, circuit_breaker=CircuitBreaker(state_store=store2),
            trade_plan_cfg={"aktif": False},
        )
        rec = ex2.reconcile_and_unlock_paper_state(owner_id="kripto-bot-v92-main")
        assert rec["ok"] is True
        assert ex2.paper_recovery_locked is False
        assert "ETH/USDT" in ex2.positions
        assert pytest.approx(ex2.positions["ETH/USDT"].stop) == saved_stop

        eng2 = UnifiedTradingEngine(ex2, cfg=cfg)
        health_ok = eng2.operational_health_snapshot(max_feed_lag_sec=30.0)
        assert health_ok["healthy"] is True
        assert health_ok["ledger_reconciled"] is True

        eng2._last_feed_ts = time.time() - 60.0
        ex2.positions.pop("ETH/USDT")
        health_bad = eng2.operational_health_snapshot(max_feed_lag_sec=15.0)
        assert health_bad["healthy"] is False
        assert any("FEED_LATENCY_ALARM" in a for a in health_bad["alarms"])
        assert any("POSITION_SET_MISMATCH" in a for a in health_bad["alarms"])
        await broker2.close()

    asyncio.run(_run())


def test_v92_oos_walk_forward_ablation_and_stress_integration():
    """V92CanonicalFlowStrategy walk-forward, ablasyon ve stres motorlarıyla uçtan uca çalışır."""
    df = _trend_ohlcv(n=220, start=100.0, drift=0.25)
    bt_cfg = BacktestConfig(timeframe="5m", starting_balance=1000.0, leverage=10.0)

    wf = run_walk_forward(
        df,
        lambda: V92CanonicalFlowStrategy(),
        train_bars=90,
        test_bars=50,
        config=bt_cfg,
    )
    assert len(wf) >= 2

    ab = run_ablation(
        df,
        lambda: V92CanonicalFlowStrategy(),
        families=("TREND_IND", "VOLUME_FLOW", "TEN_AGENT_AUDIT"),
        config=bt_cfg,
    )
    assert len(ab) == 4

    st = run_execution_stress(
        df,
        lambda: V92CanonicalFlowStrategy(),
        base_config=bt_cfg,
        scenarios=DEFAULT_SCENARIOS[:3],
    )
    assert len(st) == 3


def test_unfilled_maker_order_unlocks_paper_ledger_and_allows_next_trade(tmp_path):
    """Pasif Maker emri dolmadan zaman aşımına uğradığında (qty=0) SQLite PENDING kilidi
    temizlenmeli ve hemen sonraki paritede yeni işlem açılabilmelidir."""
    async def _run():
        cfg = copy.deepcopy(load_config())
        cfg["paper"]["gercekci_maker_kuyruk"] = True
        db_file = tmp_path / "unfilled_unlock.db"
        store = StateStore(db_file)
        broker = ExchangeManager(cfg)
        broker.update_live_bbo("binance", "ONE/USDT", 0.01500, 0.01501)
        broker.update_live_bbo("binance", "SOL/USDT", 150.00, 150.02)

        risk = RiskManager(
            stop_loss_pct=8.0,
            stop_model="marj",
            margin_stop_fraction=0.80,
            margin_stop_liq_buffer=0.85,
            lock_trigger_pct=2.5,
            lock_level_pct=1.2,
            trail_pct=1.5,
            risk_per_trade_pct=4.0,
            max_positions=1000,
            daily_max_loss_pct=20.0,
            capital_pct_per_entry=5.0,
            leverage=10,
            margin_mode="cross",
            cross_max_margin_pct=98.0,
            cross_min_free_usdt=0.0,
            max_total_margin_pct=98.0,
            state_store=store,
        )
        sizer = PositionSizer(
            4.0, 1.25, False, 0.5, 0.25, 1.5, 20, tmp_path / "k.json",
            mode="sabit_usdt", capital_pct=5.0, leverage=10, fixed_margin_usdt=50.0,
        )
        strat = Strategy(0.52, 0.48, 0.0, 20.0, -20.0, 14.0, True)
        ex = Executor(
            broker, risk, strat, sizer, _SilentAlerter(), 10, "maker", 0.06, False,
            state_store=store, circuit_breaker=CircuitBreaker(state_store=store),
            trade_plan_cfg={"aktif": False},
        )
        ex.reconcile_and_unlock_paper_state(owner_id="kripto-bot-v92-main")
        await ex.on_price_tick("ONE/USDT", 0.015005, exchange="binance")

        # 1) ONE/USDT pasif Maker emri BBO sabit kaldığı için 60ms'de dolmadan zaman aşımına uğrar
        await ex.on_signal(
            "ONE/USDT", 0.015005, {"signal": "SHORT", "total": -35.0, "ind": -30.0}, -40.0, False,
            entry_context={"exchange": "binance", "preferred_exchange": "binance"},
        )
        assert "ONE/USDT" not in ex.positions
        assert ex.paper_recovery_locked is False
        assert store.verify_paper_ledger_integrity()["ok"] is True

        # 2) Hemen ardından gelen SOL/USDT sinyali kilit engeline takılmadan kuyruğa girer ve dolar
        await ex.on_price_tick("SOL/USDT", 150.01, exchange="binance")

        async def _cross_sol_bbo():
            await asyncio.sleep(0.02)
            broker.update_live_bbo("binance", "SOL/USDT", 150.03, 150.04)

        t_cross = asyncio.create_task(_cross_sol_bbo())
        await ex.on_signal(
            "SOL/USDT", 150.01, {"signal": "SHORT", "total": -35.0, "ind": -30.0}, -40.0, False,
            entry_context={"exchange": "binance", "preferred_exchange": "binance"},
        )
        await t_cross
        assert "SOL/USDT" in ex.positions
        assert ex.paper_recovery_locked is False
        assert store.verify_paper_ledger_integrity()["ok"] is True
        await broker.close()

    asyncio.run(_run())


def test_repo_hygiene_no_personal_emails_or_fake_claims():
    """Depo dosyalarında kişisel e-posta veya doğrulanmamış test/benchmark iddiası bulunmamalı."""
    root = Path(__file__).resolve().parent.parent
    forbidden = ("@gmail.com", "760/760", "SWE-Bench")
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in {".pytest_cache", "__pycache__", "reports"} for part in p.parts):
            continue
        if p.name == "test_v92_upgrades.py":
            continue
        if p.suffix in {".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt"}:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            for bad in forbidden:
                assert bad not in txt, f"{p} içinde yasaklı ifade bulundu: {bad}"
