import json

import numpy as np
import pandas as pd
import pytest

from src.pdf_indicators import (
    accumulation_distribution,
    choppiness,
    cmf,
    dema,
    fair_value_gap,
    hma,
    hurst_exponent,
    kama,
    pdf_v2_snapshot,
    tema,
    trix,
    volatility_pack,
    wavetrend,
)
from src.risk import RiskManager
from src.shadow_lab import ShadowLab
from src.strategy import Strategy
from src.trade_quality import pdf_confluence


def make_df(n=180, trend=0.0, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.arange(n) * trend + np.cumsum(rng.normal(0, 0.35, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.random(n) * 0.8 + 0.1
    low = np.minimum(open_, close) - rng.random(n) * 0.8 - 0.1
    volume = rng.random(n) * 1000 + 100
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_pdf_snapshot_is_json_safe_and_has_expected_families():
    snapshot = pdf_v2_snapshot(make_df(trend=0.08))
    assert snapshot["data_ready"] is True
    assert set(snapshot["family_votes"]) == {"trend", "momentum", "volume", "structure", "regime"}
    assert len(snapshot["values"]) >= 60
    json.dumps(snapshot, allow_nan=False)
    assert 0 <= snapshot["values"]["hurst"] <= 1
    assert 0 <= snapshot["values"]["choppiness"] <= 100
    assert snapshot["values"]["parkinson_volatility_pct"] >= 0
    assert snapshot["values"]["garman_klass_volatility_pct"] >= 0


def test_pdf_snapshot_has_no_future_candle_dependency():
    df = make_df()
    prefix = df.iloc[:120].reset_index(drop=True)
    # Tam seriyle hesaplanan geçmiş nokta, o noktaya kadar kesilmiş seriyle aynı olmalı.
    for function in (kama, hma, dema, tema, trix):
        full_value = function(df["close"]).iloc[119]
        prefix_value = function(prefix["close"]).iloc[-1]
        assert full_value == pytest.approx(prefix_value, rel=1e-10, abs=1e-10)
    full_wt1, full_wt2 = wavetrend(df)
    prefix_wt1, prefix_wt2 = wavetrend(prefix)
    assert full_wt1.iloc[119] == pytest.approx(prefix_wt1.iloc[-1])
    assert full_wt2.iloc[119] == pytest.approx(prefix_wt2.iloc[-1])


def test_constant_series_and_moving_averages_remain_finite():
    df = make_df(trend=0)
    df.loc[:, ["open", "high", "low", "close"]] = 100.0
    close = df["close"]
    for series in (kama(close), hma(close), dema(close), tema(close)):
        assert np.isfinite(series.iloc[-1])
        assert series.iloc[-1] == pytest.approx(100.0)
    assert hurst_exponent(close) == pytest.approx(0.5)
    assert choppiness(df).iloc[-1] == pytest.approx(50.0)
    assert cmf(df).iloc[-1] == pytest.approx(0.0)
    assert np.isfinite(accumulation_distribution(df).iloc[-1])
    assert all(value >= 0 for value in volatility_pack(df).values())
    json.dumps(pdf_v2_snapshot(df), allow_nan=False)


def test_fvg_uses_only_three_closed_candles():
    df = pd.DataFrame(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},
            {"open": 100, "high": 102, "low": 100, "close": 101, "volume": 10},
            {"open": 103, "high": 105, "low": 103, "close": 104, "volume": 10},
        ]
    )
    result = fair_value_gap(df)
    assert result["fvg_direction"] == 1
    assert result["fvg_lower"] == pytest.approx(101)
    assert result["fvg_upper"] == pytest.approx(103)


def test_pdf_confluence_requires_four_aligned_families_and_is_directional():
    context = {
        "indicators": {
            "pdf_v2": {
                "data_ready": True,
                "family_votes": {"trend": 1, "momentum": 1, "volume": 1, "structure": 1, "regime": 0},
            }
        },
        "orderflow": {"score": 12, "trade_count": 30, "book_levels": 20},
    }
    config = {"pdf_confluence": {"min_aligned_families": 4, "max_opposed_families": 2}}
    accepted = pdf_confluence(context, "LONG", config)
    assert accepted["accepted"] is True
    assert accepted["aligned_count"] == 5
    assert accepted["external_data_used"] is False
    assert pdf_confluence(context, "SHORT", config)["accepted"] is False
    context["indicators"]["pdf_v2"]["family_votes"]["structure"] = 0
    context["orderflow"]["score"] = 0
    assert pdf_confluence(context, "LONG", config)["accepted"] is False


def test_pdf_shadow_variant_is_opt_in_and_preserves_default_variant_set():
    def build(pdf_enabled):
        return ShadowLab(
            strategy=Strategy(),
            baseline_risk=RiskManager(stop_model="marj", margin_stop_fraction=0.8, leverage=10),
            runner_exit_cfg={},
            supertrend_trailing=True,
            fee_cfg={},
            config={"pdf_confluence": {"aktif": pdf_enabled}},
        )

    assert "pdf-confluence" not in build(False).variants
    assert "pdf-confluence" in build(True).variants
    assert len(build(False).variants) == 6
    assert len(build(True).variants) == 7
