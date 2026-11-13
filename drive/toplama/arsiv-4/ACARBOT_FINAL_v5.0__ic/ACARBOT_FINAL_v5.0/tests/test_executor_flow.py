"""Bütünleşme: Executor ile canlı akışın uçtan uca simülasyonu.

Spike → sinyal → portföy kontrolü → limit emir → dolum → pozisyon
yönetimi → kapanış. Ayrıca asenkron Telegram uyarı katmanı.
"""

import asyncio

import pytest

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from exec.paper import PaperBroker
from infra.feed import DataIntegrityManager
from infra.market_data.models import Candle
from safety.alerts import AlertManager
from state.store import StateStore
from tests.helpers import INTERVAL_MS, START_MS, make_candles, apex_config


def _fresh_executor(tmp_path, config=None):
    config = config or apex_config()
    store = StateStore(tmp_path / "exec_state.sqlite3", config.ops)
    broker = PaperBroker(config, 1_000.0)
    risk = RiskManager(config)
    integrity = DataIntegrityManager(config.data, now_ms=START_MS)
    executor = Executor(broker, risk, config, store, integrity)
    # Test hızlandırması: ısınma ve spike tabanı kısa
    integrity.config = type(integrity.config)(
        warmup_seconds=1.0, warmup_min_ticks=2,
        tick_freshness_s=60.0, global_stale_s=600.0,
    )
    from core.spike import SpikeDetector
    executor.spike_detector = SpikeDetector(
        multiplier=3.0, lookback_seconds=5, window_seconds=1,
        direction_seconds=5, sanity_cap=100.0,
    )
    return executor, store


def _warm_and_signal(executor):
    """Mumları besler; FADE-LONG sinyali üreten dip senaryosu.

    Dönen değer: (son mum, son mum zamanına yakın tick taban zamanı)
    """
    count = 60
    closes = [100.0] * count
    volumes = [10.0] * count
    closes[-2] = 98.2
    closes[-1] = 98.0
    volumes[-1] = 40.0
    candles = make_candles(closes, volumes=volumes)
    executor.update_candles("binance:TESTUSDT", candles)
    for candle in candles[:-1]:
        executor.on_candle_closed("binance:TESTUSDT", candle)
    last = candles[-1]
    return last, last.timestamp


class TestExecutorLiveFlow:
    def test_signal_places_limit_order(self, tmp_path):
        executor, store = _fresh_executor(tmp_path)
        last, tick_base = _warm_and_signal(executor)
        # Son mum kapanışına kadar akan taze tick'ler (gerçek akış gibi)
        for i in range(3):
            executor.process_price_update(
                "binance:TESTUSDT", 100.0, tick_base - 2 + i,
            )
        # Son mumun kapanışı → sinyal → limit emir
        executor.on_candle_closed("binance:TESTUSDT", last)
        pending = executor.broker.pending("binance:TESTUSDT")
        assert pending, "limit giriş emri beklemeli"
        assert pending[0].limit_price < last.close  # bid tarafında

    def test_tick_fills_entry_and_opens_position(self, tmp_path):
        executor, store = _fresh_executor(tmp_path)
        last, tick_base = _warm_and_signal(executor)
        for i in range(3):
            executor.process_price_update(
                "binance:TESTUSDT", 100.0, tick_base - 2 + i,
            )
        executor.on_candle_closed("binance:TESTUSDT", last)
        # Trade-through: fiyat limitin altına iner → emir dolar (97.95 < limit,
        # ama stopun üstünde → pozisyon açık kalır)
        events = executor.process_price_update(
            "binance:TESTUSDT", 97.95, tick_base + 60_000,
        )
        assert "binance:TESTUSDT" in executor.broker.portfolio.positions
        position = executor.broker.portfolio.positions["binance:TESTUSDT"]
        assert position.side == "LONG"
        assert position.initial_net_risk <= 25.0
        filled_events = [e for e in events if e.get("type") == "ENTRY_FILLED"]
        assert filled_events

    def test_adverse_selection_gap_fills_then_stops(self, tmp_path):
        """Ters seçilim: limit doldu, fiyat stopun da altındaysa aynı tick'te stop.

        Yorum 2-5'in öngörüsü: maker emir tam da fiyatın aleyhte döndüğü anda
        dolar. Yeni model bu gerçeği simüle eder; eski kod kaybı gizliyordu.
        """
        executor, _ = _fresh_executor(tmp_path)
        last, tick_base = _warm_and_signal(executor)
        for i in range(3):
            executor.process_price_update(
                "binance:TESTUSDT", 100.0, tick_base - 2 + i,
            )
        executor.on_candle_closed("binance:TESTUSDT", last)
        events = executor.process_price_update(
            "binance:TESTUSDT", 97.0, tick_base + 60_000,
        )
        types = [e.get("type") for e in events]
        assert "ENTRY_FILLED" in types
        assert "CLOSE" in types
        close_event = next(e for e in events if e.get("type") == "CLOSE")
        # v5.0: 25 USDT hedefli boyutlamada gap doğrudan acil net stopu
        # tetikleyebilir; ikisi de stop tarafıdır (TP değil).
        assert close_event["reason"] in {"stop_loss", "position_loss_stop"}
        # Net zarar şeffaf: brüt - ücretler - kayma
        assert close_event["pnl"] == pytest.approx(
            close_event["gross_pnl"] - close_event["entry_fee"]
            - close_event["fee"] - close_event["funding_paid"],
            rel=1e-6,
        )

    def test_store_records_trades_and_state(self, tmp_path):
        executor, store = _fresh_executor(tmp_path)
        last, tick_base = _warm_and_signal(executor)
        for i in range(3):
            executor.process_price_update(
                "binance:TESTUSDT", 100.0, tick_base - 2 + i,
            )
        executor.on_candle_closed("binance:TESTUSDT", last)
        executor.process_price_update("binance:TESTUSDT", 97.95, tick_base + 60_000)
        store.mark_dirty()
        store.save_state_if_due(executor.snapshot(), tick_base + 61_000, force=True)
        saved = store.load_state()
        assert saved["mode"] == "paper"
        assert "binance:TESTUSDT" in saved["positions"]

    def test_state_restored_on_restart(self, tmp_path):
        executor, store = _fresh_executor(tmp_path)
        last, tick_base = _warm_and_signal(executor)
        for i in range(3):
            executor.process_price_update(
                "binance:TESTUSDT", 100.0, tick_base - 2 + i,
            )
        executor.on_candle_closed("binance:TESTUSDT", last)
        executor.process_price_update("binance:TESTUSDT", 97.95, tick_base + 60_000)
        store.save_state(executor.snapshot())
        balance_before = executor.broker.portfolio.balance

        # Yeni executor aynı depodan kurtarma yapar
        executor2, _ = _fresh_executor(tmp_path)
        executor2.restore_state()
        assert executor2.broker.portfolio.balance == pytest.approx(balance_before)
        assert "binance:TESTUSDT" in executor2.broker.portfolio.positions
        restored = executor2.broker.portfolio.positions["binance:TESTUSDT"]
        assert restored.liquidation_price > 0

    def test_suspect_rvol_blocks_signal(self, tmp_path):
        """RVOL sanity cap aşılırsa spike sinyale dönüştürülmez (Y2-1/OKX birim)."""
        executor, _ = _fresh_executor(tmp_path)
        last, tick_base = _warm_and_signal(executor)
        for i in range(3):
            executor.process_price_update(
                "binance:TESTUSDT", 100.0, tick_base - 2 + i,
            )
        # Aşırı hacim: RVOL > sanity cap (100) → suspect → None
        events = executor.process_price_update(
            "binance:TESTUSDT", 100.5, tick_base + 50_000,
            volume_24h_quote=1e12,
        )
        # Sinyal akışında hata yok; suspect spike yok sayıldı
        assert all(e.get("type") != "ENTRY_FILLED" for e in events)


class TestAlertsAsync:
    def test_notify_never_blocks_and_logs(self):
        manager = AlertManager(telegram=None, rate_limit_per_min=20)
        result = manager.notify("test mesajı", "info")
        assert "test" in result

    def test_invalid_level_rejected(self):
        manager = AlertManager(telegram=None)
        with pytest.raises(ValueError):
            manager.notify("x", "ultra")

    def test_rate_limit_drops_excess(self):
        manager = AlertManager(telegram=None, rate_limit_per_min=3)
        for i in range(5):
            manager.notify_event(f"m{i}")
        assert manager.stats()["dropped"] >= 2

    def test_critical_message_enqueued_with_loop(self):
        async def scenario():
            manager = AlertManager(telegram=None, rate_limit_per_min=50)
            manager.attach_loop(asyncio.get_running_loop())
            manager.notify("kritik olay", "critical")
            # kuyruğa girdi; worker telegram'sız da güvenle döner
            await asyncio.sleep(0.05)
            await manager.stop()
        asyncio.run(scenario())

    def test_secrets_masked(self):
        manager = AlertManager(telegram=None)
        result = manager.notify("token=abc123def456 üretildi", "info")
        assert "abc123def456" not in result
