"""Kripto Bot v8.4 — 3 Kritik Bulgu Düzeltmesi ve 10dk Sonrası Doğal Kapanış (Drain) Testleri."""
from __future__ import annotations

import asyncio
import time

import numpy as np
import pandas as pd
import pytest

from src.ai_council import MultiAICouncil
from src.executor import Executor
from src.risk import RiskManager
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.unified_v8_engine import UnifiedV8Engine
from tests._paper_fixtures import make_paper_broker


def _bullish_df(n: int = 220, base: float = 100.0) -> pd.DataFrame:
    xs = np.linspace(0, 10.0, n)
    close = base + xs + np.sin(xs * 2.0) * 0.15
    open_ = np.r_[close[0] - 0.05, close[:-1]]
    high = np.maximum(open_, close) + 0.35
    low = np.minimum(open_, close) - 0.25
    vol = np.full(n, 1400.0)
    ts = np.arange(n, dtype=float) * 300_000.0
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": vol})


def test_v84_sqlite_feedback_updates_ai_weights_maker_savings_and_churn_cooldown(tmp_path):
    store = StateStore(tmp_path / "v84_fb.db")
    broker = make_paper_broker(5000.0, fee_pct=0.02)
    df5 = _bullish_df()
    px = float(df5["close"].iloc[-1])
    broker.prices["BNB/USDT"] = px

    risk = RiskManager(stop_model="marj", margin_stop_fraction=0.8, leverage=10, unlimited_pyramiding=False)
    strat = Strategy(w_ind=0.45, w_flow=0.40, w_news=0.0, w_ml=0.0, long_th=20.0, short_th=-20.0, runner_exit=True)
    sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=100.0, leverage=10, kelly_on=False)
    ex = Executor(broker, risk, strat, sizer=sizer, state_store=store, protection_on=True)
    council = MultiAICouncil(min_consensus_score=15.0)
    engine = UnifiedV8Engine(ex, mode="hybrid_fusion", council=council)

    async def scenario():
        now_ms = int(time.time() * 1000)
        for i in range(30):
            await engine.on_trade("binance", "BNB/USDT", px, 50.0, is_buyer_maker=False, ts_ms=now_ms - (30 - i) * 1000)
        res = await engine.evaluate_and_route("binance", "BNB/USDT", df5, spread_pct=0.02)
        assert res["routed"] is True
        assert "BNB/USDT" in ex.positions

        # Pozisyonu kârla kapat ve geri-bildirim döngüsünü çalıştır
        broker.prices["BNB/USDT"] = px * 1.005
        closed_ok = await ex.close_position("BNB/USDT", px * 1.005, "KÂR KİLİDİ STOPU")
        assert closed_ok is True

        synced = engine.sync_closed_trade_feedback()
        assert synced == 1
        assert council.closed_trades_learned == 1
        assert all(row["evaluated_trades"] == 1 for row in council.get_assistants_dashboard())
        assert engine.commission_optimizer.stats["maker_entries"] == 1
        assert engine.commission_optimizer.stats["estimated_saved_usdt"] > 0.0

        # Anti-churn soğuma kilidi: BNB hemen tekrar açılmak istendiğinde engellenmeli!
        chk = engine.win_loss_analyzer.check_entry_edge(
            symbol="BNB/USDT", side="LONG", vwap_atr_z=0.4, rvol=1.5, rvol_warmed=True
        )
        assert chk.allowed is False
        assert chk.pattern_tag == "churn_cooldown"

    asyncio.run(scenario())


def test_v84_symmetric_overbought_long_blocked_by_kimi_and_winloss():
    council = MultiAICouncil(min_consensus_score=16.0, max_veto_count=1, enabled=True)
    # ESPORTS +1.80σ ve RVOL=0.85x profili artık hem Kimi K3 kritik vetosuyla hem WinLossAnalyzer ile reddedilmeli!
    rep = council.evaluate_signal(
        {
            "symbol": "ESPORTS/USDT",
            "side": "LONG",
            "price": 0.0155,
            "ind_score": 45.0,
            "flow_score": 30.0,
            "combined_total": 35.0,
            "rvol": 0.85,
            "rvol_warmed": True,
            "vwap_atr_z": 1.80,
            "atr_pct": 0.65,
            "mtf_aligned": True,
            "spread_pct": 0.02,
        }
    )
    assert rep["approved"] is False
    assert "kimi_kritik_dip_tepe_veto" in rep["reason"]


def test_v84_natural_drain_blocks_new_entries_while_managing_open_positions(tmp_path):
    store = StateStore(tmp_path / "v84_drain.db")
    broker = make_paper_broker(5000.0, fee_pct=0.02)
    df5 = _bullish_df()
    px = float(df5["close"].iloc[-1])
    broker.prices["BTC/USDT"] = px
    broker.prices["ETH/USDT"] = px

    risk = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.8,
        leverage=10,
        mfe_lock_min_usdt=1.35,
        mfe_lock_keep_ratio=0.56,
        unlimited_pyramiding=False,
    )
    strat = Strategy(w_ind=0.45, w_flow=0.40, w_news=0.0, w_ml=0.0, long_th=20.0, short_th=-20.0, runner_exit=True)
    sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=100.0, leverage=10, kelly_on=False)
    ex = Executor(
        broker, risk, strat, sizer=sizer, state_store=store, protection_on=True,
        net_breakeven_enabled=True, net_profit_buffer_usdt=0.35, exit_fee_pct=0.02,
    )
    engine = UnifiedV8Engine(ex, mode="hybrid_fusion", council=MultiAICouncil(min_consensus_score=15.0))

    async def scenario():
        now_ms = int(time.time() * 1000)
        for i in range(25):
            await engine.on_trade("binance", "BTC/USDT", px, 40.0, is_buyer_maker=False, ts_ms=now_ms - (25 - i) * 1000)
            await engine.on_trade("binance", "ETH/USDT", px, 40.0, is_buyer_maker=False, ts_ms=now_ms - (25 - i) * 1000)

        # 10dk içinde BTC açılır
        r1 = await engine.evaluate_and_route("binance", "BTC/USDT", df5, spread_pct=0.02, allow_new_entries=True)
        assert r1["routed"] is True
        assert "BTC/USDT" in ex.positions

        # 10dk doldu (allow_new_entries=False): ETH için güçlü LONG sinyali gelse bile YENİ İŞLEM AÇILMAZ!
        r2 = await engine.evaluate_and_route("binance", "ETH/USDT", df5, spread_pct=0.02, allow_new_entries=False)
        assert r2["routed"] is False
        assert r2["reason"] == "yeni_giris_durduruldu_acik_pozisyon_bekleniyor"
        assert "ETH/USDT" not in ex.positions

        # Ancak açık olan BTC pozisyonu kâr kilidiyle bota uygun doğal olarak kapanmaya devam eder!
        broker.prices["BTC/USDT"] = px * 1.004  # +$4.00 MFE -> kâr kilidi aktif
        await ex.on_price_tick("BTC/USDT", px * 1.004)
        assert ex.positions["BTC/USDT"].locked_profit is True

        broker.prices["BTC/USDT"] = px * 1.001  # kâr kilidi stopuna geri çekilme -> doğal kapanış!
        await ex.on_price_tick("BTC/USDT", px * 1.001)
        assert len(ex.positions) == 0

    asyncio.run(scenario())
