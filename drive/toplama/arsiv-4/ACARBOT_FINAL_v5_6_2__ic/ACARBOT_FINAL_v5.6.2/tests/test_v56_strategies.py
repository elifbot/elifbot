"""v5.6 — Yeni giriş stratejileri: look-ahead yasağı ve dürüstlük."""
from __future__ import annotations

import random
import unittest

from core.entry_strategies import STRATEGIES, trend_continuation_mtf
from tests.helpers import make_candles


def _random_candles(n=300, seed=7):
    rng = random.Random(seed)
    closes = []
    px = 100.0
    for _ in range(n):
        px *= 1 + rng.uniform(-0.01, 0.01)
        closes.append(px)
    return make_candles(closes)


class TestEntryStrategies(unittest.TestCase):
    def test_six_strategies_registered(self):
        self.assertEqual(len(STRATEGIES), 6)

    def test_no_lookahead_future_candles_cannot_change_signal(self):
        """i. mumdan sonraki veriyi değiştirmek sinyali DEĞİŞTİRMEMELİ."""
        cs = _random_candles(300)
        i = 200
        for key, fn in STRATEGIES.items():
            if key == "trend_continuation_mtf":
                continue
            a = fn(cs, i)
            mutated = list(cs)
            for j in range(i + 1, len(mutated)):
                c = mutated[j]
                mutated[j] = type(c)(
                    timestamp=c.timestamp, open=c.open * 3, high=c.high * 3,
                    low=c.low * 3, close=c.close * 3, volume=c.volume * 3,
                )
            b = fn(mutated, i)
            self.assertEqual(
                (a.side, a.entry, a.stop) if a else None,
                (b.side, b.entry, b.stop) if b else None,
                f"{key} geleceğe bakıyor",
            )

    def test_none_index_equals_full_history_prefix(self):
        cs = _random_candles(250)
        for key, fn in STRATEGIES.items():
            if key == "trend_continuation_mtf":
                continue
            self.assertEqual(
                str(fn(cs, 199)), str(fn(cs[:200])),
                f"{key}: i ve önek aynı sonucu vermeli",
            )

    def test_mtf_without_higher_tf_returns_nothing(self):
        """Üst TF yoksa MTF sinyali üretilmez — tek TF'yi MTF gibi sunma."""
        cs = _random_candles(300)
        self.assertIsNone(trend_continuation_mtf(cs, 250))
        self.assertIsNone(trend_continuation_mtf(cs, 250, higher_tf=None))

    def test_mtf_with_higher_tf_runs(self):
        cs = _random_candles(300)
        ht = _random_candles(300, seed=11)
        r = trend_continuation_mtf(cs, 250, higher_tf=ht)
        self.assertTrue(r is None or r.side in ("LONG", "SHORT"))

    def test_stop_is_on_the_correct_side(self):
        cs = _random_candles(400, seed=3)
        for key, fn in STRATEGIES.items():
            if key == "trend_continuation_mtf":
                continue
            for i in range(60, 350):
                s = fn(cs, i)
                if s is None:
                    continue
                if s.side == "LONG":
                    self.assertLess(s.stop, s.entry, key)
                else:
                    self.assertGreater(s.stop, s.entry, key)
                self.assertGreater(s.stop_fraction, 0.0, key)

    def test_insufficient_history_returns_none(self):
        cs = _random_candles(20)
        for key, fn in STRATEGIES.items():
            if key == "trend_continuation_mtf":
                continue
            self.assertIsNone(fn(cs, 19), key)

    def test_approximations_are_declared(self):
        """CVD ve OI yaklaşıklıkları açıkça işaretli olmalı."""
        import inspect

        from core.entry_strategies import (
            oi_volume_price_divergence,
            vwap_cvd_momentum,
        )
        for fn in (vwap_cvd_momentum, oi_volume_price_divergence):
            self.assertIn("approximation", inspect.getsource(fn))


if __name__ == "__main__":
    unittest.main()
