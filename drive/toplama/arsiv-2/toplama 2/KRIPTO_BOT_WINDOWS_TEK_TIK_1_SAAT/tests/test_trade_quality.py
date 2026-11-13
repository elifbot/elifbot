import pytest

from src.trade_quality import (
    flow_confidence,
    portfolio_guard,
    range_flow_gate,
    technical_harmony,
    volatility_quality,
)


FLOW_CFG = {
    "pencere_saniye": 300,
    "referans_notional_usdt": 1000,
    "referans_cvd_usdt": 100,
    "min_islem_sayisi": 5,
    "min_kapsama_saniye": 60,
    "max_defter_yasi_saniye": 10,
}


def _flow(total, cvd, trades=100, coverage=300):
    return {
        "buy_usdt": total * 0.75,
        "sell_usdt": total * 0.25,
        "trade_count": trades,
        "window_coverage_sec": coverage,
        "book_levels": 20,
        "book_age_sec": 0.2,
        "cvd_slope": cvd,
        "score": 56,
        "score_unclipped": 56,
        "score_components": {"taker_delta": 42, "cvd_direction": 14},
    }


def test_flow_confidence_penalizes_small_evidence_and_checks_readiness():
    small = flow_confidence(_flow(25, 6), FLOW_CFG)
    large = flow_confidence(_flow(100000, 10000), FLOW_CFG)
    assert small["taker_confidence"] < large["taker_confidence"]
    assert small["cvd_confidence"] < large["cvd_confidence"]
    assert small["adjusted_flow_score"] < large["adjusted_flow_score"]
    assert large["adjusted_flow_score"] == pytest.approx(56, abs=0.1)

    stale = flow_confidence(
        {**_flow(100000, 10000), "book_age_sec": 30}, FLOW_CFG
    )
    assert not stale["data_ready"]
    assert any("defter yaşı" in row for row in stale["data_missing"])


def test_volatility_regime_and_technical_conflict_measurements():
    low = volatility_quality(
        {"snapshot": {"price": 100, "bollinger_bandwidth_pct": 0.10, "atr_pct": 0.04}},
        {"min_bb_genisligi_yuzde": 0.20, "min_atr_yuzde": 0.0},
    )
    high = volatility_quality(
        {"snapshot": {"price": 100, "bollinger_bandwidth_pct": 1.2, "atr_pct": 0.8}},
        {"min_bb_genisligi_yuzde": 0.20, "min_atr_yuzde": 0.0},
    )
    assert not low["accepted"]
    assert high["accepted"]
    assert high["bb_cost_ratio"] > 0

    context = {
        "indicators": {
            "regime": "RANGE",
            "score": 20,
            "active_components": {"ema_trend": 20, "session_vwap": -10, "macd": -5},
        },
        "combined": {"raw_signal": "BEKLE", "trigger": "PARA_GIRISI"},
    }
    assert not range_flow_gate(context)["accepted"]
    harmony = technical_harmony(context, "LONG", max_opposed=1)
    assert not harmony["accepted"]
    assert harmony["opposed_count"] == 2


def test_portfolio_guard_limits_same_side_correlated_cluster():
    returns = {
        "AAA/USDT": [0.01, -0.02, 0.03, 0.00, 0.02],
        "BBB/USDT": [0.01, -0.02, 0.03, 0.00, 0.02],
        "CCC/USDT": [0.01, -0.02, 0.03, 0.00, 0.02],
    }
    open_entries = [
        {"symbol": "AAA/USDT", "side": "LONG"},
        {"symbol": "BBB/USDT", "side": "LONG"},
    ]
    result = portfolio_guard(
        "CCC/USDT",
        "LONG",
        open_entries,
        returns,
        {
            "ayni_yon_max_pozisyon": 50,
            "korelasyon_esik": 0.8,
            "korelasyon_max_pozisyon": 2,
            "korelasyon_min_ortak_getiri": 5,
        },
    )
    assert not result["accepted"]
    assert result["highly_correlated_count"] == 2
