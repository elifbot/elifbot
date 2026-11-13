from __future__ import annotations

import pytest

from src.attribution import (
    build_entry_attribution,
    build_session_analysis,
    render_session_analysis,
)
from src.strategy import Strategy


def entry_context() -> dict:
    return {
        "side": "LONG",
        "indicators": {
            "score": 60.0,
            "active_components": {"rsi": 20.0},
            "active_score_unclipped": 60.0,
        },
        "orderflow": {
            "score": 0.0,
            "score_components": {},
            "score_unclipped": 0.0,
        },
        "decision_inputs": {
            "news_score": 0.0,
            "ml_score": 0.0,
            "veto": False,
            "veto_long": False,
            "veto_short": False,
        },
        "mtf": None,
    }


def test_leave_one_out_measures_decision_change_not_performance_cohort():
    strategy = Strategy(
        w_ind=0.6,
        w_flow=0.3,
        w_news=0.1,
        w_ml=0.0,
        long_th=30,
        short_th=-30,
    )
    result = build_entry_attribution(strategy, entry_context(), "LONG")
    rsi = result["technical"]["rsi"]
    assert rsi["decisive"] is True
    assert rsi["without_action"] != "LONG"
    assert result["modules"]["technical_all"]["decisive"] is True
    assert result["modules"]["orderflow_all"]["decisive"] is False


def test_session_analysis_separates_aligned_decisive_exchange_and_net_costs():
    context = entry_context()
    strategy = Strategy(
        w_ind=0.6,
        w_flow=0.3,
        w_news=0.1,
        w_ml=0.0,
        long_th=30,
        short_th=-30,
    )
    context["attribution"] = build_entry_attribution(strategy, context, "LONG")
    trade = {
        "symbol": "BTC/USDT",
        "side": "LONG",
        "exchange": "okx",
        "reason": "TRAILING",
        "pnl_usdt": 10.0,
        "entry_fee_usdt": 0.2,
        "exit_fee_usdt": 0.3,
        "funding_usdt": -0.1,
        "net_pnl_usdt": 9.4,
        "entry_context": context,
    }
    analysis = build_session_analysis([trade])
    assert analysis["overall"]["net_pnl_usdt"] == pytest.approx(9.4)
    assert analysis["exchanges"]["okx"]["count"] == 1
    assert analysis["exit_modules"]["TRAILING"]["count"] == 1
    assert analysis["aligned_components"]["rsi"]["count"] == 1
    assert analysis["decisive_components"]["rsi"]["count"] == 1
    assert analysis["coverage"]["with_attribution"] == 1

    analysis["exchange_evidence"] = {
        "catalog": {"binance": 0, "okx": 1},
        "errors": {"binance": "451 restricted location"},
        "rest": {"okx": {"ohlcv_success": 2, "ohlcv_errors": 0, "paper_fills": 2}},
        "websocket": {"okx": {"trade_messages": 5, "book_messages": 3}},
    }
    report = render_session_analysis(analysis)
    assert "YETERSİZ VERİ" in report
    assert "LEAVE-ONE-OUT" in report
    assert "OKX" in report and "paper fill=2" in report
    assert "451 restricted location" in report


def test_dynamic_runner_reasons_share_one_exit_module_cohort():
    rows = [
        {"reason": "KÂR KOŞUSU: LONG SATIŞ BASKISI ($1.000, zirve %1)", "pnl_usdt": 2.0},
        {"reason": "KÂR KOŞUSU: SHORT ALIŞ BASKISI ($2.000, dip %2)", "pnl_usdt": 3.0},
    ]
    analysis = build_session_analysis(rows)
    module = analysis["exit_modules"]["KÂR KOŞUSU — ORDER-FLOW DÖNÜŞÜ"]
    assert module["count"] == 2
    assert module["net_pnl_usdt"] == pytest.approx(5.0)
    assert len(analysis["exit_modules"]) == 1
