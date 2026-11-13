"""FINAL v1.7 — bayat sinyal giriş koruması testleri.

FTT vakası: sinyal 4 dk önce kapanan mumdan (0.2288) üretildi, canlı fiyat
0.2306'ya çıkmıştı (stop 0.2306). Giriş yapılır yapılmaz AYNI SANİYE stop-out
oldu (-4.44 USDT, hold_ms=0). v1.7: canlı fiyat zaten stopun ötesindeyse
giriş iptal edilir.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from core.strategy import Regime, Signal
from exec.paper import PaperBroker
from tests.helpers import flat_series, make_candles


class StaleEntryGuardTests(unittest.TestCase):
    def _executor(self):
        cfg = SuperConfig()
        ex = Executor(PaperBroker(cfg, 1000.0), RiskManager(cfg), cfg)
        ex.store = None
        ex.broker.place_entry = Mock(return_value=SimpleNamespace(
            id="o1", limit_price=100.0, quantity=1.0,
            status=SimpleNamespace(value="PENDING"),
        ))
        ex.broker.bind_plan = Mock()
        ex.risk.check_portfolio = Mock(return_value=SimpleNamespace(
            allowed=True, reason=None,
        ))
        return ex

    def _run(self, ex, side, live_price, stop_frac=0.01):
        ex._latest_prices["okx:TEST-USDT-SWAP"] = live_price
        candles = make_candles(flat_series(price=100.0, count=80))
        sig = Signal(side, "trend", 0.5, 2.0, stop_frac, confidence=0.6)
        with patch.object(ex.resolver, "resolve", return_value=sig), \
             patch.object(ex.regime_detector, "classify",
                          return_value=Regime.TREND_UP):
            ex._evaluate_entry("okx:TEST-USDT-SWAP", candles,
                               candles[-1].timestamp)

    def test_short_live_above_stop_cancels(self):
        # SHORT stop = 100×1.01 = 101; canlı 102 → iptal
        ex = self._executor()
        self._run(ex, "SHORT", live_price=102.0)
        ex.broker.place_entry.assert_not_called()

    def test_short_live_at_stop_cancels(self):
        ex = self._executor()
        self._run(ex, "SHORT", live_price=101.0)
        ex.broker.place_entry.assert_not_called()

    def test_long_live_below_stop_cancels(self):
        # LONG stop = 100×0.99 = 99; canlı 98 → iptal
        ex = self._executor()
        self._run(ex, "LONG", live_price=98.0)
        ex.broker.place_entry.assert_not_called()

    def test_short_live_within_stop_proceeds(self):
        # SHORT stop 101; canlı 100.5 → giriş yapılmalı
        ex = self._executor()
        self._run(ex, "SHORT", live_price=100.5)
        ex.broker.place_entry.assert_called_once()

    def test_long_live_within_stop_proceeds(self):
        # LONG stop 99; canlı 99.5 → giriş yapılmalı
        ex = self._executor()
        self._run(ex, "LONG", live_price=99.5)
        ex.broker.place_entry.assert_called_once()

    def test_no_live_price_still_proceeds(self):
        # Canlı fiyat yoksa koruma devreye girmez (eski davranış)
        ex = self._executor()
        candles = make_candles(flat_series(price=100.0, count=80))
        sig = Signal("SHORT", "trend", 0.5, 2.0, 0.01, confidence=0.6)
        with patch.object(ex.resolver, "resolve", return_value=sig), \
             patch.object(ex.regime_detector, "classify",
                          return_value=Regime.TREND_UP):
            ex._evaluate_entry("okx:TEST-USDT-SWAP", candles,
                               candles[-1].timestamp)
        ex.broker.place_entry.assert_called_once()


if __name__ == "__main__":
    unittest.main()
