import math
import unittest

from core.derivatives_risk import (
    estimate_funding_cost, estimated_liquidation_price, stop_is_before_liquidation,
)
from core.elite_strategy import EliteConfluenceStrategy, candle_integrity, classify_regime
from core.orderflow import OrderFlowAnalyzer
from core.portfolio_guard import PortfolioRiskGuard, correlation
from infra.maker_queue import MakerQueueSimulator, OrderState
from infra.market_data.models import Candle


def candles(count=120, trend=0.15):
    out=[]
    price=100.0
    for i in range(count):
        old=price
        price *= (1.0+trend/100.0)
        out.append(Candle(i*300_000,old,price*1.002,old*0.998,price,100+i))
    return out


class EliteStrategyTests(unittest.TestCase):
    def test_warmup_is_fail_closed(self):
        signal=EliteConfluenceStrategy().evaluate(candles(40))
        self.assertEqual(signal.side,"HOLD")
        self.assertEqual(signal.rejection_code,"ELITE_WARMUP")

    def test_gap_and_duplicate_candle_rejected(self):
        data=candles(5)
        broken=data[:3]+[Candle(data[3].timestamp+900_000,100,101,99,100,10)]
        self.assertEqual(candle_integrity(broken),(False,"CANDLE_GAP"))
        duplicate=data[:3]+[data[2]]
        self.assertEqual(candle_integrity(duplicate),(False,"NON_MONOTONIC_CANDLES"))

    def test_regime_returns_explicit_state(self):
        regime=classify_regime(candles(120))
        self.assertIn(regime.name,{"TREND_UP","TREND_DOWN","RANGE","TRANSITION","EXTREME_VOL","WARMUP"})
        self.assertGreaterEqual(regime.atr_pct,0)

    def test_elite_returns_well_formed_signal(self):
        signal=EliteConfluenceStrategy().evaluate(candles(120))
        self.assertIn(signal.side,{"LONG","SHORT","HOLD"})
        if signal.side=="HOLD":
            self.assertIsNotNone(signal.rejection_code)
        else:
            self.assertGreater(signal.stop_distance_fraction,0)


class MakerQueueTests(unittest.TestCase):
    def test_post_only_rejects_crossing_order(self):
        sim=MakerQueueSimulator()
        order=sim.submit("1","BTCUSDT","BUY",101,1,100,101,0,1000)
        self.assertEqual(order.state,OrderState.REJECTED)
        self.assertEqual(order.reason,"POST_ONLY_WOULD_TAKE")

    def test_queue_ahead_and_partial_fill(self):
        sim=MakerQueueSimulator(participation_rate=1.0)
        order=sim.submit("2","BTCUSDT","BUY",100,2,100,101,5,1000)
        sim.on_trade("BTCUSDT","SELL",100,6,1100)
        self.assertEqual(order.state,OrderState.PARTIALLY_FILLED)
        self.assertAlmostEqual(order.filled,1.0)
        sim.on_trade("BTCUSDT","SELL",99.9,2,1200)
        self.assertEqual(order.state,OrderState.FILLED)

    def test_expire_open_order(self):
        sim=MakerQueueSimulator()
        order=sim.submit("3","ETHUSDT","SELL",102,1,100,102,0,1000)
        self.assertEqual(sim.expire("3",2000).state,OrderState.EXPIRED)


class RiskAndFlowTests(unittest.TestCase):
    def test_funding_cost_and_liquidation_screen(self):
        self.assertAlmostEqual(estimate_funding_cost(500,0.0001,3),0.15)
        liq=estimated_liquidation_price(100,10,"LONG",0.005)
        self.assertAlmostEqual(liq,90.5)
        self.assertTrue(stop_is_before_liquidation(100,95,liq,"LONG",0.2))
        self.assertFalse(stop_is_before_liquidation(100,90,liq,"LONG",0.2))

    def test_orderflow_missing_data_stays_unavailable(self):
        flow=OrderFlowAnalyzer()
        self.assertFalse(flow.snapshot(now=1000).available)
        flow.add_trade(100,2,"BUY",timestamp=995)
        flow.add_trade(99,1,"SELL",timestamp=996)
        flow.update_book([(99,10)],[(101,5)],timestamp=999)
        snap=flow.snapshot(now=1000)
        self.assertTrue(snap.available)
        self.assertEqual(snap.trade_count,2)
        self.assertGreater(snap.cvd,0)
        self.assertGreater(snap.weighted_obi if snap.weighted_obi is not None else -1,0)

    def test_portfolio_guard_same_side_and_correlation(self):
        guard=PortfolioRiskGuard(max_positions=3,max_same_side=1)
        ok,reason=guard.approve("ETH","LONG",{"BTC":"LONG"})
        self.assertFalse(ok)
        self.assertEqual(reason,"SAME_SIDE_EXPOSURE_CAP")
        self.assertIsNone(correlation([1,2,3],[1,2,3]))
        self.assertTrue(guard.approve("ETH","SHORT",{"BTC":"LONG"})[0])


if __name__=="__main__":
    unittest.main()
