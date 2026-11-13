from contextlib import redirect_stdout
from io import StringIO
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from argparse import Namespace
from unittest.mock import patch
from unittest.mock import AsyncMock, Mock

from app.executor import Executor
from app.main import (
    _process_spike_batch, _rejection_label, _select_markets,
    _selected_exchanges, build_parser, run,
)
from backtest.engine import BacktestEngine
from core.risk import (
    MAX_LOSS_PER_POS,
    MIN_IMPULSE_PERCENT,
    MIN_RVOL_FOR_ENTRY,
    MIN_24H_VOLUME,
    VOLUME_SPIKE_LOOKBACK_SECONDS,
    VOLUME_SPIKE_MULTIPLIER,
    KÂR_KİLİTLEME_ESİĞİ,
    TRAILING_ACTIVATION_USDT,
    TRAILING_DISTANCE_PERCENT,
    RiskManager,
)
from core.symbols import BLACKLISTED_ASSETS, is_blacklisted
from core.strategy import FadeStrategy, Signal, TrendMomentumStrategy
from core.volume_spike import VolumeSpike, VolumeSpikeDetector
from infra.exchanges.binance import BinancePublic
from infra.exchanges.base import (
    Market, OrderBook, PublicExchange, PublicMarketDataError, PublicTrade, Ticker,
)
from infra.exchanges.okx import OKXPublic
from infra.market_data.models import Candle
from infra.paper import PaperBroker
from safety.alerts import AlertManager, TelegramNotifier
from safety.security import mask_secrets
from state.store import StateStore


def candle(timestamp, close, volume=10.0, spread=0.1):
    return Candle(
        timestamp, close, close + spread, close - spread, close, volume
    )


def fade_setup():
    data = [candle(i * 300_000, 100.0) for i in range(30)]
    data[-2] = candle(data[-2].timestamp, 99.8)
    data[-1] = candle(data[-1].timestamp, 99.4, volume=20)
    return data


def rising_momentum():
    data = [candle(i * 300_000, 100.0) for i in range(23)]
    data[-2] = candle(data[-2].timestamp, 100.2, volume=10)
    data[-1] = candle(data[-1].timestamp, 100.6, volume=30)
    return data


class FadeStrategyTests(unittest.TestCase):
    def test_down_impulse_and_rvol_threshold_produce_long(self):
        signal = FadeStrategy().evaluate(fade_setup())
        self.assertEqual(signal.side, "LONG")
        self.assertLess(signal.impulse_pct, -0.35)
        self.assertGreaterEqual(signal.rvol, 2.0)
        self.assertAlmostEqual(signal.stop_distance_fraction, abs(signal.impulse_pct) / 100)

    def test_positive_impulse_never_produces_short(self):
        data = [candle(i * 300_000, 100.0) for i in range(30)]
        data[-1] = candle(data[-1].timestamp, 100.6, volume=30)
        self.assertEqual(FadeStrategy().evaluate(data).side, "HOLD")

    def test_missing_rvol_or_warmup_does_not_trade(self):
        data = fade_setup()
        data[-1] = candle(data[-1].timestamp, data[-1].close, volume=10)
        self.assertEqual(FadeStrategy().evaluate(data).side, "HOLD")
        self.assertEqual(FadeStrategy().evaluate(data[:10]).side, "HOLD")

    def test_fade_reports_low_impulse_and_low_volume_rejections(self):
        low_impulse = [candle(i * 300_000, 100.0) for i in range(23)]
        low_impulse[-1] = candle(
            low_impulse[-1].timestamp, 100.029, volume=30
        )
        signal = FadeStrategy().evaluate(low_impulse)
        self.assertLess(abs(signal.impulse_pct), MIN_IMPULSE_PERCENT)
        self.assertEqual(signal.rejection_code, "dusuk_momentum")

        low_volume = fade_setup()
        low_volume[-1] = candle(
            low_volume[-1].timestamp, low_volume[-1].close, volume=5
        )
        signal = FadeStrategy().evaluate(low_volume)
        self.assertLess(signal.rvol, MIN_RVOL_FOR_ENTRY)
        self.assertEqual(signal.rejection_code, "dusuk_hacim")

    def test_strategy_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            FadeStrategy(minimum_rvol=0)

    def test_trend_strategy_uses_ema_and_macd_for_both_directions(self):
        rising = [
            candle(i * 300_000, 100 + i + i * i * 0.02, spread=0.1)
            for i in range(100)
        ]
        falling = [
            candle(i * 300_000, 300 - i - i * i * 0.02, spread=0.1)
            for i in range(100)
        ]
        rising[-1] = Candle(
            rising[-1].timestamp, rising[-1].open, rising[-1].high,
            rising[-1].low, rising[-1].close, 30,
        )
        falling[-1] = Candle(
            falling[-1].timestamp, falling[-1].open, falling[-1].high,
            falling[-1].low, falling[-1].close, 30,
        )
        strategy = TrendMomentumStrategy()
        up_signal = strategy.evaluate(rising)
        down_signal = strategy.evaluate(falling)
        self.assertEqual(up_signal.side, "LONG")
        self.assertEqual(up_signal.motor, "trend")
        self.assertEqual(down_signal.side, "SHORT")
        self.assertEqual(down_signal.motor, "trend")
        self.assertGreater(up_signal.stop_distance_fraction, 0)
        self.assertEqual(up_signal.rvol, 3.0)

    def test_trend_strategy_waits_for_warmup(self):
        signal = TrendMomentumStrategy().evaluate(fade_setup())
        self.assertEqual(signal.side, "HOLD")

    def test_blacklist_normalizes_common_symbol_formats(self):
        self.assertEqual(len(BLACKLISTED_ASSETS), 19)
        for symbol in (
            "SOLUSDT", "SOL/USDT", "SOL-USDT", "ARB/USDT:USDT",
            "UNIUSDT", "LINK-USDT-SWAP", "OKX:LINK-USDT-SWAP",
            "LINK-USDT-260626", "BINANCE:LINKUSDT_260626",
        ):
            self.assertTrue(is_blacklisted(symbol))
        self.assertFalse(is_blacklisted("BTCUSDT"))


class RiskAndPaperTests(unittest.TestCase):
    def test_paper_entry_simulates_order_book_slippage_and_scales_stop(self):
        broker = PaperBroker()
        plan = RiskManager().plan(100, 100, 0.05, "LONG")
        book = OrderBook(
            "BTCUSDT",
            bids=((99.9, 10.0),),
            asks=((100.0, 0.1), (102.0, 10.0)),
            timestamp_ms=1000,
        )

        position = broker.open_position("BTCUSDT", plan, 100, order_book=book)

        self.assertGreater(position.entry, plan.entry)
        self.assertAlmostEqual(
            position.stop_loss,
            position.entry * plan.stop_loss / plan.entry,
        )
        self.assertGreater(
            broker.trades[-1]["orderbook_slippage_percent"], 0
        )
        self.assertEqual(broker.trades[-1]["post_only"], True)

    def test_paper_entry_applies_conservative_slippage_for_missing_depth(self):
        broker = PaperBroker()
        plan = RiskManager().plan(100, 100, 0.05, "LONG")
        book = OrderBook(
            "BTCUSDT",
            bids=((99.9, 0.01),),
            asks=((100.0, 0.01),),
            timestamp_ms=1000,
        )

        position = broker.open_position("BTCUSDT", plan, 100, order_book=book)

        self.assertGreater(position.entry, 100.0)
        self.assertGreater(broker.trades[-1]["orderbook_slippage_percent"], 0.19)

    def test_size_respects_fixed_notional_and_loss_formula(self):
        risk = RiskManager()
        plan = risk.plan(1000, 100, 0.05)
        expected = min(500 / 100, (25 - plan.estimated_cost) / (0.05 * 100))
        self.assertAlmostEqual(plan.quantity, expected)
        self.assertAlmostEqual(plan.margin, 50)
        self.assertAlmostEqual(plan.leverage, 10)
        self.assertLessEqual(plan.notional, 500)
        self.assertGreater(plan.notional, 400)
        self.assertAlmostEqual(risk.required_balance_per_position, 50.11)
        self.assertAlmostEqual(plan.stop_loss, 95, delta=0.01)

    def test_position_capacity_has_no_arbitrary_count_cap(self):
        risk = RiskManager()
        self.assertGreater(risk.dynamic_position_limit(10_000), 20)
        self.assertEqual(risk.dynamic_position_limit(54), 1)
        self.assertIsNone(RiskManager(max_positions=1).max_positions)
        # Position count itself never vetoes a trade; available balance does.
        plan = risk.plan(1000, 100, 0.01, open_positions=500)
        self.assertGreater(plan.quantity, 0)

    def test_trade_volume_spike_requires_history_liquidity_and_price_direction(self):
        detector = VolumeSpikeDetector(
            multiplier=VOLUME_SPIKE_MULTIPLIER,
            minimum_24h_volume=MIN_24H_VOLUME,
            lookback_seconds=3,
        )
        detector.set_24h_volume("BTCUSDT", MIN_24H_VOLUME + 1000)
        for second in range(4):
            self.assertIsNone(detector.update_trade(
                PublicTrade("BTCUSDT", 100, 100, second * 1000)
            ))
        spike = detector.update_trade(
            PublicTrade("BTCUSDT", 1000, 101, 3000)
        )
        self.assertIsNotNone(spike)
        self.assertEqual(spike.direction, "LONG")
        self.assertEqual(spike.multiplier, 11.0)
        self.assertEqual(spike.quote_volume, 1100)

    def test_trade_volume_spike_ignores_low_liquidity_and_marks_flat_price(self):
        detector = VolumeSpikeDetector(
            multiplier=5,
            minimum_24h_volume=MIN_24H_VOLUME,
            lookback_seconds=2,
        )
        detector.set_24h_volume("TINYUSDT", 100)
        for second in range(5):
            self.assertIsNone(detector.update_trade(
                PublicTrade("TINYUSDT", 100, 10, second * 1000)
            ))

        detector = VolumeSpikeDetector(
            multiplier=5, minimum_24h_volume=0, lookback_seconds=2
        )
        detector.set_24h_volume("FLATUSDT", 0)
        detector.update_trade(PublicTrade("FLATUSDT", 100, 10, 0))
        detector.update_trade(PublicTrade("FLATUSDT", 100, 10, 1000))
        detector.update_trade(PublicTrade("FLATUSDT", 100, 10, 2000))
        spike = detector.update_trade(
            PublicTrade("FLATUSDT", 1000, 10, 2000)
        )
        self.assertIsNotNone(spike)
        self.assertIsNone(spike.direction)

    def test_trade_volume_spike_uses_full_fifteen_minute_baseline(self):
        self.assertEqual(VOLUME_SPIKE_LOOKBACK_SECONDS, 900)
        detector = VolumeSpikeDetector(minimum_24h_volume=0)
        detector.set_24h_volume("BTCUSDT", 100_000)
        detector.update_trade(PublicTrade("BTCUSDT", 100, 100, 0))
        for second in range(1, 901):
            detector.update_trade(
                PublicTrade("BTCUSDT", 100, 100, second * 1000)
            )
        spike = detector.update_trade(
            PublicTrade("BTCUSDT", 900, 101, 900_000)
        )
        self.assertIsNotNone(spike)
        self.assertEqual(spike.multiplier, 10.0)

    def test_trade_volume_spike_rebuilds_window_after_long_trade_gap(self):
        detector = VolumeSpikeDetector(
            multiplier=5, minimum_24h_volume=0, lookback_seconds=3
        )
        detector.set_24h_volume("BTCUSDT", 100_000)
        detector.update_trade(PublicTrade("BTCUSDT", 100, 100, 0))
        detector.update_trade(PublicTrade("BTCUSDT", 100, 100, 100_000))
        for second in range(101, 104):
            detector.update_trade(
                PublicTrade("BTCUSDT", 100, 100, second * 1000)
            )
        spike = detector.update_trade(
            PublicTrade("BTCUSDT", 1000, 101, 104_000)
        )
        self.assertIsNotNone(spike)
        self.assertEqual(spike.multiplier, 10.0)

    def test_position_exit_rejects_disagreeing_same_bar_ticker_and_candle(self):
        broker = PaperBroker()
        broker.open_position("BTCUSDT", RiskManager().plan(100, 100, 0.01))
        broker.portfolio.positions["BTCUSDT"].motor = "trend"
        executor = Executor(broker)
        candles = [candle(i * 300_000, 100.0) for i in range(30)]
        verification = Candle(9_000_000, 65.0, 66.0, 64.0, 65.76, 100.0)
        ticker = Ticker("BTCUSDT", 0.0, 0.18, 9_000_100)

        with self.assertLogs("app.executor", level="ERROR") as logs:
            trade = executor.manage_position(
                "BTCUSDT",
                candles,
                reference_ticker=ticker,
                verification_candle=verification,
            )

        self.assertIsNone(trade)
        self.assertIn("BTCUSDT", broker.portfolio.positions)
        self.assertIn(
            "HATALI FİYAT VERİSİ REDDEDİLDİ: [BTCUSDT]",
            "\n".join(logs.output),
        )

    def test_position_exit_accepts_large_move_when_same_bar_confirms_ticker(self):
        broker = PaperBroker()
        broker.open_position("BTCUSDT", RiskManager().plan(100, 0.0004, 0.01))
        broker.portfolio.positions["BTCUSDT"].motor = "trend"
        executor = Executor(broker)
        candles = [
            Candle(i * 300_000, 0.0005, 0.00051, 0.00049, 0.0005, 10.0)
            for i in range(30)
        ]
        candles[-1] = Candle(8_700_000, 0.0005, 0.00051, 0.00039, 0.0004, 10.0)
        verification = Candle(9_000_000, 0.0004, 0.003, 0.0004, 0.003, 100.0)
        ticker = Ticker("BTCUSDT", 0.0, 0.003, 9_000_100)

        trade = executor.manage_position(
            "BTCUSDT",
            candles,
            reference_ticker=ticker,
            verification_candle=verification,
        )

        self.assertEqual(trade["reason"], "momentum_end")
        self.assertEqual(trade["price"], ticker.last_price)
        self.assertGreater(trade["pnl"], 0)
        self.assertNotIn("BTCUSDT", broker.portfolio.positions)

    def test_position_exit_rejects_wrong_ticker_symbol(self):
        broker = PaperBroker()
        broker.open_position("BTCUSDT", RiskManager().plan(100, 100, 0.01))
        executor = Executor(broker)
        candles = [candle(i * 300_000, 100.0) for i in range(30)]

        with self.assertLogs("app.executor", level="ERROR") as logs:
            trade = executor.manage_position(
                "BTCUSDT",
                candles,
                reference_ticker=Ticker("ETHUSDT", 0.0, 100.0, 9_000_100),
            )

        self.assertIsNone(trade)
        self.assertIn("BTCUSDT", broker.portfolio.positions)
        self.assertIn("HATALI FİYAT VERİSİ REDDEDİLDİ", "\n".join(logs.output))


    def test_risk_manager_does_not_reject_by_position_count(self):
        risk = RiskManager(max_positions=5)
        plan = risk.plan(1000, 100, 0.01, open_positions=50)
        self.assertGreater(plan.quantity, 0)

    def test_risk_manager_classifies_low_free_balance(self):
        from core.risk import InsufficientFunds

        with self.assertRaises(InsufficientFunds):
            RiskManager().plan(5.019, 100, 0.01)

    def test_risk_manager_sizes_short_and_rejects_insufficient_balance(self):
        from core.risk import InsufficientFunds

        risk = RiskManager()
        short_plan = risk.plan(1000, 100, 0.01, "SHORT")
        self.assertEqual(short_plan.side, "SHORT")
        self.assertAlmostEqual(short_plan.stop_loss, 101)
        self.assertLessEqual(short_plan.quantity * 100 * 0.01 + short_plan.estimated_cost, 25)
        with self.assertRaises(InsufficientFunds):
            risk.plan(5.019, 100, 0.01)

    def test_paper_broker_supports_short_stop_and_momentum_exit(self):
        risk = RiskManager()
        broker = PaperBroker(1000)
        plan = risk.plan(1000, 100, 0.05, "SHORT")
        broker.open_position("BTCUSDT", plan, 100)
        self.assertEqual(broker.portfolio.positions["BTCUSDT"].side, "SHORT")
        stop = broker.check_exit("BTCUSDT", 106, 99, 102, 200)
        self.assertEqual(stop["reason"], "stop_loss")
        self.assertEqual(stop["side"], "SHORT")
        self.assertLessEqual(-stop["pnl"], 25.0)

        broker.open_position("ETHUSDT", risk.plan(1000, 100, 0.05, "SHORT"), 300)
        broker.portfolio.positions["ETHUSDT"].motor = "trend"
        position = broker.portfolio.positions["ETHUSDT"]
        closed = broker.check_exit(
            "ETHUSDT", 90.1, 89.9, 90, 400,
            impulse_pct=1.0, rvol=3.0,
        )
        self.assertEqual(closed["reason"], "momentum_end")

    def test_paper_broker_enforces_post_only_and_reduce_only_stop(self):
        risk = RiskManager()
        broker = PaperBroker(1000)
        plan = risk.plan(1000, 100, 0.05)
        with self.assertRaises(ValueError):
            broker.open_position("BTCUSDT", plan, 100, order_type="taker")
        broker.open_position("BTCUSDT", plan, 100)
        result = broker.check_exit(
            "BTCUSDT", high=101, low=94, close=95, timestamp=200
        )
        self.assertEqual(broker.trades[0]["order_type"], "post_only")
        self.assertEqual(result["reason"], "stop_loss")
        self.assertTrue(result["reduce_only"])
        self.assertEqual(result["execution_type"], "stop_market")
        self.assertLessEqual(-result["pnl"], 25)
        self.assertNotIn("BTCUSDT", broker.portfolio.positions)

    def test_paper_margin_is_not_credited_twice_when_position_closes(self):
        broker = PaperBroker(1000, maker_fee_rate=0, taker_fee_rate=0,
                             stop_slippage_rate=0)
        plan = RiskManager(maker_fee_rate=0, stop_taker_fee_rate=0,
                           stop_slippage_rate=0).plan(1000, 100, 0.05)
        broker.open_position("BTCUSDT", plan, 100)
        broker.close_position("BTCUSDT", 100, "manual", 200)
        self.assertEqual(broker.portfolio.balance, 1000)

    def test_stop_closes_even_if_same_candle_has_a_large_favorable_move(self):
        risk = RiskManager()
        broker = PaperBroker(1000)
        plan = risk.plan(1000, 100, 0.01)
        broker.open_position("BTCUSDT", plan, 100)
        result = broker.check_exit(
            "BTCUSDT", high=110, low=plan.stop_loss - 1,
            close=100, timestamp=200,
        )
        self.assertEqual(result["reason"], "stop_loss")

    def test_time_stop_closes_after_six_new_unprofitable_bars(self):
        broker = PaperBroker(1000)
        plan = RiskManager().plan(1000, 100, 0.01)
        broker.open_position("BTCUSDT", plan, 100)
        broker.portfolio.positions["BTCUSDT"].motor = "trend"
        for timestamp in range(200, 700, 100):
            self.assertIsNone(
                broker.check_exit("BTCUSDT", 100.1, 99.9, 99.95, timestamp)
            )
        result = broker.check_exit("BTCUSDT", 100.1, 99.9, 99.95, 700)
        self.assertEqual(result["reason"], "time_stop")

    def test_fade_position_ignores_momentum_and_time_stop_but_keeps_price_stops(self):
        broker = PaperBroker(1000)
        plan = RiskManager().plan(1000, 100, 0.01)
        position = broker.open_position("BTCUSDT", plan, 100)
        position.motor = "fade"
        for timestamp in range(200, 800, 100):
            self.assertIsNone(
                broker.check_exit(
                    "BTCUSDT", 100.1, 99.9, 99.95, timestamp,
                    impulse_pct=-1.0, rvol=0.0,
                )
            )
        self.assertIn("BTCUSDT", broker.portfolio.positions)
        stopped = broker.check_exit(
            "BTCUSDT", 100.1, position.stop_loss - 0.01,
            position.stop_loss - 0.01, 800,
        )
        self.assertEqual(stopped["reason"], "stop_loss")

    def test_trend_exits_when_rvol_falls_below_one(self):
        broker = PaperBroker(1000)
        broker.open_position("BTCUSDT", RiskManager().plan(1000, 100, 0.05), 100)
        broker.portfolio.positions["BTCUSDT"].motor = "trend"
        closed = broker.check_exit(
            "BTCUSDT", 100.1, 99.9, 100, 200,
            impulse_pct=0.4, rvol=0.99,
        )
        self.assertEqual(closed["reason"], "momentum_end")

    def test_duplicate_bar_does_not_advance_time_stop(self):
        broker = PaperBroker(1000)
        plan = RiskManager().plan(1000, 100, 0.01)
        broker.open_position("BTCUSDT", plan, 100)
        for _ in range(10):
            self.assertIsNone(
                broker.check_exit("BTCUSDT", 100.1, 99.9, 99.95, 200)
            )
        self.assertEqual(broker.portfolio.positions["BTCUSDT"].bars_held, 1)

    def test_profit_lock_holds_open_while_momentum_and_volume_continue(self):
        broker = PaperBroker(
            initial_balance=1000,
            maker_fee_rate=0,
            taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        risk = RiskManager(
            maker_fee_rate=0,
            stop_taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        plan = risk.plan(1000, 100, 0.01)
        broker.open_position("BTCUSDT", plan, 100)
        broker.portfolio.positions["BTCUSDT"].motor = "trend"
        position = broker.portfolio.positions["BTCUSDT"]
        close = position.entry + (KÂR_KİLİTLEME_ESİĞİ + 5) / position.quantity
        with self.assertLogs("infra.paper", level="INFO") as logs:
            trade = broker.check_exit(
                "BTCUSDT", close, close * 0.99, close, 200,
                impulse_pct=1.0, rvol=3.0,
            )
        self.assertEqual(KÂR_KİLİTLEME_ESİĞİ, 250.0)
        self.assertIsNone(trade)
        self.assertIn("BTCUSDT", broker.portfolio.positions)
        self.assertTrue(position.profit_lock_active)
        self.assertIn(
            "MOMENTUM DEVAM EDİYOR - POZİSYON AÇIK TUTULUYOR",
            "\n".join(logs.output),
        )

    def test_momentum_reversal_closes_position_with_profit_and_logs(self):
        broker = PaperBroker(
            initial_balance=1000,
            maker_fee_rate=0,
            taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        plan = RiskManager(
            maker_fee_rate=0,
            stop_taker_fee_rate=0,
            stop_slippage_rate=0,
        ).plan(1000, 100, 0.01)
        broker.open_position("BTCUSDT", plan, 100)
        broker.portfolio.positions["BTCUSDT"].motor = "trend"
        position = broker.portfolio.positions["BTCUSDT"]
        current_price = position.entry + 30 / position.quantity
        with self.assertLogs("infra.paper", level="INFO") as logs:
            closed = broker.check_exit(
                "BTCUSDT", current_price, current_price * 0.99,
                current_price, 200,
                impulse_pct=-0.2, rvol=3.0,
            )
        self.assertEqual(closed["reason"], "momentum_end")
        self.assertTrue(closed["reduce_only"])
        self.assertNotIn("BTCUSDT", broker.portfolio.positions)
        self.assertIn("MOMENTUM BİTTİ - KÂR İLE KAPATILDI", "\n".join(logs.output))

    def test_rvol_drop_closes_position_with_profit(self):
        broker = PaperBroker(
            initial_balance=1000,
            maker_fee_rate=0,
            taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        plan = RiskManager(
            maker_fee_rate=0,
            stop_taker_fee_rate=0,
            stop_slippage_rate=0,
        ).plan(1000, 100, 0.01)
        broker.open_position("BTCUSDT", plan, 100)
        broker.portfolio.positions["BTCUSDT"].motor = "trend"

        with self.assertLogs("infra.paper", level="INFO") as logs:
            closed = broker.check_exit(
                "BTCUSDT", 101.1, 100.9, 101, 200,
                impulse_pct=0.2, rvol=0.9,
            )

        self.assertEqual(closed["reason"], "momentum_end")
        self.assertGreater(closed["pnl"], 0)
        self.assertNotIn("BTCUSDT", broker.portfolio.positions)
        self.assertIn("MOMENTUM BİTTİ - KÂR İLE KAPATILDI", "\n".join(logs.output))

    def test_long_percentage_trailing_stop_follows_highest_price(self):
        broker = PaperBroker(
            initial_balance=1000,
            maker_fee_rate=0,
            taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        risk = RiskManager(
            maker_fee_rate=0,
            stop_taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        plan = risk.plan(1000, 100, 0.01)
        position = broker.open_position("BTCUSDT", plan, 100)

        with self.assertLogs("infra.paper", level="INFO") as logs:
            activation_high = (
                100 + TRAILING_ACTIVATION_USDT / position.quantity
            )
            self.assertIsNone(
                broker.check_exit(
                    "BTCUSDT", activation_high, activation_high * 0.99,
                    activation_high, 200,
                )
            )
        self.assertTrue(position.trailing_active)
        expected_activation_stop = activation_high * (
            1 - TRAILING_DISTANCE_PERCENT / 100
        )
        self.assertAlmostEqual(position.stop_loss, expected_activation_stop)
        self.assertIn(
            "YÜZDESEL TRAILING STOP AKTİF: [BTCUSDT]", logs.output[0]
        )

        favorable_price = (
            100 + (TRAILING_ACTIVATION_USDT + 20) / position.quantity
        )
        self.assertIsNone(
            broker.check_exit(
                "BTCUSDT", favorable_price, favorable_price * 0.99,
                favorable_price, 300,
            )
        )
        expected_trailing_stop = (
            favorable_price * (1 - TRAILING_DISTANCE_PERCENT / 100)
        )
        self.assertAlmostEqual(position.stop_loss, expected_trailing_stop)

        with self.assertLogs("infra.paper", level="INFO") as close_logs:
            closed = broker.check_exit(
                "BTCUSDT", expected_trailing_stop + 1,
                expected_trailing_stop, expected_trailing_stop, 400,
            )
        self.assertEqual(closed["reason"], "trailing_stop")
        self.assertTrue(closed["reduce_only"])
        self.assertIn(
            "YÜZDESEL TRAILING STOP TETİKLENDİ: [BTCUSDT] %2 düşüş ile kapatıldı",
            close_logs.output[0],
        )
        self.assertAlmostEqual(
            closed["gross_pnl"],
            (expected_trailing_stop - position.entry) * position.quantity,
        )

    def test_short_percentage_trailing_stop_follows_lowest_price(self):
        broker = PaperBroker(
            initial_balance=1000,
            maker_fee_rate=0,
            taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        risk = RiskManager(
            maker_fee_rate=0,
            stop_taker_fee_rate=0,
            stop_slippage_rate=0,
        )
        plan = risk.plan(1000, 100, 0.01, "SHORT")
        position = broker.open_position("BTCUSDT", plan, 100)
        activation_low = 100 - TRAILING_ACTIVATION_USDT / position.quantity
        self.assertIsNone(
            broker.check_exit(
                "BTCUSDT", activation_low * 1.01, activation_low,
                activation_low, 200,
            )
        )
        self.assertAlmostEqual(
            position.stop_loss,
            activation_low * (1 + TRAILING_DISTANCE_PERCENT / 100),
        )

        lowest_price = activation_low - 10
        self.assertIsNone(
            broker.check_exit(
                "BTCUSDT", lowest_price * 1.001, lowest_price,
                lowest_price, 300,
            )
        )
        expected_stop = lowest_price * (1 + TRAILING_DISTANCE_PERCENT / 100)
        self.assertAlmostEqual(position.stop_loss, expected_stop)

        with self.assertLogs("infra.paper", level="INFO") as close_logs:
            closed = broker.check_exit(
                "BTCUSDT", expected_stop, lowest_price, expected_stop, 400
            )
        self.assertEqual(closed["reason"], "trailing_stop")
        self.assertIn(
            "YÜZDESEL TRAILING STOP TETİKLENDİ: [BTCUSDT] %2 düşüş ile kapatıldı",
            close_logs.output[0],
        )


class PublicExchangeTests(unittest.TestCase):
    def test_binance_mini_ticker_stream_parses_quote_volume_and_price(self):
        tickers = BinancePublic.parse_mini_tickers(
            '[{"s":"BTCUSDT","c":"50000","q":"1234567.8","E":1700000000000}]'
        )
        self.assertEqual(
            tickers,
            [Ticker("BTCUSDT", 1_234_567.8, 50_000.0, 1_700_000_000_000)],
        )

    def test_binance_aggregate_trade_parser_calculates_quote_notional(self):
        trade = BinancePublic.parse_aggregate_trade(
            '{"stream":"btcusdt@aggTrade","data":{"e":"aggTrade",'
            '"s":"BTCUSDT","p":"50000","q":"0.02","T":1700000000000}}'
        )
        self.assertEqual(
            trade, PublicTrade("BTCUSDT", 1000.0, 50000.0, 1700000000000)
        )

    def test_okx_trade_parser_converts_contracts_to_usdt_notional(self):
        trades = OKXPublic.parse_trade_message(
            '{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},'
            '"data":[{"instId":"BTC-USDT-SWAP","px":"50000","sz":"2",'
            '"ts":"1700000000000"}]}',
            {"BTC-USDT-SWAP": (0.01, "BTC", "BTC", "USDT")},
        )
        self.assertEqual(
            trades,
            [PublicTrade("BTC-USDT-SWAP", 1000.0, 50000.0, 1700000000000)],
        )

    def test_binance_rest_ticker_validates_returned_symbol(self):
        client = BinancePublic()
        with patch.object(client, "_get_json", return_value={
            "symbol": "BTCUSDT", "price": "50000"
        }) as request:
            ticker = client.fetch_ticker("BTCUSDT")
        self.assertEqual(ticker.symbol, "BTCUSDT")
        self.assertEqual(ticker.last_price, 50_000)
        request.assert_called_once_with(
            "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"}
        )
        with patch.object(client, "_get_json", return_value={
            "symbol": "ETHUSDT", "price": "3000"
        }):
            with self.assertRaises(PublicMarketDataError):
                client.fetch_ticker("BTCUSDT")

    def test_okx_rest_ticker_validates_returned_instrument(self):
        client = OKXPublic()
        with patch.object(client, "_get_json", return_value={
            "code": "0", "data": [{
                "instId": "BTC-USDT-SWAP", "last": "50000",
                "volCcy24h": "25", "ts": "1700000000000",
            }]
        }) as request:
            ticker = client.fetch_ticker("BTC-USDT-SWAP")
        self.assertEqual(ticker.symbol, "BTC-USDT-SWAP")
        self.assertEqual(ticker.last_price, 50_000)
        self.assertEqual(ticker.quote_volume_24h, 1_250_000)
        request.assert_called_once_with(
            "/api/v5/market/ticker", {"instId": "BTC-USDT-SWAP"}
        )
        with patch.object(client, "_get_json", return_value={
            "code": "0", "data": [{"instId": "ETH-USDT-SWAP", "last": "3000"}]
        }):
            with self.assertRaises(PublicMarketDataError):
                client.fetch_ticker("BTC-USDT-SWAP")

    def test_okx_ticker_stream_parses_quote_turnover_estimate(self):
        channel, tickers = OKXPublic.parse_ticker_message(
            '{"arg":{"channel":"tickers","instId":"BTC-USDT-SWAP"},'
            '"data":[{"instId":"BTC-USDT-SWAP","last":"50000",'
            '"volCcy24h":"25","open24h":"49000","ts":"1700000000000"}]}'
        )
        self.assertEqual(channel, "tickers")
        self.assertEqual(
            tickers,
            [Ticker("BTC-USDT-SWAP", 1_250_000.0, 50_000.0, 1_700_000_000_000)],
        )

    def test_binance_parses_public_klines(self):
        client = BinancePublic()
        with patch.object(client, "_get_json", return_value=[
            [1000, "10", "12", "9", "11", "5"]
        ]) as request:
            data = client.fetch_candles("BTCUSDT", "5m", 1)
        self.assertEqual(data[0], Candle(1000, 10, 12, 9, 11, 5))
        request.assert_called_once()

    def test_binance_order_book_parser(self):
        client = BinancePublic()
        with patch.object(client, "_get_json", return_value={
            "lastUpdateId": 10, "E": 1234,
            "bids": [["99.9", "2"]], "asks": [["100", "3"]],
        }) as request:
            book = client.fetch_order_book("BTCUSDT")
        self.assertEqual(book.bids, ((99.9, 2.0),))
        self.assertEqual(book.asks, ((100.0, 3.0),))
        self.assertEqual(book.timestamp_ms, 1234)
        request.assert_called_once_with(
            "/fapi/v1/depth", {"symbol": "BTCUSDT", "limit": 100}
        )

    def test_okx_order_book_converts_contract_size_to_base_quantity(self):
        client = OKXPublic()
        with patch.object(client, "_get_json", side_effect=[
            {
                "code": "0",
                "data": [{
                    "instId": "BTC-USDT-SWAP", "ts": "1234",
                    "bids": [["100", "10", "0", "1"]],
                    "asks": [["101", "20", "0", "1"]],
                }],
            },
            {
                "code": "0",
                "data": [{
                    "instId": "BTC-USDT-SWAP",
                    "ctVal": "0.01", "ctValCcy": "BTC", "baseCcy": "BTC",
                }],
            },
        ]) as request:
            book = client.fetch_order_book("BTC-USDT-SWAP")
        self.assertEqual(book.bids, ((100.0, 0.1),))
        self.assertEqual(book.asks, ((101.0, 0.2),))
        self.assertEqual(book.timestamp_ms, 1234)
        self.assertEqual(request.call_count, 2)

    def test_ticker_stream_reconnect_uses_exponential_backoff(self):
        class FlakyExchange(PublicExchange):
            name = "test"

            def __init__(self):
                self.failures = 0

            async def stream_tickers(self, symbols=None):
                if self.failures < 2:
                    self.failures += 1
                    raise RuntimeError("offline")
                yield Ticker("BTCUSDT", 100, 100, 1000)

        exchange = FlakyExchange()
        with patch(
            "infra.exchanges.base.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            stream = exchange.stream_tickers_reconnecting(("BTCUSDT",))
            async def get_first():
                return await anext(stream)
            received = asyncio.run(get_first())
            asyncio.run(stream.aclose())
        self.assertEqual(received.symbol, "BTCUSDT")
        self.assertEqual(
            [call.args[0] for call in sleep.await_args_list],
            [1.0, 2.0],
        )

    def test_okx_parses_reverse_chronological_public_data(self):
        client = OKXPublic()
        with patch.object(client, "_get_json", return_value={
            "code": "0", "data": [
                ["2000", "11", "12", "10", "11", "2"],
                ["1000", "9", "10", "8", "9", "1"],
            ]
        }):
            data = client.fetch_candles("BTC/USDT", "1h", 2)
        self.assertEqual([item.timestamp for item in data], [1000, 2000])

    def test_okx_normalizes_concatenated_symbol(self):
        client = OKXPublic()
        with patch.object(client, "_get_json", return_value={
            "code": "0", "data": [["1000", "9", "10", "8", "9", "1"]]
        }) as request:
            client.fetch_candles("BTCUSDT", "5m", 1)
        self.assertEqual(request.call_args.args[1]["instId"], "BTC-USDT")

    def test_exchange_request_parameters_are_validated(self):
        with self.assertRaises(ValueError):
            BinancePublic().fetch_candles("BTCUSDT", "2m", 10)

    def test_binance_universe_filters_and_sorts_usdt_futures(self):
        client = BinancePublic()
        info = {
            "symbols": [
                {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
                 "status": "TRADING", "contractType": "PERPETUAL"},
                {"symbol": "LINKUSDT", "baseAsset": "LINK", "quoteAsset": "USDT",
                 "status": "TRADING", "contractType": "PERPETUAL"},
                {"symbol": "ETHUSDC", "baseAsset": "ETH", "quoteAsset": "USDC",
                 "status": "TRADING", "contractType": "PERPETUAL"},
                {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT",
                 "status": "BREAK", "contractType": "PERPETUAL"},
            ]
        }
        with patch.object(client, "_get_json", side_effect=[
            info,
            [{"symbol": "BTCUSDT", "quoteVolume": "200",
              "priceChangePercent": "3.5"},
             {"symbol": "LINKUSDT", "quoteVolume": "100",
              "priceChangePercent": "-8.0"}],
        ]):
            markets = client.fetch_top_usdt_futures(10)
        self.assertEqual([market.symbol for market in markets], ["BTCUSDT", "LINKUSDT"])
        self.assertEqual(markets[0].quote_volume_24h, 200)
        self.assertEqual(markets[1].percentage_24h, -8.0)

    def test_okx_universe_collects_linear_usdt_swaps_and_futures(self):
        client = OKXPublic()
        def response(data):
            return {"code": "0", "data": data}

        with patch.object(client, "_get_json", side_effect=[
            response([{"instId": "BTC-USDT-SWAP", "baseCcy": "BTC",
                       "settleCcy": "USDT", "ctType": "linear", "state": "live"}]),
            response([{"instId": "BTC-USDT-SWAP", "last": "100", "volCcy24h": "2",
                       "vol24h": "2", "open24h": "80"}]),
            response([{"instId": "ETH-USDT-260626", "baseCcy": "ETH",
                       "settleCcy": "USDT", "ctType": "linear", "state": "live"}]),
            response([{"instId": "ETH-USDT-260626", "last": "10", "volCcy24h": "3",
                       "vol24h": "3", "open24h": "10"}]),
        ]):
            markets = client.fetch_top_usdt_futures(10)
        self.assertEqual([market.symbol for market in markets],
                         ["BTC-USDT-SWAP", "ETH-USDT-260626"])
        self.assertGreater(markets[0].quote_volume_24h, markets[1].quote_volume_24h)
        self.assertEqual(markets[0].percentage_24h, 25.0)

    def test_all_scan_ranks_by_volume_then_absolute_change_and_limits_to_100(self):
        class FakeExchange:
            def fetch_top_usdt_futures(self, limit):
                self.requested_limit = limit
                return [
                    Market("SOLUSDT", "SOL", 10_000, "PERPETUAL"),
                    Market("LINKUSDT", "LINK", 9_000, "PERPETUAL"),
                    Market("LOWVOLUSDT", "LOWVOL", 50, "PERPETUAL", percentage_24h=99),
                    Market("TIELOWUSDT", "TIELOW", 1903, "PERPETUAL", percentage_24h=1),
                    Market("TIEHIGHUSDT", "TIEHIGH", 1903, "PERPETUAL", percentage_24h=-12),
                    *[
                        Market(f"COIN{i}USDT", f"COIN{i}", 2000 - i if i < 97 else 1800 - i, "PERPETUAL")
                        for i in range(105)
                    ],
                ]

        exchange = FakeExchange()
        markets = _select_markets(exchange, "ALL")
        self.assertEqual(exchange.requested_limit, 1000)
        self.assertEqual(len(markets), 100)
        self.assertTrue(all(not is_blacklisted(market.base_asset) for market in markets))
        self.assertEqual(markets[0].symbol, "COIN0USDT")
        self.assertEqual(markets[1].symbol, "COIN1USDT")
        self.assertLess(
            [market.symbol for market in markets].index("TIEHIGHUSDT"),
            [market.symbol for market in markets].index("TIELOWUSDT"),
        )
        self.assertNotIn("LOWVOLUSDT", [market.symbol for market in markets])


class StateSafetyExecutorTests(unittest.TestCase):
    def test_store_uses_wal_and_persists_paper_state_and_trades(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.sqlite3")
            with StateStore(path) as store:
                store.save_state({"mode": "paper", "balance": 1000})
                store.append_trade({"type": "OPEN", "mode": "paper"})
                self.assertEqual(store.load_state()["balance"], 1000)
                self.assertEqual(store.load_trades()[0]["type"], "OPEN")
                mode = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_store_rejects_non_json_numbers(self):
        with tempfile.TemporaryDirectory() as directory, StateStore(
            os.path.join(directory, "state.db")
        ) as store:
            with self.assertRaises(ValueError):
                store.save_state({"bad": float("nan")})

    def test_daily_realized_pnl_is_utc_scoped_and_restart_safe(self):
        now = datetime.now(timezone.utc)
        today_ms = int(now.timestamp() * 1000)
        yesterday_ms = int((now - timedelta(days=1)).timestamp() * 1000)
        with tempfile.TemporaryDirectory() as directory, StateStore(
            os.path.join(directory, "state.db")
        ) as store:
            store.append_trade({"type": "CLOSE", "timestamp": today_ms, "pnl": -60})
            store.append_trade({"type": "CLOSE", "timestamp": today_ms, "pnl": -40})
            store.append_trade({"type": "CLOSE", "timestamp": yesterday_ms, "pnl": -999})
            self.assertEqual(store.realized_pnl_since_utc_midnight(now), -100)
            # Legacy daily PnL reporting remains available, but no daily
            # loss threshold blocks new paper entries.
            RiskManager().ensure_daily_loss_allowance(
                store.realized_pnl_since_utc_midnight(now)
            )

    def test_daily_loss_does_not_block_new_entries(self):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        with tempfile.TemporaryDirectory() as directory, StateStore(
            os.path.join(directory, "state.db")
        ) as store:
            store.append_trade({"type": "CLOSE", "timestamp": now_ms, "pnl": -500})
            executor = Executor(PaperBroker(1000), store=store)
            decision = executor.process("BTCUSDT", fade_setup())
            self.assertNotEqual(decision.rejection_code, "DAILY_LOSS_LIMIT")

    def test_secret_masking(self):
        self.assertEqual(
            mask_secrets("api_key=abc123 Bearer token-xyz"),
            "api_key=[REDACTED] Bearer [REDACTED]",
        )

    def test_alerts_redact_secrets_and_reject_unknown_levels(self):
        logger = Mock()
        alerts = AlertManager(logger)
        result = alerts.notify("api_key=abc123", "warning")
        self.assertEqual(result, "api_key=[REDACTED]")
        logger.warning.assert_called_once_with("%s", "api_key=[REDACTED]")
        with self.assertRaises(ValueError):
            alerts.notify("message", "trace")

    def test_telegram_notifier_sends_message_with_credentials_only_in_request(self):
        notifier = TelegramNotifier("123456:secret", "chat-1")
        response = Mock()
        response.status = 200
        response.read.return_value = b'{"ok":true}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("safety.alerts.urlopen", return_value=response) as urlopen_mock:
            self.assertTrue(notifier.send("PAPER ORDER AÇILDI: BTCUSDT"))
        request = urlopen_mock.call_args.args[0]
        self.assertIn("123456:secret", request.full_url)
        self.assertIn(b"chat-1", request.data)

    def test_alert_manager_sends_critical_and_trade_events_to_telegram(self):
        telegram = Mock()
        alerts = AlertManager(telegram=telegram)
        alerts.notify("critical failure", "critical")
        alerts.notify_event("PAPER ORDER AÇILDI: BTCUSDT")
        self.assertEqual(telegram.send.call_count, 2)

    def test_executor_persists_and_restores_paper_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            with StateStore(os.path.join(directory, "state.db")) as store:
                executor = Executor(PaperBroker(), store=store)
                executor.process("BTCUSDT", fade_setup())
                self.assertIn("BTCUSDT", executor.broker.portfolio.positions)
                self.assertEqual(store.load_trades()[0]["order_type"], "post_only")
                restored = Executor(PaperBroker(), store=store)
                position = restored.broker.portfolio.positions["BTCUSDT"]
                self.assertEqual(position.side, "LONG")
                self.assertEqual(position.bars_held, 0)

    def test_executor_does_not_reenter_same_five_minute_candle(self):
        with tempfile.TemporaryDirectory() as directory:
            with StateStore(os.path.join(directory, "state.db")) as store:
                executor = Executor(PaperBroker(), store=store)
                candles = fade_setup()
                executor.process("BTCUSDT", candles)
                position = executor.broker.portfolio.positions["BTCUSDT"]
                executor.close("BTCUSDT", position.stop_loss - 1, "stop_loss")
                executor.process("BTCUSDT", candles)
                self.assertNotIn("BTCUSDT", executor.broker.portfolio.positions)

    def test_executor_and_backtest_obey_blacklist(self):
        executor = Executor(PaperBroker())
        executor.process("SOLUSDT", fade_setup())
        self.assertNotIn("SOLUSDT", executor.broker.portfolio.positions)
        result = BacktestEngine().run("SOL/USDT", fade_setup())
        self.assertEqual(result.trade_count, 0)

    def test_executor_selects_signal_motor_and_blocks_opposite_conflict(self):
        class FixedSignal:
            def __init__(self, signal):
                self.signal = signal

            def evaluate(self, candles):
                return self.signal

        data = fade_setup()
        fade_long = Signal("LONG", -0.5, 2.0, 0.005, "fade")
        trend_short = Signal("SHORT", -0.1, 0, 0.01, "trend")
        executor = Executor(
            PaperBroker(),
            strategy=FixedSignal(fade_long),
            trend_strategy=FixedSignal(trend_short),
        )
        decision = executor.process("BTCUSDT", data)
        self.assertEqual(decision.side, "HOLD")
        self.assertEqual(decision.motor, "conflict")
        self.assertFalse(executor.broker.portfolio.positions)

    def test_executor_opens_trend_short_when_fade_has_no_signal(self):
        class FixedSignal:
            def __init__(self, signal):
                self.signal = signal

            def evaluate(self, candles):
                return self.signal

        executor = Executor(
            PaperBroker(),
            strategy=FixedSignal(Signal("HOLD", 0, 0, None, "fade")),
            trend_strategy=FixedSignal(Signal("SHORT", -0.1, 0, 0.01, "trend")),
        )
        executor.process("binance:BTCUSDT", fade_setup())
        position = executor.broker.portfolio.positions["binance:BTCUSDT"]
        self.assertEqual(position.side, "SHORT")
        self.assertEqual(position.motor, "trend")
        self.assertEqual(executor.broker.trades[-1]["motor"], "trend")

    def test_executor_has_no_fixed_position_count_cap(self):
        class FixedSignal:
            def evaluate(self, candles):
                return Signal("LONG", -0.5, 2.0, 0.005, "fade")

        broker = PaperBroker()
        executor = Executor(
            broker,
            strategy=FixedSignal(),
            trend_strategy=FixedSignal(),
            risk=RiskManager(max_positions=5),  # legacy arg is intentionally ignored
        )
        candles = fade_setup()
        for index in range(6):
            decision = executor.process(f"binance:COIN{index}USDT", candles)
            self.assertEqual(decision.side, "LONG")
        self.assertEqual(len(broker.portfolio.positions), 6)

    def test_executor_skips_impulse_below_minimum(self):
        class FixedSignal:
            def evaluate(self, candles):
                return Signal("LONG", -0.5, 2.0, 0.005, "fade")

        candles = [candle(i * 300_000, 100.0) for i in range(23)]
        candles[-1] = candle(candles[-1].timestamp, 100.029, volume=30)
        executor = Executor(
            PaperBroker(), strategy=FixedSignal(), trend_strategy=FixedSignal()
        )
        decision = executor.process("ASTER-USDT-SWAP", candles)
        self.assertEqual(decision.side, "HOLD")
        self.assertEqual(decision.rejection_code, "dusuk_momentum")
        self.assertFalse(executor.broker.portfolio.positions)

    def test_executor_skips_unreliable_low_rvol(self):
        class FixedSignal:
            def evaluate(self, candles):
                return Signal("LONG", -0.5, 2.0, 0.005, "fade")

        candles = fade_setup()
        candles[-1] = candle(
            candles[-1].timestamp, candles[-1].close, volume=5
        )
        executor = Executor(
            PaperBroker(), strategy=FixedSignal(), trend_strategy=FixedSignal()
        )
        decision = executor.process("BTCUSDT", candles)
        self.assertEqual(decision.side, "HOLD")
        self.assertEqual(decision.rejection_code, "dusuk_hacim")
        self.assertFalse(executor.broker.portfolio.positions)

    def test_executor_accepts_directional_volume_spike_override(self):
        candles = [
            candle(i * 300_000, 100.0)
            for i in range(60)
        ]
        executor = Executor(PaperBroker())
        decision = executor.process(
            "binance:BTCUSDT",
            candles,
            tick_size=0.1,
            signal_override=Signal(
                "SHORT", -0.02, VOLUME_SPIKE_MULTIPLIER, 0.01,
                "volume_spike",
            ),
            market_price=99.0,
        )
        self.assertEqual(decision.side, "SHORT")
        self.assertEqual(
            executor.broker.portfolio.positions["binance:BTCUSDT"].side,
            "SHORT",
        )
        self.assertEqual(
            executor.broker.trades[-1]["motor"], "volume_spike"
        )

    def test_insufficient_funds_skips_signal_then_recovers(self):
        class FixedSignal:
            def evaluate(self, candles):
                return Signal("LONG", -0.5, 2.0, 0.005, "fade")

        class HoldSignal:
            def evaluate(self, candles):
                return Signal("HOLD", 0.0, 0.0, None, "trend")

        broker = PaperBroker(initial_balance=200.0)
        broker.open_position("BTCUSDT", RiskManager().plan(100, 100, 0.01))
        broker.portfolio.positions["BTCUSDT"].margin = 196.0
        executor = Executor(
            broker,
            strategy=FixedSignal(),
            trend_strategy=HoldSignal(),
            risk=RiskManager(max_positions=200),
        )
        candles = fade_setup()
        rejected_candles = [
            Candle(item.timestamp + 300_000, item.open, item.high, item.low,
                   item.close, item.volume)
            for item in candles
        ]
        rejected = executor.process("ETHUSDT", rejected_candles)
        self.assertEqual(rejected.side, "HOLD")
        self.assertEqual(rejected.rejection_code, "INSUFFICIENT_FUNDS")

        executor.close("BTCUSDT", broker.portfolio.positions["BTCUSDT"].entry, "manual")
        resumed_candles = [
            Candle(item.timestamp + 600_000, item.open, item.high, item.low,
                   item.close, item.volume)
            for item in candles
        ]
        resumed = executor.process("ETHUSDT", resumed_candles)
        self.assertEqual(resumed.side, "LONG")
        self.assertIsNone(resumed.rejection_code)
        self.assertIn("ETHUSDT", broker.portfolio.positions)

    def test_executor_prices_paper_entry_one_tick_post_only(self):
        class FixedSignal:
            def evaluate(self, candles):
                return Signal("LONG", -0.5, 2.0, 0.005, "fade")

        class HoldSignal:
            def evaluate(self, candles):
                return Signal("HOLD", 0.0, 0.0, None, "trend")

        broker = PaperBroker()
        executor = Executor(
            broker, strategy=FixedSignal(), trend_strategy=HoldSignal()
        )
        candles = fade_setup()
        executor.process("BTCUSDT", candles, tick_size=0.1)
        trade = broker.trades[-1]
        self.assertEqual(trade["order_type"], "post_only")
        self.assertTrue(trade["post_only"])
        self.assertAlmostEqual(trade["limit_price"], candles[-1].close - 0.1)

    def test_position_loss_stop_closes_only_losing_position(self):
        broker = PaperBroker(initial_balance=1000)
        plan = RiskManager().plan(1000, 100, 0.01)
        losing = broker.open_position("BTCUSDT", plan, 100)
        losing.quantity = 1.0
        losing.stop_loss = 1.0
        other = broker.open_position("ETHUSDT", plan, 100)
        other.stop_loss = 1.0

        with self.assertLogs("infra.paper", level="WARNING") as logs:
            closed = broker.check_exit(
                "BTCUSDT", high=101, low=75.0, close=75.0, timestamp=200
            )

        self.assertEqual(MAX_LOSS_PER_POS, 25.0)
        self.assertEqual(closed["reason"], "position_loss_stop")
        self.assertTrue(closed["reduce_only"])
        self.assertEqual(closed["execution_type"], "stop_market")
        self.assertNotIn("BTCUSDT", broker.portfolio.positions)
        self.assertIn("ETHUSDT", broker.portfolio.positions)
        self.assertIn(
            "STOP LOSS TETİKLENDİ: [BTCUSDT] 25 USDT zarar ile kapatıldı",
            "\n".join(logs.output),
        )

    def test_executor_allows_new_position_after_an_existing_one_closes(self):
        class FixedSignal:
            def evaluate(self, candles):
                return Signal("LONG", -0.5, 2.0, 0.005, "fade")

        broker = PaperBroker()
        executor = Executor(
            broker,
            strategy=FixedSignal(),
            trend_strategy=FixedSignal(),
            risk=RiskManager(max_positions=1),
        )
        candles = fade_setup()
        executor.process("binance:COIN0USDT", candles)
        opened = executor.process("okx:COIN1USDT", candles)
        self.assertEqual(opened.side, "LONG")
        self.assertIn("binance:COIN0USDT", broker.portfolio.positions)
        self.assertIn("okx:COIN1USDT", broker.portfolio.positions)

    def test_executor_opens_trend_long_when_fade_has_no_signal(self):
        class FixedSignal:
            def __init__(self, signal):
                self.signal = signal

            def evaluate(self, candles):
                return self.signal

        executor = Executor(
            PaperBroker(),
            strategy=FixedSignal(Signal("HOLD", 0, 0, None, "fade")),
            trend_strategy=FixedSignal(Signal("LONG", 0.1, 0, 0.01, "trend")),
        )
        executor.process("BTCUSDT", fade_setup())
        position = executor.broker.portfolio.positions["BTCUSDT"]
        self.assertEqual(position.side, "LONG")
        self.assertEqual(position.motor, "trend")

    def test_executor_blocks_opposite_position_on_same_asset_other_exchange(self):
        class FixedSignal:
            def __init__(self, signal):
                self.signal = signal

            def evaluate(self, candles):
                return self.signal

        broker = PaperBroker()
        executor = Executor(
            broker,
            strategy=FixedSignal(Signal("LONG", -0.5, 2.0, 0.005, "fade")),
            trend_strategy=FixedSignal(Signal("HOLD", 0, 0, None, "trend")),
        )
        executor.process("binance:BTCUSDT", fade_setup())
        executor.strategy = FixedSignal(Signal("HOLD", 0, 0, None, "fade"))
        executor.trend_strategy = FixedSignal(
            Signal("SHORT", -0.1, 0, 0.01, "trend")
        )
        decision = executor.process("okx:BTC-USDT-SWAP", rising_momentum())
        self.assertEqual(decision.side, "HOLD")
        self.assertEqual(decision.motor, "conflict")
        self.assertEqual(len(broker.portfolio.positions), 1)

    def test_other_exchange_market_data_can_trigger_existing_position_stop(self):
        class FixedSignal:
            def __init__(self, signal):
                self.signal = signal

            def evaluate(self, candles):
                return self.signal

        broker = PaperBroker()
        executor = Executor(
            broker,
            strategy=FixedSignal(Signal("LONG", -0.5, 2.0, 0.005, "fade")),
            trend_strategy=FixedSignal(Signal("HOLD", 0, 0, None, "trend")),
        )
        candles = fade_setup()
        executor.process("binance:BTCUSDT", candles)
        stop = broker.portfolio.positions["binance:BTCUSDT"].stop_loss
        candles[-1] = Candle(
            candles[-1].timestamp, stop - 0.1, stop + 0.1, stop - 0.2,
            stop, 10,
        )
        executor.strategy = FixedSignal(Signal("HOLD", 0, 0, None, "fade"))
        decision = executor.process("okx:BTC-USDT-SWAP", candles)
        self.assertEqual(decision.motor, "conflict")
        self.assertFalse(broker.portfolio.positions)
        self.assertEqual(broker.trades[-1]["reason"], "stop_loss")

    def test_cli_requires_explicit_paper_flag(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])
        parsed = build_parser().parse_args(["--paper", "--once"])
        self.assertTrue(parsed.paper)
        self.assertEqual(parsed.balance, 1_000.0)
        self.assertEqual(parsed.request_delay, 0.1)
        self.assertIsNone(RiskManager().max_positions)
        self.assertEqual(PaperBroker().portfolio.balance, 1_000.0)
        self.assertEqual(_selected_exchanges("binance+okx"), ["binance", "okx"])

    def test_cli_one_cycle_uses_public_market_data_and_paper_state(self):
        class FakeExchange:
            def fetch_top_usdt_futures(self, limit):
                return [Market("BTCUSDT", "BTC", 100, "PERPETUAL", 0.1)]

            def fetch_candles(self, symbol, timeframe, limit):
                self.request = (symbol, timeframe, limit)
                return fade_setup()

            def fetch_order_book(self, symbol, limit=100):
                return OrderBook(
                    symbol, ((99.9, 10),), ((100.0, 10),), 1000
                )

        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(
                paper=True, balance=1000.0, interval=30.0, symbols="BTCUSDT",
                exchange="binance", state=os.path.join(directory, "state.db"),
                request_delay=0.1, once=True,
            )
            output = StringIO()
            with (
                patch.dict("app.main._EXCHANGES", {"binance": FakeExchange}),
                patch("app.main.time.sleep") as sleep,
            ):
                with redirect_stdout(output):
                    self.assertEqual(run(args), 0)
            self.assertIn("PAPER ORDER AÇILDI: [BTCUSDT] [LONG] [", output.getvalue())
            self.assertIn("rejection=yok", output.getvalue())
            sleep.assert_called_once_with(0.1)
            with StateStore(args.state) as store:
                self.assertEqual(store.load_state()["mode"], "paper")

    def test_cli_displays_human_readable_rejection_reasons(self):
        self.assertEqual(
            _rejection_label(Signal("HOLD", 0, 0, None, rejection_code="MAX_POSITIONS_REACHED")),
            "limit_dolu",
        )
        self.assertEqual(
            _rejection_label(Signal("HOLD", 0, 0, None, rejection_code="INSUFFICIENT_FUNDS")),
            "marj_yetersiz",
        )
        self.assertEqual(
            _rejection_label(Signal("HOLD", 0, 0, None, rejection_code="dusuk_momentum")),
            "dusuk_momentum",
        )
        self.assertEqual(
            _rejection_label(Signal("HOLD", 0, 0, None, rejection_code="dusuk_hacim")),
            "dusuk_hacim",
        )
        self.assertEqual(
            _rejection_label(Signal("HOLD", 0, 0, None)), "sinyal_yok"
        )

    def test_cli_all_keeps_okx_running_when_binance_universe_fails(self):
        class BrokenBinance:
            def fetch_top_usdt_futures(self, limit):
                raise PublicMarketDataError("Binance down")

        class AvailableOKX:
            def fetch_top_usdt_futures(self, limit):
                return [Market("BTC-USDT-SWAP", "BTC", 100, "SWAP")]

            def fetch_candles(self, symbol, timeframe, limit):
                return fade_setup()

            def fetch_order_book(self, symbol, limit=100):
                return OrderBook(
                    symbol, ((99.9, 10),), ((100.0, 10),), 1000
                )

        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(
                paper=True, balance=1000.0, interval=30.0, symbols="ALL",
                exchange="all", state=os.path.join(directory, "state.db"),
                request_delay=0.1, once=True,
            )
            with (
                patch.dict(
                    "app.main._EXCHANGES",
                    {"binance": BrokenBinance, "okx": AvailableOKX},
                ),
                patch("app.main.time.sleep"),
            ):
                self.assertEqual(run(args), 0)

    def test_cli_keeps_okx_running_when_binance_candle_fetch_fails(self):
        class BrokenBinance:
            def fetch_top_usdt_futures(self, limit):
                return [Market("BTCUSDT", "BTC", 100, "PERPETUAL", 0.1)]

            def fetch_candles(self, symbol, timeframe, limit):
                raise PublicMarketDataError("Binance candles unavailable")

        class AvailableOKX:
            candles_fetched = False

            def fetch_top_usdt_futures(self, limit):
                return [Market("BTC-USDT-SWAP", "BTC", 100, "SWAP", 0.1)]

            def fetch_candles(self, symbol, timeframe, limit):
                type(self).candles_fetched = True
                return fade_setup()

            def fetch_order_book(self, symbol, limit=100):
                return OrderBook(
                    symbol, ((99.9, 10),), ((100.0, 10),), 1000
                )

        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(
                paper=True, balance=1000.0, interval=30.0, symbols="ALL",
                exchange="all", state=os.path.join(directory, "state.db"),
                request_delay=0.1, once=True,
            )
            with (
                patch.dict(
                    "app.main._EXCHANGES",
                    {"binance": BrokenBinance, "okx": AvailableOKX},
                ),
                patch("app.main.time.sleep"),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(run(args), 0)
            self.assertTrue(AvailableOKX.candles_fetched)


class RealtimeSpikeTests(unittest.IsolatedAsyncioTestCase):
    async def test_spike_without_both_strategy_approvals_is_rejected(self):
        class AlwaysLong:
            def evaluate(self, candles):
                return Signal("LONG", 0.5, 2.0, 0.01, "fade")

        class Hold:
            def evaluate(self, candles):
                return Signal("HOLD", 0.0, 0.0, None, "trend")

        class FakeExchange:
            def fetch_candles(self, symbol, timeframe, limit):
                return [candle(i * 300_000, 100 + i * 0.01) for i in range(100)]

            def fetch_order_book(self, symbol, limit=100):
                return OrderBook(symbol, ((100, 100),), ((100.1, 100),), 1000)

        broker = PaperBroker()
        executor = Executor(broker, strategy=AlwaysLong(), trend_strategy=Hold())
        market = Market("BTCUSDT", "BTC", 2_000_000, "PERPETUAL", 0.1)
        spike = VolumeSpike(
            "BTCUSDT", 3000, 10, 10, "LONG", 5.0, 105, 100_000_000
        )
        await _process_spike_batch(
            [("binance", spike)],
            {"binance": FakeExchange()},
            {"binance": {"BTCUSDT": market}},
            executor,
            request_delay=0,
        )
        self.assertNotIn("binance:BTCUSDT", broker.portfolio.positions)

    async def test_ranked_volume_spike_batch_opens_paper_position(self):
        class AlwaysLong:
            def evaluate(self, candles):
                return Signal("LONG", 0.5, 2.0, 0.01, "fade")

        class FakeExchange:
            def fetch_candles(self, symbol, timeframe, limit):
                return [candle(i * 300_000, 100 + i * 0.01) for i in range(100)]

            def fetch_order_book(self, symbol, limit=100):
                return OrderBook(
                    symbol, ((100.0, 100),), ((100.1, 100),), 1000
                )

        broker = PaperBroker()
        executor = Executor(
            broker, strategy=AlwaysLong(), trend_strategy=AlwaysLong()
        )
        market = Market("BTCUSDT", "BTC", 2_000_000, "PERPETUAL", 0.1)
        spike = VolumeSpike(
            "BTCUSDT", 3000, 10, 10, "LONG", 5.0, 105, 100_000_000
        )
        await _process_spike_batch(
            [("binance", spike)],
            {"binance": FakeExchange()},
            {"binance": {"BTCUSDT": market}},
            executor,
            request_delay=0,
        )
        position = broker.portfolio.positions["binance:BTCUSDT"]
        self.assertEqual(position.side, "LONG")
        self.assertEqual(position.motor, "fade")


class BacktestTests(unittest.TestCase):
    def test_backtest_uses_fade_signals_and_closes_at_end(self):
        class AlwaysLong:
            def evaluate(self, history):
                return Signal("LONG", -0.5, 2.0, 0.005)

        data = [candle(i * 300_000, 100, spread=0.01) for i in range(4)]
        result = BacktestEngine(strategy=AlwaysLong()).run("BTCUSDT", data)
        self.assertGreaterEqual(result.trade_count, 1)
        self.assertIn(result.trades[0]["order_type"], {"post_only"})
        self.assertEqual(result.trades[-1]["reason"], "end_of_backtest")
        self.assertTrue(all(
            trade.get("side") == "LONG" for trade in result.trades
        ))


if __name__ == "__main__":
    unittest.main()
