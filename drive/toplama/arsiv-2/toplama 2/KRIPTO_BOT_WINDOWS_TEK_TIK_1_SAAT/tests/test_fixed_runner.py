from __future__ import annotations

import asyncio
import json
import time

import pytest

from src.backtest import EventDrivenBacktester, SignalEvent
from src.executor import Executor
from src.moneyflow import MoneyFlow
from src.risk import Position, RiskManager, position_limits_for_mode
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy

SYMBOL = "BTC/USDT"
RUNNER_CFG = {
    "kosan_kar": True,
    "orderflow_kontrol_saniye": 0.1,
    "orderflow_min_kar_yuzde": 0.5,
    "orderflow_orani": 1.5,
    "orderflow_min_usdt": 1000.0,
    "orderflow_min_geri_cekilme_yuzde": 0.05,
}


def run(coro):
    return asyncio.run(coro)


class FixedBroker:
    mode = "paper"
    primary = "binance"

    def __init__(self):
        self.entry = None
        self.market_calls = []

    async def fetch_balance_usdt(self):
        return 1000.0

    async def best_price(self, symbol, side):
        return "binance", 100.0

    async def execute_entry(self, symbol, side, qty, **kwargs):
        self.entry = {"qty": qty, **kwargs}
        return {"qty": qty, "price": 100.0, "emir_tipi": "market"}

    async def market_order(self, symbol, side, qty, **kwargs):
        self.market_calls.append({"symbol": symbol, "side": side, "qty": qty, **kwargs})
        return {"qty": qty, "price": kwargs.get("price_hint", 100.0)}

    async def place_protection(self, *args, **kwargs):
        return {"native": False, "kind": "bot"}

    async def cancel_protection(self, *args, **kwargs):
        return True


def fixed_executor(broker, store=None):
    risk = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        margin_stop_liq_buffer=0.85,
        leverage=10,
        dynamic_leverage_enabled=False,
        unlimited_pyramiding=False,
        max_layers=1,
    )
    sizer = PositionSizer(
        mode="sabit_usdt",
        fixed_margin_usdt=50,
        leverage=10,
        kelly_on=False,
    )
    return Executor(
        broker,
        risk,
        Strategy(runner_exit=True),
        sizer=sizer,
        state_store=store,
        protection_on=False,
        trade_plan_cfg={"aktif": False},
        runner_exit_cfg=RUNNER_CFG,
    )


def test_fixed_50_margin_10x_and_40_stop_for_both_sides():
    sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=50, leverage=10)
    qty, info = sizer.size(1000, 100, 92)
    assert qty == pytest.approx(5.0)
    assert info["margin_usdt"] == pytest.approx(50.0)
    assert info["notional"] == pytest.approx(500.0)
    assert sizer.size(49.99, 100, 92)[0] == 0

    risk = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        margin_stop_liq_buffer=0.85,
        leverage=10,
    )
    assert risk.effective_stop_pct(10) == pytest.approx(8.0)
    assert risk.initial_stop("LONG", 100, 10) == pytest.approx(92.0)
    assert risk.initial_stop("SHORT", 100, 10) == pytest.approx(108.0)
    assert qty * abs(100 - risk.initial_stop("LONG", 100, 10)) == pytest.approx(40.0)
    assert risk.effective_stop_pct(10) < 100 / 10 - risk.maintenance_margin_pct
    stopped = risk.update(Position(SYMBOL, "LONG", 100, 5, 92), 92)
    assert stopped["action"] == "close"
    assert stopped["pnl_usdt"] == pytest.approx(-40.0)
    assert stopped["reason"] == "STOP-LOSS (marjın %80)"


def test_trailing_cannot_turn_xbi_like_gain_into_early_margin_stop_loss():
    risk = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        margin_stop_liq_buffer=0.85,
        leverage=10,
        trail_pct=5.0,
    )
    entry = 149.0
    qty = 500.0 / entry
    initial_stop = risk.initial_stop("SHORT", entry, 10)
    pos = Position(
        "XBI/USDT", "SHORT", entry, qty, initial_stop,
        leverage=10, margin_usdt=50,
    )
    assert initial_stop == pytest.approx(160.92)

    early = risk.update(pos, 142.52)
    assert early["action"] == "hold"
    assert pos.stop == pytest.approx(initial_stop)  # 142.52 × 1.05 = 149.646 > giriş

    revisit = risk.update(pos, 149.66)
    assert revisit["action"] == "hold"
    assert revisit["pnl_usdt"] < 0
    assert pos.stop == pytest.approx(initial_stop)

    initial_hit = risk.update(pos, initial_stop)
    assert initial_hit["action"] == "close"
    assert initial_hit["reason"] == "STOP-LOSS (marjın %80)"
    assert initial_hit["pnl_usdt"] == pytest.approx(-40.0)

    trailed = Position(
        "XBI/USDT", "SHORT", entry, qty, initial_stop,
        leverage=10, margin_usdt=50,
    )
    risk.update(trailed, 141.80)  # 141.80 × 1.05 = 148.89 < giriş; artık kâr stopu
    assert trailed.stop == pytest.approx(148.89)
    # Stop kâr bölgesinde kurulduktan sonra fiyat gap ile girişin üstüne çıksa
    # bile neden, başlangıç %80 stopu değil gerçek trailing stopudur.
    trailing_hit = risk.update(trailed, 149.10)
    assert trailing_hit["action"] == "close"
    assert trailing_hit["reason"] == "TRAILING STOP"
    assert trailing_hit["pnl_usdt"] < 0


def test_long_trailing_and_supertrend_wait_for_breakeven():
    risk = RiskManager(stop_model="marj", leverage=10, trail_pct=5.0)
    pos = Position(SYMBOL, "LONG", 100, 5, 92, leverage=10, margin_usdt=50)
    risk.update(pos, 104.0)  # 104 × 0.95 = 98.8; hâlâ zarar bölgesinde
    assert pos.stop == pytest.approx(92.0)
    assert risk.update(pos, 99.0)["action"] == "hold"

    risk.update(pos, 106.0)  # 106 × 0.95 = 100.7; başabaş üstü trailing
    assert pos.stop == pytest.approx(100.7)
    closed = risk.update(pos, 99.50)  # gap/kayma ile zarar realizasyonu
    assert closed["reason"] == "TRAILING STOP"
    assert closed["pnl_usdt"] < 0

    executor = fixed_executor(FixedBroker())
    executor.supertrend_trailing = True
    st_pos = Position(SYMBOL, "LONG", 100, 5, 92, leverage=10, margin_usdt=50)
    executor.set_supertrend(SYMBOL, 1, 99.0)
    executor._apply_supertrend_trailing(SYMBOL, st_pos, 101.0)
    assert st_pos.stop == pytest.approx(92.0)
    executor.set_supertrend(SYMBOL, 1, 101.0)
    executor._apply_supertrend_trailing(SYMBOL, st_pos, 102.0)
    assert st_pos.stop == pytest.approx(101.0)


def test_paper_position_limit_scales_but_live_limits_stay_strict():
    cfg = {
        "max_pozisyon": 3,
        "mutlak_max_pozisyon": 6,
        "ayni_yon_max_pozisyon": 4,
        "paper_genis_pozisyon_limiti": True,
        "paper_max_pozisyon": 1000,
    }
    paper = position_limits_for_mode(cfg, "paper")
    assert paper == {
        "max_positions": 1000,
        "hard_max_positions": 1000,
        "max_same_side_positions": 1000,
    }
    for mode in ("live", "testnet"):
        assert position_limits_for_mode(cfg, mode) == {
            "max_positions": 3,
            "hard_max_positions": 6,
            "max_same_side_positions": 4,
        }

    risk = RiskManager(
        max_positions=1000,
        hard_max_positions=1000,
        max_same_side_positions=1000,
        max_total_margin_pct=60,
        unlimited_pyramiding=False,
    )
    assert risk.can_open(999, side="LONG", open_sides=["LONG"] * 999)[0] is True
    assert risk.can_open(1000, side="LONG", open_sides=["LONG"] * 1000)[0] is False
    assert risk.margin_cap_ok(59_950, 50, 100_000)[0] is True
    assert risk.margin_cap_ok(60_000, 50, 100_000)[0] is False


def test_executor_opens_fixed_position_without_tp_or_pyramiding():
    broker = FixedBroker()
    executor = fixed_executor(broker)
    run(executor._open(SYMBOL, "LONG", 100, "SABIT 50/40"))
    pos = executor.positions[SYMBOL]
    assert pos.qty == pytest.approx(5.0)
    assert pos.margin_usdt == pytest.approx(50.0)
    assert pos.leverage == 10
    assert pos.stop == pytest.approx(92.0)
    assert broker.entry["leverage"] == 10
    assert executor.get_trade_plan(SYMBOL) is None
    assert executor.risk.can_add_to_winner(pos, 110)[0] is False


def test_entry_context_is_linked_to_close_history(tmp_path):
    store = StateStore(tmp_path / "entry-context.db")
    broker = FixedBroker()
    executor = fixed_executor(broker, store=store)
    run(
        executor._open(
            SYMBOL,
            "LONG",
            100,
            "TEST GİRİŞİ",
            entry_context={
                "indicators": {"components": {"RSI": 12.5, "MACD": 8.0}},
                "mtf": {"trend": "BULLISH"},
                "ml": {"score": 4.0},
                "orderflow": {"cvd_slope": 20.0},
            },
        )
    )
    position_id = executor._position_meta[SYMBOL]["position_id"]
    run(executor._close(SYMBOL, 101, "TEST ÇIKIŞI", 1.0))
    row = store.get_trades()[0]
    assert row["position_id"] == position_id
    context = json.loads(row["entry_context"])
    assert context["indicators"]["components"]["RSI"] == 12.5
    assert context["mtf"]["trend"] == "BULLISH"
    assert context["entry_reason"] == "TEST GİRİŞİ"
    assert context["side"] == "LONG"


def test_long_selling_pressure_and_short_buying_pressure_close_symmetrically():
    long_broker = FixedBroker()
    long_executor = fixed_executor(long_broker)
    long_pos = Position(
        SYMBOL, "LONG", 100, 5, 92, peak=110, leverage=10, margin_usdt=50
    )
    long_executor.positions[SYMBOL] = long_pos
    long_snap = {
        "absorption_buy_usdt": 500,
        "absorption_sell_usdt": 3000,
        "cvd_60s": -100,
        "absorption": "YOK",
        "cvd_divergence": "BEARISH",
    }
    assert "SATIŞ" in long_executor.runner_exit_reason(long_pos, 109.8, long_snap)
    run(long_executor.maybe_orderflow_exit(SYMBOL, 109.8, long_snap))
    assert long_executor.positions == {}
    assert long_broker.market_calls[0]["side"] == "sell"
    assert long_executor.stats["runner_orderflow_exits"] == 1

    short_broker = FixedBroker()
    short_executor = fixed_executor(short_broker)
    short_pos = Position(
        SYMBOL, "SHORT", 100, 5, 108, peak=90, leverage=10, margin_usdt=50
    )
    short_executor.positions[SYMBOL] = short_pos
    short_snap = {
        "absorption_buy_usdt": 3000,
        "absorption_sell_usdt": 500,
        "cvd_60s": 100,
        "absorption": "YOK",
        "cvd_divergence": "BULLISH",
    }
    assert "ALIŞ" in short_executor.runner_exit_reason(short_pos, 90.2, short_snap)
    run(short_executor.maybe_orderflow_exit(SYMBOL, 90.2, short_snap))
    assert short_executor.positions == {}
    assert short_broker.market_calls[0]["side"] == "buy"


def test_absorbed_pressure_or_no_pullback_does_not_exit():
    executor = fixed_executor(FixedBroker())
    pos = Position(
        SYMBOL, "LONG", 100, 5, 92, peak=110, leverage=10, margin_usdt=50
    )
    snap = {
        "absorption_buy_usdt": 500,
        "absorption_sell_usdt": 3000,
        "cvd_60s": -100,
        "absorption": "SATIS_EMILIMI",
    }
    assert executor.runner_exit_reason(pos, 109.8, snap) is None
    assert executor.runner_exit_reason(pos, 110.0, {**snap, "absorption": "YOK"}) is None
    # Alışın emilimi, istenen agresif satış + CVD dönüşü olmadan Long kapatmaz.
    opposite_only = {
        "absorption_buy_usdt": 3000,
        "absorption_sell_usdt": 500,
        "cvd_60s": -100,
        "absorption": "ALIS_EMILIMI",
    }
    assert executor.runner_exit_reason(pos, 109.8, opposite_only) is None

    short_pos = Position(
        SYMBOL, "SHORT", 100, 5, 108, peak=90, leverage=10, margin_usdt=50
    )
    short_absorbed = {
        "absorption_buy_usdt": 3000,
        "absorption_sell_usdt": 500,
        "cvd_60s": 100,
        "absorption": "ALIS_EMILIMI",
    }
    assert executor.runner_exit_reason(short_pos, 90.2, short_absorbed) is None


def test_moneyflow_snapshot_feeds_runner_exit_without_vpvr_work():
    flow = MoneyFlow(SYMBOL, absorption_min_usdt=1e12)
    now = time.time()
    flow.add_trade(110, 1, False, ts=now - 30)
    for i in range(12):
        flow.add_trade(109.8, 1, True, ts=now - 20 + i)
    snap = flow.snapshot(include_vpvr=False)
    assert snap["cvd_60s"] < 0
    assert snap["absorption_sell_usdt"] >= 1000
    assert "vpvr_poc" not in snap

    executor = fixed_executor(FixedBroker())
    pos = Position(
        SYMBOL, "LONG", 100, 5, 92, peak=110, leverage=10, margin_usdt=50
    )
    assert executor.runner_exit_reason(pos, 109.8, snap) is not None


def test_runner_strategy_does_not_close_only_because_score_faded():
    strategy = Strategy(runner_exit=True)
    result = strategy.exit_decision("LONG", {"total": -80}, -100, False, 8.0)
    assert result["action"] == "hold"
    assert "kâr koşusu" in result["reason"]


def test_disabled_atr_mode_clears_old_fixed_tp_plan_on_restart(tmp_path):
    store = StateStore(tmp_path / "fixed.db")
    pos = Position(SYMBOL, "LONG", 100, 5, 92, leverage=10, margin_usdt=50)
    store.save_position(pos)
    store.set_meta(
        "trade_plans",
        {SYMBOL: {"initial_risk": 4, "initial_stop": 96, "tp1": 104, "tp2": 108, "tp1_hit": False}},
    )
    executor = fixed_executor(FixedBroker(), store=store)
    assert executor.get_trade_plan(SYMBOL) is None
    assert store.get_meta("trade_plans", {}) == {}


def test_backtest_uses_same_fixed_50_40_model_and_blocks_adds():
    engine = EventDrivenBacktester(
        initial_balance=1000,
        use_ml=False,
        fee_pct=0,
        slippage_bps=0,
        fixed_margin_usdt=50,
        leverage=10,
        stop_model="marj",
        runner_exit=True,
        trade_plan_cfg={"aktif": False},
    )
    engine._handle_signal_event(SignalEvent(0, SYMBOL, "LONG", 80, 100, "FIXED"))
    order = engine.events.popleft()
    assert order.qty == pytest.approx(5.0)
    assert order.margin_usdt == pytest.approx(50.0)
    engine._handle_order_event(order)
    engine._handle_fill_event(engine.events.popleft())
    assert engine.pos.stop == pytest.approx(92.0)
    assert engine.pos.qty * abs(engine.pos.entry - engine.pos.stop) == pytest.approx(40.0)

    engine._handle_signal_event(SignalEvent(1, SYMBOL, "ADD_LONG", 80, 110, "ADD"))
    assert len(engine.events) == 0
