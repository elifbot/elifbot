"""v5.6 — Trailing varyant deneyi ve seçim kuralı."""
from __future__ import annotations

import unittest

from backtest.trailing_experiment import (
    VARIANTS,
    apply_variant,
    evaluate_variant,
    pick_best,
)
from core.config import SuperConfig


class TestTrailingVariants(unittest.TestCase):
    def test_four_distinct_variants(self):
        self.assertEqual(len(VARIANTS), 4)
        self.assertEqual(len({v.key for v in VARIANTS}), 4)

    def test_all_four_variants_are_configurationally_distinct(self):
        """Regresyon: B ve C ilk tanımda ÖZDEŞti (break-even zaten açıktı)."""
        sigs = {
            (v.trail_activation_r, v.trail_atr_multiple, v.breakeven_enabled)
            for v in VARIANTS
        }
        self.assertEqual(len(sigs), 4, "Dört varyant birbirinden farklı olmalı")

    def test_current_variant_matches_shipped_config(self):
        cfg = SuperConfig().exit
        a = next(v for v in VARIANTS if v.key == "A_mevcut")
        self.assertEqual(a.trail_activation_r, cfg.trail_activation_r)
        self.assertEqual(a.trail_atr_multiple, cfg.trail_atr_multiple)

    def test_apply_does_not_mutate_original(self):
        cfg = SuperConfig().exit
        before = cfg.trail_activation_r
        b = next(v for v in VARIANTS if v.key == "B_tp1_sonrasi")
        new = apply_variant(cfg, b)
        self.assertEqual(cfg.trail_activation_r, before)
        self.assertEqual(new.trail_activation_r, 1.0)

    def test_insufficient_sample_is_not_selectable(self):
        r = evaluate_variant("A_mevcut", {"trades": 5, "expectancy_r": 2.0}, None)
        self.assertEqual(r["hukum"], "YETERSIZ_ORNEKLEM")
        self.assertFalse(r["secilebilir"])

    def test_positive_is_without_oos_is_not_selectable(self):
        r = evaluate_variant("A", {"trades": 100, "expectancy_r": 0.5}, None)
        self.assertEqual(r["hukum"], "IS_POZITIF_OOS_YOK")
        self.assertFalse(r["secilebilir"])

    def test_positive_is_negative_oos_rejected(self):
        r = evaluate_variant(
            "A", {"trades": 100, "expectancy_r": 0.5}, {"expectancy_r": -0.2},
        )
        self.assertEqual(r["hukum"], "OOS_DOGRULAMADI")
        self.assertFalse(r["secilebilir"])

    def test_both_positive_is_selectable(self):
        r = evaluate_variant(
            "A", {"trades": 100, "expectancy_r": 0.5}, {"expectancy_r": 0.3},
        )
        self.assertTrue(r["secilebilir"])

    def test_no_winner_when_all_negative(self):
        rows = [
            evaluate_variant(v.key, {"trades": 100, "expectancy_r": -0.4},
                             {"expectancy_r": -0.3})
            for v in VARIANTS
        ]
        p = pick_best(rows)
        self.assertEqual(p["secilen"], "HICBIRI")

    def test_loss_reduction_alone_does_not_win(self):
        """Daha az zarar, 'kazanan' demek değildir."""
        rows = [
            evaluate_variant("A", {"trades": 100, "expectancy_r": -0.6},
                             {"expectancy_r": -0.5}),
            evaluate_variant("B", {"trades": 100, "expectancy_r": -0.1},
                             {"expectancy_r": -0.05}),
        ]
        self.assertEqual(pick_best(rows)["secilen"], "HICBIRI")

    def test_best_is_chosen_by_oos(self):
        rows = [
            evaluate_variant("A", {"trades": 100, "expectancy_r": 0.9},
                             {"expectancy_r": 0.1}),
            evaluate_variant("B", {"trades": 100, "expectancy_r": 0.3},
                             {"expectancy_r": 0.5}),
        ]
        self.assertEqual(pick_best(rows)["secilen"], "B")


if __name__ == "__main__":
    unittest.main()
