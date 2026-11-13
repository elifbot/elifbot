"""v4.0 — DCA güvenlik emirleri testleri (madde 8: varsayılan kapalı, yalnız LONG)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from exec.paper import PaperBroker


def _open_long(ex: Executor, price: float = 100.0, qty: float = 1.0,
               stop_frac: float = 0.05):
    """Direkt paper pozisyon açar (DCA tetikleyicisini izole test etmek için).

    Stop, DCA adımından UZAKTA tutulur (%5) — aksi halde stop-out DCA'dan
    önce tetiklenir (gerçek kullanımda da DCA adımı stop mesafesinin
    içinde olmalıdır).
    """
    from types import SimpleNamespace
    from exec.orders import Order, OrderSide, OrderType
    order = Order(
        symbol="okx:T-USDT-SWAP", side=OrderSide.BUY,
        order_type=OrderType.POST_ONLY_LIMIT, quantity=qty,
        limit_price=price, created_ms=1_000,
        maker_fee_rate=0.0, taker_fee_rate=0.0,
    )
    order.apply_fill(price, qty, 1_100, is_maker=True)
    ex.broker._plan_for_order[order.id] = SimpleNamespace(
        side="LONG", entry=price, stop_loss=price * (1.0 - stop_frac),
        take_profit=None, quantity=qty, margin=qty * price / 10.0,
        leverage=10.0, stop_fraction=stop_frac, net_risk=1.0,
        estimated_funding_buffer=0.0,
    )
    # bind_plan yerine direkt plan kaydı: stop girişin stop_frac altında
    ex.broker._open_position_from_order("okx:T-USDT-SWAP", order, 1_200)


class DcaTests(unittest.TestCase):
    def _executor(self, dca_enabled: bool, **dca_kwargs) -> Executor:
        cfg = SuperConfig()
        if dca_enabled:
            cfg.dca = replace(cfg.dca, enabled=True, **dca_kwargs)
        return Executor(PaperBroker(cfg, 10_000.0), RiskManager(cfg), cfg)

    def test_default_disabled_no_dca(self):
        ex = self._executor(dca_enabled=False)
        _open_long(ex)
        position = ex.broker.portfolio.positions["okx:T-USDT-SWAP"]
        events = ex.process_price_update(
            "okx:T-USDT-SWAP", position.entry * 0.90, 5_000,
        )
        self.assertEqual(position.dca_count, 0)
        self.assertFalse(any(e.get("type") == "DCA" for e in events))

    def test_long_triggers_safety_order(self):
        ex = self._executor(dca_enabled=True, first_step_pct=1.0)
        _open_long(ex)
        position = ex.broker.portfolio.positions["okx:T-USDT-SWAP"]
        entry0, qty0 = position.entry, position.quantity
        balance0 = ex.broker.portfolio.balance
        events = ex.process_price_update(
            "okx:T-USDT-SWAP", entry0 * 0.99, 5_000,
        )
        dca_events = [e for e in events if e.get("type") == "DCA"]
        self.assertEqual(len(dca_events), 1)
        self.assertEqual(position.dca_count, 1)
        self.assertGreater(position.quantity, qty0)
        self.assertLess(position.entry, entry0)  # ortalama düştü
        self.assertAlmostEqual(
            position.stop_loss, entry0 * 0.95,
        )  # stop SABİT (açılıştaki %5 mesafesi)
        self.assertLess(ex.broker.portfolio.balance, balance0)  # ücret düştü
        trades = [t for t in ex.broker.trades if t.get("type") == "DCA"]
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["side"], "LONG")

    def test_step_scales_after_first_dca(self):
        ex = self._executor(
            dca_enabled=True, first_step_pct=1.0, step_scale=2.0,
        )
        _open_long(ex)
        position = ex.broker.portfolio.positions["okx:T-USDT-SWAP"]
        entry0 = position.entry
        # 1. DCA: tetik -%1 → 99.0; 98.99 kesin tetikler
        ex.process_price_update("okx:T-USDT-SWAP", entry0 * 0.9899, 5_000)
        avg_after_1 = ex.broker.portfolio.positions["okx:T-USDT-SWAP"].entry
        self.assertEqual(
            ex.broker.portfolio.positions["okx:T-USDT-SWAP"].dca_count, 1,
        )
        # 2. DCA: ort. girişin -%2'si (1.0 × 2.0); 0.979 kesin tetikler
        ex.process_price_update(
            "okx:T-USDT-SWAP", avg_after_1 * 0.979, 6_000,
        )
        self.assertEqual(
            ex.broker.portfolio.positions["okx:T-USDT-SWAP"].dca_count, 2,
        )
        # 3. DCA: max_safety_orders=2 doldu → yok (fiyat likidasyon/stop
        # altına İNMEDEN düşük kalmalı: avg×0.97 hâlâ stop üstünde)
        avg = ex.broker.portfolio.positions["okx:T-USDT-SWAP"].entry
        ex.process_price_update("okx:T-USDT-SWAP", avg * 0.97, 7_000)
        self.assertEqual(
            ex.broker.portfolio.positions["okx:T-USDT-SWAP"].dca_count, 2,
        )

    def test_short_never_dca(self):
        ex = self._executor(dca_enabled=True)
        # SHORT pozisyonu elle aç
        from types import SimpleNamespace
        from exec.orders import Order, OrderSide, OrderType
        price = 100.0
        order = Order(
            symbol="okx:T-USDT-SWAP", side=OrderSide.SELL,
            order_type=OrderType.POST_ONLY_LIMIT, quantity=1.0,
            limit_price=price, created_ms=1_000,
            maker_fee_rate=0.0, taker_fee_rate=0.0,
        )
        order.apply_fill(price, 1.0, 1_100, is_maker=True)
        ex.broker._plan_for_order[order.id] = SimpleNamespace(
            side="SHORT", entry=price, stop_loss=price * 1.05,
            take_profit=None, quantity=1.0, margin=price / 10.0,
            leverage=10.0, stop_fraction=0.05, net_risk=1.0,
            estimated_funding_buffer=0.0,
        )
        ex.broker._open_position_from_order("okx:T-USDT-SWAP", order, 1_200)
        position = ex.broker.portfolio.positions["okx:T-USDT-SWAP"]
        # SHORT'ta fiyat YÜKSELDİĞİNE DCA olurdu (LONG mantığı) — olmamalı
        ex.process_price_update("okx:T-USDT-SWAP", price * 1.05, 5_000)
        self.assertEqual(position.dca_count, 0)

    def test_risk_cap_blocks_dca(self):
        # İlk adım çok büyük (stop %5; DCA tetiği -%30) → net risk tavan aşar
        ex = self._executor(
            dca_enabled=True, first_step_pct=30.0, max_safety_orders=1,
        )
        _open_long(ex, qty=10.0)  # 1000 USDT notional
        position = ex.broker.portfolio.positions["okx:T-USDT-SWAP"]
        ex.process_price_update(
            "okx:T-USDT-SWAP", position.entry * 0.69, 5_000,
        )
        self.assertEqual(position.dca_count, 0)

    def test_snapshot_round_trip_dca_count(self):
        ex = self._executor(dca_enabled=True)
        _open_long(ex)
        position = ex.broker.portfolio.positions["okx:T-USDT-SWAP"]
        ex.process_price_update(
            "okx:T-USDT-SWAP", position.entry * 0.99, 5_000,
        )
        snap = ex.snapshot()
        raw = snap["positions"]["okx:T-USDT-SWAP"]
        self.assertEqual(raw["dca_count"], 1)
        from app.executor import Position_from_snapshot
        restored = Position_from_snapshot("okx:T-USDT-SWAP", raw)
        self.assertEqual(restored.dca_count, 1)
        self.assertEqual(restored.entry, position.entry)


if __name__ == "__main__":
    unittest.main()
