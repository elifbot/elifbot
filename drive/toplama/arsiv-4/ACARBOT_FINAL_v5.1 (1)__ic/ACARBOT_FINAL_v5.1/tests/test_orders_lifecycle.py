"""Yorum 1-A ve Yorum 2-5 — emir yaşam döngüsü ve maker dolum testleri.

Eski hata: her post-only emir anında ve tamamen doluyordu; üstüne taker
kayması uygulanıyordu. Yeni model: kuyruk + kısmi dolum + TTL + trade-through.
"""

import pytest

from core.config import SuperConfig
from core.risk import RiskManager
from exec.orders import (
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    market_fill_price,
)
from exec.paper import PaperBroker


def _plan(side="LONG", entry=100.0, stop=0.004):
    risk = RiskManager()
    return risk.plan(entry, stop, side)


class TestOrderLifecycle:
    def test_new_to_filled_via_trade_through(self):
        order = Order(
            symbol="X:TEST", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=10.0, limit_price=99.98, created_ms=0,
        )
        sim = MakerFillSimulator()
        sim.register(order, baseline_per_second=1.0)
        # Fiyat 100'de: dokunma yok
        assert sim.process_tick(order, 100.0, 5.0, 1000) is None
        assert order.status == OrderStatus.NEW
        # Trade-through: 99.0 < 99.98 → kalanın tamamı dolar
        fill = sim.process_tick(order, 99.0, 5.0, 2000)
        assert fill is not None
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == pytest.approx(10.0)
        # Maker dolum: limit fiyatından, kayma yok
        assert fill.price == pytest.approx(99.98)

    def test_partial_fill_then_fill_at_touch(self):
        order = Order(
            symbol="X:TEST", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=10.0, limit_price=100.0, created_ms=0,
        )
        sim = MakerFillSimulator(depth_factor=1.0, queue_horizon_seconds=10.0,
                                 min_fill_fraction=0.05)
        sim.register(order, baseline_per_second=10.0)  # kuyruk: 100
        # Seviyede 60 hacim işlem gördü: kuyruğun 60'ı erir, bize dokunmaz
        fill = sim.process_tick(order, 100.0, 60.0, 1000)
        assert fill is None
        assert order.status == OrderStatus.NEW
        # 30 daha: kuyrukta 10 kaldı, bize dokunmaz
        fill = sim.process_tick(order, 100.0, 30.0, 2000)
        assert fill is None
        # 15 daha: kuyruk biter, 5 bizim olur → %50 kısmi dolum
        fill = sim.process_tick(order, 100.0, 15.0, 3000)
        assert fill is not None
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == pytest.approx(5.0)
        # Trade-through: kalan dolar
        sim.process_tick(order, 99.5, 10.0, 4000)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == pytest.approx(10.0)

    def test_ttl_expiry_cancels_unfilled_order(self):
        """45 sn dolmayan emir EXPIRED olur (dolmayan maker = gerçekçi)."""
        order = Order(
            symbol="X:TEST", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=10.0, limit_price=99.0, created_ms=0, ttl_ms=45_000,
        )
        sim = MakerFillSimulator()
        sim.register(order, 1.0)
        # Fiyat hep 100'de: limit hiç dokunulmaz
        for i in range(10):
            sim.process_tick(order, 100.0, 1.0, i * 10_000)
        # 46. saniyede TTL aşılır
        result = sim.process_tick(order, 100.0, 1.0, 46_000)
        assert result is None
        assert order.status == OrderStatus.EXPIRED

    def test_maker_fill_has_no_taker_slippage(self):
        """Post-only dolumda taker kayması uygulanmaz (Y2-5 tutarlılık)."""
        order = Order(
            symbol="X:TEST", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=5.0, limit_price=99.98, created_ms=0,
            maker_fee_rate=0.0002, taker_fee_rate=0.0005,
        )
        sim = MakerFillSimulator()
        sim.register(order, 1.0)
        fill = sim.process_tick(order, 99.0, 5.0, 1000)
        assert fill is not None
        assert fill.is_maker is True
        assert fill.price == pytest.approx(order.limit_price)
        assert fill.fee == pytest.approx(fill.price * fill.quantity * 0.0002)

    def test_short_entry_fills_on_upside_trade_through(self):
        order = Order(
            symbol="X:TEST", side=OrderSide.SELL,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=10.0, limit_price=100.02, created_ms=0,
        )
        sim = MakerFillSimulator()
        sim.register(order, 1.0)
        fill = sim.process_tick(order, 101.0, 5.0, 1000)
        assert fill is not None
        assert order.status == OrderStatus.FILLED


class TestMarketFillSlippage:
    def test_stop_market_buy_fills_above(self):
        price = market_fill_price(100.0, OrderSide.BUY, 0.0005)
        assert price == pytest.approx(100.05)

    def test_stop_market_sell_fills_below(self):
        price = market_fill_price(100.0, OrderSide.SELL, 0.0005)
        assert price == pytest.approx(99.95)

    def test_invalid_slippage_rejected(self):
        with pytest.raises(ValueError):
            market_fill_price(100.0, OrderSide.BUY, 1.0)


class TestPaperBrokerEntries:
    def test_entry_order_created_and_pending(self):
        broker = PaperBroker()
        plan = _plan()
        order = broker.place_entry("X:TEST", plan, now_ms=1_000)
        assert order.status == OrderStatus.NEW
        assert broker.pending("X:TEST")
        types = [t["type"] for t in broker.trades]
        assert "ORDER_NEW" in types

    def test_filled_order_opens_position(self):
        config = SuperConfig()
        broker = PaperBroker(config, 1_000.0)
        risk = RiskManager(config)
        plan = risk.plan(100.0, 0.004, "LONG")
        order = broker.place_entry("X:TEST", plan, now_ms=0, baseline_per_second=1.0)
        broker.bind_plan(order, plan, "fade")
        broker.portfolio.balance -= 0.0  # ücret dolumda düşecek
        # Trade-through: fiyat limitin altına iner
        broker.process_entry_tick("X:TEST", 99.0, 10.0, 1_000)
        assert "X:TEST" in broker.portfolio.positions
        position = broker.portfolio.positions["X:TEST"]
        assert position.side == "LONG"
        assert position.motor == "fade"
        assert position.liquidation_price > 0
        # v5.0: hedef net risk TAM 25 USDT (float toleransıyla)
        assert position.initial_net_risk == pytest.approx(25.0, abs=1e-6)
        types = [t["type"] for t in broker.trades]
        assert "ORDER_FILL" in types and "OPEN" in types

    def test_duplicate_entry_rejected(self):
        broker = PaperBroker()
        plan = _plan()
        broker.place_entry("X:TEST", plan, 0)
        with pytest.raises(ValueError):
            broker.place_entry("X:TEST", plan, 1_000)

    def test_cancel_pending_entries(self):
        broker = PaperBroker()
        plan = _plan()
        order = broker.place_entry("X:TEST", plan, 0)
        count = broker.cancel_pending_entries(5_000, reason="safe_mode")
        assert count == 1
        assert order.status == OrderStatus.CANCELED
        assert not broker.pending("X:TEST")
