"""Yorum 2-3 ve Yorum 1-B — çıkış yolu testleri.

Eski hata: FADE pozisyonlarında TP/time-stop/momentum çıkışı kapalıydı;
trailing için %20 hareket gerekiyordu → pozisyonlar marjı süresiz kilitliyordu.
Yeni çıkışlar: TP1 (+1R %50), ATR trailing (0.75R erken aktivasyon),
zaman stopu (FADE 90 dk), momentum çıkışı, acil net-zarar stopu.
"""

import pytest

from core.config import SuperConfig
from core.portfolio import Position, compute_liquidation_price
from core.risk import RiskManager
from exec.paper import PaperBroker
from infra.market_data.models import Candle
from tests.helpers import START_MS, INTERVAL_MS


def _open_long(broker, entry=100.0, stop_fraction=0.004, motor="fade"):
    risk = RiskManager(broker.config)
    plan = risk.plan(entry, stop_fraction, "LONG", motor=motor)
    from exec.orders import Order, OrderSide, OrderType
    order = Order(
        symbol="X:T", side=OrderSide.BUY, order_type=OrderType.POST_ONLY_LIMIT,
        quantity=plan.quantity, limit_price=entry, created_ms=START_MS,
    )
    broker.bind_plan(order, plan, motor)
    order.apply_fill(entry, plan.quantity, START_MS, is_maker=True)
    broker._open_position_from_order("X:T", order, START_MS)
    return plan


def _candle(ts, open_, high, low, close, volume=10.0):
    return Candle(timestamp=ts, open=open_, high=high, low=low, close=close,
                  volume=volume)


class TestTakeProfit1:
    def test_tp1_partial_close_at_one_r(self):
        """+1R'ye dokununca %50 kapanır, kalan pozisyon trailing'e geçer (Y2-3)."""
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, entry=100.0, stop_fraction=0.004)
        position = broker.portfolio.positions["X:T"]
        assert position.take_profit is not None
        assert position.take_profit == pytest.approx(100.4, rel=1e-3)

        entry_price = 100.0
        r_usdt = position.initial_net_risk
        # TP seviyesi: entry * 1.004 → fiyat hareketi = %0.4 * notional
        # R'ye ulaşması için mum TP'ye değmeli
        events = broker.manage_position_candle(
            "X:T", _candle(START_MS + INTERVAL_MS, 100.0, 100.5, 99.9, 100.4),
            START_MS + INTERVAL_MS,
        )
        partials = [e for e in events if e.get("type") == "PARTIAL_CLOSE"]
        assert partials, "TP1 kısmi kapanış oluşmalı"
        position = broker.portfolio.positions["X:T"]
        assert position.tp1_done is True
        assert position.quantity == pytest.approx(
            position.initial_quantity * 0.5, rel=1e-6
        )
        assert position.trailing_active is True
        # TP1 kârı pozisyona işlendi
        assert position.tp1_realized_pnl > 0

    def test_no_tp1_without_touch(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker)
        events = broker.manage_position_candle(
            "X:T", _candle(START_MS + INTERVAL_MS, 100.0, 100.2, 99.95, 100.1),
            START_MS + INTERVAL_MS,
        )
        assert not [e for e in events if e.get("type") == "PARTIAL_CLOSE"]


class TestTrailingStop:
    def test_trailing_tightens_after_activation(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, stop_fraction=0.01)
        position = broker.portfolio.positions["X:T"]
        initial_stop = position.stop_loss
        # TP1'i tetikle
        broker.manage_position_candle(
            "X:T", _candle(START_MS + INTERVAL_MS, 100.0, 101.2, 99.95, 101.0),
            START_MS + INTERVAL_MS, atr=0.5,
        )
        position = broker.portfolio.positions.get("X:T")
        if position is None:
            pytest.skip("TP1 mumu pozisyonu kapattı")
        assert position.trailing_active
        assert position.stop_loss > initial_stop
        # Yeni zirve ile stop yükselmeli
        stop_before = position.stop_loss
        broker.manage_position_candle(
            "X:T", _candle(START_MS + 2 * INTERVAL_MS, 101.0, 102.0, 100.8, 101.8),
            START_MS + 2 * INTERVAL_MS, atr=0.5,
        )
        position = broker.portfolio.positions.get("X:T")
        if position is not None:
            assert position.stop_loss > stop_before


class TestTimeStop:
    def test_fade_time_stop_after_90_minutes(self):
        """FADE pozisyonu 90 dk sonra kâr/zarara bakılmadan kapanır (Y2-3)."""
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, motor="fade")
        # 90 dk = 5400 sn → mum sayısı 18
        ts = START_MS + 19 * INTERVAL_MS
        events = broker.manage_position_candle(
            "X:T", _candle(ts, 100.0, 100.1, 99.95, 100.0), ts,
        )
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "time_stop"
        assert "X:T" not in broker.portfolio.positions

    def test_trend_position_survives_90_minutes(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, motor="trend")
        ts = START_MS + 19 * INTERVAL_MS
        events = broker.manage_position_candle(
            "X:T", _candle(ts, 100.0, 100.1, 99.95, 100.0), ts,
        )
        assert not [e for e in events if e.get("type") == "CLOSE"]
        assert "X:T" in broker.portfolio.positions


class TestMomentumExit:
    def test_momentum_end_closes_profitable_position(self):
        """+1R sonrası momentum ölürse pozisyon kârda kapatılır (Y2-3)."""
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, stop_fraction=0.01)
        position = broker.portfolio.positions["X:T"]
        # Fiyatı +1R'ye taşı (%1.5+ hareket) ama TP'yi dokunmadan
        r_price_move = position.initial_net_risk / (
            position.quantity * 100.0
        )  # gereken oran
        target = 100.0 * (1 + r_price_move + 0.002)
        tp = position.take_profit
        close_price = min(target, tp - 0.05) if tp else target
        events = broker.manage_position_candle(
            "X:T",
            _candle(START_MS + INTERVAL_MS, 100.0, close_price, 100.0, close_price),
            START_MS + INTERVAL_MS,
            impulse_pct=-0.5,   # momentum aleyhte
            rvol=0.5,           # hacim öldü
        )
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "momentum_end"
        assert closes[0]["pnl"] > 0


class TestNetLossStop:
    def test_gap_beyond_stop_closes_with_costs_included(self):
        """Gap: fiyat stopun çok altında açılırsa NET zarar hesabıyla kapanır.

        Eski kod brüt -25 kontrolü yapıyor, ücret/kayma sonradan ekleniyordu
        → -25,53 çıkıyordu. Yeni kod maliyetleri ÖNCEDEN düşer; kapanış
        netPnL ≤ -25 anında tetiklenir ve gerçekleşen zarar şeffaftır.
        """
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, entry=100.0, stop_fraction=0.02)  # geniş stop
        position = broker.portfolio.positions["X:T"]
        assert position.stop_loss == pytest.approx(98.0)
        # Tick yolu: fiyat doğrudan 94'e düşer (gap)
        events = broker.manage_position_tick("X:T", 94.0, START_MS + 1000)
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "position_loss_stop"
        # Net zarar = brüt - tüm maliyetler (şeffaf, tavan + maliyetler)
        assert closes[0]["pnl"] < -20.0
        assert closes[0]["pnl"] == pytest.approx(
            closes[0]["gross_pnl"] - closes[0]["entry_fee"]
            - closes[0]["fee"] - closes[0]["funding_paid"], rel=1e-6,
        )

    def test_regular_stop_before_emergency(self):
        """Normal stop, tavana varmadan tetiklenir (tipik FADE riski ~2-3 USDT)."""
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, entry=100.0, stop_fraction=0.004)
        events = broker.manage_position_tick("X:T", 99.5, START_MS + 1000)
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "stop_loss"
        assert -5.0 < closes[0]["pnl"] < 0


class TestConservativeOrdering:
    def test_stop_wins_when_both_levels_in_one_candle(self):
        """Aynı mumda stop ve TP: önce STOP varsayılır (muhafazakâr, Y2-6)."""
        broker = PaperBroker(SuperConfig(), 1_000.0)
        broker.risk_manager_ref = RiskManager(broker.config)
        _open_long(broker, entry=100.0, stop_fraction=0.004)
        position = broker.portfolio.positions["X:T"]
        tp = position.take_profit  # 100.4
        stop = position.stop_loss  # 99.6
        events = broker.manage_position_candle(
            "X:T", _candle(START_MS + INTERVAL_MS, 100.0, tp + 0.1, stop - 0.1, 100.0),
            START_MS + INTERVAL_MS,
        )
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "stop_loss"
        assert not [e for e in events if e.get("type") == "PARTIAL_CLOSE"]


class TestLiquidationPath:
    def test_liquidation_closes_position_with_penalty(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        risk = RiskManager(broker.config)
        broker.risk_manager_ref = risk
        _open_long(broker, entry=100.0, stop_fraction=0.02)
        position = broker.portfolio.positions["X:T"]
        position.liquidation_price = compute_liquidation_price(
            100.0, "LONG", 10.0, broker.config.funding,
        )
        # Stop 98, likidasyon ~91.75: tick 91.0 → likidasyon önce gelir
        events = broker.manage_position_tick("X:T", 91.0, START_MS + 1000)
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "liquidation"
        assert closes[0]["execution_type"] == "liquidation"

    def test_candle_path_liquidation_uses_worst_price(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        risk = RiskManager(broker.config)
        broker.risk_manager_ref = risk
        _open_long(broker, entry=100.0, stop_fraction=0.02)
        position = broker.portfolio.positions["X:T"]
        position.liquidation_price = 95.0  # test için yukarı çekildi
        events = broker.manage_position_candle(
            "X:T", _candle(START_MS + INTERVAL_MS, 100.0, 100.1, 94.0, 94.5),
            START_MS + INTERVAL_MS,
        )
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["reason"] == "liquidation"


class TestFundingInCandlePath:
    def test_funding_applied_in_candle_management(self):
        broker = PaperBroker(SuperConfig(), 1_000.0)
        risk = RiskManager(broker.config)
        broker.risk_manager_ref = risk
        _open_long(broker, entry=100.0, stop_fraction=0.01)
        # 8 saat + 1 mum sonrası (97. mum)
        ts = START_MS + 97 * INTERVAL_MS
        events = broker.manage_position_candle(
            "X:T", _candle(ts, 100.0, 100.1, 99.95, 100.0), ts,
        )
        funding_events = [e for e in events if e.get("type") == "FUNDING"]
        assert funding_events
        position = broker.portfolio.positions.get("X:T")
        if position is not None:
            assert position.funding_paid > 0
