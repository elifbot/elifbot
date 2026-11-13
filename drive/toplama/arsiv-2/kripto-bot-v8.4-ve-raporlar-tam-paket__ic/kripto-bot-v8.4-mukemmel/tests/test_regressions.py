from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer

from src.arbitrage import ArbitrageEngine
from src.backtest import EventDrivenBacktester, FillEvent, SignalEvent
from src.circuit_breaker import CircuitBreaker
from src.config import LIVE_CONFIRMATION, ConfigError, load_config
from src.dashboard import ProductionBotHub, create_dashboard_app
from src.exchanges import ExchangeManager, PaperBroker
from src.executor import Executor
from src.health import build_health_payload
from src.indicators import Indicators, indicator_score
from src.main import ohlcv_to_df
from src.market_data import (
    IncrementalOrderBook,
    MarketData,
    OrderBookSyncError,
    binance_ws_base,
    to_okx_inst,
)
from src.moneyflow import MoneyFlow
from src.news import NewsEngine
from src.reconcile import reconcile_positions
from src.risk import Position, RiskManager
from src.sizing import KellyTracker, PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.telegram import InteractiveTelegramBot, send_telegram

ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "BTC/USDT"


def base_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


def test_config_removes_nested_yaml_secrets(tmp_path, monkeypatch):
    cfg = base_config()
    cfg["genel"]["api_key"] = "yaml-nested-secret"
    cfg["bildirimler"]["discord_webhook_url"] = "https://yaml-secret-webhook"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.delenv("MODE", raising=False)
    loaded = load_config(path)
    assert "yaml-nested-secret" not in repr(loaded)
    assert "yaml-secret-webhook" not in repr(loaded)


def test_config_rejects_invalid_margin_and_live_without_confirmation(tmp_path, monkeypatch):
    cfg = base_config()
    cfg["risk"]["kasa_giris_yuzde"] = 80
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="toplam_marj"):
        load_config(path)

    cfg = base_config()
    cfg["genel"]["mod"] = "live"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.setenv(name, f"fake-{name.lower()}-value")
    with pytest.raises(ConfigError, match="LIVE_TRADING_CONFIRM"):
        load_config(path)
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", LIVE_CONFIRMATION)
    assert load_config(path)["genel"]["mod"] == "live"


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("genel", "zaman_dilimi", "3m"),
        ("genel", "kaldıraç", 1.5),
        ("risk", "mola_saniye", "beş dakika"),
        ("genel", "short_izni", "false"),
        ("boyutlandirma", "mod", "bilinmeyen"),
        ("haberler", "kaynaklar", "https://example.com/rss"),
    ],
)
def test_config_rejects_values_runtime_cannot_consume(tmp_path, monkeypatch, section, key, value):
    monkeypatch.delenv("MODE", raising=False)
    cfg = base_config()
    cfg[section][key] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_config_fills_safe_defaults_for_optional_runtime_sections(tmp_path, monkeypatch):
    monkeypatch.delenv("MODE", raising=False)
    cfg = base_config()
    del cfg["risk"]["mola_saniye"]
    del cfg["para_akisi"]
    del cfg["hiz"]
    for key in (
        "telegram_periyodik_rapor",
        "telegram_rapor_araligi_sn",
        "telegram_ilk_rapor_gecikmesi_sn",
    ):
        cfg["bildirimler"].pop(key, None)
    for key in (
        "rejim_bazli", "supertrend_iz_takibi", "breakout_hacim_z_esik", "breakout_akim_onayi"
    ):
        cfg["sinyal"].pop(key, None)
    path = tmp_path / "defaults.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    loaded = load_config(path)
    assert loaded["risk"]["mola_saniye"] == 300
    assert loaded["para_akisi"]["pencere_saniye"] == 300
    assert loaded["hiz"]["mum_yenileme_saniye"] == 15
    assert loaded["bildirimler"]["telegram_periyodik_rapor"] is True
    assert loaded["bildirimler"]["telegram_rapor_araligi_sn"] == 300
    assert loaded["bildirimler"]["telegram_ilk_rapor_gecikmesi_sn"] == 10
    assert loaded["sinyal"]["rejim_bazli"] is True
    assert loaded["sinyal"]["supertrend_iz_takibi"] is True
    assert loaded["sinyal"]["breakout_hacim_z_esik"] == 1.5
    assert loaded["sinyal"]["breakout_akim_onayi"] is True


def test_config_timeframes_match_closed_candle_filter():
    from src.config import TIMEFRAME_MS

    for timeframe in TIMEFRAME_MS:
        df = ohlcv_to_df([[0, 1, 1, 1, 1, 1]], timeframe, now_ms=10**12)
        assert len(df) == 1


def test_only_closed_candles_are_used():
    now = 1_700_000_000_000
    rows = [
        [now - 300_000, 100, 102, 99, 101, 10],
        [now, 101, 103, 100, 102, 12],
    ]
    df = ohlcv_to_df(rows, "5m", now_ms=now)
    assert len(df) == 1
    assert df.iloc[0]["close"] == 101


def test_pyramiding_requires_progress_since_last_layer():
    risk = RiskManager(pyramid_min_profit_pct=0.25)
    pos = Position(SYMBOL, "LONG", 100, 1, 95, last_add_price=109)
    assert not risk.can_add_to_winner(pos, 109.1)[0]
    assert risk.can_add_to_winner(pos, 109.5)[0]


def test_zero_ml_weight_does_not_sneak_ml_back_into_score():
    strategy = Strategy(w_ind=0.5, w_flow=0.3, w_news=0.2, w_ml=0.0)
    assert strategy.combine(50, 50, 50, ml_score=-100)["total"] == 50


def test_circuit_breaker_and_risk_limits_survive_restart(tmp_path):
    store = StateStore(tmp_path / "state.db")
    breaker = CircuitBreaker(state_store=store, max_ws_disconnect_sec=10)
    breaker.trip("MANUEL KILL", lock_system=True)
    restored = CircuitBreaker(state_store=store)
    assert restored.tripped and restored.system_locked
    assert not restored.can_trade()[0]

    restored.reset()
    restored.heartbeat_ws(time.time() - 20)
    assert restored.check_ws_health()
    assert not restored.check_ws_health(), "Aynı WS kesintisi tekrar alarm üretmemeli"

    risk = RiskManager(state_store=store, daily_max_loss_pct=5)
    risk.register_close(-6)
    risk_restored = RiskManager(state_store=store, daily_max_loss_pct=5)
    assert risk_restored.daily_pnl_pct == -6
    assert not risk_restored.can_open(0)[0]


def test_flash_crash_alarm_is_idempotent_until_reset():
    breaker = CircuitBreaker(flash_crash_pct=8.0)
    now = time.time()
    assert not breaker.check_price_shock("JCT/USDT", 100.0, now=now)
    assert breaker.check_price_shock("JCT/USDT", 108.1, now=now + 1.0)
    assert breaker.tripped
    reason = breaker.trip_reason
    assert not breaker.check_price_shock("JCT/USDT", 117.0, now=now + 2.0)
    assert breaker.trip_reason == reason

    breaker.reset()
    # Reset öncesi 117 fiyatı yeni başlangıçla karşılaştırılmamalı.
    assert not breaker.check_price_shock("JCT/USDT", 117.0, now=now + 3.0)
    assert not breaker.check_price_shock("JCT/USDT", 118.0, now=now + 4.0)


def test_health_rejects_missing_and_stale_heartbeat(tmp_path):
    store = StateStore(tmp_path / "health.db")
    code, payload = build_health_payload(store)
    assert code == 503 and payload["status"] == "not_ready"
    store.set_meta("bot_status", {"ts": time.time() - 120})
    code, payload = build_health_payload(store)
    assert code == 503 and payload["status"] == "stale_heartbeat"
    store.set_meta("bot_status", {"ts": time.time(), "circuit_breaker": {}})
    code, payload = build_health_payload(store)
    assert code == 200 and payload["healthy"]


def test_state_store_creates_parent_and_preserves_exchange(tmp_path):
    store = StateStore(tmp_path / "nested" / "data" / "state.db")
    pos = Position(SYMBOL, "LONG", 100, 1, 95, exchange="okx")
    store.save_position(pos)
    assert store.db_path.exists()
    assert store.load_positions()[SYMBOL].exchange == "okx"


def test_kelly_rejects_non_finite_and_negative_edge(tmp_path):
    path = tmp_path / "nested" / "kelly.json"
    tracker = KellyTracker(path, min_trades=1)
    with pytest.raises(ValueError):
        tracker.record(float("nan"))
    tracker.record(5)
    assert json.loads(path.read_text(encoding="utf-8"))["history"] == [0.05]

    sizer = PositionSizer(stats_path=tmp_path / "negative.json", kelly_min_trades=20)
    sizer.kelly.record(1)
    for _ in range(19):
        sizer.kelly.record(-1)
    risk_pct, info = sizer.risk_pct()
    assert risk_pct == 0
    assert "negatif" in info["kaynak"]


class FakeCloseBroker:
    def __init__(self, error=False, fill_qty=1.0, fill_price=101.0, fee=0.0):
        self.mode = "live"
        self.error = error
        self.fill_qty = fill_qty
        self.fill_price = fill_price
        self.fee = fee
        self.market_calls = []
        self.cancel_calls = 0

    async def market_order(self, symbol, side, qty, price_hint=0, exchange=None, reduce_only=False):
        self.market_calls.append(
            {"symbol": symbol, "side": side, "qty": qty, "exchange": exchange, "reduce_only": reduce_only}
        )
        if self.error:
            raise TimeoutError("sonuç belirsiz")
        return {"qty": self.fill_qty, "price": self.fill_price, "fee": self.fee}

    async def cancel_protection(self, symbol, prot, exchange=None):
        self.cancel_calls += 1
        return True


def make_executor(store, broker):
    pos = Position(SYMBOL, "LONG", 100, 1, 95, exchange="binance", margin_usdt=5)
    store.save_position(pos)
    executor = Executor(broker, RiskManager(), Strategy(), state_store=store)
    executor._prot[SYMBOL] = {"native": True, "exchange": "binance"}
    return executor


def test_failed_close_keeps_position_protection_and_no_trade(tmp_path):
    store = StateStore(tmp_path / "close.db")
    broker = FakeCloseBroker(error=True)
    executor = make_executor(store, broker)
    result = run(executor._close(SYMBOL, 101, "TEST", 1.0))
    assert result is False
    assert SYMBOL in executor.positions
    assert SYMBOL in store.load_positions()
    assert store.get_trades() == []
    assert broker.cancel_calls == 0
    assert broker.market_calls[0]["reduce_only"] is True


def test_partial_close_updates_only_filled_quantity(tmp_path):
    store = StateStore(tmp_path / "partial.db")
    broker = FakeCloseBroker(fill_qty=0.4, fill_price=102)
    executor = make_executor(store, broker)
    assert run(executor._close(SYMBOL, 101, "TEST", 1.0)) is False
    assert executor.positions[SYMBOL].qty == pytest.approx(0.6)
    assert store.load_positions()[SYMBOL].qty == pytest.approx(0.6)
    assert store.get_trades()[0]["qty"] == pytest.approx(0.4)

    broker.fill_qty = 0.6
    assert run(executor._close(SYMBOL, 102, "TEST", 2.0)) is True
    assert SYMBOL not in executor.positions
    assert store.load_positions() == {}


def test_partial_closes_allocate_entry_fee_and_funding_without_loss(tmp_path):
    store = StateStore(tmp_path / "partial-cost.db")
    broker = FakeCloseBroker(fill_qty=0.4, fill_price=102, fee=0.04)
    executor = make_executor(store, broker)
    executor._position_meta[SYMBOL] = {
        "position_id": "cost-position",
        "entry_context": {"side": "LONG"},
        "entry_fee_usdt": 1.0,
        "funding_usdt": -0.2,
    }
    assert run(executor._close(SYMBOL, 101, "KISMİ", 1.0)) is False
    first = store.get_trades()[0]
    assert first["net_pnl_usdt"] == pytest.approx(0.28)
    remaining = executor._position_meta[SYMBOL]
    assert remaining["entry_fee_usdt"] == pytest.approx(0.6)
    assert remaining["funding_usdt"] == pytest.approx(-0.12)

    broker.fill_qty = 0.6
    broker.fee = 0.06
    assert run(executor._close(SYMBOL, 102, "TAM", 2.0)) is True
    rows = store.get_trades()
    assert len(rows) == 2
    assert sum(row["net_pnl_usdt"] for row in rows) == pytest.approx(0.70)
    assert sum(row["entry_fee_usdt"] for row in rows) == pytest.approx(1.0)
    assert sum(row["exit_fee_usdt"] for row in rows) == pytest.approx(0.1)
    assert sum(row["funding_usdt"] for row in rows) == pytest.approx(-0.2)


class DelayedPaperBroker:
    mode = "paper"
    primary = "binance"

    def __init__(self):
        self.paper = PaperBroker(balance_usdt=100_000, fee_taker_pct=0.05)

    async def market_order(self, symbol, side, qty, price_hint=0, exchange=None, reduce_only=False):
        # Emir gönderimi öncesi yield, eski duplicate-close yarışını görünür kılar.
        await asyncio.sleep(0.001)
        return self.paper.market_order(
            symbol, side, qty, price_hint, exchange=exchange or "binance", reduce_only=reduce_only
        )

    async def cancel_protection(self, symbol, prot, exchange=None):
        return True


def test_100_concurrent_closes_create_one_fill_fee_and_trade(tmp_path):
    store = StateStore(tmp_path / "concurrent-close.db")
    store.save_position(Position(SYMBOL, "LONG", 100, 1, 95, exchange="binance", margin_usdt=50))
    broker = DelayedPaperBroker()
    executor = Executor(broker, RiskManager(), Strategy(), state_store=store)

    async def close_repeatedly():
        return await asyncio.gather(
            *(executor._close(SYMBOL, 101, "STOP/TRAIL/FLOW Yarışı", 1.0) for _ in range(100))
        )

    results = run(close_repeatedly())
    assert sum(bool(result) for result in results) == 1
    assert executor.positions == {}
    assert len(broker.paper.trades) == 1
    assert broker.paper.trades[0]["reduce_only"] is True
    assert len(store.get_trades()) == 1
    assert executor.stats["trades"] == 1
    assert broker.paper.total_fees_usdt == pytest.approx(0.0505)
    assert broker.paper.balance == pytest.approx(100_000 + 1 - 0.0505)
    assert SYMBOL not in broker.paper.position_qty


def test_closed_trade_net_pnl_reconciles_exactly_with_paper_cash(tmp_path):
    store = StateStore(tmp_path / "net-reconcile.db")
    broker = DelayedPaperBroker()
    entry_fill = broker.paper.market_order(
        SYMBOL, "buy", 1, 100, exchange="binance", reduce_only=False
    )
    store.save_position(
        Position(SYMBOL, "LONG", 100, 1, 95, exchange="binance", margin_usdt=50)
    )
    executor = Executor(broker, RiskManager(), Strategy(), state_store=store)
    executor._position_meta[SYMBOL] = {
        "position_id": "net-position",
        "entry_context": {"side": "LONG"},
        "entry_fee_usdt": entry_fill["fee"],
        "funding_usdt": 0.0,
    }
    executor._funding_last[SYMBOL] = time.time() - 3600
    funding = executor.apply_funding(SYMBOL, 0.0001, 100, enabled=True)

    assert run(executor._close(SYMBOL, 102, "ÖLÇÜM SONU", 2.0)) is True
    row = store.get_trades()[0]
    expected = 2.0 - entry_fill["fee"] - 0.051 + funding
    assert row["exchange"] == "binance"
    assert row["entry_fee_usdt"] == pytest.approx(entry_fill["fee"])
    assert row["exit_fee_usdt"] == pytest.approx(0.051)
    assert row["funding_usdt"] == pytest.approx(funding)
    assert row["net_pnl_usdt"] == pytest.approx(expected)
    assert broker.paper.balance - 100_000 == pytest.approx(row["net_pnl_usdt"])


def test_paper_reduce_only_rejects_reversal_and_duplicate_fill():
    paper = PaperBroker(balance_usdt=1000, fee_taker_pct=0.05)
    paper.sync_position(SYMBOL, "LONG", 1)
    fill = paper.market_order(SYMBOL, "sell", 5, 100, reduce_only=True)
    assert fill["qty"] == pytest.approx(1)
    assert fill["requested_qty"] == pytest.approx(5)
    assert fill["position_qty"] == 0
    assert len(paper.trades) == 1
    fees = paper.total_fees_usdt
    with pytest.raises(ValueError, match="açık pozisyon yok"):
        paper.market_order(SYMBOL, "sell", 1, 100, reduce_only=True)
    assert len(paper.trades) == 1
    assert paper.total_fees_usdt == fees

    paper.sync_position(SYMBOL, "SHORT", 1)
    with pytest.raises(ValueError, match="yönü pozisyonu kapatmıyor"):
        paper.market_order(SYMBOL, "sell", 1, 100, reduce_only=True)
    assert len(paper.trades) == 1


def test_concurrent_pair_rescue_rechecks_and_closes_each_leg_once(tmp_path):
    store = StateStore(tmp_path / "pair-close.db")
    winner = Position("ETH/USDT", "LONG", 100, 1, 95, exchange="binance", margin_usdt=50)
    loser = Position("SOL/USDT", "SHORT", 100, 1, 105, exchange="binance", margin_usdt=50)
    store.save_position(winner)
    store.save_position(loser)
    risk = RiskManager(pair_rescue_enabled=True, rescue_min_loser_pct=0.5)
    broker = DelayedPaperBroker()
    executor = Executor(broker, risk, Strategy(), state_store=store)
    executor.last_prices.update({"ETH/USDT": 101, "SOL/USDT": 101})
    rescue = risk.find_pair_rescue(executor.positions, executor.last_prices)
    assert rescue and rescue["action"] == "pair_close"

    async def rescue_twice():
        return await asyncio.gather(
            executor.execute_pair_rescue(rescue), executor.execute_pair_rescue(rescue)
        )

    run(rescue_twice())
    assert executor.positions == {}
    assert len(broker.paper.trades) == 2
    assert len(store.get_trades()) == 2
    assert executor.stats["pair_rescues"] == 1
    assert executor.stats["trades"] == 2


def test_reconciliation_is_exchange_aware():
    local = {SYMBOL: Position(SYMBOL, "LONG", 100, 1, 95, exchange="binance")}
    report = reconcile_positions(
        local, [{"symbol": "BTC/USDT:USDT", "side": "LONG", "qty": 1, "exchange": "okx"}]
    )
    assert report["ghosts"][0]["exchange"] == "binance"
    assert report["orphans"][0]["exchange"] == "okx"


def paper_exchange_config():
    return {
        "genel": {"mod": "paper", "semboller": [SYMBOL], "borsalar": ["binance", "okx"], "kaldıraç": 20},
        "api": {},
        "emirler": {},
        "failover": {"aktif": True, "timeout_esigi": 5, "soguma_saniye": 123},
    }


def test_failover_uses_documented_config_keys_and_swap_symbol():
    manager = ExchangeManager(paper_exchange_config())
    assert manager.max_exchange_timeouts == 5
    assert manager.failover_cooldown_sec == 123
    assert manager._ccxt_symbol(SYMBOL) == "BTC/USDT:USDT"
    run(manager.close())


def test_binance_market_discovery_is_usdt_m_futures_only():
    manager = ExchangeManager(paper_exchange_config())
    try:
        assert manager.default_type == "swap"
        assert manager._ex["binance"].options["defaultType"] == "swap"
        assert manager._ex["binance"].options["fetchMarkets"]["types"] == [
            "linear"
        ]
        # CCXT'nin varsayılan spot + linear + inverse katalog yüklemesi,
        # spot api.binance.com erişim hatasını Futures keşfine taşımamalı.
        assert "spot" not in manager._ex["binance"].options["fetchMarkets"]["types"]
        assert "inverse" not in manager._ex["binance"].options["fetchMarkets"]["types"]
    finally:
        run(manager.close())


def test_binance_public_www_override_does_not_touch_private_urls(monkeypatch):
    monkeypatch.setenv("BINANCE_PUBLIC_WWW", "1")
    manager = ExchangeManager(paper_exchange_config())
    try:
        urls = manager._ex["binance"].urls["api"]
        assert urls["fapiPublic"] == "https://www.binance.com/fapi/v1"
        assert urls["fapiPublicV2"] == "https://www.binance.com/fapi/v2"
        assert urls["fapiPublicV3"] == "https://www.binance.com/fapi/v3"
        assert urls["fapiData"] == "https://www.binance.com/futures/data"
        assert urls["fapiPrivate"] == "https://fapi.binance.com/fapi/v1"
        assert urls["fapiPrivateV2"] == "https://fapi.binance.com/fapi/v2"
        assert urls["dapiPublic"] == "https://dapi.binance.com/dapi/v1"
    finally:
        run(manager.close())


class TimeoutExchange:
    def __init__(self):
        self.calls = 0

    async def create_market_order(self, symbol, side, qty, params=None):
        self.calls += 1
        raise TimeoutError("timeout after send")

    async def close(self):
        return None


def test_live_order_timeout_is_not_retried_on_other_exchange():
    manager = ExchangeManager(paper_exchange_config())
    manager.mode = "live"
    primary = TimeoutExchange()
    backup = TimeoutExchange()
    manager._ex = {"binance": primary, "okx": backup}
    manager._default_primary = manager._active_primary = "binance"
    with pytest.raises(RuntimeError, match="tekrar denenmedi"):
        run(manager.market_order(SYMBOL, "sell", 1, exchange="binance", reduce_only=True))
    assert primary.calls == 1
    assert backup.calls == 0
    run(manager.close())


class NoFillExchange(TimeoutExchange):
    async def fetch_ticker(self, symbol):
        return {"bid": 100.0, "ask": 101.0, "last": 100.5}

    def price_to_precision(self, symbol, price):
        return str(price)

    async def create_limit_order(self, symbol, side, qty, price, params=None):
        self.calls += 1
        return {"id": "order-1"}

    async def fetch_order(self, oid, symbol):
        return {"id": oid, "status": "canceled", "filled": 0.0}


def test_chase_order_does_not_report_requested_qty_when_unfilled(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr("src.exchanges.asyncio.sleep", no_sleep)
    manager = ExchangeManager(paper_exchange_config())
    manager.mode = "live"
    fake = NoFillExchange()
    manager._ex = {"binance": fake}
    manager._default_primary = manager._active_primary = "binance"
    with pytest.raises(RuntimeError, match="dolmadı"):
        run(manager._chase_limit_order(SYMBOL, "buy", 2, 100, 104, "binance", steps=1))
    run(manager.close())


def test_live_arbitrage_is_fail_closed():
    class LiveBroker:
        mode = "live"
        calls = 0

        async def market_order(self, *args, **kwargs):
            self.calls += 1

    engine = ArbitrageEngine()
    broker = LiveBroker()
    opp = {
        "symbol": SYMBOL,
        "buy_exchange": "binance",
        "sell_exchange": "okx",
        "buy_price": 100.0,
        "sell_price": 101.0,
        "notional_usdt": 1000.0,
        "est_profit_usdt": 5.0,
        "gross_spread_pct": 1.0,
        "net_spread_pct": 0.8,
    }
    result = run(engine.execute_arbitrage(opp, broker))
    assert result["status"] == "DISABLED_LIVE"
    assert broker.calls == 0
    assert engine.total_trades == 0


def test_backtest_trade_pnl_includes_entry_and_exit_fees():
    engine = EventDrivenBacktester(initial_balance=1000, fee_pct=1.0, slippage_bps=0)
    engine._handle_fill_event(
        FillEvent(0, SYMBOL, "OPEN", "LONG", 1, 100, 1.0, 0, 10, 1, "test")
    )
    engine._handle_fill_event(
        FillEvent(1, SYMBOL, "CLOSE", "LONG", 1, 110, 1.1, 0, 0, 1, "test")
    )
    trade = engine.trades[0]
    assert trade["gross_pnl_usdt"] == 10
    assert trade["fees_usdt"] == pytest.approx(2.1)
    assert trade["pnl_usdt"] == pytest.approx(7.9)
    assert engine.balance == pytest.approx(1007.9)


def test_backtest_final_equity_marks_open_position_to_market():
    import pandas as pd

    engine = EventDrivenBacktester(initial_balance=1000, fee_pct=0, slippage_bps=0, funding_8h_pct=0)
    engine.risk.unlimited_pyramiding = False
    engine.pos = Position(SYMBOL, "LONG", 100, 1, 95, leverage=1, margin_usdt=10)
    engine.balance = 990
    rows = []
    for i in range(70):
        price = 110 if i == 69 else 100
        rows.append({"open": price, "high": price, "low": price, "close": price, "volume": 10})
    report = engine.run_df(pd.DataFrame(rows), warmup=60)
    assert engine.pos is not None
    assert report["final_balance"] == 990
    assert report["final_equity"] == 1000
    assert report["total_return_pct"] == 0


def test_backtest_pyramiding_respects_total_margin_cap():
    engine = EventDrivenBacktester(initial_balance=100, fee_pct=0, slippage_bps=0)
    engine.pos = Position(SYMBOL, "LONG", 100, 1, 95, leverage=1, margin_usdt=55)
    engine._handle_signal_event(SignalEvent(1, SYMBOL, "ADD_LONG", 20, 110, "test"))
    assert len(engine.events) == 0


def test_swap_market_data_uses_correct_instruments_and_contract_sizes():
    assert to_okx_inst(SYMBOL, "swap") == "BTC-USDT-SWAP"
    assert to_okx_inst(SYMBOL, "spot") == "BTC-USDT"
    assert "fstream.binance.com" in binance_ws_base("swap")
    market = MarketData(
        [SYMBOL], ["okx"], market_type="swap",
        contract_sizes={("okx", SYMBOL): 0.01},
    )
    assert market.normalize_quantity("okx", SYMBOL, 2) == pytest.approx(0.02)
    assert market.normalize_quantity("binance", SYMBOL, 2) == 2
    missing = MarketData([SYMBOL], ["okx"], market_type="swap")
    assert missing.normalize_quantity("okx", SYMBOL, 2) is None


def test_okx_incremental_orderbook_applies_snapshot_and_rejects_sequence_gap():
    book = IncrementalOrderBook()
    with pytest.raises(OrderBookSyncError):
        book.apply("update", {"prevSeqId": 0, "seqId": 1, "bids": [], "asks": []})
    book.apply(
        "snapshot",
        {
            "seqId": 10,
            "bids": [["100", "1", "0", "1"], ["99", "2", "0", "1"]],
            "asks": [["101", "1", "0", "1"]],
        },
    )
    book.apply(
        "update",
        {
            "prevSeqId": 10,
            "seqId": 11,
            "bids": [["100", "0", "0", "0"], ["100.5", "3", "0", "1"]],
            "asks": [["101", "2", "0", "1"]],
        },
    )
    bids, asks = book.top(20)
    assert bids == [(100.5, 3.0), (99.0, 2.0)]
    assert asks == [(101.0, 2.0)]
    with pytest.raises(OrderBookSyncError, match="sıra boşluğu"):
        book.apply(
            "update",
            {"prevSeqId": 9, "seqId": 12, "bids": [], "asks": []},
        )


def test_indicator_snapshot_exposes_requested_ma_ema_rsi_macd():
    import numpy as np
    import pandas as pd

    close = np.linspace(80, 120, 220)
    df = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(220, 100.0),
        }
    )
    result = indicator_score(df, funding_rate=0.0001)
    snap = result["snapshot"]
    for key in ("ma20", "ma50", "ema9", "ema21", "ema50", "ema200", "rsi", "macd", "macd_signal", "macd_hist"):
        assert key in snap
    assert snap["ma20"] > snap["ma50"]
    assert snap["ema9"] > snap["ema21"] > snap["ema50"]
    assert snap["ema200"] > 0
    assert "ma_trend" in result["components"]


def make_ohlcv(close, volume=100.0, start_ts=None):
    close = np.asarray(close, dtype=float)
    data = {
        "open": np.roll(close, 1),
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.full(len(close), volume, dtype=float),
    }
    data["open"][0] = close[0]
    if start_ts is not None:
        data["ts"] = np.asarray(start_ts, dtype=float)
    return pd.DataFrame(data)


def test_session_and_anchored_vwap_reset_and_volume_profile_bounds():
    stamps = [
        pd.Timestamp("2025-01-01 23:59", tz="UTC").timestamp() * 1000,
        pd.Timestamp("2025-01-02 00:01", tz="UTC").timestamp() * 1000,
        pd.Timestamp("2025-01-02 00:02", tz="UTC").timestamp() * 1000,
    ]
    df = make_ohlcv([100, 200, 300], start_ts=stamps)
    session = Indicators.session_vwap(df)
    assert session.iloc[0] == pytest.approx(100)
    assert session.iloc[1] == pytest.approx(200), "Yeni UTC günü VWAP'ı sıfırlamalı"
    assert session.iloc[2] == pytest.approx(250)
    anchored = Indicators.anchored_vwap(df, 1)
    assert anchored.iloc[-1] == pytest.approx(250)
    week_stamps = [
        pd.Timestamp("2025-01-05 23:59", tz="UTC").timestamp() * 1000,
        pd.Timestamp("2025-01-06 00:01", tz="UTC").timestamp() * 1000,
    ]
    weekly = Indicators.session_vwap(make_ohlcv([100, 200], start_ts=week_stamps), "W")
    assert weekly.iloc[1] == pytest.approx(200), "Yeni UTC haftası VWAP'ı sıfırlamalı"

    profile_df = make_ohlcv([90, 95, 100, 100, 100, 105, 110])
    profile = Indicators.volume_profile(profile_df, lookback=7, bins=10)
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    assert 99 <= profile["poc"] <= 102


def test_regime_score_keeps_overbought_trend_long_and_legacy_ab_score():
    df = make_ohlcv(np.linspace(80, 120, 220))
    df["high"] = np.maximum(df["open"], df["close"]) + 0.2
    df["low"] = np.minimum(df["open"], df["close"]) - 0.2
    result = indicator_score(df)
    legacy = indicator_score(df, regime_aware=False)
    assert result["regime"] == "TREND"
    assert result["score"] > 0
    assert result["components"]["rsi"] < 0, "RSI aşırı alım puanı hâlâ tanısal olarak görünmeli"
    assert Indicators.rsi(df["close"]).iloc[-1] == pytest.approx(100)
    assert Indicators.mfi(df["high"], df["low"], df["close"], df["volume"]).iloc[-1] == pytest.approx(100)
    assert result["snapshot"]["supertrend_direction"] == 1
    assert result["snapshot"]["supertrend"] < result["snapshot"]["price"]
    assert legacy["score"] == legacy["legacy_score"]


def test_squeeze_blocks_entry_even_with_strong_score_and_flow():
    close = np.concatenate((np.linspace(80, 99, 170), np.full(50, 100.0)))
    df = make_ohlcv(close)
    df.loc[df.index[-50:], "high"] = 101.0
    df.loc[df.index[-50:], "low"] = 99.0
    result = indicator_score(df)
    assert result["regime"] == "SIKISMA"
    assert result["snapshot"]["bb_kc_squeeze"] is True
    assert result["entry_allowed"] is False

    strategy = Strategy(w_ind=1.0, w_flow=0.0, w_news=0.0)
    combined = strategy.combine(100, 80, 0, market_context=result["snapshot"])
    assert combined["raw_signal"] == "LONG" and combined["signal"] == "BEKLE"
    decision = strategy.entry_decision(combined, False, has_position=False)
    assert decision["action"] == "yok"
    assert "REJİM" in decision["reason"]


def test_breakout_requires_volume_flow_and_non_conflicting_oi():
    close = np.linspace(80, 119, 220)
    close[-1] = 130.0
    df = make_ohlcv(close, volume=100.0)
    df.loc[df.index[-1], "volume"] = 10.0
    low_volume = indicator_score(df)
    assert low_volume["snapshot"]["breakout_long"] is True
    assert low_volume["regime"] == "BREAKOUT"
    assert low_volume["entry_allowed"] is False
    legacy = indicator_score(df, regime_aware=False)
    legacy_decision = Strategy(w_ind=1.0, w_flow=0.0, w_news=0.0).combine(
        100, 0, 0, market_context=legacy["snapshot"]
    )
    assert legacy_decision["entry_allowed"] is True

    df.loc[df.index[-1], "volume"] = 1000.0
    confirmed = indicator_score(df)
    assert confirmed["entry_allowed"] is True
    strategy = Strategy(w_ind=1.0, w_flow=0.0, w_news=0.0)
    no_flow = strategy.combine(100, 0, 0, market_context=confirmed["snapshot"])
    assert no_flow["entry_allowed"] is False and no_flow["signal"] == "BEKLE"
    with_flow = strategy.combine(100, 20, 0, market_context=confirmed["snapshot"])
    assert with_flow["entry_allowed"] is True and with_flow["signal"] == "LONG"
    conflict = dict(confirmed["snapshot"], oi_signal="YENI_SHORT_GIRISI")
    with_conflict = strategy.combine(100, 20, 0, market_context=conflict)
    assert with_conflict["entry_allowed"] is False
    assert "OI/fiyat" in with_conflict["entry_block_reason"]
    strong_conflict = dict(confirmed["snapshot"], cvd_slope=1.0)
    assert strategy.combine(100, -50, 0, market_context=strong_conflict)["entry_allowed"] is False

    trigger_context = dict(
        confirmed["snapshot"], entry_allowed=True, oi_signal="YENI_SHORT_GIRISI"
    )
    flow_trigger = Strategy().combine(20, 60, 0, market_context=trigger_context)
    assert flow_trigger["signal"] == "BEKLE"
    assert flow_trigger["trigger"] is None
    assert "OI/fiyat" in flow_trigger["entry_block_reason"]


def test_oi_price_matrix_distinguishes_short_covering_from_new_longs():
    now = time.time()
    flow = MoneyFlow(SYMBOL)
    flow.update_open_interest(100_000, price=100, ts=now - 60)
    flow.update_open_interest(95_000, price=110, ts=now)
    snap = flow.snapshot()
    assert snap["oi_signal"] == "SHORT_KAPAMA_RALLISI"
    assert snap["oi_liq_boost"] == pytest.approx(3.0)

    new_shorts = MoneyFlow(SYMBOL)
    new_shorts.update_open_interest(100_000, price=100, ts=now - 60)
    new_shorts.update_open_interest(105_000, price=90, ts=now)
    assert new_shorts.snapshot()["oi_signal"] == "YENI_SHORT_GIRISI"


def test_supertrend_trailing_only_tightens_profitable_position_stop():
    executor = Executor(
        FakeCloseBroker(), RiskManager(), Strategy(), supertrend_trailing=True
    )
    pos = Position(SYMBOL, "LONG", 100, 1, 95)
    executor.positions[SYMBOL] = pos
    executor.set_supertrend(SYMBOL, 1, 103)
    run(executor.on_price_tick(SYMBOL, 105))
    assert SYMBOL in executor.positions
    assert pos.stop == pytest.approx(103)
    assert executor.stats["supertrend_trail_updates"] == 1

    executor.set_supertrend(SYMBOL, 1, 98)
    run(executor.on_price_tick(SYMBOL, 106))
    assert pos.stop == pytest.approx(103), "Supertrend stopu asla gevşetmemeli"
    executor.set_supertrend(SYMBOL, 1, float("nan"))
    assert SYMBOL not in executor._supertrend


def test_realistic_paper_market_uses_ask_for_buy_and_bid_for_sell():
    cfg = paper_exchange_config()
    cfg["paper"] = {"gercekci_yurutme": True, "funding_aktif": True, "bakiye": 1000}
    manager = ExchangeManager(cfg)

    class Quotes(TimeoutExchange):
        async def fetch_ticker(self, symbol):
            return {"bid": 100.0, "ask": 102.0, "last": 101.0}

    manager._ex = {"binance": Quotes()}
    manager._default_primary = manager._active_primary = "binance"
    buy = run(manager.market_order(SYMBOL, "buy", 1, price_hint=101, exchange="binance"))
    sell = run(manager.market_order(SYMBOL, "sell", 1, price_hint=101, exchange="binance"))
    assert buy["price"] == 102 and sell["price"] == 100
    assert buy["price_source"] == "rest_bid_ask"
    assert buy["slippage_pct"] == pytest.approx(100 / 101)
    run(manager.close())


def test_paper_funding_is_time_weighted_and_directional(tmp_path):
    # Independent long and short actual paper fills on isolated SQLite stores;
    # never mutate a live position's direction without a corresponding fill.
    from tests._paper_fixtures import make_paper_broker
    def run_case(side):
        broker = make_paper_broker(balance=1000.)
        store = StateStore(tmp_path / f"funding-{side}.db")
        risk = RiskManager(leverage=10, dynamic_leverage_enabled=False)
        sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=20, leverage=10,
                              stats_path=tmp_path / f"kelly-{side}.json")
        executor = Executor(broker, risk, Strategy(), sizer=sizer,
                            state_store=store, protection_on=False)
        run(executor._open(SYMBOL, side, 100., 'FUNDING TEST'))
        assert executor.positions[SYMBOL].qty == pytest.approx(2.)
        last = time.time() - 3600
        executor._funding_last[SYMBOL] = last
        store.set_meta('paper_funding_clock', {SYMBOL: last})
        delta = executor.apply_funding(SYMBOL, 0.0008, 100, enabled=True)
        assert broker.paper.total_funding_usdt == pytest.approx(delta)
        assert store.get_meta('paper_account')['balance'] == pytest.approx(broker.paper.balance)
        return delta

    delta = run_case('LONG')
    assert delta == pytest.approx(-0.02, abs=0.001)
    short_delta = run_case('SHORT')
    assert short_delta == pytest.approx(0.02, abs=0.001)


def test_old_news_does_not_create_fresh_veto():
    engine = NewsEngine([], fear_greed_on=False)
    engine._register(
        "Old exchange hack", "RSS", "", -90, True, ["KRİTİK"],
        published_ts=time.time() - 7200,
    )
    mood = engine.mood()
    assert mood["score"] == 0
    assert not mood["veto"]
    engine.push_item("New exchange hack", "RSS")
    assert engine.mood()["veto"]


def test_live_market_order_reads_actual_fill_instead_of_requested_qty():
    class DeferredFill(TimeoutExchange):
        async def create_market_order(self, symbol, side, qty, params=None):
            self.calls += 1
            return {"id": "order-1", "status": "open", "filled": None, "average": None}

        async def fetch_order(self, oid, symbol):
            return {"id": oid, "status": "closed", "filled": 0.4, "average": 101.0}

    manager = ExchangeManager(paper_exchange_config())
    manager.mode = "live"
    fake = DeferredFill()
    manager._ex = {"binance": fake}
    manager._default_primary = manager._active_primary = "binance"
    fill = run(manager.market_order(SYMBOL, "buy", 2, price_hint=100, exchange="binance"))
    assert fill["qty"] == 0.4 and fill["price"] == 101
    assert fake.calls == 1
    run(manager.close())


class TelegramQuoteBroker:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def fetch_balance_usdt(self):
        return 1000.0

    async def fetch_price(self, symbol, exchange=None):
        self.calls.append((symbol, exchange))
        if self.fail:
            raise TimeoutError("quote unavailable")
        return 110.0


class TelegramPositionExecutor:
    def __init__(self):
        self.positions = {
            SYMBOL: Position(
                SYMBOL, "LONG", 100, 1, 95, exchange="okx", leverage=2, margin_usdt=50
            )
        }
        self.last_prices = {SYMBOL: 100.0}
        self.risk = RiskManager()
        self.stats = {"pnl_usdt_sum": 25.0, "trades": 3, "wins": 2, "losses": 1}

    def total_unrealized_usdt(self):
        return round(
            sum(
                self.risk.pnl_usdt(pos, self.last_prices.get(symbol, pos.entry))
                for symbol, pos in self.positions.items()
            ),
            2,
        )


def test_telegram_plain_guncel_and_pnl_use_fresh_exchange_prices():
    executor = TelegramPositionExecutor()
    broker = TelegramQuoteBroker()
    bot = InteractiveTelegramBot(
        allowed_chat_id="6425796299", executor=executor, broker=broker
    )

    current = run(bot.handle_command("güncel", sender_chat_id="6425796299"))
    assert "GÜNCEL AÇIK POZİSYONLAR" in current
    assert SYMBOL in current and "110.0000 (canlı)" in current
    assert "Nakit Kasa" not in current
    assert broker.calls[-1] == (SYMBOL, "okx")

    pnl = run(bot.handle_command("kar zarar", sender_chat_id="6425796299"))
    assert "Gerçekleşen fiyat K/Z (brüt, bu oturum): $+25.00" in pnl
    assert "Açık K/Z: $+10.00" in pnl
    assert "Toplam K/Z: $+35.00" in pnl
    assert "Toplam Özsermaye: $1,010.00" in pnl

    status = run(bot.handle_command("/durum", sender_chat_id="6425796299"))
    assert "ANLIK DURUM RAPORU" in status and "AÇIK POZİSYONLAR" in status


def test_telegram_marks_stale_price_and_rejects_unauthorized_natural_text():
    executor = TelegramPositionExecutor()
    broker = TelegramQuoteBroker(fail=True)
    bot = InteractiveTelegramBot(
        allowed_chat_id="authorized", executor=executor, broker=broker
    )
    report = run(bot.handle_command("/guncel", sender_chat_id="authorized"))
    assert "100.0000 (önbellek)" in report
    assert "tazelenemedi" in report

    calls_before = len(broker.calls)
    rejected = run(bot.handle_command("güncel", sender_chat_id="attacker"))
    assert "Yetkisiz" in rejected
    assert len(broker.calls) == calls_before


def test_telegram_poll_filters_unauthorized_and_accepts_plain_guncel(monkeypatch):
    import aiohttp

    updates = [
        {"update_id": 1, "message": {"chat": {"id": "attacker"}, "text": "/kill"}},
        {"update_id": 2, "message": {"chat": {"id": "authorized"}, "text": "güncel"}},
    ]
    posts = []

    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {"ok": True, "result": updates}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, *args, **kwargs):
            return FakeResponse()

        async def post(self, url, **kwargs):
            posts.append((url, kwargs))
            return FakeResponse()

    bot = InteractiveTelegramBot(
        token="test-token", allowed_chat_id="authorized", poll_interval=0
    )
    handled = []

    async def fake_handle(text, sender_chat_id=None):
        handled.append((text, sender_chat_id))
        return "güncel pozisyon raporu"

    async def stop_after_poll(_):
        bot.stop()

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(bot, "handle_command", fake_handle)
    monkeypatch.setattr("src.telegram.asyncio.sleep", stop_after_poll)
    run(bot.poll_forever())

    assert handled == [("güncel", "authorized")]
    assert len(posts) == 1
    assert posts[0][1]["json"]["text"] == "güncel pozisyon raporu"


def test_telegram_market_report_reads_indicators_and_news(tmp_path):
    store = StateStore(tmp_path / "market-report.db")
    store.set_meta(
        "live_scores",
        {
            SYMBOL: {
                "symbol": SYMBOL,
                "signal": "LONG",
                "total": 62,
                "price": 101,
                "ma20": 100,
                "ma50": 99,
                "ema9": 100.5,
                "ema21": 100.2,
                "ema50": 100.1,
                "ema200": 95,
                "rsi": 61,
                "macd": 1.2,
                "macd_signal": 1.0,
                "macd_hist": 0.2,
                "para_akisi": 35,
                "bid_ask_ratio": 1.8,
                "funding_rate": 0.0001,
            }
        },
    )
    news = NewsEngine([])
    news.push_item("ETF approved for Bitcoin", "TestRSS")
    bot = InteractiveTelegramBot(
        allowed_chat_id="authorized", state_store=store, news_engine=news
    )
    report = run(bot.handle_command("piyasa", sender_chat_id="authorized"))
    assert "CANLI PİYASA / TEKNİK ANALİZ" in report
    assert "MA20/50: 100.0000 / 99.0000" in report
    assert "RSI(14): 61.0" in report
    assert "Funding: +0.0100%" in report
    assert "ETF approved for Bitcoin" in report


def make_periodic_telegram_bot(tmp_path):
    store = StateStore(tmp_path / "periodic.db")
    now = time.time()
    store.set_meta(
        "bot_status",
        {
            "ts": now,
            "mode": "PAPER",
            "primary_exchange": "binance",
            "market_data": {"market_type": "swap", "last_message_ts": now, "latency_ms": 42},
        },
    )
    store.set_meta(
        "live_scores",
        {
            SYMBOL: {
                "signal": "LONG", "total": 62, "price": 110,
                "ma20": 105, "ma50": 100, "ema9": 108, "ema21": 106,
                "rsi": 61, "macd_hist": 0.2, "para_akisi": 35,
                "bid_ask_ratio": 1.8, "funding_rate": 0.0001,
                "regime": "TREND", "setup": "PULLBACK", "supertrend": 104,
                "session_vwap": 106, "volume_profile_poc": 105,
                "volume_zscore": 2.1, "oi_signal": "YENI_LONG_GIRISI",
            }
        },
    )

    class PeriodicBroker(TelegramQuoteBroker):
        mode = "paper"
        primary = "binance"

        def __init__(self):
            super().__init__()
            self.paper = PaperBroker(balance_usdt=1000)
            self.paper.total_fees_usdt = 2.0
            self.paper.total_funding_usdt = -0.1

    executor = TelegramPositionExecutor()
    news = NewsEngine([])
    news.push_item("ETF approved for Bitcoin", "TestRSS")
    bot = InteractiveTelegramBot(
        token="test-token",
        allowed_chat_id="authorized",
        executor=executor,
        circuit_breaker=CircuitBreaker(),
        broker=PeriodicBroker(),
        state_store=store,
        news_engine=news,
        periodic_reports=True,
        report_interval_sec=0.01,
        initial_report_delay_sec=0,
    )
    return bot


def test_periodic_report_contains_real_health_pnl_indicators_and_news(tmp_path):
    bot = make_periodic_telegram_bot(tmp_path)
    report = run(bot.handle_command("/rapor", sender_chat_id="authorized"))
    assert "OTOMATİK BOT ANALİZİ — PAPER" in report
    assert "Durum kaydı: GÜNCEL" in report
    assert "swap / canlı" in report
    assert "Net Paper K/Z" in report
    assert "RSI 61.0" in report and "EMA9>21/MA20>50" in report
    assert "Funding +0.010%" in report
    assert "TREND/PULLBACK" in report and "YENI_LONG_GIRISI" in report
    assert "ETF approved for Bitcoin" in report


def test_compact_periodic_report_prioritizes_status_pnl_and_positions(tmp_path):
    bot = make_periodic_telegram_bot(tmp_path)
    bot.detailed_reports = False
    report = run(bot.handle_command("/rapor", sender_chat_id="authorized"))
    assert "OTOMATİK GENEL DURUM — PAPER" in report
    assert "Durum kaydı: GÜNCEL" in report
    assert "Net Paper K/Z" in report
    assert "POZİSYONLAR (1)" in report and SYMBOL in report
    assert "TEKNİK / PARA AKIŞI" not in report
    assert "RSI 61.0" not in report
    assert "ETF approved for Bitcoin" not in report


def test_periodic_report_loop_sends_and_updates_delivery_stats(tmp_path, monkeypatch):
    bot = make_periodic_telegram_bot(tmp_path)
    messages = []

    async def fake_send(token, chat_id, text):
        messages.append((token, chat_id, text))
        bot.stop()
        return True

    monkeypatch.setattr("src.telegram.send_telegram", fake_send)
    run(bot.periodic_report_forever())
    assert len(messages) == 1
    assert messages[0][0] == "test-token" and messages[0][1] == "authorized"
    assert "OTOMATİK BOT ANALİZİ" in messages[0][2]
    assert bot.report_stats["sent"] == 1
    assert bot.report_stats["failed"] == 0
    assert bot.report_stats["last_success_ts"] is not None


def test_send_telegram_checks_api_and_truncates_long_report(monkeypatch):
    import aiohttp

    posts = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self, content_type=None):
            return {"ok": True}

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def post(self, url, **kwargs):
            posts.append(kwargs["json"])
            return Response()

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    delivered = run(send_telegram("test-token", "authorized", "x" * 5000))
    assert delivered is True
    assert len(posts[0]["text"]) <= 4000
    assert "kısaltıldı" in posts[0]["text"]


def test_dashboard_requires_token_and_production_queues_commands(tmp_path, monkeypatch):
    token= "***REDACTED***"
    monkeypatch.setenv("DASHBOARD_TOKEN", token)
    hub = ProductionBotHub(tmp_path / "panel.db")
    assert hub.build_state_payload()["open_positions"] == []

    async def scenario():
        client = TestClient(TestServer(create_dashboard_app(hub)))
        await client.start_server()
        try:
            assert (await client.get("/api/state")).status == 401
            headers = {"X-Dashboard-Token": token}
            response = await client.get("/api/state", headers=headers)
            assert response.status == 200
            assert (await response.json())["demo"] is False
            response = await client.post(
                "/api/action", json={"action": "toggle_pause"}, headers=headers
            )
            assert response.status == 200
            assert hub.store.pop_commands()[0]["cmd"] == "PAUSE"
        finally:
            await client.close()

    run(scenario())


def test_executor_and_exchange_manager_paper_entry_and_close_roundtrip(tmp_path):
    from src.config import load_config
    from src.exchanges import ExchangeManager
    from src.sizing import PositionSizer

    cfg = load_config()
    cfg["paper"]["bakiye"] = 1_000.0
    broker = ExchangeManager(cfg)

    async def fake_bid_ask(symbol: str, exchange: str | None = None):
        return (99.98, 100.02)

    async def fake_best_price(symbol: str, side: str):
        return ("binance", 100.02 if side == "LONG" else 99.98)

    broker.fetch_bid_ask = fake_bid_ask  # type: ignore[method-assign]
    broker.best_price = fake_best_price  # type: ignore[method-assign]
    risk = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        leverage=10,
        unlimited_pyramiding=False,
        max_layers=1,
        pair_rescue_enabled=False,
    )
    strat = Strategy(runner_exit=True)
    sizer = PositionSizer(
        mode="sabit_usdt",
        fixed_margin_usdt=50.0,
        leverage=10,
        stats_path=tmp_path / "kelly.json",
    )
    store = StateStore(tmp_path / "state.db")
    breaker = CircuitBreaker(state_store=store)
    ex = Executor(
        broker,
        risk,
        strat,
        sizer=sizer,
        order_type="maker",
        maker_timeout=3.0,
        protection_on=True,
        state_store=store,
        circuit_breaker=breaker,
        runner_exit_cfg=cfg["cikis"],
    )

    async def scenario():
        try:
            combined = strat.combine(80.0, 75.0, 20.0, 60.0, market_context={"regime_aware": False})
            await ex.on_signal("BTC/USDT", 100.0, combined, -20.0, False)
            assert "BTC/USDT" in ex.positions
            assert breaker.tripped is False
            assert broker.rest_data_stats["binance"]["paper_fills"] >= 1
            await ex.on_price_tick("BTC/USDT", 112.0)
            assert ex.positions["BTC/USDT"].locked_profit is True
            closed_n = await ex.close_all_positions("TEST SONU")
            assert closed_n == 1
            assert "BTC/USDT" not in ex.positions
        finally:
            await broker.close()

    run(scenario())


def test_normalize_telegram_credentials_extracts_token_from_bot_url():
    from src.telegram import _normalize_telegram_credentials

    tok, cid = _normalize_telegram_credentials(
        "https://api.telegram.org/bot1234567890:ABCDEF_ghijklmno123456789012345/getUpdates",
        "chat_id=-100123456789",
    )
    assert tok == "1234567890:ABCDEF_ghijklmno123456789012345"
    assert cid == "-100123456789"


