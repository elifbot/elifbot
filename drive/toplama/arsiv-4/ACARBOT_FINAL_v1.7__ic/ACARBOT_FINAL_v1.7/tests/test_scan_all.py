"""FINAL v1.5 testleri: tam pazar taraması (--scan-all).

Kullanıcı isteği (7 Kasım 2026): Binance 500+ / OKX 200+ coinin TAMAMI
aynı anda taranacak. Bu testler evren keşfi, CLI, isteğe bağlı sweep
defter tazeleme, OKX bağlantı parçalama ve rapor alanlarını kilitler.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.executor import Executor
from app.main import build_parser, write_session_report
from core.config import SuperConfig
from core.risk import RiskManager
from core.strategy import Signal
from exec.paper import PaperBroker
from infra.symbol_universe import binance_usdt_symbols, okx_usdt_swaps, discover
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


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def _get_json(self, path, params):
        self.calls.append((path, params))
        return self.payload


class UniverseDiscoveryTests(unittest.TestCase):
    def test_binance_spot_format(self):
        payload = {"symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT", "status": "TRADING", "quoteAsset": "USDT"},
            {"symbol": "ETHBTC", "status": "TRADING", "quoteAsset": "BTC"},
            {"symbol": "OLDUSDT", "status": "BREAK", "quoteAsset": "USDT"},
        ]}
        out = binance_usdt_symbols(_FakeClient(payload))
        self.assertEqual(out, ["BTCUSDT", "ETHUSDT"])

    def test_binance_futures_perpetual_only(self):
        payload = {"symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT",
             "contractType": "PERPETUAL"},
            {"symbol": "BTCUSDT_250328", "status": "TRADING",
             "quoteAsset": "USDT", "contractType": "CURRENT_QUARTER"},
        ]}
        out = binance_usdt_symbols(_FakeClient(payload))
        self.assertEqual(out, ["BTCUSDT"])

    def test_binance_dedup_sorted(self):
        payload = {"symbols": [
            {"symbol": "SOLUSDT", "status": "TRADING", "quoteAsset": "USDT"},
            {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT"},
            {"symbol": "SOLUSDT", "status": "TRADING", "quoteAsset": "USDT"},
        ]}
        out = binance_usdt_symbols(_FakeClient(payload))
        self.assertEqual(out, ["BTCUSDT", "SOLUSDT"])

    def test_binance_bad_payload_raises(self):
        with self.assertRaises(ValueError):
            binance_usdt_symbols(_FakeClient({"nope": 1}))

    def test_okx_live_linear_usdt(self):
        payload = {"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "state": "live",
             "settleCcy": "USDT", "ctType": "linear"},
            {"instId": "ETH-USD-SWAP", "state": "live",
             "settleCcy": "USD", "ctType": "inverse"},
            {"instId": "OLD-USDT-SWAP", "state": "suspend",
             "settleCcy": "USDT", "ctType": "linear"},
        ]}
        out = okx_usdt_swaps(_FakeClient(payload))
        self.assertEqual(out, ["BTC-USDT-SWAP"])

    def test_okx_bad_code_raises(self):
        with self.assertRaises(ValueError):
            okx_usdt_swaps(_FakeClient({"code": "50011", "data": []}))

    def test_discover_routes(self):
        bn = _FakeClient({"symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT"},
        ]})
        self.assertEqual(discover("binance", bn), ["BTCUSDT"])
        self.assertEqual(bn.calls[0][0], "/fapi/v1/exchangeInfo")
        with self.assertRaises(ValueError):
            discover("kraken", bn)


class BookFetcherTests(unittest.TestCase):
    def _executor(self, sweep_guard, book_fetcher):
        cfg = SuperConfig()
        broker = PaperBroker(cfg, 1000.0)
        ex = Executor(broker, RiskManager(cfg), cfg, sweep_guard=sweep_guard)
        ex.book_fetcher = book_fetcher
        return ex

    def _run_to_sweep(self, ex):
        candles = make_candles(flat_series(count=80))
        sig = Signal("LONG", "trend", 0.5, 2.0, 0.01, confidence=0.6)
        with patch.object(ex.resolver, "resolve", return_value=sig), \
             patch.object(ex.regime_detector, "classify",
                          return_value=__import__("core.strategy", fromlist=["Regime"]).Regime.TREND_UP):
            ex._evaluate_entry("okx:BTC-USDT-SWAP", candles, candles[-1].timestamp)

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
        from infra.exchanges.okx import OKXPublic
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
        from infra.exchanges.okx import OKXPublic
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
                # Gerçek akış sonsuzdur; testte tam 600 ticker alıp çıkıyoruz.
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
        from infra.exchanges.okx import OKXPublic
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


class ScanAllReportTests(unittest.TestCase):
    def _fake_executor(self):
        portfolio = SimpleNamespace(balance=1000.0, positions={})
        broker = SimpleNamespace(
            portfolio=portfolio, trades=[],
            mark_to_market=lambda prices: portfolio.balance,
        )
        portfolio.unrealized_pnl = lambda prices: 0.0
        return SimpleNamespace(
            broker=broker,
            risk=SimpleNamespace(kill_switch_state=SimpleNamespace(value="NORMAL")),
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


class FullMarketIntegrityTests(unittest.TestCase):
    """v1.5: 1000+ sembolde ısınma/bayatlık kuralları ölçeklenmeli."""

    def _mgr(self, full_market: bool):
        from dataclasses import replace
        from core.config import DataConfig
        from infra.feed import DataIntegrityManager
        cfg = replace(DataConfig(), full_market=full_market, warmup_seconds=1.0)
        return DataIntegrityManager(cfg, now_ms=0)

    def test_apply_profile_sets_full_market(self):
        from app.main import apply_profile
        cfg = apply_profile(_parse(["--paper", "--scan-all"]), SuperConfig())
        self.assertTrue(cfg.data.full_market)
        cfg2 = apply_profile(_parse(["--paper"]), SuperConfig())
        self.assertFalse(cfg2.data.full_market)

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
        # 50 yerleşik feed taze (ısınma: 50/100 ≥ gerekli 50 → geçer)
        for i in range(50):
            for _ in range(5):
                m.record_tick(f"HOT{i}", now)
        # 50 düşük hacimli coin: 1 tick, çok eski → yerleşik DEĞİL, sayılmaz
        for i in range(50):
            m.record_tick(f"COLD{i}", 1000)
        self.assertFalse(m.update_global_state(now))  # safe mode YOK

    def test_full_market_pipeline_death_triggers_safe(self):
        m = self._mgr(full_market=True)
        # 10 yerleşik feed'in hepsi 120 sn önce tick almış → %100 bayat
        for i in range(10):
            for _ in range(5):
                m.record_tick(f"F{i}", 1000)
        self.assertTrue(m.update_global_state(200_000))
        self.assertEqual(m.safe_mode_reason, "global_stale_data")


if __name__ == "__main__":
    unittest.main()
