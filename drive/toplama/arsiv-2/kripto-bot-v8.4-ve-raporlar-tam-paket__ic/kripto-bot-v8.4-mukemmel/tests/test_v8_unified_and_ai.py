"""Kripto Bot v8.0 Mükemmel Birleşim Test Paketi:
  1. Tamamlanmış/açık paper işlemleri sonrası gerçek alt süreç (subprocess) çift-taraflı
     kasa/komisyon/funding mutabakatı ile güvenli restart ve yeni işlem açılışı.
  2. Bozulmuş kasa denklemi, PENDING intent veya rakip canlı yazar (single-writer lease)
     durumunda fail-closed kilit koruması.
  3. Devre dışı trade planlarının geçmişi silinmeden arşivlenerek (`trade_plans_archive`)
     pasifleştirilmesi.
  4. UnifiedV8Engine (V4 Saf Kripto Evreni + VWAP60/ATR14 + V7.8 300s MoneyFlow +
     Çoklu-YZ Konseyi [Claude + DeepSeek + GPT + Gemini] + ACID SQLite Executor) uçtan uca akışı.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[1]


SUBPROCESS_LIFECYCLE = r"""
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1])))
from src.config import load_config
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.sizing import PositionSizer
from src.state_store import StateStore

db_dir = Path(sys.argv[2])
phase = sys.argv[3]
cfg = load_config()
cfg['genel']['mod'] = 'paper'
cfg['paper']['bakiye'] = 1000.0
broker = ExchangeManager(cfg)
async def ba(symbol, exchange=None): return 99.98, 100.02
async def bp(symbol, side): return 'binance', (100.02 if side == 'LONG' else 99.98)
broker.fetch_bid_ask = ba
broker.best_price = bp

risk = RiskManager(stop_model='marj', margin_stop_fraction=0.8, leverage=10,
                   unlimited_pyramiding=False, max_layers=1, pair_rescue_enabled=False)
strat = Strategy(runner_exit=True)
sizer = PositionSizer(mode='sabit_usdt', fixed_margin_usdt=50, leverage=10,
                      stats_path=db_dir / 'kelly.json')
store = StateStore(db_dir / 'v8_state.db')
plan_on = (phase == 'run1')
ex = Executor(broker, risk, strat, sizer=sizer, order_type='maker', maker_timeout=3.0,
              protection_on=False, state_store=store,
              trade_plan_cfg={'aktif': plan_on, 'tp1_r': 1.0, 'tp2_r': 2.0, 'tp1_kapatma_orani': 0.5})
combined = strat.combine(80.0, 75.0, 20.0, 60.0, market_context={'regime_aware': False})

async def main():
    if phase == 'run1':
        rec = ex.reconcile_and_unlock_paper_state(owner_id='proc-1')
        assert rec['ok'] is True
        ex.set_atr('BTC/USDT', 2.0)
        ex.set_atr('ETH/USDT', 2.0)
        await ex.on_price_tick('BTC/USDT', 100.0)
        await ex.on_signal('BTC/USDT', 100.0, combined, 60.0, False)
        assert 'BTC/USDT' in ex.positions
        # Simüle funding tahakkuku + tam kapanış + ikinci açık pozisyon
        ex._funding_last['BTC/USDT'] = time.time() - 3600.0
        store.set_meta('paper_funding_clock', ex._funding_last)
        ex.apply_funding('BTC/USDT', 0.0004, 100.0, enabled=True)
        closed = await ex._close('BTC/USDT', 103.0, 'KAR AL', 3.0)
        assert closed is True
        await ex.on_price_tick('ETH/USDT', 100.0)
        await ex.on_signal('ETH/USDT', 100.0, combined, 60.0, False)
        store.set_meta('trade_plans', {'ETH/USDT': {'tp1': 108.0, 'tp2': 116.0, 'tp1_hit': False, 'initial_risk': 8.0, 'initial_stop': 92.0}})
        ex.release_writer_ownership()
        print('OUT=' + json.dumps({
            'positions': sorted(ex.positions),
            'balance': broker.paper.balance,
            'trades': len(store.get_trades()),
            'locked': ex.paper_recovery_locked,
        }), flush=True)
    elif phase == 'run2_reconcile':
        locked_before = ex.paper_recovery_locked
        rec = ex.reconcile_and_unlock_paper_state(owner_id='proc-2')
        assert rec['ok'] is True, rec
        # Restart sonrası yeni işlem açılabilmeli ve açık ETH pozisyonu kapatılabilmeli
        await ex.on_price_tick('SOL/USDT', 100.0)
        await ex.on_signal('SOL/USDT', 100.0, combined, 60.0, False)
        await ex.on_price_tick('ETH/USDT', 102.0)
        eth_closed = await ex._close('ETH/USDT', 102.0, 'RESTART SONRASI CIKIS', 2.0)
        integrity = store.verify_paper_ledger_integrity()
        ex.release_writer_ownership()
        print('OUT=' + json.dumps({
            'locked_before': locked_before,
            'locked_after': ex.paper_recovery_locked,
            'eth_closed': eth_closed,
            'positions': sorted(ex.positions),
            'trades': len(store.get_trades()),
            'active_plans': store.get_meta('trade_plans', {}),
            'archived_plans_count': len(store.get_meta('trade_plans_archive', [])),
            'integrity': integrity,
        }), flush=True)
    await broker.close()

asyncio.run(main())
"""


def _make_bullish_ohlcv(n: int = 220, start: float = 100.0) -> pd.DataFrame:
    ts = np.arange(n, dtype=float) * 300_000.0
    # Gerçekçi konsolidasyon + geri çekilme + taze hacimli kırılım (RSI ~65, pozitif MACD)
    base = start + np.sin(np.linspace(0, 14, n)) * 1.2 + np.linspace(0.0, 4.0, n)
    base[-35:-12] -= np.linspace(0.2, 2.2, 23)  # sağlıklı düzeltme (RSI soğutma)
    base[-12:] += np.linspace(0.4, 4.2, 12)      # hacimli yukarı kırılım
    closes = base
    opens = np.r_[closes[0] - 0.05, closes[:-1]]
    highs = np.maximum(opens, closes) + 0.35
    lows = np.minimum(opens, closes) - 0.25
    vols = np.full(n, 200.0)
    vols[-12:] = 1400.0
    return pd.DataFrame(
        {"ts": ts, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


def test_v8_subprocess_safe_restart_double_entry_reconciliation_and_plan_archive(tmp_path):
    p1 = subprocess.run(
        [sys.executable, "-c", SUBPROCESS_LIFECYCLE, str(ROOT), str(tmp_path), "run1"],
        cwd=ROOT, capture_output=True, text=True, timeout=25,
    )
    assert p1.returncode == 0, p1.stdout + p1.stderr
    r1 = json.loads(next(line[4:] for line in p1.stdout.splitlines() if line.startswith("OUT=")))
    assert r1["positions"] == ["ETH/USDT"]
    assert r1["trades"] == 1
    assert r1["locked"] is False

    p2 = subprocess.run(
        [sys.executable, "-c", SUBPROCESS_LIFECYCLE, str(ROOT), str(tmp_path), "run2_reconcile"],
        cwd=ROOT, capture_output=True, text=True, timeout=25,
    )
    assert p2.returncode == 0, p2.stdout + p2.stderr
    r2 = json.loads(next(line[4:] for line in p2.stdout.splitlines() if line.startswith("OUT=")))
    assert r2["locked_before"] is True  # Doğrulama öncesi salt-okunur kilitli başlar
    assert r2["locked_after"] is False  # Matematiksel mutabakat sonrası güvenle açılır
    assert r2["eth_closed"] is True
    assert r2["positions"] == ["SOL/USDT"]
    assert r2["trades"] == 2
    assert r2["active_plans"] == {}
    assert r2["archived_plans_count"] == 1  # Geçmiş silinmedi, arşivlendi!
    assert r2["integrity"]["ok"] is True
    assert r2["integrity"]["balance"] == pytest.approx(r2["integrity"]["expected_balance"])


def test_v8_tampered_cash_or_rival_writer_blocks_unlock(tmp_path):
    store = StateStore(tmp_path / "tamper.db")
    broker = make_paper_broker(1000.0, fee_pct=0.05)
    risk = RiskManager(stop_model="marj", margin_stop_fraction=0.8, leverage=10, unlimited_pyramiding=False)
    strat = Strategy(runner_exit=True)
    sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=50, leverage=10, kelly_on=False)
    ex = Executor(broker, risk, strat, sizer=sizer, state_store=store, protection_on=False)

    asyncio.run(ex._open("BTC/USDT", "LONG", 100.0, "TEST"))
    assert store.verify_paper_ledger_integrity()["ok"] is True

    # 1) Rakip canlı yazar kilidi varken ikinci Executor kilidi açamaz
    store.acquire_writer_lease("other-live-owner", ttl_sec=120.0)
    ex2 = Executor(make_paper_broker(1000.0, fee_pct=0.05), risk, strat, sizer=sizer, state_store=store, protection_on=False)
    conflict = ex2.reconcile_and_unlock_paper_state(owner_id="my-owner")
    assert conflict["ok"] is False and "writer_lease_conflict" in conflict["reason"]
    assert ex2.paper_recovery_locked is True
    store.release_writer_lease("other-live-owner")

    # 2) Kasa bakiyesi kurcalanırsa (0.01 USDT sapma bile) çift-taraflı denklem reddeder
    acc = store.get_meta("paper_account")
    acc["balance"] += 0.05
    store.set_meta("paper_account", acc)
    bad = ex2.reconcile_and_unlock_paper_state(owner_id="my-owner")
    assert bad["ok"] is False and "cash_conservation_mismatch" in bad["reason"]
    assert ex2.paper_recovery_locked is True


def test_v8_unified_engine_fuses_v4_vwap_atr_v78_orderflow_and_ai_council(tmp_path):
    # 1) V4 saf kripto evren filtresi hisse/altın/endeks sembollerini eler
    filtered = UnifiedV8Engine.filter_pure_crypto_symbols(
        ["BTCUSDT", "ETHUSDT", "XAUUSDT", "TSLAUSDT", "USDCUSDT", "SOLUSDT"]
    )
    assert "BTCUSDT" in filtered and "ETHUSDT" in filtered and "SOLUSDT" in filtered
    assert "XAUUSDT" not in filtered and "TSLAUSDT" not in filtered and "USDCUSDT" not in filtered

    # 2) Tam birleşik sinyal akışı: 60dk V4 mumları + 300s balina akışı + 4'lü YZ Konseyi -> ACID Executor
    store = StateStore(tmp_path / "unified.db")
    broker = make_paper_broker(2000.0, fee_pct=0.02)
    df5 = _make_bullish_ohlcv()
    last_px = float(df5["close"].iloc[-1])
    broker.prices["BTC/USDT"] = last_px

    risk = RiskManager(stop_model="marj", margin_stop_fraction=0.8, leverage=10, unlimited_pyramiding=False)
    strat = Strategy(w_ind=0.45, w_flow=0.40, w_news=0.0, w_ml=0.0, long_th=22.0, short_th=-22.0, runner_exit=True)
    sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=50, leverage=10, kelly_on=False)
    ex = Executor(broker, risk, strat, sizer=sizer, state_store=store, protection_on=False)
    engine = UnifiedV8Engine(ex, mode="hybrid_fusion", council=MultiAICouncil(min_consensus_score=15.0))

    now_ms = int(time.time() * 1000)
    last_closed_mid = now_ms // 60_000 - 1
    for i, mid in enumerate(range(last_closed_mid - 59, last_closed_mid + 1)):
        c_px = last_px - 0.6 + (i / 60.0) * 0.5
        engine.ingest_closed_1m_candle("binance", "BTC/USDT", mid, c_px - 0.1, c_px + 0.3, c_px - 0.3, c_px, 15.0)

    async def scenario():
        # Güçlü alıcı + $150k balina alışı besle
        for i in range(40):
            t_ms = now_ms - (40 - i) * 1000
            qty = 1400.0 if i == 5 else 2.0
            await engine.on_trade("binance", "BTC/USDT", last_px, qty, is_buyer_maker=False, ts_ms=t_ms)

        res = await engine.evaluate_and_route("binance", "BTC/USDT", df5, spread_pct=0.02)
        assert res["signal"] == "LONG"
        assert res["routed"] is True
        assert res["council"]["approved"] is True
        assert len(res["council"]["votes"]) == 10
        assert "BTC/USDT" in ex.positions
        assert store.verify_paper_ledger_integrity()["ok"] is True

        # Claude Opus 5 kayma/makas vetosu testi: aşırı spread (%0.65 > %0.30) geldiğinde konsey VETO eder!
        veto_res = await engine.evaluate_and_route("binance", "ETH/USDT", df5, spread_pct=0.65)
        assert veto_res["routed"] is False
        assert "claude_kritik_veto" in veto_res["reason"]
        assert "ETH/USDT" not in ex.positions

    asyncio.run(scenario())


def test_v82_top10_coding_council_and_fee_aware_pair_rescue():
    from src.ai_council import COUNCIL_MODELS
    from src.risk import Position

    # 1) Dünyanın en iyi 10 kodlama & algoritma modeli tam kadro ve ağırlık toplamı = 1.00
    assert len(COUNCIL_MODELS) == 10
    total_w = sum(float(m["weight"]) for m in COUNCIL_MODELS)
    assert total_w == pytest.approx(1.0, abs=1e-9)

    council = MultiAICouncil()
    audit = council.audit_bot_engineering({"live_ticks": 55000})
    assert audit["council_size"] == 10
    assert audit["overall_engineering_score"] >= 95.0
    assert len(audit["specialist_audits"]) == 10

    # 2) Ücret-Duyarlı Çapraz Kurtarma (pair_rescue_fee_aware=True):
    # Küçük kâr (+$0.80) ile büyük zararı (-$5.50) kapatıp net zarar kilitlemeyi REDDEDER!
    risk_v82 = RiskManager(
        pair_rescue_enabled=True,
        rescue_min_loser_pct=0.5,
        pair_rescue_fee_aware=True,
        pair_rescue_min_net_usdt=0.15,
    )
    small_win = Position("ESPORTS/USDT", "LONG", 100.0, 10.0, 92.0, margin_usdt=100.0, entry_fee_usdt=0.20)
    big_loss = Position("HYPE/USDT", "SHORT", 100.0, 10.0, 108.0, margin_usdt=100.0, entry_fee_usdt=0.50)
    bad_rescue = risk_v82.find_pair_rescue(
        {"ESPORTS/USDT": small_win, "HYPE/USDT": big_loss},
        {"ESPORTS/USDT": 100.08, "HYPE/USDT": 100.55},  # +$0.80 vs -$5.50 -> net zarar!
    )
    assert bad_rescue is None

    # Gerçekten komisyonlar dahil net kâr bırakan (+$8.00 vs -$5.50 -> net > +$0.15) kurtarmayı ONAYLAR!
    good_rescue = risk_v82.find_pair_rescue(
        {"ESPORTS/USDT": small_win, "HYPE/USDT": big_loss},
        {"ESPORTS/USDT": 100.80, "HYPE/USDT": 100.55},  # +$8.00 - $5.50 - ~$1.70 ücret = +$0.80 net!
    )
    assert good_rescue is not None
    assert good_rescue["action"] == "pair_close"
    assert good_rescue["net_pnl_usdt"] >= 0.15

