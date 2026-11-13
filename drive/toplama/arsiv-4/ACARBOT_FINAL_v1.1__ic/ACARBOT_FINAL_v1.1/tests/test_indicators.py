import math
import unittest

from core.indicators import (
    adx,
    atr,
    bollinger_bands,
    cci,
    ema,
    macd,
    obv,
    rsi,
    sma,
    stochastic,
    supertrend,
    true_range,
    vwap,
)


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.close = [float(value) for value in range(1, 41)]
        self.high = [value + 1.0 for value in self.close]
        self.low = [value - 1.0 for value in self.close]
        self.volume = [10.0] * len(self.close)

    def test_sma_and_ema_have_explicit_warmup_and_expected_values(self):
        self.assertEqual(sma([1, 2, 3, 4], 3), [None, None, 2.0, 3.0])
        result = ema([1, 2, 3, 4], 3)
        self.assertIsNone(result[1])
        self.assertEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)

    def test_rsi_handles_up_down_and_flat_series(self):
        self.assertEqual(rsi([1, 2, 3, 4], 2)[-1], 100.0)
        self.assertEqual(rsi([4, 3, 2, 1], 2)[-1], 0.0)
        self.assertEqual(rsi([5, 5, 5, 5], 2)[-1], 50.0)

    def test_true_range_and_atr(self):
        self.assertEqual(
            true_range([10, 12], [8, 10], [9, 11]),
            [2.0, 3.0],
        )
        self.assertEqual(atr([10, 12], [8, 10], [9, 11], 2), [None, 2.5])

    def test_macd_returns_aligned_components(self):
        result = macd(self.close, fast_period=3, slow_period=5, signal_period=2)
        self.assertEqual(len(result.line), len(self.close))
        self.assertIsNone(result.line[3])
        self.assertIsNotNone(result.line[4])
        self.assertIsNone(result.signal[4])
        self.assertIsNotNone(result.histogram[-1])

    def test_adx_directional_indices_are_bounded(self):
        result = adx(self.high, self.low, self.close, period=3)
        self.assertTrue(all(value is None for value in result.adx[:4]))
        self.assertGreater(result.plus_di[-1], result.minus_di[-1])
        self.assertTrue(0 <= result.adx[-1] <= 100)

    def test_stochastic_and_cci_are_aligned(self):
        result = stochastic(self.high, self.low, self.close, k_period=5, d_period=3)
        self.assertEqual(len(result.percent_k), len(self.close))
        self.assertTrue(0 <= result.percent_k[-1] <= 100)
        self.assertIsNotNone(result.percent_d[-1])
        self.assertGreater(cci(self.high, self.low, self.close, period=5)[-1], 0)

    def test_obv_vwap_and_bollinger_bands(self):
        self.assertEqual(obv([1, 2, 2, 1], [10, 5, 3, 2]), [0.0, 5.0, 5.0, 3.0])
        weighted = vwap(
            [11, 21], [9, 19], [10, 20], [1, 3], period=2
        )
        self.assertEqual(weighted, [None, 17.5])
        bands = bollinger_bands([1, 2, 3], period=3)
        self.assertEqual(bands.middle[-1], 2.0)
        self.assertAlmostEqual(bands.upper[-1], 2.0 + 2.0 * math.sqrt(2 / 3))
        self.assertAlmostEqual(bands.lower[-1], 2.0 - 2.0 * math.sqrt(2 / 3))

    def test_supertrend_returns_direction_after_atr_warmup(self):
        result = supertrend(self.high, self.low, self.close, period=3, multiplier=2)
        self.assertTrue(all(value is None for value in result.direction[:2]))
        self.assertEqual(result.direction[-1], 1)
        self.assertLess(result.line[-1], self.close[-1])

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            ema([1, 2], 0)
        with self.assertRaises(ValueError):
            sma([1, float("nan")], 1)
        with self.assertRaises(ValueError):
            atr([2, 1], [1, 2], [1, 1], period=1)
        with self.assertRaises(ValueError):
            vwap([2], [1], [1], [-1], period=1)


if __name__ == "__main__":
    unittest.main()
