"""v5.6 — Funding backtest'e bağlı ve ölçülmeyen sıfır gösterilmiyor."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backtest.funding import (
    FUNDING_INTERVAL_MS,
    funding_status,
    load_funding_csv,
    load_funding_dir,
)


class TestFunding(unittest.TestCase):
    def test_missing_data_is_not_zero(self):
        st = funding_status({}, {})
        self.assertEqual(st["durum"], "UYGULANMADI")
        self.assertIn("HESAPLAMADI", st["neden"])
        self.assertIn("sıfır", st["neden"])

    def test_csv_roundtrip_and_sort(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "BTC_funding.csv"
            p.write_text("timestamp,rate\n2000,0.0002\n1000,0.0001\n", encoding="utf-8")
            rows = load_funding_csv(p)
            self.assertEqual(rows, [(1000, 0.0001), (2000, 0.0002)])

    def test_full_coverage_is_reported_complete(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "BTCUSDT_funding.csv"
            lines = ["timestamp,rate"]
            for i in range(4):
                lines.append(f"{i * FUNDING_INTERVAL_MS},0.0001")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            rates, cov = load_funding_dir(d, 0, 3 * FUNDING_INTERVAL_MS)
            self.assertIn("BTCUSDT", rates)
            st = funding_status(rates, cov)
            self.assertEqual(st["durum"], "UYGULANDI")

    def test_partial_coverage_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ETHUSDT_funding.csv"
            p.write_text("timestamp,rate\n0,0.0001\n", encoding="utf-8")
            rates, cov = load_funding_dir(d, 0, 10 * FUNDING_INTERVAL_MS)
            st = funding_status(rates, cov)
            self.assertEqual(st["durum"], "EKSIK_KAPSAMA")
            self.assertIn("ETHUSDT", st["eksik_kapsamali_semboller"])

    def test_empty_dir_returns_empty_not_fabricated(self):
        with tempfile.TemporaryDirectory() as d:
            rates, cov = load_funding_dir(d)
            self.assertEqual(rates, {})
            self.assertEqual(funding_status(rates, cov)["durum"], "UYGULANMADI")

    def test_engine_accepts_funding_rates(self):
        """Motor funding parametresini gerçekten kabul ediyor."""
        import inspect

        from backtest.engine import BacktestEngine
        self.assertIn("funding_rates", inspect.signature(BacktestEngine.run).parameters)

    def test_validator_passes_funding_to_engine(self):
        """Doğrulama aracı funding'i motora geçiriyor (v5.6 öncesi geçmiyordu)."""
        src = Path("tools/validate_strategy.py").read_text(encoding="utf-8")
        self.assertIn("funding_rates=funding_rates", src)
        self.assertIn("load_funding_dir", src)


if __name__ == "__main__":
    unittest.main()
