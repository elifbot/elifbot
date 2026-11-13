"""Kripto Bot v8.3 — Komisyon Optimizasyonu, Kazanan/Kaybeden Ayrımı ve 10-YZ Yardımcı Testleri."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.ai_council import COUNCIL_MODELS, MultiAICouncil
from src.commission_optimizer import CommissionOptimizer
from src.exchanges import ExchangeManager
from src.risk import Position, RiskManager
from src.win_loss_analyzer import WinLossAnalyzer


def test_commission_optimizer_saves_60_percent_roundtrip():
    opt = CommissionOptimizer(maker_fee_pct=0.02, taker_fee_pct=0.05)
    res = opt.estimate_roundtrip_cost_usdt(
        1000.0, spread_pct=0.02, prefer_maker_entry=True, prefer_maker_exit=True
    )
    assert res["entry_fee_usdt"] == pytest.approx(0.20)
    assert res["exit_fee_usdt"] == pytest.approx(0.20)
    assert res["total_cost_usdt"] == pytest.approx(0.40)
    assert res["potential_saving_usdt"] >= 0.60  # $1.00+ Taker yerine $0.40 Maker!

    # Mikro-testere (ATR %0.07 -> beklenen hareket ~$0.70 < 3.0x * $0.40 = $1.20) reddedilmeli
    bad = opt.evaluate_fee_viability(notional_usdt=1000.0, atr_pct=0.07, spread_pct=0.02, rvol=1.0)
    assert bad.viable is False
    assert "komisyon_yuku_yuksek" in bad.reason

    # Sağlıklı oynaklık (ATR %0.45 -> beklenen hareket ~$3.82 >= 3.0x * $0.40) onaylanmalı
    good = opt.evaluate_fee_viability(notional_usdt=1000.0, atr_pct=0.45, spread_pct=0.02, rvol=1.5)
    assert good.viable is True
    assert good.fee_multiple >= 3.0


def test_realistic_paper_smart_maker_entry_and_exit_fees(monkeypatch):
    cfg = {
        "genel": {"mod": "paper", "borsalar": ["binance"], "semboller": ["ETH/USDT"], "kaldıraç": 10},
        "paper": {"bakiye": 10000.0, "gercekci_yurutme": True, "akilli_maker_yurutme": True},
        "emirler": {"max_kayma_yuzde": 0.30, "max_maker_makas_yuzde": 0.08},
    }
    ex = ExchangeManager(cfg)

    async def fake_bid_ask(symbol: str, exchange: str | None = None):
        return (2000.00, 2000.40)  # %0.02 dar makas

    async def fake_lev(symbol: str, lev: int, exchange: str | None = None):
        return True

    monkeypatch.setattr(ex, "fetch_bid_ask", fake_bid_ask)
    monkeypatch.setattr(ex, "ensure_leverage", fake_lev)

    # 1) Giriş: prefer_maker=True iken Taker ($0.50) yerine Pasif Maker ($0.20) kesmeli!
    entry_fill = asyncio.run(ex.execute_entry("ETH/USDT", "buy", 0.5, price_hint=2000.2, prefer_maker=True))
    assert entry_fill["emir_tipi"] == "maker_post_only"
    assert entry_fill["price"] == pytest.approx(2000.00)
    assert entry_fill["fee"] == pytest.approx(0.20)  # $1,000 * %0.02 = $0.20!

    # 2) Kâr Kilidi çıkışı: %0.02 Reduce-Only Maker ($0.20) kesmeli!
    tp_exit = asyncio.run(
        ex.execute_exit("ETH/USDT", "sell", 0.5, price_hint=2004.0, reason="KÂR KİLİDİ STOPU")
    )
    assert tp_exit["emir_tipi"] == "maker_reduce_only"
    assert tp_exit["fee"] == pytest.approx(0.20004, rel=1e-3)

    # 3) Yeni pozisyon açıp acil Zarar Durdur çıkışını test et: güvenlik için derhal %0.05 Taker Market kesmeli!
    asyncio.run(ex.execute_entry("ETH/USDT", "buy", 0.5, price_hint=2000.2, prefer_maker=True))
    sl_exit = asyncio.run(
        ex.execute_exit("ETH/USDT", "sell", 0.5, price_hint=1985.0, reason="STOP LOSS (MARJ)")
    )
    assert sl_exit["emir_tipi"] == "market"
    assert sl_exit["fee"] == pytest.approx(0.50, rel=2e-2)


def test_fee_inclusive_mfe_lock_never_locks_at_net_loss():
    risk = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        leverage=10,
        mfe_lock_min_usdt=1.20,
        mfe_lock_keep_ratio=0.55,
    )
    pos = Position(
        symbol="ZEC/USDT",
        side="LONG",
        entry=100.0,
        qty=10.0,  # $1,000 notional
        stop=92.0,
        leverage=10,
        margin_usdt=100.0,
        entry_fee_usdt=0.50,
        exit_fee_pct=0.05,  # $0.50 tahmini çıkış komisyonu -> toplam $1.00 ücret!
        net_breakeven_enabled=True,
        net_profit_buffer_usdt=0.35,
    )
    # MFE = +$1.25 brüt iken (ücret sonrası yalnızca +$0.25) erken kilitlenmemeli!
    risk.update(pos, 100.125)
    assert pos.locked_profit is False

    # MFE = +$1.80 brüte ulaştığında kilit devreye girmeli ve stop >= $100.135 (en az +$1.35 brüt = +$0.35 NET kâr!) olmalı
    risk.update(pos, 100.18)
    assert pos.locked_profit is True
    locked_gross_at_stop = (pos.stop - pos.entry) * pos.qty
    assert locked_gross_at_stop >= 1.35  # $1.00 ücret düşüldükten sonra kesin >= +$0.35 NET kâr!


def test_win_loss_analyzer_blocks_oversold_short_and_boosts_high_rvol_runner():
    wla = WinLossAnalyzer()

    # #11 BZ SHORT profili: VWAP_Z = -2.05σ, RVOL = 0.60x -> KESİN ENGEL!
    trap = wla.check_entry_edge(
        symbol="BZ/USDT", side="SHORT", vwap_atr_z=-2.05, rvol=0.60, rvol_warmed=True, now_ts=1000.0
    )
    assert trap.allowed is False
    assert trap.pattern_tag == "oversold_short_trap"

    # #3 KORU LONG kazanan koşucu profili: VWAP_Z = +2.36σ, RVOL = 4.35x -> ONAY & BONUS!
    runner = wla.check_entry_edge(
        symbol="KORU/USDT", side="LONG", vwap_atr_z=2.36, rvol=4.35, rvol_warmed=True, now_ts=1000.0
    )
    assert runner.allowed is True
    assert runner.pattern_tag == "high_rvol_runner"
    assert runner.edge_score_bonus > 10.0

    # Bayatlayan zarar pozisyonu (210 sn geçti, MFE +$0.40, anlık -$2.50) -> Erken Kes!
    stag = wla.evaluate_stagnant_loser(age_sec=210.0, mfe_usdt=0.40, current_gross_pnl_usdt=-2.50)
    assert stag["should_cut"] is True


def test_10_ai_assistants_kimi_veto_and_bayesian_weight_learning():
    council = MultiAICouncil(min_consensus_score=16.0, max_veto_count=1, enabled=True)
    assert len(COUNCIL_MODELS) == 10

    # Aşırı satılmış dipte düşük RVOL'lü SHORT -> Kimi K3 + DeepSeek V4 Pro ortak VETO!
    bad_rep = council.evaluate_signal(
        {
            "symbol": "BZ/USDT",
            "side": "SHORT",
            "price": 0.1,
            "ind_score": -45.0,
            "flow_score": -30.0,
            "combined_total": -35.0,
            "rvol": 0.60,
            "rvol_warmed": True,
            "vwap_atr_z": -2.05,
            "atr_pct": 0.50,
            "mtf_aligned": True,
            "spread_pct": 0.02,
        }
    )
    assert bad_rep["approved"] is False
    assert bad_rep["veto_count"] >= 2

    # Kapanan işlemden Bayesçi ağırlık öğrenimi (Qwen3-Coder adaptif güncellemesi)
    votes_sample = {m["id"]: (-40.0 if m["id"] in ("kimi", "deepseek") else 25.0) for m in COUNCIL_MODELS}
    before_kimi = council.effective_weights()["kimi"]
    after_weights = council.update_weights_from_closed_trade(votes_sample, net_pnl_usdt=-4.87)
    assert sum(after_weights.values()) == pytest.approx(1.0)
    # Zarar eden işlemi VETO eden Kimi K3'ün ağırlığı artmış olmalı!
    assert after_weights["kimi"] > before_kimi
    dash = council.get_assistants_dashboard()
    assert len(dash) == 10


def test_empirical_replay_on_real_live_sqlite_databases():
    db1 = Path("/home/user/kripto-bot-v8-mukemmel/reports/canli_15dk_state.db")
    db2 = Path("/home/user/kripto-bot-v8-mukemmel/reports/canli_10dk_v82_state.db")
    existing = [p for p in (db1, db2) if p.exists()]
    if not existing:
        pytest.skip("Canlı oturum veritabanı yok")
    report = WinLossAnalyzer.analyze_sqlite_databases(existing)
    assert report["total_trades"] >= 11
    # v8.3 karşı-olgusal (counterfactual) simülasyonu gerçek sonuca göre anlamlı net iyileşme sağlamalı!
    assert report["v83_counterfactual_replay"]["net_improvement_usdt"] > 10.0
