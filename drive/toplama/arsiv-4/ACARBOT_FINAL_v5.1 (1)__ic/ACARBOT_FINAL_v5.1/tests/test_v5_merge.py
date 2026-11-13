"""FINAL v5.0 — BİRLEŞİM regresyonları.

v5.0 = v4.0'ın sinyal/analiz katmanı (uzmanlar, rejim, MTF, orderflow, DCA,
montecarlo, analist ajanı) + v1.10'un canlıda doğrulanmış risk/infüzyon
düzeltmeleri (RVOL likidite tabanı, 25 USDT hedef net risk, dinamik teminat,
stop fiyat ızgarası, dolum anı teminat kilidi).

Bu dosya iki kümenin KESİŞİMİNİ test eder: v4.0 özellikleri port edilen
düzeltmelerle birlikte çalışırken bozuluyor mu?
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.executor import Executor
from core.config import SuperConfig
from core.risk import RiskManager
from exec.paper import PaperBroker
from core.spike import SpikeDetector
from tests.helpers import apex_config
from tests.test_rvol_liquidity import _feed

BTTC_ENTRY = 3.5007e-07
BTTC_TICK = 1e-08


def _executor(balance: float = 10_000.0, config: SuperConfig | None = None) -> Executor:
    cfg = config or apex_config()
    broker = PaperBroker(cfg, balance)
    risk = RiskManager(cfg)
    broker.risk_manager_ref = risk
    return Executor(broker, risk, cfg)


class TestGridAlignmentKeepsV4Meta:
    """Izgara hizalama v4.0'ın skor/rejim/uzman meta'sını düşürmemeli."""

    def test_meta_survives_grid_realign(self):
        ex = _executor()
        sym = "binance:BTTCUSDT"
        ex.tick_sizes[sym] = BTTC_TICK
        ex.broker.tick_sizes = ex.tick_sizes
        plan = ex.risk.plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order, plan, "trend", meta={
            "score": 7.5, "regime": "trend_down", "experts": "mtf,orderflow",
        })
        assert ex.broker.grid_realign_count == 1
        assert ex.broker._meta_for_order[order.id]["experts"] == "mtf,orderflow"
        assert ex.broker._meta_for_order[order.id]["regime"] == "trend_down"
        ex.broker.process_entry_tick(sym, BTTC_ENTRY * 1.002, 1e12, 1_000)
        pos = ex.broker.portfolio.positions[sym]
        assert pos.score == pytest.approx(7.5)
        assert pos.regime == "trend_down"

    def test_aligned_entry_equals_fill_price(self):
        """Plan girişi = limit fiyatı olmalı; dolumda yeniden ölçekleme yok."""
        ex = _executor()
        sym = "binance:BTTCUSDT"
        ex.broker.tick_sizes[sym] = BTTC_TICK
        plan = ex.risk.plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order, plan, "trend")
        aligned = ex.broker._plan_for_order[order.id]
        assert aligned.entry == pytest.approx(order.limit_price)
        steps = aligned.stop_loss / BTTC_TICK
        assert steps == pytest.approx(round(steps), abs=1e-6)

    def test_grid_realign_reported_in_order_new(self):
        ex = _executor()
        sym = "binance:BTTCUSDT"
        ex.broker.tick_sizes[sym] = BTTC_TICK
        plan = ex.risk.plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order, plan, "trend")
        rec = [t for t in ex.broker.trades if t.get("type") == "ORDER_NEW"][-1]
        assert rec["grid_aligned"] is True
        assert rec["net_risk"] == pytest.approx(25.0, abs=1e-6)
        assert rec["notional"] > 0


class TestTargetRiskEndToEndV5:
    def test_bttc_short_stop_lands_on_target(self):
        ex = _executor()
        sym = "binance:BTTCUSDT"
        ex.broker.tick_sizes[sym] = BTTC_TICK
        plan = ex.risk.plan(BTTC_ENTRY, 0.025, "SHORT", tick_size=BTTC_TICK)
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order, plan, "trend")
        ex.broker.process_entry_tick(sym, BTTC_ENTRY * 1.002, 1e12, 1_000)
        assert sym in ex.broker.portfolio.positions
        events = ex.broker.manage_position_tick(sym, 3.6e-07, 2_000)
        closes = [e for e in events if e.get("type") == "CLOSE"]
        assert closes, "stop tetiklenmedi"
        assert -26.5 <= closes[0]["pnl"] <= -23.0

    def test_open_event_reports_dynamic_margin_and_notional(self):
        ex = _executor()
        sym = "okx:BTC-USDT-SWAP"
        plan = ex.risk.plan(50_000.0, 0.004, "LONG")
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order, plan, "trend")
        ex.broker.process_entry_tick(sym, 49_980.0, 1e12, 1_000)
        rec = [t for t in ex.broker.trades if t.get("type") == "OPEN"][-1]
        assert rec["notional"] == pytest.approx(rec["margin"] * 10.0, rel=1e-9)
        assert rec["net_risk"] == pytest.approx(25.0, abs=1e-3)
        # nominal tavan kapalı: 0.4% stop → ~4464 USDT nominal (500 değil)
        assert rec["notional"] > 500.0

    def test_partial_fill_scales_net_risk_down(self):
        """v3.0 kısmi dolumu: net risk dolan orana göre ölçeklenmeli."""
        ex = _executor()
        sym = "okx:ETH-USDT-SWAP"
        plan = ex.risk.plan(3_000.0, 0.005, "LONG")
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order, plan, "trend")
        aligned = ex.broker._plan_for_order[order.id]
        order.apply_fill(aligned.entry, aligned.quantity * 0.25, 1_000, is_maker=True)
        ex.broker._open_position_from_order(sym, order, 1_100)
        rec = [t for t in ex.broker.trades if t.get("type") == "OPEN"][-1]
        assert rec["partial"] is True
        assert rec["net_risk"] < 25.0


class TestMarginLockWithV4Portfolio:
    def test_second_order_blocked_when_first_consumes_margin(self):
        ex = _executor(balance=700.0)
        a, b = "okx:A-USDT-SWAP", "okx:B-USDT-SWAP"
        # A önce planlanır ve DOLAR (teminatı bağlar)
        plan_a = ex.risk.plan(100.0, 0.004, "LONG")
        order_a = ex.broker.place_entry(a, plan_a, now_ms=0, baseline_per_second=1e12)
        ex.broker.bind_plan(order_a, plan_a, "trend")
        ex.broker.process_entry_tick(a, 99.0, 1e12, 1_000)
        assert a in ex.broker.portfolio.positions
        # B sonra planlanır: planlama anında serbest teminat yetmiyor gibi
        # görünse de emir TTL boyunca bekler; dolum anında kilit devreye girer
        plan_b = ex.risk.plan(100.0, 0.004, "LONG")
        order_b = ex.broker.place_entry(b, plan_b, now_ms=1_500, baseline_per_second=1e12)
        ex.broker.bind_plan(order_b, plan_b, "trend")
        ex.broker.process_entry_tick(b, 99.0, 1e12, 2_000)
        assert b not in ex.broker.portfolio.positions
        assert ex.broker.margin_lock_cancels == 1
        assert any(
            t.get("reason") == "TEMINAT_KILIDI" for t in ex.broker.trades
        )

    def test_reserved_margin_counts_pending_v4_orders(self):
        ex = _executor(balance=10_000.0)
        plan = ex.risk.plan(100.0, 0.004, "LONG")
        order = ex.broker.place_entry(
            "okx:A-USDT-SWAP", plan, now_ms=0, baseline_per_second=1e12,
        )
        ex.broker.bind_plan(order, plan, "trend")
        assert ex.broker.reserved_margin() > 0
        assert ex.broker.free_margin() < 10_000.0


class TestVolumeFilterV5:
    def _detector(self):
        return SpikeDetector(
            multiplier=3.0, lookback_seconds=60, window_seconds=3,
            sanity_cap=100.0, min_baseline_notional_per_second=5.0,
        )

    def test_illiquid_and_suspect_are_distinct(self):
        det = self._detector()
        hot = _feed(det, "okx:LIQ-USDT-SWAP", 100.0, 1.0, 63, burst=1000.0)
        assert hot is not None and hot.suspect and not hot.illiquid
        cold = _feed(det, "binance:DEADUSDT", 100.0, 0.001, 63, burst=10.0)
        assert cold is not None and cold.illiquid and not cold.suspect

    def test_log_throttle_counts_suppressed(self):
        ex = _executor()
        det = self._detector()
        spike = _feed(det, "binance:DEADUSDT", 100.0, 0.001, 63, burst=10.0)
        assert spike is not None
        for k in range(5):
            ex._log_volume_filter("binance:DEADUSDT", spike, 10_000 + k * 1_000)
        assert ex.low_liquidity_count == 5
        assert ex._volume_log_suppressed["binance:DEADUSDT"] == 4

    def test_fill_simulation_fed_without_spike(self):
        """Sakin ama LİKİT piyasada spike=None olur; maker emir yine dolmalı.

        Eski kod `tick_volume = base_delta if spike is not None else 0.0`
        diyordu: hacim patlaması olmayan normal piyasada dolum simülasyonu
        sıfır hacim görüyor ve emirler TTL sonunda iptal oluyordu.
        """
        ex = _executor(balance=10_000.0)
        sym = "binance:DEADUSDT"
        plan = ex.risk.plan(100.0, 0.004, "LONG")
        order = ex.broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1_000.0)
        ex.broker.bind_plan(order, plan, "trend")
        # Sabit/likit hacim: RVOL≈1 → spike None; eski kod tick_volume=0 verirdi
        for i in range(12):
            ex.process_price_update(
                sym, 99.97, 1_000 + i * 1_000,
                base_volume_24h=1_000.0 * (i + 1),  # kümülatif, sabit/likit
                exchange="binance",
            )
        assert sym in ex.broker.portfolio.positions, "maker emir aç kaldı"


class TestApexProfileV5:
    def test_apex_keeps_25_risk_but_disables_caps(self):
        cfg = apex_config()
        assert cfg.account.max_loss_per_position == pytest.approx(25.0)
        assert cfg.account.max_notional_per_position == 0.0
        assert cfg.account.margin_per_position == 0.0
        assert cfg.portfolio.daily_soft_loss <= 0

    def test_invalid_risk_config_fails_closed(self):
        cfg = apex_config()
        for bad in (
            replace(cfg.account, max_loss_per_position=0.0),
            replace(cfg.account, max_notional_per_position=-5.0),
            replace(cfg.account, leverage=0.0),
            replace(cfg.account, margin_per_position=-1.0),
        ):
            with pytest.raises(ValueError):
                RiskManager(replace(cfg, account=bad))

    def test_coarse_grid_beyond_widen_cap_is_rejected(self):
        cfg = apex_config()
        risk = RiskManager(cfg)
        # tick fiyatın %40'ı: 1.5x genişleme tavanını aşar → işlem YOK
        with pytest.raises(ValueError):
            risk.plan(1.0, 0.004, "LONG", tick_size=0.4)


class TestSessionReportV5:
    def test_report_contains_v5_audit_blocks(self, tmp_path):

        from app.main import write_session_report

        class _Reporter:
            def daily_report(self, **kwargs):
                return "ok"

        class _Metrics:
            counters: dict = {}

            def as_dict(self):
                return {}

            def inc(self, *a, **k):
                pass

        ex = _executor()
        from app.main import build_parser

        args = build_parser().parse_args([
            "--mode", "paper", "--paper", "--report-file", str(tmp_path / "r.json"),
        ])
        report = write_session_report(
            args, ex, _Reporter(), _Metrics(), 0, 10_000.0,
        )
        assert "volume_filter" in report
        assert "target_risk_audit" in report
        assert report["target_risk_audit"]["target_net_risk"] == pytest.approx(25.0)
        assert report["target_risk_audit"]["max_notional_cap"] == 0.0
        assert report["volume_filter"]["min_baseline_notional_per_second"] == 5.0
