"""v2.0 — Kontrol paneli, canlı eşleme güvenliği ve executor entegrasyonu."""

from __future__ import annotations


import pytest

from app.executor import Executor
from core.risk import RiskManager
from exec.paper import PaperBroker
from infra.feed import DataIntegrityManager
from infra.market_data.models import Candle
from monitor.dashboard import collect_snapshot, render_text
from state.store import StateStore
from tests.helpers import INTERVAL_MS, START_MS, make_candles, apex_config


def _fresh_executor(tmp_path, config=None, balance=1_000.0):
    config = config or apex_config()
    store = StateStore(tmp_path / "v2_state.sqlite3", config.ops)
    broker = PaperBroker(config, balance)
    risk = RiskManager(config)
    integrity = DataIntegrityManager(config.data, now_ms=START_MS)
    executor = Executor(broker, risk, config, store, integrity)
    integrity.config = type(integrity.config)(
        warmup_seconds=1.0, warmup_min_ticks=2,
        tick_freshness_s=60.0, global_stale_s=600.0,
    )
    return executor, store


def _dip_candles(count=60):
    closes = [100.0] * count
    volumes = [10.0] * count
    closes[-2] = 98.2
    closes[-1] = 98.0
    volumes[-1] = 40.0
    return make_candles(closes, volumes=volumes)


def _warm_ticks(executor, symbol: str, ts_ms: int, price: float = 100.0):
    """Isınma + taze tick şartı için birkaç tık besler (canlı akış gibi)."""
    for i in range(3):
        executor.process_price_update(symbol, price, ts_ms - 2_000 + i * 1_000)


class TestDashboard:
    def _exec_with_signal(self, tmp_path):
        executor, store = _fresh_executor(tmp_path)
        candles = _dip_candles()
        _warm_ticks(executor, "binance:TESTUSDT", candles[-1].timestamp)
        executor.update_candles("binance:TESTUSDT", candles)
        for candle in candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", candles[-1])
        return executor, store, candles

    def test_snapshot_has_nine_sections(self, tmp_path):
        executor, _, _ = self._exec_with_signal(tmp_path)
        snapshot = collect_snapshot(executor)
        for section in ("overview", "positions", "signals", "scanner",
                        "risk", "orders", "strategy", "health",
                        "performance"):
            assert section in snapshot
        assert snapshot["overview"]["data_source"] == "perp"
        assert snapshot["overview"]["equity_floor"] == pytest.approx(850.0)

    def test_snapshot_reports_why_not_trading(self, tmp_path):
        """Panel 'neden işlem açmadı' bilgisini taşır (şartname 8)."""
        executor, _, _ = self._exec_with_signal(tmp_path)
        snapshot = collect_snapshot(executor)
        assert snapshot["signals"], "değerlendirme kaydı olmalı"
        top = snapshot["signals"][0]
        assert "reason" in top and top["reason"]
        assert top["score"] > 0

    def test_render_text_contains_sections(self, tmp_path):
        executor, _, _ = self._exec_with_signal(tmp_path)
        text = render_text(collect_snapshot(executor))
        for header in ("GENEL", "AÇIK POZİSYONLAR", "SİNYAL MERKEZİ",
                       "RİSK MERKEZİ", "PERFORMANS", "veri:"):
            assert header in text

    def test_position_section_after_fill(self, tmp_path):
        executor, _, candles = self._exec_with_signal(tmp_path)
        last = candles[-1]
        executor.process_price_update(
            "binance:TESTUSDT", 97.9, last.timestamp + 60_000,
        )
        snapshot = collect_snapshot(executor)
        assert snapshot["positions"], "dolumdan sonra pozisyon görünmeli"
        pos = snapshot["positions"][0]
        assert pos["side"] == "LONG"
        assert "score" in pos and "regime" in pos


class TestExecutorV2:
    def test_forming_candle_replaced_not_duplicated(self, tmp_path):
        """Eksik (forming) mum kapanmış mumla DEĞİŞİR (şartname 2)."""
        executor, _ = _fresh_executor(tmp_path)
        candles = _dip_candles()
        executor.update_candles("binance:TESTUSDT", candles)
        closed = candles[-1]
        forming = Candle(
            timestamp=closed.timestamp + INTERVAL_MS,
            open=closed.close, high=closed.close, low=closed.close,
            close=closed.close, volume=0.0,
        )
        # REST listesi forming ile biter; kapanan mum bildirilir
        executor.update_candles("binance:TESTUSDT", candles + [forming])
        executor.on_candle_closed("binance:TESTUSDT", closed)
        stored = executor._candles["binance:TESTUSDT"]
        assert stored[-1].timestamp == closed.timestamp
        assert sum(1 for c in stored if c.timestamp == closed.timestamp) == 1

    def test_mtf_conflict_blocks_entry(self, tmp_path):
        """5m LONG sinyali + 15m/1h güçlü SHORT → işlem engellenir."""
        executor, _ = _fresh_executor(tmp_path)
        down = make_candles(
            [200.0 * (1 - i * 0.004) for i in range(60)],
        )
        executor.update_htf_candles("binance:TESTUSDT", "15m", down)
        executor.update_htf_candles("binance:TESTUSDT", "1h", down)
        candles = _dip_candles()
        _warm_ticks(executor, "binance:TESTUSDT", candles[-1].timestamp)
        executor.update_candles("binance:TESTUSDT", candles)
        for candle in candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", candles[-1])
        assert not executor.broker.pending("binance:TESTUSDT")
        assert "MTF uyumsuz" in executor.last_block_reason.get(
            "binance:TESTUSDT", "",
        )

    def test_rate_limit_defers_second_entry_same_minute(self, tmp_path):
        """Dakikada 1 gerçek giriş sınırı: ikinci aday KUYRUĞA alınır."""
        from dataclasses import replace
        config = apex_config()
        config.v2 = replace(
            config.v2, gates=replace(config.v2.gates, entry_rate_per_min=1),
        )
        # v5.0: 25 USDT risk → pozisyon başına ~500 USDT teminat. Testin
        # amacı hız limiti olduğu için bakiye iki pozisyonu rahat kaldırır.
        executor, _ = _fresh_executor(tmp_path, config, balance=10_000.0)
        candles_a = _dip_candles()
        base_ts = candles_a[-1].timestamp
        # İlk sembol: sinyal → emir → dolum (GERÇEK giriş sayılır)
        _warm_ticks(executor, "binance:AAAUSDT", base_ts)
        executor.update_candles("binance:AAAUSDT", candles_a)
        for candle in candles_a[:-1]:
            executor.on_candle_closed("binance:AAAUSDT", candle)
        executor.on_candle_closed("binance:AAAUSDT", candles_a[-1])
        assert executor.broker.pending("binance:AAAUSDT")
        executor.process_price_update(
            "binance:AAAUSDT", 97.9, base_ts + 1_000,
        )
        assert "binance:AAAUSDT" in executor.broker.portfolio.positions
        # İkinci sembol aynı dakikada sinyal üretir → hız limiti
        candles_b = _dip_candles()
        _warm_ticks(executor, "binance:BBBUSDT", candles_b[-1].timestamp + 500)
        executor.update_candles("binance:BBBUSDT", candles_b)
        for candle in candles_b[:-1]:
            executor.on_candle_closed("binance:BBBUSDT", candle)
        executor.on_candle_closed("binance:BBBUSDT", candles_b[-1])
        assert not executor.broker.pending("binance:BBBUSDT")
        stats = executor.rate_limiter.stats()
        assert stats["deferred"] >= 1

    def test_reentry_cooldown_after_stop(self, tmp_path):
        """Stop sonrası aynı sembolde 15 dk yeni giriş yok (şartname A-5)."""
        executor, _ = _fresh_executor(tmp_path)
        candles = _dip_candles()
        _warm_ticks(executor, "binance:TESTUSDT", candles[-1].timestamp)
        executor.update_candles("binance:TESTUSDT", candles)
        for candle in candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", candles[-1])
        # Dolum + stop
        last = candles[-1]
        executor.process_price_update(
            "binance:TESTUSDT", 97.0, last.timestamp + 60_000,
        )
        assert "binance:TESTUSDT" not in executor.broker.portfolio.positions
        # 15 dk içinde yeni dip sinyali → bekleme nedeniyle emir YOK
        closes = [98.0] * 58 + [96.2, 96.0]
        volumes = [10.0] * 59 + [40.0]
        new_candles = make_candles(
            closes, volumes=volumes,
            start_ms=last.timestamp + 3 * INTERVAL_MS - 59 * INTERVAL_MS,
        )
        executor.update_candles("binance:TESTUSDT", new_candles)
        _warm_ticks(
            executor, "binance:TESTUSDT", new_candles[-1].timestamp, 96.0,
        )
        for candle in new_candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", new_candles[-1])
        assert not executor.broker.pending("binance:TESTUSDT")
        assert "yeniden giriş" in executor.last_block_reason.get(
            "binance:TESTUSDT", "",
        )

    def test_score_recorded_on_position(self, tmp_path):
        executor, _, = _fresh_executor(tmp_path)
        candles = _dip_candles()
        _warm_ticks(executor, "binance:TESTUSDT", candles[-1].timestamp)
        executor.update_candles("binance:TESTUSDT", candles)
        for candle in candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", candles[-1])
        last = candles[-1]
        executor.process_price_update(
            "binance:TESTUSDT", 97.9, last.timestamp + 60_000,
        )
        position = executor.broker.portfolio.positions["binance:TESTUSDT"]
        assert position.score > 0
        assert position.regime

    def test_data_source_label_updates(self, tmp_path):
        executor, _ = _fresh_executor(tmp_path)
        executor.set_data_source("spot-mirror")
        assert executor.data_source == "spot-mirror"
        snapshot = executor.snapshot()
        assert snapshot["data_source"] == "spot-mirror"

    def test_session_report_contains_v2_fields(self, tmp_path):
        executor, store = _fresh_executor(tmp_path)
        candles = _dip_candles()
        _warm_ticks(executor, "binance:TESTUSDT", candles[-1].timestamp)
        executor.update_candles("binance:TESTUSDT", candles)
        for candle in candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", candles[-1])
        executor.process_price_update(
            "binance:TESTUSDT", 97.9, candles[-1].timestamp + 60_000,
        )
        stats = executor.risk_stats
        assert stats["max_concurrent_positions"] >= 1.0
        assert stats["equity_peak"] >= stats["equity_trough"]
        assert executor.last_shock_summary["unavailable"] >= 1


class TestShadowPersistence:
    def test_blocked_entry_persisted_to_store(self, tmp_path):
        """Haber koruması engelli giriş gölge kayda düşer (şartname B-6)."""
        executor, store = _fresh_executor(tmp_path)

        class _FakeGuard:
            def blackout(self, now_ms):
                return True, "test_engel"

            def status(self):
                return {}

        executor.news_guard = _FakeGuard()
        candles = _dip_candles()
        _warm_ticks(executor, "binance:TESTUSDT", candles[-1].timestamp)
        executor.update_candles("binance:TESTUSDT", candles)
        for candle in candles[:-1]:
            executor.on_candle_closed("binance:TESTUSDT", candle)
        executor.on_candle_closed("binance:TESTUSDT", candles[-1])
        assert executor.shadow_tracker.records
        assert executor.shadow_tracker.records[0].reason == "NEWS_GUARD"
        rows = store.load_shadow_signals()
        assert rows and rows[0]["reason"] == "NEWS_GUARD"


class TestEntryTiming1m:
    def test_entry_timing_neutral_without_data(self):
        """1m verisi yoksa 'ok' ('uygulanmadı' — engel konmaz)."""
        from core.mtf import MtfAnalyzer
        analyzer = MtfAnalyzer()
        assert analyzer.entry_timing(None, "LONG") == "ok"
        assert analyzer.entry_timing([], "LONG") == "ok"

    def test_entry_timing_blocks_opposite_1m(self, tmp_path):
        """1m bariz ters yönde → giriş ertelenir ('wait')."""
        executor, _ = _fresh_executor(tmp_path)
        down = make_candles(
            [300.0 * (1 - i * 0.003) for i in range(60)],
            interval_ms=60_000,
        )
        executor.update_htf_candles("binance:TESTUSDT", "1m", down)
        assert executor.mtf_analyzer.entry_timing(down, "LONG") == "wait"
        assert executor.mtf_analyzer.entry_timing(down, "SHORT") == "ok"
