"""AI OmniStudio test paketi — ağ gerektirmez, deterministik.

Kapsam: fiyat indeksi eşdeğerliği, dedektör kapıları, risk/stop yolu,
PAPER muhasebesi, konsey fail-closed, LIVE kilidi, süreklilik, supervisor,
SQLite lease ve uçtan uca sanal yaşam döngüsü.
"""
from __future__ import annotations

import pathlib

import asyncio
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omnistudio.ai.council import AICouncil, CouncilConfig, QUANT_AUDITORS
from omnistudio.ai.adapters import CircuitBreaker, NotConfigured, ProviderAdapter, extract_json
from omnistudio.ai.registry import PROVIDERS, BY_ID, registry_status
from omnistudio.core.clock import ContinuityEngine, Stopwatch
from omnistudio.core.config import Config, ConfigError
from omnistudio.core.types import (Candle, Mode, Order, OrderState, Position,
                                   Quote, Side, Signal, Tick)
from omnistudio.execution.live_guard import LiveTradingBlocked, assert_mode_allowed
from omnistudio.execution.paper import PaperConfig, PaperExecutor
from omnistudio.risk.manager import RiskConfig, RiskManager
from omnistudio.state.store import StateStore, WriterLeaseError
from omnistudio.strategy import indicators
from omnistudio.strategy.detector import DetectorConfig, SpikeDetector
from omnistudio.strategy.policy import (EntryPolicy, PolicyConfig,
                                        closed_bar_key, total_cost_bps)
from omnistudio.strategy.price_history import (PriceHistory,
                                               linear_first_at_or_after)
from omnistudio.runtime.supervisor import TaskSupervisor


# ---------------------------------------------------------------- fixtures
def mk_candles(n=120, start=100.0, step=0.05, vol=1000.0, seed=1):
    rng = random.Random(seed)
    out = []
    px = start
    for i in range(n):
        o = px
        c = o + rng.uniform(-step, step)
        h = max(o, c) + step * 0.6
        l = min(o, c) - step * 0.6
        out.append(Candle("BTCUSDT", "test", 1_700_000_000_000 + i * 60_000,
                          o, h, l, c, vol, True))
        px = c
    return out


def mk_trend_candles(n=120, drift=0.02, noise=0.5, seed=1, end=100.0, vol=1000.0):
    """Gerçekçi hafif trend serisi — tüm politika kapılarını DOĞAL olarak geçer.

    Eşikler gevşetilmez; seri, kapıların geçebileceği gerçek bir piyasa
    durumunu temsil eder (choppiness ~58, ATR ~%0.63, uzama ~1.3 ATR).
    Son kapanış `end` değerine hizalanır, böylece sinyal fiyatı tutarlıdır.
    """
    rng = random.Random(seed)
    vals = []
    px = 0.0
    for _ in range(n):
        px += drift + rng.uniform(-noise, noise)
        vals.append(px)
    off = end - vals[-1]
    out = []
    for i, v in enumerate(vals):
        c = v + off
        o = (vals[i - 1] + off) if i else c - drift
        out.append(Candle("BTCUSDT", "test", 1_700_000_000_000 + i * 60_000,
                          o, max(o, c) + noise * 0.4, min(o, c) - noise * 0.4,
                          c, vol, True))
    return out


def mk_signal(**kw):
    base = dict(exchange="test", symbol="BTCUSDT", side=Side.LONG, price=100.0,
                ts_ms=1_700_000_000_000, ret_pct=0.8, rvol=3.0,
                volume_usd=50_000.0, window_ms=180_000, ctx_ret=0.6,
                ctx_vratio=1.5, ctx_vratio3=1.6, breadth_ratio=0.3,
                flow_score=10.0, signal_id="test:BTC:1")
    base.update(kw)
    return Signal(**base)


def mk_quote(bid=99.99, ask=100.01, symbol="BTCUSDT"):
    return Quote("test", symbol, bid, ask, 1_700_000_000_000)


# ============================================================ PriceHistory
class TestPriceHistory:
    def test_equivalence_random_sorted_and_unsorted(self):
        rng = random.Random(42)
        for trial in range(120):
            n = rng.randint(1, 400)
            ts = [rng.randint(0, 8000) for _ in range(n)]
            if trial % 2:
                ts.sort()
            rows = [(t, 50.0 + i * 0.1) for i, t in enumerate(ts)]
            ph = PriceHistory(maxlen=rng.choice([8, 32, 128, 1024]))
            for t, p in rows:
                ph.append(t, p)
            kept = rows[-ph._maxlen:]
            for _ in range(8):
                thr = rng.randint(-500, 8500)
                assert ph.first_at_or_after(thr) == linear_first_at_or_after(kept, thr)

    def test_empty(self):
        ph = PriceHistory(10)
        assert ph.first_at_or_after(0) is None
        assert ph.last is None
        assert len(ph) == 0
        assert not ph

    def test_eviction_keeps_semantics(self):
        ph = PriceHistory(maxlen=5)
        for i in range(50):
            ph.append(i * 10, 100.0 + i)
        assert len(ph) == 5
        assert ph.first_at_or_after(460) == (460, 146.0)
        assert ph.first_at_or_after(0) == (450, 145.0)
        assert ph.first_at_or_after(500) is None

    def test_unsorted_timestamp_fallback(self):
        ph = PriceHistory(64)
        rows = [(500, 1.0), (100, 2.0), (900, 3.0), (200, 4.0), (700, 5.0)]
        for t, p in rows:
            ph.append(t, p)
        for thr in (0, 100, 200, 450, 500, 700, 900, 1000):
            assert ph.first_at_or_after(thr) == linear_first_at_or_after(rows, thr)

    def test_nan_timestamp_invalidates_but_stays_correct(self):
        ph = PriceHistory(32)
        for i in range(10):
            ph.append(i, float(i))
        ph.append(float("nan"), 99.0)
        for i in range(10, 20):
            ph.append(i, float(i))
        rows = ph.items()
        assert not ph.stats()["index_valid"]
        for thr in (0, 5, 12, 19, 25):
            assert ph.first_at_or_after(thr) == linear_first_at_or_after(rows, thr)

    def test_clear_resets(self):
        ph = PriceHistory(16)
        for i in range(10):
            ph.append(i, float(i))
        ph.clear()
        assert len(ph) == 0
        assert ph.first_at_or_after(0) is None
        ph.append(5, 5.0)
        assert ph.first_at_or_after(3) == (5, 5.0)

    def test_invalid_maxlen(self):
        with pytest.raises(ValueError):
            PriceHistory(0)

    def test_rebuild_triggered_and_correct(self):
        ph = PriceHistory(maxlen=64)
        for i in range(5000):
            ph.append(i, float(i))
        assert ph.stats()["rebuilds"] > 0
        assert ph.first_at_or_after(4990) == (4990, 4990.0)

    def test_indexed_faster_than_linear(self):
        """Bileşen kıyası — tüm bot hızlanması İDDİASI DEĞİLDİR."""
        import time
        n = 4000
        rows = [(i, float(i)) for i in range(n)]
        ph = PriceHistory(maxlen=n)
        for t, p in rows:
            ph.append(t, p)
        thrs = [random.Random(1).randint(0, n) for _ in range(400)]
        t0 = time.perf_counter()
        for thr in thrs:
            linear_first_at_or_after(rows, thr)
        lin = time.perf_counter() - t0
        t0 = time.perf_counter()
        for thr in thrs:
            ph.first_at_or_after(thr)
        idx = time.perf_counter() - t0
        assert idx < lin  # yalnız doğru yönde hızlanma


class TestRollingVolumeSum:
    """Kayan pencere toplamı, tam taramayla birebir eşdeğer olmalı."""

    def test_equivalence_monotonic_and_unsorted(self):
        rng = random.Random(9)
        for trial in range(24):
            ph = PriceHistory(maxlen=rng.choice([16, 64, 512]))
            tot = 0.0
            lo = hi = 0
            t = 0
            for _ in range(150):
                t += rng.randint(0, 300) if trial % 3 else rng.randint(-50, 300)
                ph.append(t, rng.uniform(0, 100))
                cutoff = t - rng.randint(100, 5000)
                tot, lo, hi = SpikeDetector._roll_sum(ph, cutoff, tot, lo, hi)
                exact = sum(q for ts, q in ph if ts >= cutoff)
                assert tot == pytest.approx(exact, rel=1e-6, abs=1e-6)

    def test_shrinking_cutoff_recomputes(self):
        ph = PriceHistory(64)
        for i in range(40):
            ph.append(i * 100, 1.0)
        tot, lo, hi = SpikeDetector._roll_sum(ph, 3500, 0.0, 0, 0)
        assert tot == pytest.approx(5.0)
        # cutoff geriye gitti: imleç yeniden hizalanmalı
        tot, lo, hi = SpikeDetector._roll_sum(ph, 1000, tot, lo, hi)
        exact = sum(q for ts, q in ph if ts >= 1000)
        assert tot == pytest.approx(exact)

    def test_eviction_keeps_sum_correct(self):
        ph = PriceHistory(maxlen=8)
        tot = 0.0
        lo = hi = 0
        for i in range(200):
            ph.append(i * 10, 2.0)
            tot, lo, hi = SpikeDetector._roll_sum(ph, i * 10 - 30, tot, lo, hi)
            exact = sum(q for ts, q in ph if ts >= i * 10 - 30)
            assert tot == pytest.approx(exact)

    def test_volume_rate_matches_full_scan(self):
        """Dedektör hız/rvol değerleri tam taramayla aynı olmalı."""
        cfg = DetectorConfig(context_enabled=False, min_breadth_ratio=0)
        d = SpikeDetector(cfg)
        rng = random.Random(5)
        t0 = 1_700_000_000_000
        t = t0
        for _ in range(300):
            t += rng.randint(20, 400)
            d.feed_tick(Tick("test", "AAA", 100.0 + rng.uniform(-1, 1),
                             rng.uniform(0.1, 5.0), t))
        st = d.state("test", "AAA")
        exact_short = sum(q for ts, q in st.volumes if ts >= t - cfg.short_ms)
        exact_long = sum(q for ts, q in st.volumes if ts >= t - cfg.long_ms)
        assert st.speed_short == pytest.approx(exact_short / (cfg.short_ms / 1000.0), rel=1e-6)
        assert st.speed_long == pytest.approx(exact_long / (cfg.long_ms / 1000.0), rel=1e-6)

    def test_price_history_tracks_monotonicity(self):
        ph = PriceHistory(32)
        for i in range(5):
            ph.append(i, float(i))
        assert ph.monotonic
        ph.append(1, 9.0)
        assert not ph.monotonic
        assert ph.seq == 6
        ph.clear()
        assert ph.monotonic and ph.seq == 0


# ============================================================ indicators
class TestIndicators:
    def test_insufficient_data_returns_none(self):
        assert indicators.atr(mk_candles(5)) is None
        assert indicators.rsi([1.0] * 5) is None
        assert indicators.ema([1.0] * 3, 10) is None
        assert indicators.choppiness(mk_candles(5)) is None

    def test_rsi_monotonic_up_is_100(self):
        assert indicators.rsi([float(i) for i in range(40)], 14) == 100.0

    def test_rsi_monotonic_down_is_0(self):
        assert indicators.rsi([float(40 - i) for i in range(40)], 14) == 0.0

    def test_atr_positive(self):
        a = indicators.atr(mk_candles(120))
        assert a is not None and a > 0

    def test_choppiness_range(self):
        c = indicators.choppiness(mk_candles(120))
        assert c is not None and 0 <= c <= 100

    def test_ema_trend_direction(self):
        up = [100.0 + i for i in range(120)]
        down = [220.0 - i for i in range(120)]
        assert indicators.ema_trend(up) == 1
        assert indicators.ema_trend(down) == -1

    def test_snapshot_keys(self):
        s = indicators.snapshot(mk_candles(120))
        for k in ("atr", "atr_pct", "rsi", "choppiness", "ema_trend", "candles"):
            assert k in s


# ============================================================ detector
class TestDetector:
    def test_no_signal_during_warmup(self):
        d = SpikeDetector(DetectorConfig())
        for i in range(20):
            assert d.feed_tick(Tick("test", "BTCUSDT", 100.0 + i * 0.01,
                                    1.0, 1_700_000_000_000 + i * 100)) is None
        assert d.signals_emitted == 0

    def test_stale_volume_blocks_volumeless_ticks(self):
        """Hacim taşımayan tick'ler (REST quote fallback) hacmi tazelemez.

        Gerçek aggTrade tick'i hacim taşır ve akışı taze sayılır; bu doğru
        davranıştır. Bayat hacim kapısı, hacimsiz beslemede devreye girer.
        """
        cfg = DetectorConfig(context_enabled=False, min_breadth_ratio=0)
        d = SpikeDetector(cfg)
        t0 = 1_700_000_000_000
        d.feed_candle_volume("test", "BTCUSDT", 50_000, t0, 10_000_000)
        # qty=0 => quote=0 => hacim tazelenmez, fiyat ilerler
        for i in range(30):
            d.feed_tick(Tick("test", "BTCUSDT", 100.0, 0.0, t0 + i * 100))
        d.feed_tick(Tick("test", "BTCUSDT", 200.0, 0.0, t0 + 120_000))
        assert d.gates.get("stale_volume", 0) > 0

    def test_volume_bearing_tick_refreshes_freshness(self):
        """Hacim taşıyan gerçek tick hacim tazeliğini günceller."""
        d = SpikeDetector(DetectorConfig(context_enabled=False, min_breadth_ratio=0))
        t0 = 1_700_000_000_000
        d.feed_tick(Tick("test", "AAA", 100.0, 2.0, t0))
        st = d.state("test", "AAA")
        assert st.last_volume_ms == t0
        assert st.cvd == 200.0

    def test_breadth_independent_of_context(self):
        """v20 sistemsel hatası: bağlam kapalıyken genişlik ölçülmeli."""
        d = SpikeDetector(DetectorConfig(context_enabled=False))
        t0 = 1_700_000_000_000
        for sym_i in range(10):
            sym = f"S{sym_i}USDT"
            st = d.state("test", sym)
            st.prices.append(t0, 100.0)
            st.prices.append(t0 + 180_000, 100.0 + (2.0 if sym_i < 6 else 0.01))
        ratio = d.update_breadth(t0 + 180_000, force=True)
        assert d.breadth_total == 10
        assert ratio == pytest.approx(0.6)

    def test_breadth_empty_universe_is_zero(self):
        d = SpikeDetector()
        assert d.update_breadth(1_700_000_000_000, force=True) == 0.0

    def test_cooldown_blocks_second_signal(self):
        cfg = DetectorConfig(context_enabled=False, min_breadth_ratio=0,
                             ret_min_pct=0.1, rvol_min=0.1,
                             min_volume_usd=1, min_volume_24h_usd=0,
                             cooldown_ms=60_000)
        d = SpikeDetector(cfg)
        t0 = 1_700_000_000_000
        d.feed_candle_volume("test", "X", 1e6, t0, 1e9)
        st = d.state("test", "X")
        st.prices.append(t0, 100.0)
        st.speed_long = 1000.0
        st.speed_short = 5000.0
        st.rvol = 5.0
        st.ret_window = 1.0
        st.last_volume_ms = t0 + 180_000
        st.last_price_ms = t0 + 180_000
        st.vol_24h_usd = 1e9
        s1 = d._evaluate(st, t0 + 180_000)
        assert s1 is not None
        s2 = d._evaluate(st, t0 + 181_000)
        assert s2 is None
        assert d.gates.get("cooldown", 0) >= 1

    def test_signal_side_is_market_direction(self):
        """SÖZLEŞME: dedektör piyasa yönünü verir, fade çevirmez."""
        cfg = DetectorConfig(context_enabled=False, min_breadth_ratio=0,
                             ret_min_pct=0.1, rvol_min=0.1,
                             min_volume_usd=1, min_volume_24h_usd=0)
        d = SpikeDetector(cfg)
        t0 = 1_700_000_000_000
        st = d.state("test", "Y")
        st.prices.append(t0, 100.0)
        st.last_price = 102.0
        st.speed_long = 1000.0
        st.speed_short = 5000.0
        st.rvol = 5.0
        st.ret_window = -2.0
        st.last_volume_ms = t0
        st.last_price_ms = t0
        st.vol_24h_usd = 1e9
        sig = d._evaluate(st, t0)
        assert sig is not None and sig.side is Side.SHORT

    def test_flow_cvd_sign(self):
        d = SpikeDetector()
        st = d.state("test", "Z")
        st.add_flow(Tick("test", "Z", 100.0, 2.0, 1, is_buyer_maker=False))
        assert st.cvd == 200.0
        st.add_flow(Tick("test", "Z", 100.0, 1.0, 2, is_buyer_maker=True))
        assert st.cvd == 100.0
        assert st.flow_score == pytest.approx(100.0 / 3.0)


# ============================================================ policy
class TestPolicy:
    def test_fade_inverts_market_side(self):
        p = EntryPolicy(PolicyConfig(strategy="fade"))
        assert p.entry_side(mk_signal(side=Side.LONG)) is Side.SHORT
        assert p.entry_side(mk_signal(side=Side.SHORT)) is Side.LONG

    def test_momentum_keeps_side(self):
        p = EntryPolicy(PolicyConfig(strategy="momentum"))
        assert p.entry_side(mk_signal(side=Side.LONG)) is Side.LONG

    def test_one_attempt_per_closed_bar(self):
        p = EntryPolicy(PolicyConfig(max_spread_bps=0.0001))
        sig = mk_signal()
        ok1, g1, _ = p.evaluate(sig, mk_quote(), mk_candles())
        assert not ok1
        ok2, g2, _ = p.evaluate(sig, mk_quote(), mk_candles())
        assert not ok2
        assert g2[0].code == "ONE_ATTEMPT_PER_CLOSED_BAR"
        assert p.state.evaluation_repeats == 1

    def test_next_bar_reopens(self):
        p = EntryPolicy(PolicyConfig(max_spread_bps=0.0001))
        sig = mk_signal()
        p.evaluate(sig, mk_quote(), mk_candles())
        sig2 = mk_signal(ts_ms=sig.ts_ms + 60_000, signal_id="test:BTC:2")
        _, g2, _ = p.evaluate(sig2, mk_quote(), mk_candles())
        assert g2[0].code != "ONE_ATTEMPT_PER_CLOSED_BAR"

    def test_wide_spread_rejected(self):
        p = EntryPolicy(PolicyConfig(max_spread_bps=1.0))
        ok, gates, _ = p.evaluate(mk_signal(), mk_quote(99.0, 101.0), mk_candles())
        assert not ok
        assert any(g.code == "SPREAD_TOO_WIDE" for g in gates)

    def test_indicator_warmup_rejected(self):
        p = EntryPolicy()
        ok, gates, _ = p.evaluate(mk_signal(), mk_quote(), mk_candles(10))
        assert not ok
        assert any(g.code == "INDICATOR_WARMUP" for g in gates)

    def test_funding_blackout(self):
        p = EntryPolicy()
        ok, gates, _ = p.evaluate(mk_signal(), mk_quote(), mk_trend_candles(),
                                  funding={"rate": 0.0001, "minutes_to_funding": 1.0})
        assert not ok
        assert any(g.code == "FUNDING_BLACKOUT" for g in gates)

    def test_edge_below_cost_rejected(self):
        p = EntryPolicy(PolicyConfig(min_edge_ratio=100.0))
        ok, gates, _ = p.evaluate(mk_signal(), mk_quote(), mk_trend_candles())
        assert not ok
        assert any(g.code == "EDGE_BELOW_COST" for g in gates)

    def test_cost_arithmetic(self):
        cfg = PolicyConfig(roundtrip_fee_bps=7.0, slippage_bps_per_side=3.0)
        assert total_cost_bps(cfg, 1.5) == pytest.approx(14.5)

    def test_closed_bar_key_stable(self):
        base = (1_700_000_000_000 // 60_000) * 60_000  # mum başlangıcına hizala
        assert closed_bar_key("BTC", base) == closed_bar_key("BTC", base + 59_999)
        assert closed_bar_key("BTC", base) != closed_bar_key("BTC", base + 60_000)


# ============================================================ risk
class TestRisk:
    def test_plan_respects_notional_cap(self):
        rm = RiskManager(RiskConfig(max_position_notional=500.0))
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        assert plan is not None
        assert plan.notional <= 500.0 + 1e-6

    def test_long_stop_below_entry(self):
        rm = RiskManager()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        assert plan.stop_price < 100.0 < plan.take_profit_price

    def test_short_stop_above_entry(self):
        rm = RiskManager()
        plan = rm.plan(Side.SHORT, 100.0, 1.0)
        assert plan.stop_price > 100.0 > plan.take_profit_price

    def test_stop_pct_clamped(self):
        rm = RiskManager(RiskConfig(min_stop_pct=0.5, max_stop_pct=2.0))
        p = rm.plan(Side.LONG, 100.0, 0.001)
        assert abs(100.0 - p.stop_price) / 100.0 * 100 >= 0.5 - 1e-9
        p2 = rm.plan(Side.LONG, 100.0, 50.0)
        assert abs(100.0 - p2.stop_price) / 100.0 * 100 <= 2.0 + 1e-9

    def test_tiny_size_returns_none(self):
        rm = RiskManager(RiskConfig(min_position_notional=1e9))
        assert rm.plan(Side.LONG, 100.0, 1.0) is None

    def test_invalid_inputs(self):
        rm = RiskManager()
        assert rm.plan(Side.LONG, 0.0, 1.0) is None
        assert rm.plan(Side.LONG, 100.0, 0.0) is None

    def test_max_open_positions_gate(self):
        rm = RiskManager(RiskConfig(max_open_positions=1))
        p = Position("p1", "test", "AAA", Side.LONG, 1, 100, 0, 0.1, 99, 102)
        gates = rm.check_portfolio("BBB", Side.LONG, [p])
        assert any(g.name == "max_open" and not g.passed for g in gates)

    def test_symbol_already_open_gate(self):
        rm = RiskManager()
        p = Position("p1", "test", "AAA", Side.LONG, 1, 100, 0, 0.1, 99, 102)
        gates = rm.check_portfolio("AAA", Side.SHORT, [p])
        assert any(g.code == "SYMBOL_ALREADY_OPEN" and not g.passed for g in gates)

    def test_daily_loss_breaker(self):
        rm = RiskManager(RiskConfig(daily_loss_limit_pct=1.0))
        rm.state.equity = rm.cfg.equity_start * 0.98
        rm.update_breaker([], {})
        assert rm.state.breaker_tripped
        assert "zarar limiti" in rm.state.breaker_reason

    def test_consecutive_loss_breaker(self):
        rm = RiskManager(RiskConfig(max_consecutive_losses=3))
        for _ in range(3):
            rm.state.record_close(-1.0, 0.1)
        rm.update_breaker([], {})
        assert rm.state.breaker_tripped

    def test_stop_loss_exit(self):
        rm = RiskManager()
        p = Position("p", "test", "A", Side.LONG, 1, 100, 0, 0.1, 99.0, 103.0)
        assert rm.manage(p, 98.5, 1000) == "STOP_LOSS"

    def test_take_profit_exit(self):
        rm = RiskManager()
        p = Position("p", "test", "A", Side.LONG, 1, 100, 0, 0.1, 99.0, 103.0)
        assert rm.manage(p, 103.5, 1000) == "TAKE_PROFIT"

    def test_short_stop_loss(self):
        rm = RiskManager()
        p = Position("p", "test", "A", Side.SHORT, 1, 100, 0, 0.1, 101.0, 97.0)
        assert rm.manage(p, 101.5, 1000) == "STOP_LOSS"

    def test_breakeven_lock_moves_stop(self):
        rm = RiskManager(RiskConfig(breakeven_at_r=0.9))
        p = Position("p", "test", "A", Side.LONG, 1, 100, 0, 0.1, 99.0, 110.0,
                     peak_price=100.0)
        rm.manage(p, 101.0, 1000)
        assert p.stop_price >= 100.0
        assert p.trail_active

    def test_max_hold_time(self):
        rm = RiskManager(RiskConfig(max_hold_sec=10.0))
        p = Position("p", "test", "A", Side.LONG, 1, 100, 0, 0.1, 90.0, 200.0)
        assert rm.manage(p, 100.5, 20_000) == "MAX_HOLD_TIME"

    def test_mfe_mae_tracked(self):
        rm = RiskManager()
        p = Position("p", "test", "A", Side.LONG, 2, 100, 0, 0.1, 90.0, 200.0)
        rm.manage(p, 105.0, 1000)
        rm.manage(p, 95.0, 2000)
        assert p.mfe == 10.0
        assert p.mae == -10.0

    def test_fee_maker_cheaper(self):
        rm = RiskManager()
        assert rm.fee(1000, True) < rm.fee(1000, False)


# ============================================================ PAPER executor
class TestPaperExecutor:
    def _setup(self):
        rm = RiskManager(RiskConfig())
        ex = PaperExecutor(rm, PaperConfig(require_trade_through=True))
        ex.on_quote(mk_quote())
        return rm, ex

    def test_maker_requires_trade_through(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        o = ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        assert o is not None
        # tam limite dokunma yetmez
        ex.on_tick(Tick("test", "BTCUSDT", o.limit_price, 100.0, 1100))
        assert o.filled_qty == 0.0
        # seviyenin altından geçmeli
        ex.on_tick(Tick("test", "BTCUSDT", o.limit_price - 0.05, 100.0, 1200))
        assert o.filled_qty > 0

    def test_full_lifecycle_open_and_close(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        o = ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        for i in range(60):
            ex.on_tick(Tick("test", "BTCUSDT", 99.0, 1000.0, 1100 + i))
        assert o.state is OrderState.FILLED
        assert len(ex.open_positions) == 1
        p = ex.open_positions[0]
        ex.on_quote(Quote("test", "BTCUSDT", 105.0, 105.02, 5000))
        ex.close_position(p, "TEST_TP", 5000)
        assert len(ex.open_positions) == 0
        assert len(ex.closed) == 1
        assert ex.closed[0].realized_net is not None
        assert ex.closed[0].realized_net > 0
        assert rm.state.closed_trades == 1

    def test_stop_exit_loses_money(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        for i in range(60):
            ex.on_tick(Tick("test", "BTCUSDT", 99.0, 1000.0, 1100 + i))
        p = ex.open_positions[0]
        ex.on_quote(Quote("test", "BTCUSDT", 90.0, 90.02, 9000))
        closed = ex.manage_open(9000, {"BTCUSDT": 1.0})
        assert p.position_id in closed
        assert ex.closed[0].realized_net < 0
        assert ex.closed[0].exit_reason == "STOP_LOSS"

    def test_maker_timeout_expires(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        o = ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        ex.on_tick(Tick("test", "BTCUSDT", 150.0, 1.0, 60_000))
        assert o.state is OrderState.EXPIRED
        assert o.filled_qty == 0.0
        assert ex.stats["expired"] == 1

    def test_no_order_without_quote(self):
        rm = RiskManager()
        ex = PaperExecutor(rm)
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        assert ex.submit_entry("NOQUOTE", "test", Side.LONG, plan) is None
        assert ex.stats["rejected"] == 1

    def test_partial_fill_respects_tick_size(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        o = ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        ex.on_tick(Tick("test", "BTCUSDT", 99.0, 0.001, 1100))
        assert 0 < o.filled_qty <= 0.001 * 0.25 + 1e-12
        assert o.state is OrderState.PARTIAL

    def test_fees_recorded_both_sides(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        for i in range(60):
            ex.on_tick(Tick("test", "BTCUSDT", 99.0, 1000.0, 1100 + i))
        p = ex.open_positions[0]
        assert p.entry_fee > 0
        ex.close_position(p, "TEST", 9000)
        assert rm.state.fees_paid > 0
        assert ex.closed[0].exit_fee > 0

    def test_funding_applied_with_sign(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        for i in range(60):
            ex.on_tick(Tick("test", "BTCUSDT", 99.0, 1000.0, 1100 + i))
        cost = ex.apply_funding("BTCUSDT", 0.0001, 5000)
        assert cost > 0  # LONG pozitif funding öder
        assert ex.open_positions[0].funding_paid > 0

    def test_zero_real_orders_always(self):
        rm, ex = self._setup()
        assert ex.summary()["real_orders_sent_to_exchange"] == 0
        assert ex.summary()["mode"] == "PAPER"

    def test_equity_separates_unrealized(self):
        rm, ex = self._setup()
        plan = rm.plan(Side.LONG, 100.0, 1.0)
        ex.submit_entry("BTCUSDT", "test", Side.LONG, plan, ts_ms=1000)
        for i in range(60):
            ex.on_tick(Tick("test", "BTCUSDT", 99.0, 1000.0, 1100 + i))
        ex.marks["BTCUSDT"] = 200.0
        snap = ex.equity_snapshot()
        assert snap["unrealized"] > 0
        assert snap["realized_equity"] == pytest.approx(rm.cfg.equity_start)
        assert "GERÇEKLEŞMİŞ" in snap["note"]


# ============================================================ AI council
class TestCouncil:
    def test_twenty_providers_registered(self):
        assert len(PROVIDERS) == 20
        assert len(BY_ID) == 20
        assert registry_status()["total"] == 20

    def test_no_key_means_rule_mode(self, monkeypatch):
        for p in PROVIDERS:
            monkeypatch.delenv(p.env_key, raising=False)
        c = AICouncil(CouncilConfig())
        assert c.mode == "RULE_BASED_QUANT"
        assert c.live_specs == []

    def test_rule_mode_is_honestly_labeled(self, monkeypatch):
        for p in PROVIDERS:
            monkeypatch.delenv(p.env_key, raising=False)
        c = AICouncil(CouncilConfig())
        v = asyncio.run(c.evaluate(mk_signal(), {
            "entry_side": "LONG", "spread_bps": 1.0,
            "roundtrip_cost_bps": 14.0, "expected_move_bps": 60.0,
            "choppiness": 40.0, "mtf_aligned": True}))
        assert v.mode == "RULE_BASED_QUANT"
        assert v.ai_generated is False
        assert v.rounds == 3
        assert len(v.member_votes) == 20
        assert "YAPILMADI" in v.reason

    def test_twenty_quant_auditors(self):
        assert len(QUANT_AUDITORS) == 20
        assert len({a.auditor_id for a in QUANT_AUDITORS}) == 20

    def test_hard_cost_gate_cannot_be_bypassed(self, monkeypatch):
        for p in PROVIDERS:
            monkeypatch.delenv(p.env_key, raising=False)
        c = AICouncil(CouncilConfig())
        v = asyncio.run(c.evaluate(mk_signal(), {
            "roundtrip_cost_bps": 20.0, "expected_move_bps": 5.0}))
        assert not v.approved
        assert v.reject_code == "COUNCIL_EDGE_BELOW_COST"

    def test_wide_spread_veto(self, monkeypatch):
        for p in PROVIDERS:
            monkeypatch.delenv(p.env_key, raising=False)
        c = AICouncil(CouncilConfig(max_spread_bps=5.0))
        v = asyncio.run(c.evaluate(mk_signal(), {"spread_bps": 50.0}))
        assert not v.approved
        assert v.reject_code == "COUNCIL_SPREAD_TOO_WIDE"

    def test_contra_flow_lowers_score(self, monkeypatch):
        for p in PROVIDERS:
            monkeypatch.delenv(p.env_key, raising=False)
        c = AICouncil(CouncilConfig())
        base = {"entry_side": "LONG", "spread_bps": 1.0,
                "roundtrip_cost_bps": 14.0, "expected_move_bps": 60.0,
                "choppiness": 40.0, "mtf_aligned": True}
        # flow_score SİNYALDEN okunur (build_context sözleşmesi)
        good = asyncio.run(c.evaluate(mk_signal(flow_score=40.0), base))
        bad = asyncio.run(c.evaluate(mk_signal(flow_score=-60.0), base))
        assert bad.score < good.score

    def test_disabled_council_passes(self):
        c = AICouncil(CouncilConfig(enabled=False))
        v = asyncio.run(c.evaluate(mk_signal(), {}))
        assert v.mode == "DISABLED" and v.approved

    def test_unconfigured_adapter_raises_not_configured(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        ad = ProviderAdapter(BY_ID["openai"])
        with pytest.raises(NotConfigured):
            asyncio.run(ad.complete_json(None, "s", "u"))
        assert ad.stats.skipped_unconfigured == 1

    def test_key_marks_configured(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-real")
        assert BY_ID["deepseek"].configured
        c = AICouncil(CouncilConfig())
        assert c.mode == "LIVE_LLM"
        assert "deepseek" in [s.provider_id for s in c.live_specs]
        # Anahtar asla public_info'da görünmez
        assert "test-key-not-real" not in str(BY_ID["deepseek"].public_info())

    def test_quorum_failure_is_fail_closed(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        c = AICouncil(CouncilConfig(min_quorum_ratio=1.0))

        async def boom(*a, **k):
            from omnistudio.ai.adapters import ProviderError
            raise ProviderError("simulated network failure")
        for ad in c.adapters:
            ad.complete_json = boom
        v = asyncio.run(c._live_rounds(
            {"roundtrip_cost_bps": 14.0, "expected_move_bps": 60.0}, None))
        assert not v.approved
        assert v.reject_code == "COUNCIL_INSUFFICIENT_QUORUM"

    def test_json_extraction_robust(self):
        assert extract_json('{"a":1}') == {"a": 1}
        assert extract_json('```json\n{"a":2}\n```')["a"] == 2
        assert extract_json('önsöz {"a":3} sonsöz')["a"] == 3
        from omnistudio.ai.adapters import ProviderError
        for bad in ("", "no json here", "[1,2]", "{broken"):
            with pytest.raises(ProviderError):
                extract_json(bad)

    def test_circuit_breaker_opens_and_recovers(self):
        cb = CircuitBreaker(fail_threshold=2, cooldown_sec=0.05)
        cb.record_failure()
        assert not cb.is_open
        cb.record_failure()
        assert cb.is_open
        import time
        time.sleep(0.07)
        assert not cb.is_open


# ============================================================ safety / config
class TestSafety:
    def test_live_mode_blocked(self):
        with pytest.raises(LiveTradingBlocked):
            assert_mode_allowed(Mode.LIVE)

    def test_live_mode_string_blocked(self):
        with pytest.raises(LiveTradingBlocked):
            assert_mode_allowed("LIVE")

    def test_paper_and_observe_allowed(self):
        assert_mode_allowed(Mode.PAPER)
        assert_mode_allowed(Mode.OBSERVE)

    def test_config_rejects_live(self):
        with pytest.raises(LiveTradingBlocked):
            Config.load(overrides={"run": {"mode": "LIVE"}})

    def test_config_rejects_unknown_key(self):
        with pytest.raises(ConfigError):
            Config.load(overrides={"policy": {"nonexistent_setting": 1}})

    def test_config_rejects_edge_below_one(self):
        with pytest.raises(ConfigError):
            Config.load(overrides={"policy": {"min_edge_ratio": 0.5}})

    def test_config_rejects_bad_risk(self):
        with pytest.raises(ConfigError):
            Config.load(overrides={"risk": {"risk_per_trade_pct": 50}})

    def test_config_rejects_zero_duration(self):
        with pytest.raises(ConfigError):
            Config.load(overrides={"run": {"duration_sec": 0}})

    def test_default_config_is_paper(self):
        assert Config.load().run.mode is Mode.PAPER

    def test_no_secrets_in_config_dump(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
        assert "super-secret" not in str(Config.load().to_dict())


# ============================================================ continuity
class TestContinuity:
    def test_no_gap_on_regular_beats(self):
        ce = ContinuityEngine()
        ce.start()
        for _ in range(3):
            ce.beat(0.0)
        assert ce.is_continuous

    def test_detects_poll_gap(self):
        ce = ContinuityEngine(poll_delay_threshold_sec=0.05)
        ce.start()
        import time
        time.sleep(0.12)
        ev = ce.beat(0.0)
        assert ev is not None
        assert ev.kind == "RUN_DISCONTINUITY_DETECTED"
        assert ce.gap_count == 1
        assert not ce.is_continuous

    def test_summary_shape(self):
        ce = ContinuityEngine()
        ce.start()
        s = ce.summary()
        assert "gap_count" in s and "max_poll_delay_sec" in s

    def test_stopwatch_counts(self):
        sw = Stopwatch("x")
        for _ in range(3):
            with sw:
                pass
        assert sw.calls == 3
        assert sw.stats()["note"] == "inclusive_wall_time_not_cpu"


# ============================================================ supervisor
class TestSupervisor:
    def test_task_exception_halts_entries(self):
        async def scenario():
            sup = TaskSupervisor()

            async def bad():
                raise ValueError("boom")
            t = sup.spawn("bad", bad())
            await asyncio.sleep(0.05)
            assert sup.fatal.is_set()
            assert sup.entries_halted
            assert "bad" in sup.failures
            # İstisna supervisor tarafından kayda alındı; testi temiz kapat.
            with pytest.raises(ValueError):
                await t
        asyncio.run(scenario())

    def test_normal_return_is_also_failure(self):
        async def scenario():
            sup = TaskSupervisor()

            async def sneaky():
                return 1
            sup.spawn("sneaky", sneaky())
            await asyncio.sleep(0.05)
            assert sup.entries_halted
            assert "TASK_RETURNED_UNEXPECTEDLY" in sup.failures["sneaky"]
        asyncio.run(scenario())

    def test_heartbeat_stale_alarm(self):
        sup = TaskSupervisor()
        sup.register_heartbeat("hb", stale_after_sec=0.0)
        import time
        time.sleep(0.02)
        assert "hb" in sup.check_heartbeats()
        assert sup.alarms

    def test_heartbeat_fresh_no_alarm(self):
        sup = TaskSupervisor()
        sup.register_heartbeat("hb", 30.0)
        sup.beat("hb")
        assert sup.check_heartbeats() == []

    def test_stale_alarm_fires_once_per_episode(self):
        """Aynı bayatlık epizodu log'u boğmamalı; beat gelince sıfırlanır."""
        sup = TaskSupervisor()
        sup.register_heartbeat("hb", 0.0)
        import time
        time.sleep(0.02)
        sup.check_heartbeats()
        sup.check_heartbeats()
        sup.check_heartbeats()
        assert len(sup.alarms) == 1
        sup.beat("hb")
        sup.heartbeats["hb"].stale_after_sec = 0.0
        time.sleep(0.02)
        sup.check_heartbeats()
        assert len(sup.alarms) == 2

    def test_open_position_priority_uses_exchange_field(self):
        """Position.exchange kullanılır; .venue yoktur ve görevi öldürürdü."""
        import dataclasses
        from omnistudio.core.types import Position
        names = {f.name for f in dataclasses.fields(Position)}
        assert "exchange" in names and "venue" not in names
        src = pathlib.Path("omnistudio/runtime/engine.py").read_text()
        assert "p.venue" not in src, "quote önceliği olmayan alanı kullanıyor"
        assert 'getattr(p, "exchange", "")' in src

    def test_rate_limiter_throttles_and_recovers(self):
        """429 hızı düşürür, toparlanma taban hızı aşmaz."""
        from omnistudio.market.data import VenueRateLimiter
        lim = VenueRateLimiter(8.0)
        base = lim.rate
        lim.on_throttle(1.0)
        assert lim.rate < base and lim.throttles == 1
        for _ in range(1000):
            lim.on_success()
        assert lim.rate <= base

    def test_data_heartbeat_threshold_scales_with_refresh(self):
        """Mum yenileme aralığı büyürse eşik de büyümeli (yanlış alarm önleme)."""
        from omnistudio.core.config import Config
        cfg = Config.load(overrides={"run": {"candle_refresh_sec": 45}})
        derived = max(45.0, cfg.run.candle_refresh_sec * 2.0 + 30.0)
        assert derived > cfg.run.candle_refresh_sec + 10.0

    def test_no_signal_is_not_task_death(self):
        async def scenario():
            sup = TaskSupervisor()

            async def idle():
                while True:
                    sup.beat("idle")
                    await asyncio.sleep(0.01)
            sup.register_heartbeat("idle", 30.0)
            t = sup.spawn("idle", idle())
            await asyncio.sleep(0.05)
            assert not sup.fatal.is_set()
            t.cancel()
        asyncio.run(scenario())


# ============================================================ state store
class TestStateStore:
    def test_fresh_db_created(self, tmp_path):
        s = StateStore(tmp_path / "s.db", fresh=True)
        s.acquire_lease()
        s.write_event("TEST", a=1)
        s.commit()
        assert s.counts["events"] == 1
        s.close()

    def test_lease_conflict_detected(self, tmp_path):
        p = tmp_path / "l.db"
        a = StateStore(p, fresh=True)
        a.acquire_lease()
        b = StateStore(p, fresh=False)
        with pytest.raises(WriterLeaseError):
            b.acquire_lease()
        a.close()
        b.close()

    def test_lease_renew(self, tmp_path):
        s = StateStore(tmp_path / "r.db")
        s.acquire_lease()
        s.renew_lease()
        assert s.counts["lease_renewals"] == 1
        s.close()

    def test_lease_loss_raises(self, tmp_path):
        p = tmp_path / "x.db"
        a = StateStore(p, fresh=True)
        a.acquire_lease()
        a.conn.execute("UPDATE lease SET owner='someone-else' WHERE id=1")
        with pytest.raises(WriterLeaseError):
            a.renew_lease()
        a.close()

    def test_decision_roundtrip(self, tmp_path):
        from omnistudio.core.types import Decision, GateResult
        s = StateStore(tmp_path / "d.db")
        s.acquire_lease()
        d = Decision("d1", 1000, "test", "BTC", "BTC:0", accepted=False,
                     gates=[GateResult("spread", False, "SPREAD_TOO_WIDE")])
        s.write_decision(d)
        s.commit()
        assert s.reject_histogram().get("SPREAD_TOO_WIDE") == 1
        s.close()

    def test_pending_orders_persist(self, tmp_path):
        s = StateStore(tmp_path / "o.db")
        s.acquire_lease()
        o = Order("o1", "i1", "test", "BTC", Side.LONG, 1.0, 100.0, True,
                  OrderState.PENDING, 1000, 1000)
        s.write_order(o)
        s.commit()
        assert len(s.pending_orders()) == 1
        assert s.pending_orders()[0]["state"] == "PENDING"
        s.close()

    def test_fresh_wipes_old(self, tmp_path):
        p = tmp_path / "w.db"
        a = StateStore(p, fresh=True)
        a.acquire_lease()
        a.write_event("OLD")
        a.commit()
        a.close()
        b = StateStore(p, fresh=True)
        b.acquire_lease()
        assert b.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 0
        b.close()


# ============================================================ integration
class TestIntegration:
    def test_full_pipeline_produces_decision(self):
        """Uçtan uca: dedektör → politika → konsey → PAPER, ağ yok."""
        async def scenario():
            det = SpikeDetector(DetectorConfig(
                context_enabled=False, min_breadth_ratio=0, ret_min_pct=0.1,
                rvol_min=0.1, min_volume_usd=1, min_volume_24h_usd=0))
            pol = EntryPolicy(PolicyConfig(require_mtf=False, min_edge_ratio=1.0,
                                           max_spread_bps=50.0))
            rm = RiskManager()
            ex = PaperExecutor(rm)
            council = AICouncil(CouncilConfig(min_consensus_score=0.0))
            ex.on_quote(mk_quote())
            t0 = 1_700_000_000_000
            det.feed_candle_volume("test", "BTCUSDT", 1e6, t0, 1e9)
            st = det.state("test", "BTCUSDT")
            st.prices.append(t0, 100.0)
            st.last_price = 101.0
            st.speed_long, st.speed_short, st.rvol = 1000.0, 9000.0, 9.0
            st.ret_window = 1.0
            st.last_volume_ms = t0
            st.last_price_ms = t0
            st.vol_24h_usd = 1e9
            sig = det._evaluate(st, t0)
            assert sig is not None
            candles = mk_trend_candles(120)
            ok, gates, metrics = pol.evaluate(sig, mk_quote(), candles)
            v = await council.evaluate(sig, metrics)
            assert v.mode == "RULE_BASED_QUANT"
            if ok and v.approved:
                plan = rm.plan(Side(metrics["entry_side"]), sig.price, 0.5)
                if plan:
                    o = ex.submit_entry("BTCUSDT", "test",
                                        Side(metrics["entry_side"]), plan, ts_ms=t0)
                    assert o is not None
            assert ex.summary()["real_orders_sent_to_exchange"] == 0
        asyncio.run(scenario())

    def test_report_generation(self, tmp_path):
        from omnistudio.reporting.report import write_reports
        result = {
            "run_id": "test", "version": "1.0.0", "mode": "PAPER",
            "run_status": "COMPLETED",
            "timing": {"total_monotonic_sec": 100, "active_sec_estimated": 80,
                       "drain_sec": 20, "active_window_completed": True, "note": "n"},
            "counters": {"ticks": 10, "signals": 1, "accepted": 0, "rejected": 1},
            "execution": {"closed_trades": 0, "closed_net_total": 0,
                          "equity": {"unrealized": 0, "total_equity": 10000, "note": ""},
                          "risk": {}, "exit_reasons": {}, "mean_hold_sec": 0},
            "ai_council": {"mode": "RULE_BASED_QUANT", "members": 20,
                           "live_members": 0, "stats": {}, "honesty_note": "x"},
            "market_data": {"reachable": ["test"], "venues": {}},
            "continuity": {"gap_count": 0}, "supervision": {},
            "timers": {}, "honesty": {"profitability_claim": False},
        }
        out = write_reports(tmp_path, result)
        md = Path(out["markdown"]).read_text(encoding="utf-8")
        assert "AI OmniStudio" in md
        assert "Gerçek borsa emri gönderilmedi" in md
        assert "20 YZ konseyi" in md