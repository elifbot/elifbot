"""v3.1 — RVOL sahte-hacim düzeltmesi testleri (dış v1.6 özelliğinin birleşimi).

Hata: quote hacmi = baz × fiyat olarak hesaplanınca, fiyat oynaklığı işlem
olmasa bile sahte hacim deltası yaratıyor, spike dedektörü RVOL'u 100-500x
şişiriyor ve gerçek sinyaller "şüpheli" diye engelleniyordu.

Çözüm: 24s BAZ hacim deltası (fiyattan bağımsız) ÖNCELİKLİ kullanılır
(Binance miniTicker "v", OKX volCcy24h). Baz hacim yoksa eski quote yolu
(geriye uyum). Bu testler düzeltmeyi kilitler.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from exec.paper import PaperBroker
from infra.exchanges.base import Ticker
from infra.exchanges.binance import BinancePublic
from infra.exchanges.okx import OKXPublic


class TickerBaseVolumeTests(unittest.TestCase):
    def test_ticker_has_base_volume_field(self):
        t = Ticker("BTCUSDT", 1000.0, 100.0, 1, base_volume_24h=10.0)
        self.assertEqual(t.base_volume_24h, 10.0)

    def test_ticker_base_volume_default_none(self):
        t = Ticker("BTCUSDT", 1000.0, 100.0, 1)
        self.assertIsNone(t.base_volume_24h)

    def test_binance_mini_ticker_extracts_base(self):
        msg = json.dumps([
            {"s": "BTCUSDT", "c": "100", "q": "1000", "v": "10", "E": 1},
        ])
        tickers = BinancePublic.parse_mini_tickers(msg)
        self.assertEqual(tickers[0].base_volume_24h, 10.0)
        self.assertEqual(tickers[0].quote_volume_24h, 1000.0)

    def test_binance_mini_ticker_without_v_falls_back_to_none(self):
        msg = json.dumps([
            {"s": "BTCUSDT", "c": "100", "q": "1000", "E": 1},
        ])
        tickers = BinancePublic.parse_mini_tickers(msg)
        self.assertIsNone(tickers[0].base_volume_24h)

    def test_okx_ticker_extracts_base(self):
        msg = json.dumps({
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [{"instId": "BTC-USDT-SWAP", "last": "100",
                      "volCcy24h": "10", "vol24h": "1000",
                      "open24h": "99", "ts": "1"}],
        })
        _, tickers = OKXPublic.parse_ticker_message(msg)
        # volCcy24h=10 baz hacim; quote=10×100=1000
        self.assertEqual(tickers[0].base_volume_24h, 10.0)
        self.assertEqual(tickers[0].quote_volume_24h, 1000.0)

    def test_okx_ticker_without_volccy_base_is_none(self):
        msg = json.dumps({
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [{"instId": "BTC-USDT-SWAP", "last": "100",
                      "vol24h": "1000", "open24h": "99", "ts": "1"}],
        })
        _, tickers = OKXPublic.parse_ticker_message(msg)
        self.assertIsNone(tickers[0].base_volume_24h)


class ExecutorBaseVolumeTests(unittest.TestCase):
    def _executor(self):
        cfg = SuperConfig()
        return Executor(PaperBroker(cfg, 1000.0), RiskManager(cfg), cfg)

    def test_price_move_without_volume_no_spike_input(self):
        """Fiyat %0.5 oynadı ama baz hacim sabit → spike girdisi 0 olmalı."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=None)
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.0, 1000,
                                base_volume_24h=100000.0)
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.5, 2000,
                                base_volume_24h=100000.0)
        # İkinci tick'te spike dedektörüne giden baz hacim 0 olmalı
        args = ex.spike_detector.update.call_args[0]
        self.assertEqual(args[2], 0.0)

    def test_real_volume_increase_correct_delta(self):
        """Baz hacim 50 arttı → fiyat ne olursa olsun delta 50 olmalı."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=None)
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.0, 1000,
                                base_volume_24h=100000.0)
        ex.process_price_update("okx:TEST-USDT-SWAP", 200.0, 2000,
                                base_volume_24h=100050.0)
        args = ex.spike_detector.update.call_args[0]
        self.assertEqual(args[2], 50.0)  # fiyat 2 katına çıktı ama delta 50

    def test_base_volume_preferred_over_quote(self):
        """Baz hacim varken quote yolu KULLANILMAMALI."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=None)
        # quote büyük oynuyor ama baz sabit → baz yolu kazanır, delta 0
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.0, 1000,
                                volume_24h_quote=10_000_000.0,
                                base_volume_24h=100000.0)
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.5, 2000,
                                volume_24h_quote=10_050_000.0,
                                base_volume_24h=100000.0)
        args = ex.spike_detector.update.call_args[0]
        self.assertEqual(args[2], 0.0)

    def test_quote_fallback_when_no_base(self):
        """Baz hacim yoksa eski quote yolu çalışır (geriye uyum)."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=None)
        ex.process_price_update("binance:TESTUSDT", 100.0, 1000,
                                volume_24h_quote=1000.0)
        ex.process_price_update("binance:TESTUSDT", 100.0, 2000,
                                volume_24h_quote=1100.0)
        args = ex.spike_detector.update.call_args[0]
        self.assertAlmostEqual(args[2], 1.0)  # delta 100 quote / fiyat 100 = 1 baz

    def test_decreasing_base_volume_ignored(self):
        """24s baz hacim düşerse (yeni pencere) delta ÜRETİLMEMELİ."""
        ex = self._executor()
        ex.spike_detector.update = Mock(return_value=None)
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.0, 1000,
                                base_volume_24h=100000.0)
        ex.process_price_update("okx:TEST-USDT-SWAP", 100.0, 2000,
                                base_volume_24h=99999.0)
        # İlk tick'te referans yok, ikinci tick'te düşüş → update çağrılmaz
        self.assertEqual(ex.spike_detector.update.call_count, 0)


if __name__ == "__main__":
    unittest.main()
