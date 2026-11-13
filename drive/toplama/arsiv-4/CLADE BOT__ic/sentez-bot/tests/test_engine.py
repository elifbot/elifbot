import unittest

from sentez.engine import Engine, FUNDING_MS
from sentez.models import Bar, Config
from tests.helpers import FakeSource, bar, flat, long_sig, zero_cost_cfg, H


def run(cfg, source, bars_by_sym, finish=True):
    eng = Engine(cfg, source)
    stamps = sorted({b.ts for bs in bars_by_sym.values() for b in bs})
    for t in stamps:
        eng.step(t, {s: b for s, bs in bars_by_sym.items() for b in bs if b.ts == t})
    if finish:
        last = {s: bs[-1] for s, bs in bars_by_sym.items()}
        eng.finish(last, stamps[-1])
    return eng


def one(sym="A", sig_ts=0):
    return FakeSource({(sym, sig_ts): long_sig(ts=sig_ts)})


class TestFills(unittest.TestCase):
    def test_entry_at_next_open_not_signal_close(self):
        bars = [flat(0), bar(1, 100.3, 100.6, 100.0, 100.3), flat(2, 100.3)]
        e = run(zero_cost_cfg(), one(), {"A": bars})
        self.assertAlmostEqual(e.trades[0].entry, 100.3)

    def test_price_drift_rejected(self):
        bars = [flat(0), bar(1, 101.0, 101.2, 100.8, 101.0)]
        e = run(zero_cost_cfg(), one(), {"A": bars})
        self.assertEqual(e.stats["REJECT_PRICE_DRIFT"], 1)
        self.assertEqual(len(e.trades), 0)

    def test_stop_wins_when_both_hit_same_bar(self):
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 103.0, 98.0, 100)]
        e = run(zero_cost_cfg(), one(), {"A": bars})
        t = e.trades[0]
        self.assertEqual(t.reason, "STOP")
        self.assertAlmostEqual(t.exit, 98.8)
        self.assertAlmostEqual(t.r_mult, -1.0, places=6)

    def test_gap_through_stop_fills_at_open(self):
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 97.0, 97.5, 96.5, 97.0)]
        e = run(zero_cost_cfg(), one(), {"A": bars})
        self.assertAlmostEqual(e.trades[0].exit, 97.0)
        self.assertAlmostEqual(e.trades[0].r_mult, -2.5, places=6)

    def test_target_is_two_r(self):
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 102.5, 99.9, 102)]
        e = run(zero_cost_cfg(), one(), {"A": bars})
        self.assertEqual(e.trades[0].reason, "TARGET")
        self.assertAlmostEqual(e.trades[0].r_mult, 2.0, places=6)

    def test_short_mirrors_long(self):
        src = FakeSource({("A", 0): long_sig(ts=0, side=-1)})
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 100.1, 97.0, 98)]
        e = run(zero_cost_cfg(), src, {"A": bars})
        self.assertEqual(e.trades[0].reason, "TARGET")
        self.assertAlmostEqual(e.trades[0].r_mult, 2.0, places=6)

    def test_breakeven_then_stopped_flat(self):
        bars = [flat(0), bar(1, 100, 101.0, 99.5, 100.5), bar(2, 100.2, 100.4, 99.9, 100.0)]
        e = run(zero_cost_cfg(), one(), {"A": bars})
        t = e.trades[0]
        self.assertEqual(t.reason, "BREAKEVEN")
        self.assertAlmostEqual(t.r_mult, 0.0, places=6)

    def test_breakeven_not_used_on_same_bar(self):
        # giriş mumu 0.8R'yi aşıyor ama dibi 99.9: stop aynı mumda taşınsaydı (100) pozisyon
        # o mumda kapanırdı. Doğru davranış: mum kapandıktan SONRA taşınır, pozisyon yaşar.
        bars = [flat(0), bar(1, 100, 101.0, 99.9, 100.5)]
        e = run(zero_cost_cfg(), one(), {"A": bars}, finish=False)
        self.assertEqual(len(e.trades), 0)
        p = e.positions["A"]
        self.assertEqual(p.stop_kind, "BREAKEVEN")
        self.assertAlmostEqual(p.stop, p.entry)

    def test_time_exit(self):
        bars = [flat(0)] + [flat(i) for i in range(1, 8)]
        e = run(zero_cost_cfg(max_hold_bars=3), one(), {"A": bars})
        self.assertEqual(e.trades[0].reason, "TIME")
        self.assertEqual(e.trades[0].bars, 3)

    def test_costs_reduce_pnl_exactly(self):
        cfg = zero_cost_cfg(taker_bps=5.0)
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 102.5, 99.9, 102)]
        e = run(cfg, one(), {"A": bars})
        t = e.trades[0]
        gross = (t.exit - t.entry) * t.qty
        fees = (t.entry * t.qty + t.exit * t.qty) * 5 / 10_000
        self.assertAlmostEqual(t.pnl, gross - fees, places=9)
        self.assertAlmostEqual(t.fees, fees, places=9)

    def test_slippage_hurts_both_sides(self):
        cfg = zero_cost_cfg(slip_bps=10.0)
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 98.0, 97.0, 97.5)]
        e = run(cfg, one(), {"A": bars})
        t = e.trades[0]
        self.assertGreater(t.entry, 100.0)           # long daha pahalıya girer
        self.assertLess(t.exit, t.entry - 1.2)       # ve stop seviyesinden daha ucuza çıkar

    def test_risk_sizing_one_r_equals_risk_pct(self):
        cfg = zero_cost_cfg(risk_pct=0.5)
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 100.1, 98.0, 99.0)]
        e = run(cfg, one(), {"A": bars})
        self.assertAlmostEqual(e.trades[0].pnl, -5.0, places=6)    # 1000 × %0.5

    def test_max_notional_clips_risk_down(self):
        cfg = zero_cost_cfg(max_notional=100.0)
        bars = [flat(0), bar(1, 100, 100.2, 99.9, 100), bar(2, 100, 100.1, 98.0, 99.0)]
        e = run(cfg, one(), {"A": bars})
        self.assertAlmostEqual(e.trades[0].qty * e.trades[0].entry, 100.0, places=6)
        self.assertGreater(e.trades[0].pnl, -5.0)                  # risk artmaz, azalır


class TestFunding(unittest.TestCase):
    def _run(self, side):
        step = H
        src = FakeSource({("A", 6 * step): long_sig(ts=6 * step, side=side)})
        bars = [Bar(k * step, 100, 100.3, 99.7, 100, 10) for k in range(6, 12)]
        cfg = zero_cost_cfg(funding_bps_8h=10.0, bar_ms=step, max_hold_bars=4)
        return run(cfg, src, {"A": bars}).trades[0]

    def test_long_pays_short_receives(self):
        self.assertLess(self._run(1).funding, 0)
        self.assertGreater(self._run(-1).funding, 0)


class TestGates(unittest.TestCase):
    def test_cooldown_blocks_reentry(self):
        cfg = zero_cost_cfg(cooldown_bars=5, max_hold_bars=2)
        bars = [flat(i) for i in range(30)]
        e = run(cfg, FakeSource(always=long_sig()), {"A": bars})
        self.assertGreater(e.stats["SKIP_COOLDOWN"], 0)
        opens = [t.open_ts for t in e.trades]
        for a, b in zip(e.trades, e.trades[1:]):
            self.assertGreaterEqual(b.open_ts - a.close_ts, 5 * 60_000)

    def test_max_positions_prefers_higher_score(self):
        syms = {s: [flat(0), flat(1), flat(2), flat(3)] for s in "ABC"}
        src = FakeSource({("A", 0): long_sig(score=4), ("B", 0): long_sig(score=7), ("C", 0): long_sig(score=5)})
        e = run(zero_cost_cfg(max_positions=2), src, syms, finish=False)
        self.assertEqual(sorted(e.positions), ["B", "C"])
        self.assertEqual(e.stats["REJECT_MAX_POSITIONS"], 1)

    def test_max_same_side(self):
        syms = {s: [flat(0), flat(1), flat(2)] for s in "ABCD"}
        src = FakeSource({(s, 0): long_sig(score=5) for s in "ABCD"})
        e = run(zero_cost_cfg(max_positions=10, max_same_side=2), src, syms, finish=False)
        self.assertEqual(len(e.positions), 2)

    def test_max_gross(self):
        syms = {s: [flat(0), flat(1), flat(2)] for s in "ABC"}
        src = FakeSource({(s, 0): long_sig(score=5) for s in "ABC"})
        cfg = zero_cost_cfg(max_positions=10, max_same_side=10, max_notional=500.0, max_gross_pct=60.0)
        e = run(cfg, src, syms, finish=False)
        self.assertLessEqual(e.gross(), 600.0 + 1e-6)
        self.assertGreater(e.stats["REJECT_MAX_GROSS"], 0)

    def test_edge_gate_blocks_cheap_moves(self):
        cfg = zero_cost_cfg(taker_bps=5, slip_bps=2, spread_bps=2, min_edge_ratio=2.0)
        tiny = long_sig(atr=0.01)                   # 1 bps ATR → hedef maliyetin çok altında
        e = run(cfg, FakeSource({("A", 0): tiny}), {"A": [flat(0), flat(1), flat(2)]})
        self.assertEqual(e.stats["REJECT_EDGE_BELOW_COST"], 1)

    def test_breadth_guard_blocks_longs_in_weak_market(self):
        cfg = zero_cost_cfg(breadth_guard=0.35)
        e = run(cfg, FakeSource({("A", 0): long_sig()}, breadth=-0.6), {"A": [flat(0), flat(1), flat(2)]})
        self.assertEqual(e.stats["REJECT_BREADTH"], 1)
        e = run(cfg, FakeSource({("A", 0): long_sig(side=-1)}, breadth=-0.6), {"A": [flat(0), flat(1), flat(2)]})
        self.assertEqual(e.stats["REJECT_BREADTH"], 0)

    def test_consecutive_losses_pause_then_resume(self):
        cfg = zero_cost_cfg(max_consec_losses=2, loss_pause_bars=10, daily_loss_pct=50.0)
        bars = []
        for i in range(0, 60, 3):                  # her 3 mumda: giriş mumu, stop mumu, boş
            bars += [flat(i), bar(i + 1, 100, 100.2, 99.9, 100), bar(i + 2, 100, 100.1, 98.0, 99)]
        e = run(cfg, FakeSource(always=long_sig()), {"A": bars})
        self.assertGreater(e.stats["REJECT_LOSS_PAUSE"], 0)
        self.assertGreaterEqual(e.breaker.trips.get("CONSEC_LOSSES", 0), 1)

    def test_equity_halt_is_permanent(self):
        cfg = zero_cost_cfg(equity_halt_pct=1.0, max_consec_losses=99, daily_loss_pct=99.0)
        bars = []
        for i in range(0, 60, 3):
            bars += [flat(i), bar(i + 1, 100, 100.2, 99.9, 100), bar(i + 2, 100, 100.1, 98.0, 99)]
        e = run(cfg, FakeSource(always=long_sig()), {"A": bars})
        self.assertEqual(e.breaker.halted, "EQUITY_HALT")
        n = len(e.trades)
        self.assertLessEqual(n, 4)                  # %1 = 10$ ⇒ en fazla birkaç 5$'lık kayıp

    def test_liq_too_close_blocks_high_leverage(self):
        e = run(zero_cost_cfg(leverage=20.0), one(), {"A": [flat(0), flat(1), flat(2)]})
        self.assertEqual(e.stats["REJECT_LIQ_TOO_CLOSE"], 1)


if __name__ == "__main__":
    unittest.main()
