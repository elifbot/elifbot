from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.backtest import EventDrivenBacktester, MarketEvent, SignalEvent
from src.config import ConfigError, load_config
from src.executor import Executor
from src.moneyflow import MoneyFlow
from src.risk import Position, RiskManager
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from tests._paper_fixtures import FixturePaperBroker

ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "BTC/USDT"
PLAN_CFG = {
    "aktif": True,
    "atr_stop_katsayi": 1.5,
    "swing_mum": 20,
    "swing_atr_buffer": 0.2,
    "max_stop_yuzde": 12.0,
    "tp1_r": 1.0,
    "tp2_r": 2.0,
    "tp1_kapatma_orani": 0.5,
}


def run(coro):
    return asyncio.run(coro)


class EntryBroker(FixturePaperBroker):
    """Use the same real synthetic ledger for entry, fees and restore."""
    pass


class CloseBroker:
    mode = "live"

    def __init__(self, fill_price):
        self.fill_price = fill_price
        self.calls = []

    async def market_order(self, symbol, side, qty, **kwargs):
        self.calls.append({"symbol": symbol, "side": side, "qty": qty, **kwargs})
        return {"qty": qty, "price": self.fill_price}

    async def cancel_protection(self, symbol, prot, exchange=None):
        return True


def test_atr_structure_reduces_leverage_and_sizes_by_actual_risk(tmp_path):
    risk = RiskManager(dynamic_leverage_enabled=False)
    pure = risk.atr_structure_plan("LONG", 100, 1, 20, swing_low=98)
    assert pure["accepted"] is True
    assert pure["stop"] == pytest.approx(97.8)  # swing - 0.2 ATR; daraltılmadı
    assert pure["source"] == "ATR+SWING"

    store = StateStore(tmp_path / "entry.db")
    broker = EntryBroker()
    sizer = PositionSizer(mode="kasa_10_20x", capital_pct=10, leverage=20)
    executor = Executor(
        broker,
        risk,
        Strategy(),
        sizer=sizer,
        state_store=store,
        protection_on=False,
        trade_plan_cfg=PLAN_CFG,
    )
    executor.set_atr(SYMBOL, 3.0)  # 4.5% stop, 20x likidasyon tamponuna sığmaz
    executor.set_market_structure(SYMBOL, None, None)
    run(executor._open(SYMBOL, "LONG", 100, "ATR TEST"))

    pos = executor.positions[SYMBOL]
    assert pos.leverage == 10
    assert broker.entry["leverage"] == 10
    assert pos.stop == pytest.approx(95.5)
    assert pos.qty == pytest.approx(10.0 / 4.5)  # 1000 USDT × %1 / 4.5 USDT
    plan = executor.get_trade_plan(SYMBOL)
    assert plan["tp1"] == pytest.approx(104.5)
    assert plan["tp2"] == pytest.approx(109.0)
    assert store.get_meta("trade_plans", {})[SYMBOL]["initial_risk"] == pytest.approx(4.5)

    restored = Executor(
        EntryBroker(), risk, Strategy(), state_store=store, trade_plan_cfg=PLAN_CFG
    )
    assert restored.get_trade_plan(SYMBOL)["tp2"] == pytest.approx(109.0)


def test_excessively_wide_structure_stop_is_rejected_not_clamped():
    plan = RiskManager().atr_structure_plan("SHORT", 100, 10, 20)
    assert plan["accepted"] is False
    assert "maksimum" in plan["reason"]
    assert "stop" not in plan


def test_tp1_partial_breakeven_survives_restart_then_tp2_cleans_plan(tmp_path):
    store = StateStore(tmp_path / "tp.db")
    broker = CloseBroker(fill_price=104.5)
    executor = Executor(
        broker,
        RiskManager(),
        Strategy(),
        state_store=store,
        protection_on=False,
        trade_plan_cfg=PLAN_CFG,
    )
    pos = Position(SYMBOL, "LONG", 100, 2, 95.5, leverage=10, margin_usdt=20)
    executor.positions[SYMBOL] = pos
    executor._trade_plans[SYMBOL] = executor._make_position_plan(
        "LONG", 100, 95.5, source="ATR"
    )
    executor._save_trade_plans()
    store.save_position(pos)

    run(executor.on_price_tick(SYMBOL, 104.5))
    assert broker.calls[0]["qty"] == pytest.approx(1.0)
    assert pos.qty == pytest.approx(1.0)
    assert pos.stop == pytest.approx(100.0)
    assert executor.get_trade_plan(SYMBOL)["tp1_hit"] is True
    assert store.load_positions()[SYMBOL].stop == pytest.approx(100.0)

    restarted_broker = CloseBroker(fill_price=109.0)
    restarted = Executor(
        restarted_broker,
        RiskManager(),
        Strategy(),
        state_store=store,
        protection_on=False,
        trade_plan_cfg=PLAN_CFG,
    )
    run(restarted.on_price_tick(SYMBOL, 104.6))
    assert restarted_broker.calls == []  # TP1 restart'ta ikinci kez kapatılmadı
    assert restarted.get_trade_plan(SYMBOL)["tp1_hit"] is True

    run(restarted.on_price_tick(SYMBOL, 109.0))
    assert len(restarted_broker.calls) == 1
    assert restarted.positions == {}
    assert restarted.get_trade_plan(SYMBOL) is None
    assert store.get_meta("trade_plans", {}) == {}
    assert len(store.get_trades()) == 2


def test_cvd_bearish_divergence_and_long_veto():
    flow = MoneyFlow(SYMBOL, absorption_min_usdt=1e12)
    now = time.time()
    for i in range(5):
        flow.add_trade(100, 1, False, ts=now - 100 + i * 10)
    for i in range(5):
        flow.add_trade(101, 1, True, ts=now - 40 + i * 10)
    snap = flow.snapshot()
    assert snap["cvd_divergence"] == "BEARISH"

    decision = Strategy(w_ind=1, w_flow=0, w_news=0).combine(
        80,
        0,
        0,
        market_context={"regime_aware": False, "cvd_divergence": "BEARISH"},
    )
    assert decision["raw_signal"] == "LONG"
    assert decision["signal"] == "BEKLE"
    assert "divergence" in decision["orderflow_veto"]


def test_sell_absorption_requires_price_hold_and_bid_depth():
    flow = MoneyFlow(SYMBOL, absorption_min_usdt=100)
    now = time.time()
    flow.update_book([[99, 10]], [[101, 10]], ts=now - 50)
    for i in range(12):
        flow.add_trade(100, 0.1, True, ts=now - 45 + i * 2)
    flow.add_trade(100, 0.1, False, ts=now - 20)
    flow.update_book([[99, 12]], [[101, 10]], ts=now - 5)
    snap = flow.snapshot()
    assert snap["absorption"] == "SATIS_EMILIMI"
    assert snap["absorption_sell_usdt"] == pytest.approx(120.0)
    assert snap["absorption_depth_change_pct"] == pytest.approx(20.0)


def test_tick_vpvr_uses_trade_prices_and_reports_warmup():
    flow = MoneyFlow(SYMBOL, vpvr_bins=10)
    now = time.time()
    for i in range(120):
        dominant = i < 100
        flow.add_trade(
            100.0 if dominant else 110.0,
            1.0 if dominant else 0.1,
            False,
            ts=now - 400 + i * 3,
        )
    profile = flow.tick_volume_profile()
    assert profile["vpvr_source"] == "TICK_VPVR"
    assert profile["vpvr_trades"] == 120
    assert profile["vpvr_coverage_sec"] >= 300
    assert profile["vpvr_warm"] is True
    assert 100.0 <= profile["vpvr_poc"] < 101.0
    assert profile["vpvr_val"] <= profile["vpvr_poc"] <= profile["vpvr_vah"]


def test_event_backtest_atr_risk_and_partial_tp_accounting():
    engine = EventDrivenBacktester(
        initial_balance=1000,
        use_ml=False,
        fee_pct=0,
        slippage_bps=0,
        funding_8h_pct=0,
        trade_plan_cfg=PLAN_CFG,
    )
    engine._last_atr = 3.0
    engine._swing_low = None
    engine._swing_high = None
    engine._handle_signal_event(SignalEvent(0, SYMBOL, "LONG", 80, 100, "ATR TEST"))
    order = engine.events.popleft()
    assert order.leverage == 10
    assert order.qty == pytest.approx(10.0 / 4.5)
    assert order.trade_plan["stop"] == pytest.approx(95.5)
    engine._handle_order_event(order)
    engine._handle_fill_event(engine.events.popleft())
    original_qty = engine.pos.qty
    assert engine.pos.stop == pytest.approx(95.5)

    history = pd.DataFrame(
        {
            "open": [100.0] * 61,
            "high": [101.0] * 61,
            "low": [99.0] * 61,
            "close": [100.0] * 61,
            "volume": [100.0] * 61,
        }
    )
    engine._handle_market_event(
        MarketEvent(1, 1, 100, 100, 104.5, 104.5, 100), history
    )
    tp1_order = engine.events.popleft()
    assert "TP1" in tp1_order.reason
    engine._handle_order_event(tp1_order)
    engine._handle_fill_event(engine.events.popleft())
    assert engine.pos.qty == pytest.approx(original_qty / 2)
    assert engine.pos.stop == pytest.approx(100.0)
    assert engine.trades[-1]["partial"] is True
    assert engine._trade_plan["tp1_hit"] is True

    engine._handle_market_event(
        MarketEvent(2, 2, 104.5, 104.5, 109.0, 109.0, 100), history
    )
    tp2_order = engine.events.popleft()
    assert "TP2" in tp2_order.reason
    engine._handle_order_event(tp2_order)
    engine._handle_fill_event(engine.events.popleft())
    assert engine.pos is None
    assert engine._trade_plan is None
    assert engine.trades[-1]["partial"] is False
    assert len(engine.trades) == 2


def test_trade_plan_config_rejects_inverted_r_targets(tmp_path, monkeypatch):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["islem_plani"]["tp1_r"] = 2.0
    cfg["islem_plani"]["tp2_r"] = 1.0
    path = tmp_path / "bad-plan.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.delenv("MODE", raising=False)
    with pytest.raises(ConfigError, match="tp2_r"):
        load_config(path)
