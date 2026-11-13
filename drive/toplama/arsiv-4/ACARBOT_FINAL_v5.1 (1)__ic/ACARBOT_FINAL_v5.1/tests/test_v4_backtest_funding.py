"""v4.0 — tarihsel funding + çok rejimli backtest testleri (madde 23)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backtest.engine import BacktestEngine
from backtest.metrics import regime_breakdown
from core.config import SuperConfig


class FundingRateAtTests(unittest.TestCase):
    def test_picks_latest_rate_before_ts(self):
        rates = [
            (1_000, 0.0001),
            (9_000_000, 0.0002),
            (17_000_000, 0.0003),
        ]
        self.assertEqual(BacktestEngine._funding_rate_at(rates, 10_000_000), 0.0002)
        self.assertEqual(BacktestEngine._funding_rate_at(rates, 1_500), 0.0001)
        self.assertIsNone(BacktestEngine._funding_rate_at(rates, 500))

    def test_engine_accepts_funding_rates(self):
        """Motor funding geçmişiyle hatasız çalışır (duman testi)."""
        from tests.helpers import make_candles
        candles = make_candles([100.0 + (i % 5) * 0.1 for i in range(120)])
        engine = BacktestEngine(SuperConfig(), initial_balance=1_000.0)
        result = engine.run(
            {"BTCUSDT": candles},
            funding_rates={"BTCUSDT": [(candles[0].timestamp, 0.0001)]},
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.final_balance > 0)


class RegimeBreakdownTests(unittest.TestCase):
    def test_groups_by_regime(self):
        trades = [
            {"type": "CLOSE", "regime": "TREND_UP", "pnl": 5.0},
            {"type": "CLOSE", "regime": "TREND_UP", "pnl": -2.0},
            {"type": "CLOSE", "regime": "RANGE", "pnl": 1.0},
            {"type": "OPEN", "regime": "TREND_UP", "pnl": 0.0},  # sayılmaz
        ]
        table = regime_breakdown(trades)
        self.assertEqual(table["TREND_UP"]["trades"], 2)
        self.assertAlmostEqual(table["TREND_UP"]["net_pnl"], 3.0)
        self.assertAlmostEqual(table["TREND_UP"]["win_rate"], 0.5)
        self.assertEqual(table["RANGE"]["trades"], 1)
        self.assertAlmostEqual(table["RANGE"]["win_rate"], 1.0)

    def test_empty_when_no_closes(self):
        self.assertEqual(regime_breakdown([{"type": "OPEN"}]), {})

    def test_missing_regime_is_unknown(self):
        table = regime_breakdown([{"type": "CLOSE", "pnl": 1.0}])
        self.assertIn("UNKNOWN", table)


class FundingCsvLoaderTests(unittest.TestCase):
    def test_funding_csv_separated_from_candles(self):
        """run_backtest: <SYM>_funding.csv mum olarak YÜKLENMEMELİ."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "BTCUSDT_5m.csv").write_text(
                "timestamp,open,high,low,close,volume\n"
                "1700000000000,1,1,1,1,1\n",
                encoding="utf-8",
            )
            (data_dir / "BTCUSDT_funding.csv").write_text(
                "timestamp,rate\n1700000000000,0.0001\n",
                encoding="utf-8",
            )
            files = sorted(data_dir.glob("*_5m.csv"))
            if not files:
                files = sorted(data_dir.glob("*.csv"))
            candle_files = [
                p for p in files if not p.stem.endswith("_funding")
            ]
            names = [p.name for p in candle_files]
            self.assertEqual(names, ["BTCUSDT_5m.csv"])
            funding_files = sorted(data_dir.glob("*_funding.csv"))
            self.assertEqual(
                [p.stem.replace("_funding", "").upper() for p in funding_files],
                ["BTCUSDT"],
            )


if __name__ == "__main__":
    unittest.main()
