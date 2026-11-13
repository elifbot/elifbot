"""Binance ayna (mirror) fallback testleri — FINAL v1.2.

Bölgesel engel (HTTP 451/403) durumunda resmî mainnet spot veri aynasına
(data-api.binance.vision) otomatik geçişi ve yardımcı dönüşümleri kilitler.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.main import _symbols_for
from infra.exchanges.base import PublicExchange, PublicMarketDataError
from infra.exchanges.binance import BinancePublic


def _http_error(code: int) -> HTTPError:
    return HTTPError(url="https://fapi.binance.com", code=code,
                     msg="blocked", hdrs=None, fp=None)


class MirrorFallbackTests(unittest.TestCase):
    def test_451_activates_mirror_and_rewrites_path(self):
        ex = BinancePublic()
        calls = []

        def fake_base_get(self_, path, params):
            calls.append(path)
            raise PublicMarketDataError("blocked") from _http_error(451)

        def fake_mirror(self_, path, params):
            calls.append(("mirror", path))
            return []  # boş kline listesi

        with patch.object(PublicExchange, "_get_json", fake_base_get), \
             patch.object(BinancePublic, "_mirror_get_json", fake_mirror):
            candles = ex.fetch_candles("BTCUSDT", "5m", 10)
        self.assertTrue(ex.mirror_mode)
        self.assertEqual(candles, [])
        self.assertIn(("mirror", "/fapi/v1/klines"), calls)

    def test_subsequent_calls_go_straight_to_mirror(self):
        ex = BinancePublic()
        ex.mirror_mode = True
        seen = []

        def fake_mirror(self_, path, params):
            seen.append(path)
            return {"symbol": "BTCUSDT", "price": "100.0"}

        with patch.object(BinancePublic, "_mirror_get_json", fake_mirror):
            ticker = ex.fetch_ticker("BTCUSDT")
        self.assertEqual(ticker.last_price, 100.0)
        self.assertEqual(seen, ["/fapi/v1/ticker/price"])

    def test_other_http_errors_do_not_trigger_mirror(self):
        ex = BinancePublic()

        def fake_base_get(self_, path, params):
            raise PublicMarketDataError("rate limited") from _http_error(429)

        with patch.object(PublicExchange, "_get_json", fake_base_get):
            with self.assertRaises(PublicMarketDataError):
                ex.fetch_candles("BTCUSDT", "5m", 10)
        self.assertFalse(ex.mirror_mode)

    def test_mirror_path_mapping(self):
        self.assertEqual(BinancePublic._mirror_path("/fapi/v1/klines"),
                         "/api/v3/klines")
        self.assertEqual(BinancePublic._mirror_path("/fapi/v1/depth"),
                         "/api/v3/depth")
        self.assertEqual(BinancePublic._mirror_path("/fapi/v1/exchangeInfo"),
                         "/api/v3/exchangeInfo")

    def test_mirror_websocket_selection(self):
        ex = BinancePublic()
        self.assertIn("fstream.binance.com", ex._active_websocket_url)
        ex.mirror_mode = True
        self.assertIn("data-stream.binance.vision", ex._active_websocket_url)
        self.assertEqual(ex._active_stream_host, "data-stream.binance.vision")

    def test_env_override(self):
        with patch.dict(os.environ, {
            "BINANCE_BASE_URL": "https://proxy.example.com/",
            "BINANCE_WS_URL": "wss://proxy.example.com/ws/!miniTicker@arr",
        }):
            ex = BinancePublic()
        self.assertEqual(ex.base_url, "https://proxy.example.com")
        self.assertEqual(ex.websocket_url,
                         "wss://proxy.example.com/ws/!miniTicker@arr")

    def test_mirror_market_parsing_accepts_spot(self):
        ex = BinancePublic()
        ex.mirror_mode = True

        def fake_mirror(self_, path, params):
            if path.endswith("exchangeInfo"):
                return {"symbols": [{
                    "symbol": "BTCUSDT", "status": "TRADING",
                    "quoteAsset": "USDT", "baseAsset": "BTC",
                    "filters": [{"filterType": "PRICE_FILTER",
                                 "tickSize": "0.01"}],
                }]}
            return [{"symbol": "BTCUSDT", "quoteVolume": "1000000",
                     "priceChangePercent": "1.5"}]

        with patch.object(BinancePublic, "_mirror_get_json", fake_mirror):
            markets = ex.fetch_top_usdt_futures(10)
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].symbol, "BTCUSDT")
        self.assertEqual(markets[0].contract_type, "SPOT")
        self.assertEqual(markets[0].tick_size, 0.01)


class DepthLimitTests(unittest.TestCase):
    def test_clamp_to_valid_values(self):
        self.assertEqual(BinancePublic._clamp_depth_limit(400), 500)
        self.assertEqual(BinancePublic._clamp_depth_limit(100), 100)
        self.assertEqual(BinancePublic._clamp_depth_limit(3), 5)
        self.assertEqual(BinancePublic._clamp_depth_limit(999), 1000)

    def test_fetch_order_book_sends_valid_limit(self):
        ex = BinancePublic()
        seen = {}

        def fake_get(self_, path, params):
            seen.update(params)
            return {"bids": [["99", "1"]], "asks": [["101", "1"]], "E": 123}

        with patch.object(PublicExchange, "_get_json", fake_get):
            book = ex.fetch_order_book("BTCUSDT", 400)
        self.assertEqual(seen["limit"], 500)
        self.assertEqual(book.timestamp_ms, 123)


class SymbolMappingTests(unittest.TestCase):
    def test_binance_format(self):
        raw = ["BTC-USDT-SWAP", "ETHUSDT", "sol-usdt-swap"]
        self.assertEqual(_symbols_for("binance", raw),
                         ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    def test_okx_format(self):
        raw = ["BTCUSDT", "ETH-USDT-SWAP", "solusdt"]
        self.assertEqual(_symbols_for("okx", raw),
                         ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"])

    def test_dedup_after_conversion(self):
        self.assertEqual(_symbols_for("binance", ["BTCUSDT", "BTC-USDT-SWAP"]),
                         ["BTCUSDT"])

    def test_empty_and_whitespace(self):
        self.assertEqual(_symbols_for("okx", ["", "  ", "BTCUSDT"]),
                         ["BTC-USDT-SWAP"])


if __name__ == "__main__":
    unittest.main()
