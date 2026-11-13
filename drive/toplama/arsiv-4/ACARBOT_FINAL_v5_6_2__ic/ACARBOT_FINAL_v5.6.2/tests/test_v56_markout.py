"""v5.6 — Maker ters seçilim ölçümü. Ölçülmeyen sıfır gösterilmez."""
from __future__ import annotations

import unittest

from exec.markout import (
    MIN_FILLS_FOR_VERDICT,
    FillRecord,
    analyze_fills,
)


def _fill(i: int, post5: float, side: str = "LONG", filled: bool = True) -> FillRecord:
    return FillRecord(
        order_id=f"o{i}", symbol="BTC-USDT-SWAP", side=side,
        signal_ts_ms=1_000_000, signal_price=100.0,
        submit_ts_ms=1_000_100, submit_price=100.0,
        filled=filled, fill_ts_ms=1_000_200, fill_price=100.0, fill_qty=1.0,
        post_prices={"5": post5}, market_post_returns={"5": 0.0},
    )


class TestMarkout(unittest.TestCase):
    def test_long_positive_markout(self):
        r = _fill(1, 101.0)
        self.assertAlmostEqual(r.markout_bps(5), 100.0, places=6)

    def test_short_sign_is_inverted(self):
        r = _fill(1, 99.0, side="SHORT")
        self.assertAlmostEqual(r.markout_bps(5), 100.0, places=6)

    def test_missing_post_price_is_none_not_zero(self):
        r = _fill(1, 101.0)
        r.post_prices = {}
        self.assertIsNone(r.markout_bps(5))

    def test_unfilled_has_no_markout(self):
        self.assertIsNone(_fill(1, 101.0, filled=False).markout_bps(5))

    def test_market_drift_is_removed(self):
        """Piyasa düşerken LONG'un negatif markout'u ters seçilim değildir."""
        r = _fill(1, 99.0)
        r.market_post_returns = {"5": -0.01}
        self.assertAlmostEqual(r.markout_bps(5), -100.0, places=6)
        self.assertAlmostEqual(r.markout_excess_bps(5), 0.0, places=6)

    def test_no_records_reports_missing_data(self):
        a = analyze_fills([])
        self.assertEqual(a["hukum"], "VERI_YOK")
        self.assertIsNone(a["dolum_orani"])

    def test_below_threshold_is_insufficient_not_clean(self):
        a = analyze_fills([_fill(i, 101.0) for i in range(50)])
        self.assertEqual(a["hukum"], "YETERSIZ_ORNEKLEM")
        self.assertIn("300", a["neden"])

    def test_adverse_selection_detected_with_enough_fills(self):
        recs = [_fill(i, 99.0) for i in range(MIN_FILLS_FOR_VERDICT)]
        a = analyze_fills(recs)
        self.assertEqual(a["hukum"], "TERS_SECILIM_VAR")
        self.assertLess(a["markout"]["5"]["arindirilmis_ortalama_bps"], 0)

    def test_positive_markout_with_enough_fills(self):
        recs = [_fill(i, 101.0) for i in range(MIN_FILLS_FOR_VERDICT)]
        self.assertEqual(analyze_fills(recs)["hukum"], "TERS_SECILIM_YOK_POZITIF")

    def test_filled_and_unfilled_are_both_counted(self):
        recs = [_fill(i, 101.0) for i in range(10)]
        recs += [_fill(100 + i, 101.0, filled=False) for i in range(5)]
        a = analyze_fills(recs)
        self.assertEqual(a["dolan"], 10)
        self.assertEqual(a["dolmayan"], 5)
        self.assertAlmostEqual(a["dolum_orani"], 10 / 15)

    def test_horizons_match_specification(self):
        a = analyze_fills([_fill(1, 101.0)])
        self.assertEqual(a["pencereler_dk"], [1, 5, 15, 30])


if __name__ == "__main__":
    unittest.main()
