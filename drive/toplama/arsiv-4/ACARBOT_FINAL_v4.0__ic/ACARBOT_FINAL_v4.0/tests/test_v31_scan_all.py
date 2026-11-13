"""v3.1 — tam pazar taraması (--scan-all) testleri (dış v1.5 birleşimi).

Evren keşfi, CLI, giriş anında sweep defter tazeleme (book_fetcher), OKX WS
bağlantı parçalama, 429 pacer, rapor alanları ve tam pazar veri bütünlüğü.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.executor import Executor
from app.main import (
    _scan_all_universe,
    _ScanPacer,
    build_parser,
    write_session_report,
)
from core.config import SuperConfig
from core.risk import RiskManager
from core.strategy import Regime, Signal
from exec.paper import PaperBroker
from infra.exchanges.binance import BinancePublic
from infra.exchanges.okx import OKXPublic
from tests.helpers import flat_series, make_candles


def _parse(argv):
    return build_parser().parse_args(argv)


class ScanAllCliTests(unittest.TestCase):
    def test_scan_all_flag(self):
        args = _parse(["--paper", "--scan-all"])
        self.assertTrue(args.scan_all)

    def test_scan_all_default_off(self):
        args = _parse(["--paper"])
        self.assertFalse(args.scan_all)

    def test_scan_cycle_default(self):
        args = _parse(["--paper", "--scan-all"])
        self.assertEqual(args.scan_cycle_seconds, 60.0)

    def test_scan_cycle_custom(self):
        args = _parse(["--paper", "--scan-all", "--scan-cycle-seconds", "90"])
        self.assertEqual(args.scan_cycle_seconds, 90.0)

    def test_combined_with_motors_and_apex(self):
        args = _parse(["--paper", "--scan-all", "--motors", "trend",
                       "--profile", "apex"])
        self.assertTrue(args.scan_all)
        self.assertEqual(args.motors, "trend")
        self.assertEqual(args.profile, "apex")

    def test_apply_profile_sets_full_market(self):
        from app.main import apply_profile
        cfg = apply_profile(_parse(["--paper", "--scan-all"]), SuperConfig())
        self.assertTrue(cfg.data.full_market)
        cfg2 = apply_profile(_parse(["--paper"]), SuperConfig())
        self.assertFalse(cfg2.data.full_market)


class UniverseDiscoveryTests(unittest.TestCase):
    """Evren keşfi: fetch_top_usdt_futures tüm canlı USDT sözleşmelerini
    döndürür (hacimsel sıralı); --scan-all YALNIZ perpetual/spot ayna
    enstrümanlarını alır (vadeliler hariç). Filtreleme bu testlerle kilitli."""

    def _binance_client(self):
        client = BinancePublic()
        payloads = {
            "/fapi/v1/exchangeInfo": {"symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING",
                 "quoteAsset": "USDT", "contractType": "PERPETUAL",
                 "baseAsset": "BTC", "filters": []},
                {"symbol": "ETHUSDT", "status": "TRADING",
                 "quoteAsset": "USDT", "contractType": "PERPETUAL",
                 "baseAsset": "ETH", "filters": []},
                {"symbol": "BTCUSDT_250328", "status": "TRADING",
                 "quoteAsset": "USDT", "contractType": "CURRENT_QUARTER",
                 "baseAsset": "BTC", "filters": []},
                {"symbol": "ETHBTC", "status": "TRADING",
                 "quoteAsset": "BTC", "contractType": "PERPETUAL",
                 "baseAsset": "ETH", "filters": []},
                {"symbol": "OLDUSDT", "status": "BREAK",
                 "quoteAsset": "USDT", "contractType": "PERPETUAL",
                 "baseAsset": "OLD", "filters": []},
            ]},
            "/fapi/v1/ticker/24hr": [
                {"symbol": "BTCUSDT", "quoteVolume": "1000",
                 "priceChangePercent": "1"},
                {"symbol": "ETHUSDT", "quoteVolume": "500",
                 "priceChangePercent": "2"},
            ],
        }
        client._get_json = Mock(
            side_effect=lambda path, params: payloads[path],
        )
        return client

    def test_binance_excludes_non_usdt_and_halted(self):
        """fetch_top_usdt_futures: USDT-perp dışı + duran listeler DIŞARIDA;
        vadeli sözleşmeler FONKSİYONDA kalır (evren adımında düşürülür)."""
        markets = self._binance_client().fetch_top_usdt_futures(10_000)
        symbols = {m.symbol for m in markets}
        self.assertEqual(symbols, {"BTCUSDT", "ETHUSDT", "BTCUSDT_250328"})

    def test_okx_live_linear_usdt_only(self):
        client = OKXPublic()
        payloads = {
            ("/api/v5/public/instruments", "SWAP"): {"code": "0", "data": [
                {"instId": "BTC-USDT-SWAP", "state": "live",
                 "settleCcy": "USDT", "ctType": "linear", "ctVal": "0.01",
                 "baseCcy": "BTC", "minSz": "1", "lotSz": "1",
                 "tickSz": "0.1"},
                {"instId": "ETH-USD-SWAP", "state": "live",
                 "settleCcy": "USD", "ctType": "inverse", "ctVal": "0.01",
                 "baseCcy": "ETH", "minSz": "1", "lotSz": "1",
                 "tickSz": "0.1"},
                {"instId": "OLD-USDT-SWAP", "state": "suspend",
                 "settleCcy": "USDT", "ctType": "linear", "ctVal": "0.01",
                 "baseCcy": "OLD", "minSz": "1", "lotSz": "1",
                 "tickSz": "0.1"},
            ]},
            ("/api/v5/market/tickers", "SWAP"): {"code": "0", "data": [
                {"instId": "BTC-USDT-SWAP", "last": "100", "open24h": "99",
                 "vol24h": "10", "volCcy24h": "1", "ts": "1"},
            ]},
            ("/api/v5/public/instruments", "FUTURES"): {
                "code": "0", "data": [],
            },
            ("/api/v5/market/tickers", "FUTURES"): {
                "code": "0", "data": [],
            },
        }

        def fake_get(path, params):
            return payloads[(path, params["instType"])]

        client._get_json = Mock(side_effect=fake_get)
        markets = client.fetch_top_usdt_futures(10_000)
        symbols = {m.symbol for m in markets}
        self.assertEqual(symbols, {"BTC-USDT-SWAP"})

    def test_universe_sorted_by_volume_not_alphabetical(self):
        markets = self._binance_client().fetch_top_usdt_futures(10_000)
        # Sıralama hacimsel, alfabetik değil (BTCUSDT 1000 > ETHUSDT 500 >
        # vadeliler 0 hacim); BTCUSDT_250328 alfabetikte öne geçerdi.
        self.assertEqual(
            [m.symbol for m in markets],
            ["BTCUSDT", "ETHUSDT", "BTCUSDT_250328"],
        )

    def test_universe_builder_drops_quarterlies(self):
        """--scan-all evreni vadeli sözleşmeleri DÜŞÜRMELİ (main.py kuralı)."""
        markets = self._binance_client().fetch_top_usdt_futures(10_000)
        universe = _scan_all_universe(markets, "binance")
        self.assertEqual(universe, ["BTCUSDT", "ETHUSDT"])

    def test_universe_builder_okx_keeps_swaps_only(self):
        """OKX'te SWAP = lineer perpetual; FUTURES (vadeliler) düşürülmeli."""
        from infra.exchanges.base import Market
        markets = [
            Market("BTC-USDT-SWAP", "BTC", 1000.0, "SWAP", 0.1, 1.0),
            Market("BTC-USDT-250926", "BTC", 500.0, "FUTURES", 0.1, 1.0),
        ]
        self.assertEqual(_scan_all_universe(markets, "okx"), ["BTC-USDT-SWAP"])
        # hacimsel sıra KORUNUR (fetch zaten hacim sıralı verir; fonksiyon
        # yeniden sıralamaz, yalnız süzer)
        mixed = [
            Market("BTCUSDT", "BTC", 900.0, "PERPETUAL", 0.1, 1.0),
            Market("SOLUSDT", "SOL", 500.0, "PERPETUAL", 0.1, 1.0),
            Market("ETHUSDT", "ETH", 100.0, "PERPETUAL", 0.1, 1.0),
        ]
        self.assertEqual(
            _scan_all_universe(mixed, "binance"),
            ["BTCUSDT", "SOLUSDT", "ETHUSDT"],
        )


class BookFetcherTests(unittest.TestCase):
    def _executor(self, sweep_guard, book_fetcher):
        cfg = SuperConfig()
        cfg.v2 = replace(cfg.v2, enabled=False)
        broker = PaperBroker(cfg, 1000.0)
        ex = Executor(broker, RiskManager(cfg), cfg, sweep_guard=sweep_guard)
        ex.book_fetcher = book_fetcher
        ex.store = None
        ex.broker.place_entry = Mock(return_value=SimpleNamespace(
            id="o1", limit_price=100.0, quantity=1.0,
            status=SimpleNamespace(value="PENDING"),
        ))
        ex.broker.bind_plan = Mock()
        return ex

    def _run_to_sweep(self, ex):
        candles = make_candles(flat_series(count=80))
        sig = Signal("LONG", "trend", 0.5, 2.0, 0.01, confidence=0.6)
        with patch.object(ex.resolver, "resolve", return_value=sig), \
             patch.object(ex.regime_detector, "classify",
                          return_value=Regime.TREND_UP):
            ex._evaluate_entry("okx:BTC-USDT-SWAP", candles,
                               candles[-1].timestamp)

    def test_book_fetcher_called_before_sweep(self):
        calls = []
        sweep = Mock()
        sweep.entry_block = Mock(
            side_effect=lambda *a: calls.append("sweep") or "blok",
        )
        fetcher = Mock(side_effect=lambda key: calls.append("fetch"))
        ex = self._executor(sweep, fetcher)
        self._run_to_sweep(ex)
        fetcher.assert_called_once_with("okx:BTC-USDT-SWAP")
        self.assertEqual(calls, ["fetch", "sweep"])

    def test_book_fetcher_error_does_not_crash(self):
        sweep = Mock()
        sweep.entry_block = Mock(return_value="blok")
        fetcher = Mock(side_effect=RuntimeError("ağ hatası"))
        ex = self._executor(sweep, fetcher)
        self._run_to_sweep(ex)  # exception yutulmalı
        sweep.entry_block.assert_called_once()

    def test_no_fetcher_still_checks_sweep(self):
        sweep = Mock()
        sweep.entry_block = Mock(return_value=None)
        ex = self._executor(sweep, None)
        self._run_to_sweep(ex)
        sweep.entry_block.assert_called_once()


class OkxShardingTests(unittest.TestCase):
    def test_small_list_single_chunk(self):
        client = OKXPublic()
        seen = []

        async def fake_chunk(ids):
            seen.append(list(ids))
            for i in ids:
                yield SimpleNamespace(symbol=i)

        async def run():
            with patch.object(client, "_stream_tickers_chunk", fake_chunk):
                return [t.symbol async for t in client.stream_tickers(
                    [f"C{i}-USDT-SWAP" for i in range(10)])]

        out = asyncio.run(run())
        self.assertEqual(len(out), 10)
        self.assertEqual(len(seen), 1)

    def test_large_list_sharded_and_merged(self):
        client = OKXPublic()
        seen = []

        async def fake_chunk(ids):
            seen.append(len(ids))
            for i in ids:
                yield SimpleNamespace(symbol=i)

        async def run():
            with patch.object(client, "_stream_tickers_chunk", fake_chunk):
                gen = client.stream_tickers(
                    [f"C{i:04d}-USDT-SWAP" for i in range(600)])
                out = []
                # Gerçek akış sonsuzdur; testte 600 ticker alıp çıkıyoruz.
                async for t in gen:
                    out.append(t.symbol)
                    if len(out) == 600:
                        break
                await gen.aclose()
                return out

        out = asyncio.run(run())
        self.assertEqual(len(out), 600)
        self.assertEqual(sorted(seen), [100, 250, 250])

    def test_chunk_error_propagates(self):
        client = OKXPublic()

        async def fake_chunk(ids):
            if len(ids) == 250:
                raise RuntimeError("ws koptu")
            for i in ids:
                yield SimpleNamespace(symbol=i)

        async def run():
            with patch.object(client, "_stream_tickers_chunk", fake_chunk):
                async for _ in client.stream_tickers(
                    [f"C{i:04d}-USDT-SWAP" for i in range(300)]):
                    pass

        with self.assertRaises(RuntimeError):
            asyncio.run(run())


class ScanPacerTests(unittest.TestCase):
    """v3.1: 429 rate limit koruması — saniyelik istek pacer'ı."""

    def test_pacer_enforces_min_interval(self):
        async def run():
            loop = asyncio.get_running_loop()
            pacer = _ScanPacer(50.0, loop)  # 20 ms istek aralığı
            start = loop.time()
            for _ in range(5):
                await pacer.wait()
            return loop.time() - start

        elapsed = asyncio.run(run())
        # 5 istek → 4 bekleme aralığı ≈ 80 ms; toleransla ≥ 60 ms
        self.assertGreaterEqual(elapsed, 0.06)

    def test_pacer_zero_delay_when_idle(self):
        async def run():
            loop = asyncio.get_running_loop()
            pacer = _ScanPacer(1000.0, loop)
            start = loop.time()
            await pacer.wait()
            await pacer.wait()
            return loop.time() - start

        elapsed = asyncio.run(run())
        self.assertLess(elapsed, 0.5)  # 1 ms aralıkla anında dönmeli


class ScanAllReportTests(unittest.TestCase):
    def _fake_executor(self):
        portfolio = SimpleNamespace(
            balance=1000.0, positions={}, initial_balance=1000.0,
        )
        broker = SimpleNamespace(
            portfolio=portfolio, trades=[],
            mark_to_market=lambda prices: portfolio.balance,
        )
        portfolio.unrealized_pnl = lambda prices: 0.0
        return SimpleNamespace(
            broker=broker,
            risk=SimpleNamespace(
                kill_switch_state=SimpleNamespace(value="NORMAL"),
            ),
            data_integrity=SimpleNamespace(safe_mode=False),
            _latest_prices={},
        )

    def test_report_universe_fields(self):
        from monitor.report import SimpleMetrics
        args = _parse(["--paper", "--scan-all"])
        with tempfile.TemporaryDirectory() as tmp:
            args.report_file = str(Path(tmp) / "r.json")
            report = write_session_report(
                args, self._fake_executor(), Mock(), SimpleMetrics(),
                1_800_000_000_000, 1000.0,
                universe={"binance": ["A", "B"], "okx": ["C"]},
            )
        self.assertTrue(report["scan_all"])
        self.assertEqual(report["universe_sizes"], {"binance": 2, "okx": 1})
        self.assertEqual(report["symbols"], "ALL-USDT")

    def test_report_without_scan_all(self):
        from monitor.report import SimpleMetrics
        args = _parse(["--paper"])
        with tempfile.TemporaryDirectory() as tmp:
            args.report_file = str(Path(tmp) / "r.json")
            report = write_session_report(
                args, self._fake_executor(), Mock(), SimpleMetrics(),
                1_800_000_000_000, 1000.0,
            )
        self.assertFalse(report["scan_all"])
        self.assertEqual(report["symbols"], args.symbols)

    def test_report_signal_thresholds_and_stale_counter(self):
        from monitor.report import SimpleMetrics
        args = _parse([
            "--paper", "--min-rvol", "1.2", "--motors", "trend",
        ])
        ex = self._fake_executor()
        ex.config = SimpleNamespace(signal=SimpleNamespace(
            min_rvol_for_entry=1.2, fade_impulse_pct=0.35,
            spike_multiplier=3.0, enabled_motors=("trend",),
        ))
        ex.stale_entry_cancels = 3
        with tempfile.TemporaryDirectory() as tmp:
            args.report_file = str(Path(tmp) / "r.json")
            report = write_session_report(
                args, ex, Mock(), SimpleMetrics(),
                1_800_000_000_000, 1000.0,
            )
        self.assertEqual(
            report["signal_thresholds"]["min_rvol_for_entry"], 1.2,
        )
        self.assertEqual(
            report["signal_thresholds"]["enabled_motors"], ["trend"],
        )
        self.assertEqual(report["stale_entry_cancels"], 3)


class FullMarketIntegrityTests(unittest.TestCase):
    """v3.1: 1000+ sembolde ısınma/bayatlık kuralları ölçeklenmeli."""

    def _mgr(self, full_market: bool):
        from infra.feed import DataIntegrityManager
        cfg = replace(
            SuperConfig().data,
            full_market=full_market, warmup_seconds=1.0,
        )
        return DataIntegrityManager(cfg, now_ms=0)

    def test_narrow_list_requires_all_warm(self):
        m = self._mgr(full_market=False)
        for i in range(10):
            for _ in range(5):
                m.record_tick(f"S{i}", 2000)
        m.record_tick("COLD", 2000)  # 1 tick < 5
        self.assertFalse(m.is_warmed_up(2000))  # TÜMÜ şart

    def test_full_market_majority_warm(self):
        m = self._mgr(full_market=True)
        # 10 feed ısınmış (5 tick), 4 feed soğuk (1 tick) → %71 ≥ %50
        for i in range(10):
            for _ in range(5):
                m.record_tick(f"W{i}", 2000)
        for i in range(4):
            m.record_tick(f"C{i}", 2000)
        self.assertTrue(m.is_warmed_up(2000))

    def test_full_market_minority_warm_fails(self):
        m = self._mgr(full_market=True)
        for i in range(3):
            for _ in range(5):
                m.record_tick(f"W{i}", 2000)
        for i in range(20):
            m.record_tick(f"C{i}", 2000)
        self.assertFalse(m.is_warmed_up(2000))  # 3/23 < %50 ve < 5

    def test_full_market_stale_ignores_cold_coins(self):
        m = self._mgr(full_market=True)
        now = 200_000
        # 50 yerleşik feed taze (ısınma: 50/100 ≥ gerekli → geçer)
        for i in range(50):
            for _ in range(5):
                m.record_tick(f"HOT{i}", now)
        # 50 düşük hacimli coin: 1 tick, çok eski → yerleşik DEĞİL, sayılmaz
        for i in range(50):
            m.record_tick(f"COLD{i}", 1000)
        self.assertFalse(m.update_global_state(now))  # safe mode YOK

    def test_full_market_pipeline_death_triggers_safe(self):
        m = self._mgr(full_market=True)
        # 10 yerleşik feed'in hepsi 200 sn önce tick almış → %100 bayat
        for i in range(10):
            for _ in range(5):
                m.record_tick(f"F{i}", 1000)
        self.assertTrue(m.update_global_state(200_000))
        self.assertEqual(m.safe_mode_reason, "global_stale_data")


if __name__ == "__main__":
    unittest.main()
