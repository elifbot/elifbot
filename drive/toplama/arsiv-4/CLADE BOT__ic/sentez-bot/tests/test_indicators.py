import math
import unittest

from sentez.data import synthetic
from sentez.indicators import (Indicators, adx_series, atr_series, ema, rsi_series,
                               supertrend_series, vwap_series)
from sentez.models import Bar
from sentez.signals import VOTE_NAMES, evaluate, votes_at
from tests.helpers import bar


def trend(n=300, up=True, step=0.5):
    out = []
    px = 100.0
    for i in range(n):
        o = px
        px = px + step if up else px - step
        out.append(Bar(1_700_000_000_000 + i * 900_000, o, max(o, px) + 0.1, min(o, px) - 0.1, px, 100.0))
    return out


class TestIndicators(unittest.TestCase):
    def test_ema_constant(self):
        self.assertTrue(all(abs(x - 5) < 1e-12 for x in ema([5.0] * 50, 10)))

    def test_rsi_extremes(self):
        up = [float(i) for i in range(60)]
        self.assertGreater(rsi_series(up)[-1], 99)
        self.assertLess(rsi_series(up[::-1])[-1], 1)

    def test_atr_positive_and_warmup_none(self):
        a = atr_series(trend())
        self.assertIsNone(a[3])
        self.assertTrue(all(x > 0 for x in a[20:]))

    def test_adx_strong_trend_high(self):
        self.assertGreater(adx_series(trend())[-1], 40)

    def test_supertrend_direction(self):
        self.assertEqual(supertrend_series(trend(up=True))[-1], 1.0)
        self.assertEqual(supertrend_series(trend(up=False))[-1], -1.0)

    def test_vwap_resets_each_utc_day(self):
        day = 86_400_000
        bars = [Bar(day - 60_000, 10, 10, 10, 10, 1), Bar(day, 20, 20, 20, 20, 1)]
        v = vwap_series(bars)
        self.assertAlmostEqual(v[1], 20.0)       # yeni günde önceki gün karışmaz

    def test_causality_prefix_equals_full(self):
        """i. değer gelecekteki mumlardan etkilenmemeli (ileriye bakış yok)."""
        bars = synthetic(n_bars=500, n_symbols=1, seed=3)["SYN1USDT"]
        full = Indicators.compute(bars)
        for i in (250, 333, 420):
            pre = Indicators.compute(bars[:i + 1])
            self.assertEqual(votes_at(full, i), votes_at(pre, i))
            self.assertAlmostEqual(full.atr[i], pre.atr[i])
            self.assertAlmostEqual(full.adx[i], pre.adx[i])

    def test_evaluate_same_with_truncated_future(self):
        bars = synthetic(n_bars=600, n_symbols=1, seed=11)["SYN1USDT"]
        from sentez.models import Config
        cfg = Config()
        full = Indicators.compute(bars)
        for i in range(230, 600, 17):
            a = evaluate(full, i, cfg)
            b = evaluate(Indicators.compute(bars[:i + 1]), i, cfg)
            self.assertEqual(a[1], b[1])
            if a[0]:
                self.assertEqual((a[0].side, a[0].score), (b[0].side, b[0].score))


class TestSignals(unittest.TestCase):
    def test_vote_names_complete(self):
        ind = Indicators.compute(trend())
        self.assertEqual(set(votes_at(ind, 280)), set(VOTE_NAMES))

    def test_warmup(self):
        from sentez.models import Config
        ind = Indicators.compute(trend(n=300))
        self.assertEqual(evaluate(ind, 100, Config())[1], "WARMUP")

    def test_clean_uptrend_long_downtrend_short(self):
        from sentez.models import Config
        cfg = Config(conf_th=4)
        sig, why = evaluate(Indicators.compute(trend(up=True)), 290, cfg)
        self.assertEqual(why, "SIGNAL")
        self.assertEqual(sig.side, 1)
        sig, why = evaluate(Indicators.compute(trend(up=False, step=0.3)), 290, cfg)
        self.assertEqual(why, "SIGNAL")
        self.assertEqual(sig.side, -1)

    def test_candle_gap_blocks(self):
        from sentez.models import Config
        bars = trend()
        del bars[289:291]                      # iki ardışık mum eksik
        ind = Indicators.compute(bars)
        self.assertEqual(evaluate(ind, 289, Config())[1], "CANDLE_GAP")

    def test_single_missing_candle_tolerated(self):
        from sentez.models import Config
        bars = trend()
        del bars[289]
        ind = Indicators.compute(bars)
        self.assertNotEqual(evaluate(ind, 289, Config())[1], "CANDLE_GAP")

    def test_threshold_clamped(self):
        from sentez.models import Config
        self.assertEqual(Config(conf_th=99).validate().conf_th, 8)
        self.assertEqual(Config(conf_th=0).validate().conf_th, 2)


if __name__ == "__main__":
    unittest.main()
