"""v4.0 — para akışı verileri testleri (madde 17: L/S oranı, likidasyon, funding)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from exec.paper import PaperBroker
from infra.exchanges.binance import BinancePublic
from infra.exchanges.okx import OKXPublic


class BinanceMoneyFlowTests(unittest.TestCase):
    def _client(self, payloads):
        client = BinancePublic()
        client._get_json = Mock(side_effect=lambda p, q: payloads[p])
        return client

    def test_funding_rate(self):
        client = self._client({
            "/fapi/v1/premiumIndex": {"lastFundingRate": "0.00012345"},
        })
        self.assertAlmostEqual(
            client.fetch_funding_rate("BTCUSDT"), 0.00012345,
        )

    def test_funding_rate_failure_is_none(self):
        from infra.exchanges.base import PublicMarketDataError
        client = BinancePublic()
        client._get_json = Mock(side_effect=PublicMarketDataError("ağ"))
        self.assertIsNone(client.fetch_funding_rate("BTCUSDT"))

    def test_long_short_ratio(self):
        client = self._client({
            "/futures/data/globalLongShortAccountRatio": [
                {"longShortRatio": "1.87", "longAccount": "0.65"},
            ],
        })
        self.assertAlmostEqual(client.fetch_long_short_ratio("BTCUSDT"), 1.87)

    def test_force_order_parse(self):
        msg = json.dumps({
            "e": "forceOrder",
            "o": {"s": "BTCUSDT", "S": "SELL", "p": "50000", "q": "0.4",
                  "T": 1_700_000_000_000},
        })
        event = BinancePublic.parse_force_order(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.liquidated_side, "LONG")  # SELL → LONG likide
        self.assertAlmostEqual(event.notional_usd, 20_000.0)

    def test_force_order_invalid_schema_is_none(self):
        self.assertIsNone(BinancePublic.parse_force_order('{"e": "aggTrade"}'))
        self.assertIsNone(BinancePublic.parse_force_order("bozuk"))


class OkxMoneyFlowTests(unittest.TestCase):
    def test_funding_rate(self):
        client = OKXPublic()
        client._get_json = Mock(return_value={
            "code": "0", "data": [{"fundingRate": "0.0001"}],
        })
        self.assertAlmostEqual(
            client.fetch_funding_rate("BTC-USDT-SWAP"), 0.0001,
        )

    def test_long_short_ratio(self):
        client = OKXPublic()
        client._get_json = Mock(return_value={
            "code": "0", "data": [{"ratio": "1.42"}],
        })
        self.assertAlmostEqual(
            client.fetch_long_short_ratio("BTC-USDT-SWAP"), 1.42,
        )

    def test_long_short_failure_is_none(self):
        from infra.exchanges.base import PublicMarketDataError
        client = OKXPublic()
        client._get_json = Mock(side_effect=PublicMarketDataError("uç yok"))
        self.assertIsNone(client.fetch_long_short_ratio("BTC-USDT-SWAP"))


class ExecutorMoneyFlowTests(unittest.TestCase):
    def _executor(self):
        cfg = SuperConfig()
        return Executor(PaperBroker(cfg, 1000.0), RiskManager(cfg), cfg)

    def test_liquidation_window_sum_and_expiry(self):
        ex = self._executor()
        ex.update_liquidation("okx:T-USDT-SWAP", "LONG", 1_000.0, 1_000)
        ex.update_liquidation("okx:T-USDT-SWAP", "LONG", 500.0, 2_000)
        ex.update_liquidation("okx:T-USDT-SWAP", "SHORT", 250.0, 3_000)
        flow = ex.liquidation_flow("okx:T-USDT-SWAP", 3_000)
        self.assertEqual(flow["long_liq_usd"], 1_500.0)
        self.assertEqual(flow["short_liq_usd"], 250.0)
        # pencere dışı kalanlar düşer (varsayılan pencere 300 sn)
        flow = ex.liquidation_flow("okx:T-USDT-SWAP", 3_000 + 301_000)
        self.assertEqual(flow["long_liq_usd"], 0.0)
        self.assertEqual(flow["short_liq_usd"], 0.0)

    def test_long_short_ratio_staleness(self):
        ex = self._executor()
        ex.update_long_short("okx:T-USDT-SWAP", 1.5, 1_000)
        self.assertEqual(ex.long_short_ratio("okx:T-USDT-SWAP", 2_000), 1.5)
        # moneyflow_max_age_s (900 sn) aşılırsa 'uygulanmadı'
        self.assertIsNone(ex.long_short_ratio("okx:T-USDT-SWAP", 1_000 + 901_000))

    def test_funding_rate_used_by_risk_manager(self):
        ex = self._executor()
        ex.set_funding_rate("okx:T-USDT-SWAP", 0.001)  # %0.1 / 8s — gerçekçi
        from core.portfolio import Position
        position = Position(
            symbol="okx:T-USDT-SWAP", side="LONG", entry=100.0,
            quantity=10.0, initial_quantity=10.0, margin=100.0,
            stop_loss=99.0, opened_at_ms=1,
        )
        # 8 saat sınırı sonrası: pozitif rate LONG öder
        boundary = 8 * 3_600_000 + 10_000
        payment = ex.risk.apply_funding_if_due(
            position, 100.0, boundary, funding_rate=0.001,
        )
        self.assertIsNotNone(payment)
        # 1000 USDT notional × %0.1 = 1.0 USDT (gerçek oran; vars. %0.01 değil)
        self.assertAlmostEqual(payment, 1.0, places=6)

    def test_money_flow_summary_for_open_position(self):
        ex = self._executor()
        ex.broker.portfolio.balance = 5_000.0
        from core.portfolio import Position
        ex.broker.portfolio.positions["okx:T-USDT-SWAP"] = Position(
            symbol="okx:T-USDT-SWAP", side="LONG", entry=100.0,
            quantity=1.0, initial_quantity=1.0, margin=10.0,
            stop_loss=99.0, opened_at_ms=1,
        )
        ex.set_funding_rate("okx:T-USDT-SWAP", 0.0001)
        ex.update_long_short("okx:T-USDT-SWAP", 2.0, 1_000)
        summary = ex.money_flow_summary(1_500)
        row = summary["okx:T-USDT-SWAP"]
        self.assertEqual(row["long_short_ratio"], 2.0)
        self.assertEqual(row["funding_rate"], 0.0001)
        self.assertIn("liquidation", row)


if __name__ == "__main__":
    unittest.main()
