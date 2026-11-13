import json
import tempfile
import unittest
from pathlib import Path

from sentez.data import (load_csv, parse_klines, save_csv, synthetic, validate_bars)
from sentez.models import Bar, Config, Trade
from sentez.risk import (CircuitBreaker, KellyTracker, edge_ratio, edge_ok, liq_distance_pct,
                         round_trip_cost_bps, size_position)


def trade(pnl, close_ts=0):
    return Trade("A", 1, 0, close_ts, 1, 1, 1, pnl, pnl, "STOP", 1, 0, 0, 1, {})


class TestSizing(unittest.TestCase):
    def test_basic_risk(self):
        cfg = Config(max_notional=1e9)
        q, r, why = size_position(1000, 100, 2.0, cfg)
        self.assertEqual(why, "")
        self.assertAlmostEqual(r, 5.0)
        self.assertAlmostEqual(q * 2.0, 5.0)

    def test_notional_cap_reduces_risk_never_increases(self):
        q, r, _ = size_position(1000, 100, 0.5, Config(max_notional=250))
        self.assertAlmostEqual(q * 100, 250)
        self.assertLess(r, 5.0)

    def test_below_min_notional(self):
        self.assertEqual(size_position(1000, 100, 1e6, Config())[2], "BELOW_MIN_NOTIONAL")

    def test_bad_inputs(self):
        for args in ((0, 100, 1), (1000, 0, 1), (1000, 100, 0)):
            self.assertEqual(size_position(*args, Config())[2], "BAD_INPUT")

    def test_edge_ratio_math(self):
        cfg = Config(taker_bps=5, slip_bps=2, spread_bps=2, tp_atr=2.0, min_edge_ratio=2.0)
        self.assertEqual(round_trip_cost_bps(cfg), 16.0)
        self.assertAlmostEqual(edge_ratio(100, 0.8, cfg), (2 * 0.8 / 100 * 1e4) / 16.0)
        self.assertTrue(edge_ok(100, 0.8, cfg))
        self.assertFalse(edge_ok(100, 0.1, cfg))
        self.assertTrue(edge_ok(100, 0.0001, Config(min_edge_ratio=0)))

    def test_liq_distance(self):
        self.assertAlmostEqual(liq_distance_pct(Config(leverage=5, mmr=0.005)), 19.5)


class TestKelly(unittest.TestCase):
    def test_needs_history(self):
        k = KellyTracker()
        for _ in range(5):
            k.add(1.0)
        self.assertIsNone(k.half_kelly(20))
        self.assertEqual(k.risk_pct(Config(risk_pct=0.5, kelly_min_trades=20)), 0.5)

    def test_positive_edge_scales_up_with_band(self):
        k = KellyTracker()
        for i in range(40):
            k.add(2.0 if i % 2 == 0 else -1.0)          # p=.5, b=2 → Kelly .25 → yarım .125
        cfg = Config(risk_pct=0.5, kelly_min_trades=20)
        self.assertAlmostEqual(k.risk_pct(cfg), 0.5 * 1.5)    # üst bant

    def test_negative_edge_scales_down_to_floor(self):
        k = KellyTracker()
        for i in range(40):
            k.add(1.0 if i % 4 == 0 else -1.0)
        self.assertAlmostEqual(k.risk_pct(Config(risk_pct=0.5, kelly_min_trades=20)), 0.5 * 0.25)


class TestBreaker(unittest.TestCase):
    def test_consecutive_losses_pause_and_resume(self):
        cfg = Config(max_consec_losses=3, loss_pause_bars=10, bar_ms=1000, daily_loss_pct=99)
        b = CircuitBreaker(cfg)
        for i in range(3):
            b.on_trade(trade(-1, close_ts=5000))
        self.assertEqual(b.allow(5001, 1000), (False, "LOSS_PAUSE"))
        self.assertTrue(b.allow(5000 + 10_000, 1000)[0])

    def test_win_resets_streak(self):
        b = CircuitBreaker(Config(max_consec_losses=2))
        b.on_trade(trade(-1)); b.on_trade(trade(+1)); b.on_trade(trade(-1))
        self.assertTrue(b.allow(0, 1000)[0])

    def test_daily_loss_blocks_until_next_utc_day(self):
        b = CircuitBreaker(Config(daily_loss_pct=2.0))
        day = 86_400_000
        self.assertTrue(b.allow(10, 1000)[0])
        self.assertEqual(b.allow(20, 979), (False, "DAILY_LOSS"))
        self.assertTrue(b.allow(day + 5, 979)[0])         # yeni günün tabanı 979

    def test_equity_halt_permanent(self):
        b = CircuitBreaker(Config(equity=1000, equity_halt_pct=50))
        self.assertEqual(b.allow(0, 499), (False, "EQUITY_HALT"))
        self.assertEqual(b.allow(10 * 86_400_000, 2000), (False, "EQUITY_HALT"))


class TestData(unittest.TestCase):
    def test_csv_roundtrip_and_iso(self):
        with tempfile.TemporaryDirectory() as d:
            bars = [Bar(1_700_000_000_000 + i * 60_000, 1, 2, 0.5, 1.5, 10) for i in range(3)]
            save_csv(Path(d) / "x.csv", bars)
            self.assertEqual(load_csv(Path(d) / "x.csv"), bars)
            (Path(d) / "iso.csv").write_text("timestamp,open,high,low,close,volume\n"
                                             "2024-01-01T00:00:00Z,1,2,0.5,1.5,10\nBOZUK,satır\n")
            got = load_csv(Path(d) / "iso.csv")
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0].ts, 1_704_067_200_000)

    def test_validate_drops_bad_dups_sorts_counts_gaps(self):
        good = lambda t: Bar(t, 10, 11, 9, 10, 1)
        bars = [good(120_000), good(0), good(0), Bar(60_000, 10, 9, 11, 10, 1),
                Bar(180_000, float("nan"), 1, 1, 1, 1), good(600_000)]
        clean, issues = validate_bars(bars, 60_000)
        self.assertEqual([b.ts for b in clean], [0, 120_000, 600_000])
        self.assertEqual(issues, {"bad": 2, "dup": 1, "gaps": 2})

    def test_parse_klines_skips_bad_rows(self):
        rows = [[1, "1", "2", "0.5", "1.5", "10"], ["x"], [2, "a", 1, 1, 1, 1]]
        self.assertEqual(len(parse_klines(rows)), 1)
        self.assertEqual(parse_klines(None), [])

    def test_synthetic_deterministic_and_valid(self):
        a, b = synthetic(n_bars=300, n_symbols=2, seed=5), synthetic(n_bars=300, n_symbols=2, seed=5)
        self.assertEqual(a, b)
        self.assertNotEqual(a["SYN1USDT"], synthetic(n_bars=300, n_symbols=2, seed=6)["SYN1USDT"])
        for bars in a.values():
            clean, issues = validate_bars(bars, 900_000)
            self.assertEqual(len(clean), 300)
            self.assertEqual(issues, {"bad": 0, "dup": 0, "gaps": 0})


class TestConfig(unittest.TestCase):
    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            Config.from_dict({"nope": 1})

    def test_invalid_values_rejected(self):
        for bad in ({"risk_pct": 0}, {"risk_pct": 50}, {"equity": -1}, {"stop_atr": 0}, {"leverage": 0.5}):
            with self.assertRaises(ValueError):
                Config.from_dict(bad)

    def test_roundtrip(self):
        c = Config(conf_th=5)
        self.assertEqual(Config.from_dict(c.to_dict()), c)


if __name__ == "__main__":
    unittest.main()
