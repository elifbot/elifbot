"""Kripto Bot v9.1 — Güvenlik, Kilitli Risk Tavanları, Çift Borsa, Rejim Kapısı,
Ayı/Dağıtım Düşen-Hacim Filtresi, Hacim Uyumsuzluğu ve Katı Hakem Test Paketi."""
from __future__ import annotations

import ast
import asyncio
import copy
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import BASE_DIR, CANONICAL_CONFIG_PATH, ConfigError, load_config, validate_config
from src.exchanges import ExchangeManager
from src.live_runner import DualVenueLiveRunner
from src.llm_referee import LiveLLMReferee
from src.regime_state_machine import RegimeStateMachine
from src.risk import Position


def test_single_canonical_config_and_hard_risk_caps() -> None:
    """Tek kanonik JSON ve kodda sabitlenmiş (IMMUTABLE_HARD_CAPS) sert risk/kaldıraç tavanlarını doğrular."""
    assert CANONICAL_CONFIG_PATH.exists()
    assert not (BASE_DIR / "config.yaml").exists()

    cfg = load_config()
    assert cfg["version"] == "9.4.3"
    assert cfg["genel"]["borsalar"] == ["binance", "okx"]
    assert cfg["risk"]["gunluk_max_zarar_yuzde"] <= 25.0
    assert cfg["risk"]["marj_zarar_orani"] <= 0.80
    assert cfg["genel"]["kaldıraç"] <= 10

    bad_lev = copy.deepcopy(cfg)
    bad_lev["genel"]["kaldıraç"] = 25
    with pytest.raises(ConfigError):
        validate_config(bad_lev, bad_lev["api"])

    bad_dd = copy.deepcopy(cfg)
    bad_dd["risk"]["gunluk_max_zarar_yuzde"] = 30.0
    with pytest.raises(ConfigError):
        validate_config(bad_dd, bad_dd["api"])


def test_ast_security_clean_across_all_modules() -> None:
    py_files = list((BASE_DIR / "src").glob("*.py")) + list((BASE_DIR / "scanner").glob("*.py"))
    assert len(py_files) >= 25
    forbidden_calls = {"eval", "exec"}
    for fpath in py_files:
        tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls


def test_dual_exchange_live_bbo_and_venue_isolation() -> None:
    cfg = load_config()
    runner = DualVenueLiveRunner(cfg, duration_sec=5.0, port=18089, report_prefix="unit_iso91")
    try:
        now_s = time.time()
        runner.broker.update_live_bbo("binance", "BTC/USDT", 77100.0, 77100.5, now_s)
        runner.broker.update_live_bbo("okx", "BTC/USDT", 77100.0, 77104.0, now_s)
        best_ex, _ = runner.broker.select_best_exchange("BTC/USDT", "LONG", {})
        assert best_ex == "binance"

        pos = Position("BTC/USDT", "LONG", 77100.0, 0.02, 77050.0, exchange="okx")
        runner.executor.positions["BTC/USDT"] = pos

        async def _run() -> None:
            await runner.executor.on_price_tick("BTC/USDT", 77010.0, exchange="binance")
            assert "BTC/USDT" in runner.executor.positions
            await runner.broker.close()

        asyncio.run(_run())
    finally:
        for f in runner.reports_dir.glob("unit_iso91*"):
            f.unlink(missing_ok=True)


def test_choppy_and_crash_hard_block_plus_bearish_declining_volume_long_block() -> None:
    """1) Testere ve Çöküş rejimlerinde %100 blok;
    2) Düşen hacimli Ayı / Yatay Dağıtım rejiminde %100 LONG engeli ve SHORT iznini doğrular."""
    rm = RegimeStateMachine(min_confirm_bars=2, choppy_choppiness_min=61.8)
    rm.update("SOL/USDT", raw_regime="RANGE", adx=14.0, bar_id=1)

    # Testere (Choppy Range) -> %100 Hard Block
    df_chop = pd.DataFrame(
        {
            "ts": np.arange(30) * 300_000,
            "open": np.full(30, 100.0),
            "high": np.full(30, 100.3),
            "low": np.full(30, 99.7),
            "close": np.full(30, 100.0),
            "volume": np.full(30, 1000.0),
        }
    )
    chop_macro = rm.evaluate_macro_regime(
        "SOL/USDT", df_chop, adx=14.0, choppiness_14=66.5, vwap_atr_z=0.2, rvol=0.9, rvol_warmed=True
    )
    assert chop_macro["macro_regime"] == "CHOPPY_RANGE"
    assert chop_macro["hard_blocked"] is True

    # Çöküş (Crash) -> %100 Hard Block
    closes_crash = np.concatenate([np.full(29, 100.0), [97.5]])
    df_crash = df_chop.copy()
    df_crash["close"] = closes_crash
    crash_macro = rm.evaluate_macro_regime(
        "SOL/USDT", df_crash, adx=30.0, choppiness_14=42.0, vwap_atr_z=-2.5, rvol=2.5, rvol_warmed=True
    )
    assert crash_macro["macro_regime"] == "CRASH_RISK_OFF"
    assert crash_macro["hard_blocked"] is True

    # Düşen hacimli Ayı Trendi -> LONG %100 Engelli, SHORT Serbest!
    rm_bear = RegimeStateMachine(min_confirm_bars=2)
    rm_bear.update("ETH/USDT", raw_regime="TREND", adx=26.0, bar_id=1)
    closes_bear = np.linspace(2600.0, 2540.0, 30)
    vols_declining = np.concatenate([np.full(25, 5000.0), np.full(5, 2200.0)])
    df_bear = pd.DataFrame(
        {
            "ts": np.arange(30) * 300_000,
            "open": closes_bear + 1.0,
            "high": closes_bear + 2.0,
            "low": closes_bear - 2.0,
            "close": closes_bear,
            "volume": vols_declining,
        }
    )
    bear_macro = rm_bear.evaluate_macro_regime(
        "ETH/USDT",
        df_bear,
        adx=26.0,
        choppiness_14=45.0,
        vwap_atr_z=-0.9,
        rvol=0.78,
        rvol_warmed=True,
        mtf_trend="BEARISH",
    )
    assert bear_macro["macro_regime"] == "BEARISH_TREND"
    assert bear_macro["volume_declining"] is True

    long_ok, long_why = rm_bear.check_bearish_distribution_gate(side="LONG", macro_info=bear_macro)
    short_ok, _ = rm_bear.check_bearish_distribution_gate(side="SHORT", macro_info=bear_macro)
    assert long_ok is False and "long_engeli" in long_why
    assert short_ok is True


def test_bearish_volume_divergence_short_trigger() -> None:
    """Fiyat zirve testi yaparken hacim dibe vurduğunda Spike + MoneyFlow ile agresif SHORT tetiklenmesini doğrular."""
    rm = RegimeStateMachine()
    closes = np.concatenate([np.linspace(100.0, 104.5, 14), [103.8, 104.4, 104.55]])
    highs = closes + 0.15
    highs[13] = 104.70  # Önceki yüksek hacimli zirve
    vols = np.full(len(closes), 4000.0)
    vols[13] = 9500.0   # Zirve mumu yüksek hacim
    vols[-2] = 2100.0   # Yeni tepe testinde hacim dibe vurdu (%22!)
    vols[-1] = 1800.0
    df = pd.DataFrame(
        {
            "ts": np.arange(len(closes)) * 300_000,
            "open": closes - 0.1,
            "high": highs,
            "low": closes - 0.3,
            "close": closes,
            "volume": vols,
        }
    )
    div = rm.detect_bearish_volume_divergence(
        df,
        price=104.62,
        ema20=103.10,
        rvol=0.62,
        rvol_warmed=True,
        spike_ret_2s=-0.03,
        flow_snap={"score": -11.5, "buy_usdt": 18000.0, "sell_usdt": 32000.0},
    )
    assert div["triggered"] is True
    assert div["side"] == "SHORT"
    assert div["playbook"] == "VOLUME_DIVERGENCE_SHORT"


def test_strict_llm_referee_filters_noise() -> None:
    """LiveLLMReferee'nin kör onay vermek yerine gürültülü ve ters akışlı sinyalleri elediğini doğrular."""
    ref = LiveLLMReferee(strict_noise_filter=True, min_consensus_score=40.0, max_allowed_choppiness=61.5)

    async def _check() -> None:
        v_chop = await ref.adjudicate(
            {
                "symbol": "ADA/USDT",
                "side": "LONG",
                "playbook": "MOMENTUM_BREAKOUT",
                "macro_regime": "RANGE",
                "choppiness_14": 65.0,
                "flow_score": 12.0,
                "consensus_score": 55.0,
                "rvol": 1.1,
            }
        )
        assert v_chop["approved"] is False

        v_contra = await ref.adjudicate(
            {
                "symbol": "XRP/USDT",
                "side": "LONG",
                "playbook": "MOMENTUM_BREAKOUT",
                "macro_regime": "BULLISH_TREND",
                "choppiness_14": 44.0,
                "flow_score": -15.0,
                "consensus_score": 52.0,
                "rvol": 1.2,
            }
        )
        assert v_contra["approved"] is False

        v_clean = await ref.adjudicate(
            {
                "symbol": "BTC/USDT",
                "side": "SHORT",
                "playbook": "VOLUME_DIVERGENCE_SHORT",
                "macro_regime": "BEARISH_TREND",
                "volume_declining": True,
                "choppiness_14": 48.0,
                "flow_score": -18.0,
                "consensus_score": 48.0,
                "rvol": 0.65,
            }
        )
        assert v_clean["approved"] is True

    asyncio.run(_check())
