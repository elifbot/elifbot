from __future__ import annotations

import pytest

from src.cohort_report import (
    build_cohort_report,
    entry_rationale,
    is_manual_close,
    render_cohort_report,
    split_cohorts,
)


def context() -> dict:
    return {
        "indicators": {
            "score": 60.0,
            "active_components": {"rsi": 20.0, "macd": -4.0},
        },
        "orderflow": {
            "score": 10.0,
            "score_components": {"taker_delta": 8.0, "whale_balance": -2.0},
        },
        "decision_inputs": {"news_score": 0.0, "ml_score": 5.0},
        "mtf": {"trend": "BULLISH"},
        "combined": {"signal": "LONG", "total": 65.0, "regime": "TREND"},
        "attribution": {
            "technical": {"rsi": {"decisive": True}},
            "orderflow": {"taker_delta": {"decisive": False}},
        },
    }


def trade(reason: str, position_id: str, net: float) -> dict:
    return {
        "position_id": position_id,
        "symbol": "BTC/USDT",
        "side": "LONG",
        "exchange": "binance",
        "entry": 100.0,
        "exit_price": 110.0,
        "leverage": 10,
        "margin_usdt": 50.0,
        "reason": reason,
        "pnl_usdt": net,
        "net_pnl_usdt": net,
        "entry_context": context(),
    }


def test_manual_and_bot_cohorts_have_separate_reporting():
    bot = trade("TRAILING", "bot-1", 9.4)
    manual = trade("SÜRELİ PAPER ÖLÇÜMÜ SONU", "manual-1", -100.0)
    bot_rows, manual_rows = split_cohorts([bot, manual])
    assert bot_rows == [bot]
    assert manual_rows == [manual]

    report = build_cohort_report([bot, manual])
    assert report["coverage"] == {
        "total_closed": 2,
        "bot_closed": 1,
        "manual_closed": 1,
    }
    assert report["bot_closed_analysis"]["overall"]["count"] == 1
    assert report["bot_closed_analysis"]["overall"]["net_pnl_usdt"] == pytest.approx(9.4)
    assert report["reconciliation"]["net_pnl_usdt"] == pytest.approx(-90.6)
    assert len(report["bot_closed_trades"]) == 1
    bot_detail = report["bot_closed_trades"][0]
    assert bot_detail["position_id"] == "bot-1"
    assert bot_detail["entry_price"] == 100.0
    assert bot_detail["exit_price"] == 110.0
    assert bot_detail["net_pnl_usdt"] == pytest.approx(9.4)
    assert bot_detail["technical_support"] == {"rsi": 20.0}
    assert len(report["manual_entries"]) == 1
    entry = report["manual_entries"][0]
    assert entry["position_id"] == "manual-1"
    assert entry["technical_support"] == {"rsi": 20.0}
    assert entry["orderflow_support"] == {"taker_delta": 8.0}
    assert entry["module_support"] == {
        "technical_all": 60.0,
        "orderflow_all": 10.0,
        "ml_score": 5.0,
        "mtf_filter": "BULLISH",
    }
    assert entry["decisive_leave_one_out"] == ["rsi"]
    assert "pnl_usdt" not in entry and "exit_price" not in entry

    text = render_cohort_report(report)
    assert "BOTUN KENDİ KAPATTIĞI" in text
    assert "MANUEL/ERKEN KAPANANLAR" in text
    assert "bot-1" in text and "çıkış=110" in text and "net=+9.40 USDT" in text
    assert "GENEL PAPER KASA MUTABAKATI" in text
    assert "manual-1" in text and "rsi=+20" in text
    assert "mtf_filter=BULLISH" in text


def test_manual_markers_include_kill_web_and_partial_session_close():
    assert is_manual_close(trade("TELEGRAM /kill ACİL KAPAMA", "x", 0))
    assert is_manual_close(trade("WEB PANELİ MANUEL KAPAMA", "x", 0))
    assert is_manual_close(
        trade("KISMİ KAPAMA — SÜRELİ PAPER ÖLÇÜMÜ SONU", "x", 0)
    )
    assert not is_manual_close(trade("WS >10 SN KOPMA SİGORTASI", "x", 0))


def test_short_entry_support_uses_direction_and_handles_empty_cohorts():
    row = trade("TELEGRAM /kill ACİL KAPAMA", "short-1", 0)
    row["side"] = "SHORT"
    row["entry_context"] = context()
    row["entry_context"]["mtf"]["trend"] = "BEARISH"
    rationale = entry_rationale(row)
    assert rationale["technical_support"] == {"macd": 4.0}
    assert rationale["orderflow_support"] == {"whale_balance": 2.0}
    assert rationale["module_support"]["mtf_filter"] == "BEARISH"
    empty = build_cohort_report([])
    assert empty["coverage"]["total_closed"] == 0
    assert "Manuel/erken kapanış yok" in render_cohort_report(empty)
