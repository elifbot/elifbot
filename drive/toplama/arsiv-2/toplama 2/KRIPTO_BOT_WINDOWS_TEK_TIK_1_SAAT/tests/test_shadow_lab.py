import json

import pytest

from src.risk import Position, RiskManager
from src.shadow_lab import ShadowLab, render_shadow_report
from src.state_store import StateStore
from src.strategy import Strategy


def _context():
    return {
        "indicators": {
            "score": 20,
            "regime": "TREND",
            "entry_allowed": True,
            "regime_aware": True,
            "active_components": {"ema_trend": 20, "session_vwap": -10, "macd": -5},
            "snapshot": {"price": 100, "bollinger_bandwidth_pct": 1.2, "atr_pct": 0.8},
        },
        "combined": {"raw_signal": "BEKLE", "trigger": "PARA_GIRISI"},
        "orderflow": {
            "score": 56,
            "score_unclipped": 56,
            "score_components": {
                "taker_delta": 42, "cvd_direction": 14,
                "whale_balance": 0, "orderbook_depth": 0,
                "oi_liquidation": 0, "volume_spike": 0,
            },
            "buy_usdt": 75000,
            "sell_usdt": 25000,
            "trade_count": 100,
            "window_coverage_sec": 300,
            "book_levels": 20,
            "book_age_sec": 0.1,
            "cvd_slope": 10000,
            "cvd_divergence": "YOK",
            "absorption": "YOK",
            "oi_signal": "NOTR",
        },
        "decision_inputs": {"news_score": 0, "ml_score": 0, "veto": False},
        "mtf": {"trend": "BULLISH", "allow_long": True, "allow_short": False},
    }


def _lab():
    return ShadowLab(
        strategy=Strategy(
            w_ind=0.4, w_flow=0.25, w_news=0.2, w_ml=0.15,
            flow_trigger=True, flow_th=50, flow_ind_min=10, flow_min_total=15,
        ),
        baseline_risk=RiskManager(
            stop_model="marj", margin_stop_fraction=0.8, leverage=10, trail_pct=5,
        ),
        runner_exit_cfg={"kosan_kar": True, "orderflow_min_kar_yuzde": 0.5},
        supertrend_trailing=True,
        fee_cfg={"komisyon_maker_yuzde": 0.02, "komisyon_taker_yuzde": 0.05},
        config={
            "sanal_kasa_usdt": 100000,
            "max_karsi_teknik_bilesen": 1,
            "flow": {
                "pencere_saniye": 300, "referans_notional_usdt": 1000,
                "referans_cvd_usdt": 100, "min_islem_sayisi": 5,
                "min_kapsama_saniye": 60, "max_defter_yasi_saniye": 10,
            },
            "volatility": {"min_bb_genisligi_yuzde": 0.2, "min_atr_yuzde": 0},
            "portfolio": {
                "ayni_yon_max_pozisyon": 50, "korelasyon_esik": 0.8,
                "korelasyon_max_pozisyon": 3, "korelasyon_min_ortak_getiri": 20,
            },
        },
    )


def _open(lab):
    pos = Position(
        symbol="BTC/USDT:USDT", side="LONG", entry=100, qty=5, stop=92,
        leverage=10, margin_usdt=50, exchange="binance",
        entry_fee_usdt=0.10, exit_fee_pct=0.05,
    )
    lab.on_baseline_open(pos.symbol, pos, "position-1", _context(), {})
    return pos


def _trade(exit_price=102, reason="SÜRELİ PAPER ÖLÇÜMÜ SONU"):
    gross = (exit_price - 100) * 5
    exit_fee = exit_price * 5 * 0.0005
    return {
        "ts": 123456.0, "position_id": "position-1", "symbol": "BTC/USDT:USDT",
        "side": "LONG", "entry": 100, "exit_price": exit_price, "qty": 5,
        "leverage": 10, "margin_usdt": 50, "pnl_pct": (exit_price - 100),
        "roe_pct": (exit_price - 100) * 10, "pnl_usdt": gross,
        "reason": reason, "layers": 1, "entry_context": _context(),
        "exchange": "binance", "entry_fee_usdt": 0.1,
        "exit_fee_usdt": exit_fee, "funding_usdt": 0,
        "net_pnl_usdt": gross - 0.1 - exit_fee,
        "mfe_usdt": gross, "mae_usdt": 0, "stop_price": 92,
    }


def test_paired_mirrors_and_forced_net_exit_reconcile_balances():
    lab = _lab()
    pos = _open(lab)
    assert lab.variants["technical-harmony"]["rejected_count"] == 1
    trade = _trade()
    trade["entry_context"]["ml"] = {"nonfinite": float("nan")}
    lab.on_baseline_close(pos.symbol, pos, trade, True)
    report = lab.report()
    json.dumps(report, allow_nan=False)
    assert report["closeout_completed"]
    by_name = {row["name"]: row for row in report["variants"]}
    assert by_name["technical-harmony"]["analysis"]["overall"]["count"] == 0
    for name in ("net-exit", "flow-confidence", "volatility-gate", "range-confirmation", "portfolio-guard"):
        row = by_name[name]
        assert row["analysis"]["overall"]["count"] == 1
        assert row["analysis"]["overall"]["net_pnl_usdt"] == pytest.approx(9.645)
        assert row["balance_reconciliation_error"] == pytest.approx(0, abs=1e-9)
    assert "Shadow Lab" in render_shadow_report(report)


def test_net_exit_can_diverge_from_baseline_and_close_independently():
    lab = _lab()
    pos = _open(lab)
    lab.on_price_tick(pos.symbol, 106)
    net_pos = lab.variants["net-exit"]["entries"][pos.symbol]
    assert net_pos.stop > 100
    baseline_trade = _trade(exit_price=106, reason="KÂR KOŞUSU: LONG SATIŞ BASKISI")
    lab.on_baseline_close(pos.symbol, pos, baseline_trade, True)
    assert pos.symbol in lab.variants["net-exit"]["entries"]
    assert lab.divergent_after_baseline_close == 1

    lab.on_price_tick(pos.symbol, 100.5)
    net_trades = lab.variants["net-exit"]["trades"]
    assert len(net_trades) == 1
    assert net_trades[0]["exit_price"] == 100.5
    assert net_trades[0]["reason"].startswith("TRAILING")
    lab.close_all("TEST SONU")
    report = lab.report()
    assert report["closeout_completed"]
    assert all(row["balance_reconciliation_error"] == pytest.approx(0, abs=1e-9) for row in report["variants"])


def test_trade_history_persists_exit_measurements(tmp_path):
    store = StateStore(tmp_path / "state.db")
    store.record_trade(
        symbol="BTC/USDT:USDT", side="LONG", entry=100, exit_price=102,
        qty=5, pnl_pct=2, reason="TEST", leverage=10, margin_usdt=50,
        pnl_usdt=10, entry_fee_usdt=0.1, exit_fee_usdt=0.255,
        funding_usdt=0.01, net_pnl_usdt=9.655,
        mfe_usdt=12, mae_usdt=-1.5, stop_price=100.2,
        net_breakeven_price=100.07, ts=12345,
    )
    row = store.get_trades_since(12340)[0]
    assert row["mfe_usdt"] == 12
    assert row["mae_usdt"] == -1.5
    assert row["stop_price"] == 100.2
    assert row["net_breakeven_price"] == 100.07
    assert row["ts"] == 12345
