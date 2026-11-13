import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from sentez.backtest import run_backtest, walk_forward
from sentez.cli import main
from sentez.data import synthetic
from sentez.live import run_live
from sentez.models import Config
from sentez.report import attribution, max_drawdown_pct, metrics, render_markdown
from sentez.signals import VOTE_NAMES


class TestBacktest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = synthetic(n_bars=1500, n_symbols=4, seed=7)

    def test_deterministic(self):
        a = run_backtest(self.data, Config())
        b = run_backtest(self.data, Config())
        self.assertEqual([(t.sym, t.open_ts, t.pnl) for t in a.trades],
                         [(t.sym, t.open_ts, t.pnl) for t in b.trades])

    def test_accounting_identity(self):
        cfg = Config()
        r = run_backtest(self.data, cfg)
        self.assertAlmostEqual(r.equity_curve[-1][1], cfg.equity + sum(t.pnl for t in r.trades), places=6)

    def test_no_open_positions_left_and_times_ordered(self):
        r = run_backtest(self.data, Config())
        for t in r.trades:
            self.assertLessEqual(t.open_ts, t.close_ts)
            self.assertGreater(t.qty, 0)
            self.assertLessEqual(t.qty * t.entry, Config().max_notional + 1e-6)

    def test_range_slicing_is_disjoint(self):
        cfg = Config()
        stamps = sorted({b.ts for bs in self.data.values() for b in bs})
        mid = stamps[len(stamps) // 2]
        a = run_backtest(self.data, cfg, end_ts=mid)
        b = run_backtest(self.data, cfg, start_ts=mid)
        self.assertTrue(all(t.close_ts <= mid for t in a.trades))
        self.assertTrue(all(t.open_ts >= mid for t in b.trades))

    def test_stricter_threshold_means_fewer_trades(self):
        lo = run_backtest(self.data, Config(conf_th=3, min_edge_ratio=0))
        hi = run_backtest(self.data, Config(conf_th=6, min_edge_ratio=0))
        self.assertGreater(len(lo.trades), len(hi.trades))

    def test_higher_costs_never_improve_pnl_per_same_signals(self):
        base = run_backtest(self.data, Config(min_edge_ratio=0))
        costly = run_backtest(self.data, Config(min_edge_ratio=0, taker_bps=20, slip_bps=10))
        self.assertLess(sum(t.pnl for t in costly.trades), sum(t.pnl for t in base.trades))

    def test_edge_gate_rejections_counted(self):
        r = run_backtest(self.data, Config(min_edge_ratio=50.0))
        self.assertEqual(len(r.trades), 0)
        self.assertGreater(r.stats.get("REJECT_EDGE_BELOW_COST", 0), 0)

    def test_walk_forward_structure(self):
        wf = walk_forward(synthetic(n_bars=1500, n_symbols=3, seed=2), Config(), train_bars=700,
                          test_bars=300, grid={"conf_th": [3, 5]}, min_trades=1)
        self.assertEqual(wf["n_folds"], 2)
        for f in wf["folds"]:
            self.assertLess(f["train_range"][0], f["train_range"][1])
            self.assertLess(f["test_range"][0], f["test_range"][1])
            self.assertEqual(f["train_range"][1], f["test_range"][0])   # test, eğitimin hemen sonrasında
            self.assertIn("expectancy_r", f["test"]) if f["test"].get("trades") else None
            self.assertIn(f["chosen"]["conf_th"], (3, 5))


class TestReport(unittest.TestCase):
    def test_metrics_math(self):
        from tests.test_risk_data import trade
        ts = [trade(2.0), trade(-1.0), trade(-1.0), trade(3.0)]
        m = metrics(ts, [(0, 1000), (1, 1010), (2, 990)], Config())
        self.assertEqual(m["trades"], 4)
        self.assertEqual(m["win_rate_pct"], 50.0)
        self.assertAlmostEqual(m["profit_factor"], 2.5)
        self.assertAlmostEqual(m["net_pnl_usd"], 3.0)
        self.assertFalse(m["significant"])
        self.assertAlmostEqual(m["max_drawdown_pct"], (1010 - 990) / 1010 * 100, places=2)

    def test_empty(self):
        self.assertEqual(metrics([], [], Config())["trades"], 0)

    def test_drawdown(self):
        self.assertAlmostEqual(max_drawdown_pct([(0, 100), (1, 150), (2, 75), (3, 200)], 100), 50.0)

    def test_attribution_shape_and_markdown_warns(self):
        r = run_backtest(synthetic(n_bars=1200, n_symbols=3), Config())
        a = attribution(r.trades)
        self.assertEqual(set(a["vote"]), set(VOTE_NAMES))
        md = render_markdown("T", {"x": 1}, metrics(r.trades, r.equity_curve, Config()), a, r.stats, r.breaker_trips)
        self.assertIn("PAPER", md)
        self.assertIn("Dürüst sınırlar", md)

    def test_markdown_warns_on_few_trades(self):
        from tests.test_risk_data import trade
        md = render_markdown("T", {}, metrics([trade(1)], [], Config()), {}, {}, {})
        self.assertIn("anlamsız", md)


class TestCli(unittest.TestCase):
    def test_demo_writes_reports(self):
        with tempfile.TemporaryDirectory() as d:
            rc = main(["demo", "--bars", "1200", "--symbols", "3", "--out", d, "--set", "conf_th=5"])
            self.assertEqual(rc, 0)
            for f in ("RAPOR.md", "SONUC.json", "trades.csv"):
                self.assertTrue((Path(d) / f).exists())
            self.assertEqual(json.loads((Path(d) / "SONUC.json").read_text())["config"]["conf_th"], 5)

    def test_bad_set_key_exits(self):
        with self.assertRaises(SystemExit):
            main(["demo", "--set", "yok=1"])

    def test_csv_dir_backtest(self):
        from sentez.data import save_csv
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as o:
            for s, b in synthetic(n_bars=1000, n_symbols=2).items():
                save_csv(Path(d) / f"{s}.csv", b)
            self.assertEqual(main(["backtest", "--csv-dir", d, "--out", o]), 0)


class TestLive(unittest.TestCase):
    def test_live_with_injected_feeds_no_network(self):
        data = synthetic(n_bars=430, n_symbols=2, seed=9)
        calls = {s: 0 for s in data}

        def hist(sym, interval, n):
            return data[sym][:400]

        def recent(sym, interval, n):
            calls[sym] += 1
            return data[sym][:400 + calls[sym]]

        with tempfile.TemporaryDirectory() as d:
            m = run_live(list(data), Config(), "15m", Path(d), minutes=0.02, log=lambda *_: None,
                         fetch_history=hist, fetch_recent=recent, sleep=lambda s: time.sleep(0.05))
            self.assertIsInstance(m, dict)
            self.assertTrue((Path(d) / "RAPOR.md").exists())
            self.assertTrue((Path(d) / "events.jsonl").exists())
            self.assertGreater(min(calls.values()), 1)

    def test_live_survives_feed_errors(self):
        data = synthetic(n_bars=410, n_symbols=1, seed=1)
        def hist(s, i, n): return data[s][:400]
        def broken(s, i, n): raise RuntimeError("ağ yok")
        with tempfile.TemporaryDirectory() as d:
            m = run_live(list(data), Config(), "15m", Path(d), minutes=0.01, log=lambda *_: None,
                         fetch_history=hist, fetch_recent=broken, sleep=lambda s: time.sleep(0.02))
            self.assertEqual(m["trades"], 0)


if __name__ == "__main__":
    unittest.main()
