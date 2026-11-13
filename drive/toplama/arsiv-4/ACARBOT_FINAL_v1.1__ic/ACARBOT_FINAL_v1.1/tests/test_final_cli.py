"""FINAL v1.0 eklemeleri için testler: süreli oturum + oturum raporu."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import __version__
from app.main import build_parser, write_session_report
from monitor.report import PerformanceReporter, SimpleMetrics


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


class FinalCliTests(unittest.TestCase):
    def test_version_present(self):
        self.assertTrue(__version__)
        self.assertIn("final", __version__)

    def test_duration_flag_parses(self):
        args = _parse(["--paper", "--duration-minutes", "15"])
        self.assertEqual(args.duration_minutes, 15.0)

    def test_duration_default_is_zero(self):
        args = _parse(["--paper"])
        self.assertEqual(args.duration_minutes, 0.0)

    def test_report_file_default(self):
        args = _parse(["--paper"])
        self.assertEqual(args.report_file, "session_report.json")

    def test_negative_duration_not_auto_enabled(self):
        args = _parse(["--paper", "--duration-minutes", "-5"])
        self.assertFalse(args.duration_minutes and args.duration_minutes > 0)


class SessionReportTests(unittest.TestCase):
    def _fake_executor(self, trades):
        portfolio = SimpleNamespace(balance=1002.5, positions={})
        broker = SimpleNamespace(
            portfolio=portfolio,
            trades=trades,
            mark_to_market=lambda prices: portfolio.balance,
        )
        portfolio.unrealized_pnl = lambda prices: 0.0
        return SimpleNamespace(
            broker=broker,
            risk=SimpleNamespace(kill_switch_state=SimpleNamespace(value="NORMAL")),
            data_integrity=SimpleNamespace(safe_mode=False),
            _latest_prices={},
        )

    def test_report_written_with_expected_fields(self):
        now_ms = 1_800_000_000_000
        trades = [
            {"type": "OPEN", "timestamp": now_ms + 1000, "symbol": "okx:BTC-USDT-SWAP"},
            {"type": "CLOSE", "timestamp": now_ms + 2000, "pnl": 2.5,
             "symbol": "okx:BTC-USDT-SWAP", "motor": "TREND"},
        ]
        executor = self._fake_executor(trades)
        metrics = SimpleMetrics()
        metrics.inc("ticks_total", 42)
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "rapor.json"
            args = _parse(["--paper", "--report-file", str(report_path)])
            report = write_session_report(
                args, executor, PerformanceReporter(None), metrics,
                now_ms, 1000.0,
            )
            self.assertTrue(report_path.exists())
            on_disk = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, report)
        self.assertEqual(report["version"], __version__)
        self.assertEqual(report["entries"], 1)
        self.assertEqual(report["closes"], 1)
        self.assertAlmostEqual(report["realized_pnl_session"], 2.5)
        self.assertEqual(report["counters"]["ticks_total"], 42)
        self.assertEqual(report["kill_switch"], "NORMAL")
        self.assertFalse(report["safe_mode"])

    def test_trades_before_session_excluded(self):
        now_ms = 1_800_000_000_000
        trades = [
            {"type": "CLOSE", "timestamp": now_ms - 5000, "pnl": 99.0},
        ]
        executor = self._fake_executor(trades)
        with tempfile.TemporaryDirectory() as tmp:
            args = _parse(["--paper", "--report-file", str(Path(tmp) / "r.json")])
            report = write_session_report(
                args, executor, PerformanceReporter(None), SimpleMetrics(),
                now_ms, 1000.0,
            )
        self.assertEqual(report["closes"], 0)
        self.assertEqual(report["realized_pnl_session"], 0.0)


if __name__ == "__main__":
    unittest.main()
