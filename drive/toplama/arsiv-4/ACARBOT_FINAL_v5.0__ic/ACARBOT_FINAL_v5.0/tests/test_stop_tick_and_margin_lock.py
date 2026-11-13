"""FINAL v1.10 — stop'un TAM 25 USDT zararda kapanması + dolum anı teminat kilidi.

Kullanıcı şartı (7 Kasım 2026):
  "bizim stopumuz girdiğimiz işlem 25 dolar zarar ederse kapanacak şekilde olacak"

Tespit edilen sapma (v1.8 canlı oturumu, BTTCUSDT SHORT):
  giriş 3.5007e-7 · teorik stop %2,50 → 3.58822e-7
  Binance fiyat ızgarası 1e-8 = fiyatın %2,86'sı (!)
  → ilk tetiklenebilir tick 3.6e-7 = %2,837 → NET -28,10 USDT (hedef -25)

Sebep: pozisyon TEORİK stop mesafesinden boyutlanıyordu, borsa ise yalnız
ızgara adımlarında fiyat verebiliyordu. v1.10 stopu ızgaraya DIŞA yuvarlar ve
pozisyonu bu GERÇEK mesafeden boyutlar → stop tetiklenince net zarar 25 USDT.

İkinci iş: dolum anı teminat kilidi. Planlama anında teminat yeterliydi ama
emir 45 sn TTL boyunca beklerken başka emirler teminatı tüketebiliyordu;
dolum anında hiç kontrol yoktu.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.config import SuperConfig
from core.risk import RiskManager
from exec.paper import PaperBroker

BTTC_ENTRY = 3.5007e-07
BTTC_TICK = 1e-08


def _risk() -> RiskManager:
    return RiskManager(SuperConfig())


class TestStopTickGrid:
    def test_without_tick_size_legacy_behaviour(self):
        risk = _risk()
        plan = risk.plan(100.0, 0.0077, "SHORT")
        assert plan.stop_loss == pytest.approx(100.0 * 1.0077)
        assert plan.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)

    def test_short_stop_snaps_up_to_grid(self):
        plan = _risk().plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        # 3.58822e-7 → yukarı ızgara → 3.6e-7
        assert plan.stop_loss == pytest.approx(3.6e-07, rel=1e-9)
        assert plan.stop_loss > BTTC_ENTRY * 1.025

    def test_long_stop_snaps_down_to_grid(self):
        plan = _risk().plan(100.0, 0.0103, "LONG", tick_size=0.5)
        # teorik 98.97 → aşağı ızgara → 98.5
        assert plan.stop_loss == pytest.approx(98.5)
        assert plan.stop_loss < 100.0 * (1 - 0.0103)

    def test_position_sized_down_so_target_stays_25(self):
        risk = _risk()
        legacy = risk.plan(BTTC_ENTRY, 0.025, "SHORT")
        fixed = risk.plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        assert fixed.notional < legacy.notional
        assert fixed.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)
        assert legacy.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)

    def test_liquid_coin_barely_changes(self):
        risk = _risk()
        legacy = risk.plan(100_000.0, 0.0077, "LONG")
        fixed = risk.plan(100_000.0, 0.0077, "LONG", tick_size=0.1)
        # BTC'de ızgara adımının fiyata oranı 1e-6 → fark ihmal edilebilir
        assert fixed.notional == pytest.approx(legacy.notional, rel=1e-3)
        assert fixed.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)

    def test_take_profit_scales_with_snapped_stop(self):
        plan = _risk().plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        stop_frac = abs(plan.stop_loss - BTTC_ENTRY) / BTTC_ENTRY
        expected_tp = BTTC_ENTRY * (1.0 - stop_frac)
        assert plan.take_profit == pytest.approx(expected_tp, rel=1e-9)

    def test_coarse_grid_rejected(self):
        # tick, fiyatın %100'ü → stop %0,3'ten %100'e fırlar → işlem açılamaz
        with pytest.raises(ValueError, match="STOP_IZGARA_KABA"):
            _risk().plan(1e-07, 0.003, "SHORT", tick_size=1e-07)

    def test_widen_ratio_is_configurable(self):
        cfg = SuperConfig()
        cfg = replace(cfg, exit=replace(cfg.exit, stop_tick_max_widen_ratio=1.05))
        with pytest.raises(ValueError, match="STOP_IZGARA_KABA"):
            RiskManager(cfg).plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        # 0 = kontrol kapalı, yine de dışa yuvarlama ve doğru boyutlama yapılır
        cfg_off = replace(cfg, exit=replace(cfg.exit, stop_tick_max_widen_ratio=0.0))
        plan = RiskManager(cfg_off).plan(1e-07, 0.003, "SHORT", tick_size=1e-07)
        assert plan.net_risk_at_stop == pytest.approx(25.0, abs=1e-9)

    def test_default_widen_ratio(self):
        assert SuperConfig().exit.stop_tick_max_widen_ratio == 1.5


class TestRealizedStopLossIs25:
    """Uçtan uca: ızgarada sıçrayan fiyat stopu tetiklediğinde gerçek net PnL."""

    def _run(self, tick_size: float) -> float:
        cfg = SuperConfig()
        broker = PaperBroker(cfg, 1_000.0)
        risk = RiskManager(cfg)
        broker.risk_manager_ref = risk
        sym = "binance:BTTCUSDT"
        broker.tick_sizes[sym] = BTTC_TICK if tick_size > 0 else 0.0
        plan = risk.plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=tick_size)
        order = broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        broker.bind_plan(order, plan, "trend")
        # limit fiyatının ÖTESİNDE işlem → tamamı dolar (maker)
        broker.process_entry_tick(sym, BTTC_ENTRY * 1.002, 1e12, 1_000)
        assert sym in broker.portfolio.positions, "giriş dolmadı"
        # Fiyat ızgarada bir adım sıçrar: stopun ötesindeki İLK tick
        events = broker.manage_position_tick(sym, 3.6e-07, 2_000)
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes, "stop tetiklenmedi"
        return closes[0]["pnl"]

    def test_fixed_sizing_lands_on_25(self):
        pnl = self._run(BTTC_TICK)
        assert -26.5 <= pnl <= -23.0, f"25 USDT hedefinden saptı: {pnl}"

    def test_legacy_sizing_overshoots(self):
        pnl = self._run(0.0)
        assert pnl < -26.5, f"eski davranış sapmayı üretmeliydi: {pnl}"

    def test_fix_reduces_overshoot(self):
        assert abs(self._run(BTTC_TICK)) < abs(self._run(0.0))


class TestFillTimeMarginLock:
    def _broker(self, balance: float = 1_000.0) -> PaperBroker:
        return PaperBroker(SuperConfig(), balance)

    def _place(self, broker, sym, entry=100.0, stop=0.004):
        plan = _risk().plan(entry, stop, "LONG")
        order = broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1.0)
        broker.bind_plan(order, plan, "trend")
        return order, plan

    def test_free_margin_excludes_own_reservation(self):
        broker = self._broker()
        order, plan = self._place(broker, "okx:A-USDT-SWAP")
        assert broker.free_margin() == pytest.approx(1_000.0 - broker.reserved_margin())
        assert broker.free_margin(exclude_order_id=order.id) == pytest.approx(1_000.0)

    def test_order_fills_when_margin_sufficient(self):
        broker = self._broker(10_000.0)
        self._place(broker, "okx:A-USDT-SWAP")
        broker.process_entry_tick("okx:A-USDT-SWAP", 99.0, 10.0, 1_000)
        assert "okx:A-USDT-SWAP" in broker.portfolio.positions
        assert broker.margin_lock_cancels == 0

    def test_lock_cancels_when_margin_no_longer_sufficient(self):
        broker = self._broker(1_000.0)
        order, plan = self._place(broker, "okx:A-USDT-SWAP")
        # Başka bir pozisyon teminatı tüketir (plan anında boştu)
        other_plan = _risk().plan(100.0, 0.004, "LONG")
        broker.portfolio.positions["okx:B-USDT-SWAP"] = _make_position(
            other_plan, margin=900.0,
        )
        broker.process_entry_tick("okx:A-USDT-SWAP", 99.0, 10.0, 1_000)
        assert "okx:A-USDT-SWAP" not in broker.portfolio.positions
        assert broker.margin_lock_cancels == 1
        cancels = [t for t in broker.trades if t["type"] == "ORDER_CANCELLED"]
        assert len(cancels) == 1
        assert cancels[0]["reason"] == "TEMINAT_KILIDI"
        assert cancels[0]["required_margin"] > cancels[0]["free_margin"]

    def test_cancelled_order_leaves_pending_list(self):
        broker = self._broker(1_000.0)
        order, plan = self._place(broker, "okx:A-USDT-SWAP")
        broker.portfolio.positions["okx:B-USDT-SWAP"] = _make_position(plan, margin=900.0)
        broker.process_entry_tick("okx:A-USDT-SWAP", 99.0, 10.0, 1_000)
        assert broker.pending("okx:A-USDT-SWAP") == []
        assert broker.reserved_margin() == pytest.approx(0.0)

    def test_lock_is_per_tick_not_only_at_placement(self):
        broker = self._broker(10_000.0)
        order, plan = self._place(broker, "okx:A-USDT-SWAP")
        # İlk tick: fiyat limit seviyesinde, hacim yok → dolmaz
        broker.process_entry_tick("okx:A-USDT-SWAP", 99.98, 0.0, 1_000)
        assert broker.margin_lock_cancels == 0
        # Arada teminat tüketilir
        broker.portfolio.positions["okx:B-USDT-SWAP"] = _make_position(
            plan, margin=9_800.0,
        )
        broker.process_entry_tick("okx:A-USDT-SWAP", 99.0, 10.0, 2_000)
        assert broker.margin_lock_cancels == 1
        assert "okx:A-USDT-SWAP" not in broker.portfolio.positions


def _make_position(plan, margin: float | None = None):
    from core.portfolio import Position
    return Position(
        symbol="okx:B-USDT-SWAP", side=plan.side, entry=plan.entry,
        quantity=plan.quantity, initial_quantity=plan.quantity,
        margin=plan.margin if margin is None else margin,
        stop_loss=plan.stop_loss, opened_at_ms=0, entry_fee=0.0,
        leverage=plan.leverage, liquidation_price=plan.liquidation_price,
        take_profit=plan.take_profit, initial_net_risk=plan.net_risk_at_stop,
        motor="trend",
    )
