"""PDF v3 Hazırlık Modülleri (pdf_v3_prep + derivatives_intel) Birim Testleri."""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pandas as pd

from src.derivatives_intel import (
    DerivativesIntelEngine,
    compute_crowding_verdict,
    normalize_external_alpha,
)
from src.pdf_v3_prep import (
    CalendarEvent,
    MacroCalendarGuard,
    OrderBookAnomalyTracker,
    advanced_performance_metrics,
    btc_regime_and_correlation,
    classify_statistical_regime,
    classic_stochastic,
    elder_safezone_stop,
    ema_ribbon_state,
    ema_smoothed_oscillators,
    estimated_liquidation_clusters,
    frama,
    jma_approx,
    minimal_roi_exit_check,
    monte_carlo_drawdown,
    pdf_v3_snapshot,
    rma,
    t3,
    vader_crypto_sentiment,
    vidya,
    volume_profile_nodes,
)


def _sample_df(n: int = 160, seed: int = 17, drift: float = 0.15) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, 0.75, n)
    close = 100.0 + np.cumsum(steps)
    close = np.maximum(close, 10.0)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    spread = np.abs(rng.normal(0.55, 0.2, n)) + 0.12
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.uniform(500.0, 4000.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol}
    )


def test_adaptive_and_ribbon_indicators_have_no_lookahead() -> None:
    df_full = _sample_df(160, seed=21, drift=0.25)
    df_cut = df_full.iloc[:120].copy()

    # T3, VIDYA, JMA, RMA ve FRAMA prefix değişmezliği (lookahead yok)
    for fn in (rma, t3, vidya, jma_approx):
        s_full = fn(df_full["close"])
        s_cut = fn(df_cut["close"])
        assert np.allclose(
            s_full.iloc[:120].to_numpy(),
            s_cut.to_numpy(),
            rtol=1e-9,
            atol=1e-9,
            equal_nan=True,
        )

    f_full = frama(df_full["high"], df_full["low"], df_full["close"], 16)
    f_cut = frama(df_cut["high"], df_cut["low"], df_cut["close"], 16)
    assert np.allclose(
        f_full.iloc[:120].to_numpy(),
        f_cut.to_numpy(),
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
    )

    snap_full_prefix = pdf_v3_snapshot(df_full.iloc[:120].reset_index(drop=True))
    snap_cut = pdf_v3_snapshot(df_cut.reset_index(drop=True))
    assert snap_full_prefix == snap_cut
    assert snap_cut["data_ready"] is True
    encoded = json.dumps(snap_cut, allow_nan=False)
    assert isinstance(encoded, str) and len(encoded) > 50


def test_oscillators_safezone_and_minimal_roi() -> None:
    df = _sample_df(140, seed=9, drift=0.3)
    rib = ema_ribbon_state(df["close"])
    assert -100.0 <= rib["score"] <= 100.0
    assert isinstance(rib["bull_stacked"], bool)

    st = classic_stochastic(df["high"], df["low"], df["close"])
    assert 0.0 <= st["stoch_fast_k"] <= 100.0
    assert 0.0 <= st["stoch_slow_d"] <= 100.0

    sm = ema_smoothed_oscillators(df)
    assert 0.0 <= sm["rsi_ema"] <= 100.0
    assert 0.0 <= sm["mfi_ema"] <= 100.0

    sz = elder_safezone_stop(df["high"], df["low"], df["close"])
    assert sz["safezone_long"] < float(df["close"].iloc[-1]) + 20.0
    assert sz["safezone_short"] > float(df["close"].iloc[-1]) - 20.0

    roi_hit = minimal_roi_exit_check(
        elapsed_sec=35.0 * 60.0,
        net_profit_pct=2.1,
        roi_table={0: 4.0, 30: 2.0, 60: 1.0},
    )
    assert roi_hit["should_exit"] is True
    assert roi_hit["target_pct"] == 2.0


def test_hvn_lvn_liquidation_clusters_and_flat_safety() -> None:
    df = _sample_df(120, seed=33)
    vp = volume_profile_nodes(df, bins=20)
    assert len(vp["hvn_levels"]) >= 1
    assert vp["in_lvn_vacuum"] in (True, False)

    liq = estimated_liquidation_clusters(df)
    last_close = float(df["close"].iloc[-1])
    if liq["long_liq_zones"]:
        assert liq["long_liq_zones"][0] < last_close
    if liq["short_liq_zones"]:
        assert liq["short_liq_zones"][0] > last_close

    # Düz (flat) seri NaN üretmemeli
    flat = pd.DataFrame(
        {
            "open": [50.0] * 100,
            "high": [50.0] * 100,
            "low": [50.0] * 100,
            "close": [50.0] * 100,
            "volume": [100.0] * 100,
        }
    )
    snap_flat = pdf_v3_snapshot(flat)
    assert snap_flat["data_ready"] is True
    json.dumps(snap_flat, allow_nan=False)


def test_orderbook_spoof_and_iceberg_tracker() -> None:
    tracker = OrderBookAnomalyTracker(wall_mult=3.0, window_sec=15.0)
    bids_t0 = [(100.0, 250.0), (99.9, 10.0), (99.8, 12.0), (99.7, 11.0), (99.6, 9.0)]
    asks_t0 = [(100.1, 10.0), (100.2, 12.0), (100.3, 11.0), (100.4, 9.0), (100.5, 10.0)]
    tracker.on_book(bids_t0, asks_t0, ts=1000.0)
    assert tracker.detect(now_ts=1000.0)["spoof_candidate"] == "YOK"

    # Duvar işlem görmeden 1.5 sn içinde silinirse -> spoof adayı
    bids_t1 = [(100.0, 5.0), (99.9, 10.0), (99.8, 12.0), (99.7, 11.0), (99.6, 9.0)]
    tracker.on_book(bids_t1, asks_t0, ts=1001.5)
    r1 = tracker.detect(now_ts=1001.5)
    assert r1["spoof_candidate"] == "SAHTE_ALIS_DUVARI_CEKILDI"

    # Görünür satış kademesine >2x alıcı vurmasına rağmen kademe erimiyorsa -> iceberg adayı
    tracker2 = OrderBookAnomalyTracker(wall_mult=3.0, window_sec=15.0)
    tracker2.on_book(bids_t1, asks_t0, ts=2000.0)
    tracker2.on_trade(price=100.1, qty=35.0, is_buyer_maker=False, ts=2001.0)
    tracker2.on_book(bids_t1, asks_t0, ts=2002.0)
    r2 = tracker2.detect(now_ts=2002.0)
    assert r2["iceberg_candidate"] == "GIZLI_SATICI_ICEBERG_ADAYI"


def test_statistical_regime_btc_corr_sentiment_calendar_and_montecarlo() -> None:
    df_alt = _sample_df(150, seed=5, drift=0.35)
    df_btc = _sample_df(150, seed=6, drift=0.20)

    reg = classify_statistical_regime(df_alt)
    assert reg["state"] in ("LOW_VOL_RANGE", "BULL_TREND", "BEAR_TREND", "HIGH_VOL_SHOCK")
    assert 0.0 <= reg["persistence_prob"] <= 1.0

    rel = btc_regime_and_correlation(df_alt, df_btc)
    assert rel["available"] is True
    assert -1.0 <= rel["corr_btc"] <= 1.0
    assert rel["btc_trend"] in ("BULL", "BEAR", "NEUTRAL")

    sent = vader_crypto_sentiment(
        "Massive institutional approved inflow rally breakout surge ath",
        contrarian_threshold=0.65,
    )
    assert sent["compound"] > 0.65
    assert sent["label"] == "BULLISH"
    assert sent["contrarian_signal"] == -1

    cal = MacroCalendarGuard(
        events=[CalendarEvent(name="FOMC Rate Decision", ts_utc=1_800_000_000.0, kind="MACRO")]
    )
    assert cal.check("BTC/USDT", now_ts=1_800_000_000.0 - 600.0)["blocked"] is True
    assert cal.check("BTC/USDT", now_ts=1_800_000_000.0 + 7200.0)["blocked"] is False

    pnls = [12.0, -5.0, 18.0, 9.0, -4.0, 15.0, -6.0, 21.0, 7.0, -3.0, 14.0, 11.0]
    perf = advanced_performance_metrics(pnls, start_balance=1000.0)
    assert perf["expectancy_usdt"] > 0
    assert perf["sharpe"] > 0

    mc = monte_carlo_drawdown(pnls, start_balance=1000.0, n_sims=200, seed=42)
    assert mc["mc_p95_dd_pct"] >= mc["mc_median_dd_pct"] >= 0.0


def test_derivatives_intel_engine_offline_mock() -> None:
    def fake_http(url: str, params: dict | None = None):
        if "premiumIndex" in url:
            return {"markPrice": "65130.0", "indexPrice": "65000.0", "lastFundingRate": "0.0006"}
        if "globalLongShortAccountRatio" in url:
            return [{"longShortRatio": "2.45"}]
        if "topLongShortPositionRatio" in url:
            return [{"longShortRatio": "0.88"}]
        if "takerlongshortRatio" in url:
            return [{"buySellRatio": "1.31"}]
        if "mark-price" in url:
            return {"data": [{"markPx": "65100.0"}]}
        if "funding-rate" in url:
            return {"data": [{"fundingRate": "0.0002"}]}
        if "long-short-account-ratio" in url:
            return {"data": [["1700000000000", "2.10"]]}
        if "get_volatility_index_data" in url:
            return {"result": {"data": [[1700000000000, 51.0, 53.0, 50.5, 52.4]]}}
        if "get_book_summary_by_currency" in url:
            return {
                "result": [
                    {"instrument_name": "BTC-29DEC26-70000-C", "open_interest": 1200.0},
                    {"instrument_name": "BTC-29DEC26-60000-P", "open_interest": 900.0},
                ]
            }
        return None

    eng = DerivativesIntelEngine(ttl_sec=60.0, http_get_json=fake_http)
    sym_intel = asyncio.run(eng.fetch_symbol_intel("BTC/USDT:USDT"))
    assert sym_intel["available"] is True
    assert abs(sym_intel["basis_pct"] - 0.2) < 1e-4
    assert abs(sym_intel["cross_funding_bps"] - 4.0) < 1e-4
    assert sym_intel["crowding"]["crowding_state"] == "LONG_KALABALIK"
    assert sym_intel["crowding"]["smart_money_divergence"] == "TOP_TRADER_SHORT_PERAKENDE_LONG"

    opt_intel = asyncio.run(eng.fetch_deribit_options_overview("BTC"))
    assert opt_intel["available"] is True
    assert opt_intel["dvol"] == 52.4
    assert opt_intel["put_call_oi_ratio"] == 0.75

    ext_empty = normalize_external_alpha(None)
    assert ext_empty["available"] is False
    assert ext_empty["onchain"]["mvrv_z"] is None

    verdict = compute_crowding_verdict(funding_rate=-0.0007, global_ls_ratio=0.55)
    assert verdict["crowding_state"] == "SHORT_KALABALIK"
