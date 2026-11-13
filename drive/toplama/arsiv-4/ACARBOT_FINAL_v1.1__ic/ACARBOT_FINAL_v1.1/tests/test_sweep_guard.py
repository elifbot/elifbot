"""Stop-hunt / likidasyon duvarı dedektörü testleri (FINAL v1.1)."""

from __future__ import annotations

import unittest

from core.config import SweepGuardConfig
from core.sweep_guard import SweepGuard, detect_walls

CFG = SweepGuardConfig()
MID = 100.0
NOW = 1_700_000_000_000


def _uniform_book(levels: int = 60, qty_usd: float = 20_000.0):
    """Düzgün dağılmış defter: her seviyede eşit nominal, duvar yok."""
    bids, asks = [], []
    for i in range(1, levels + 1):
        price_gap = MID * 0.0001 * i  # her seviye %0.01 aralıklı
        bid_p = MID - price_gap
        ask_p = MID + price_gap
        bids.append((bid_p, qty_usd / bid_p))
        asks.append((ask_p, qty_usd / ask_p))
    return bids, asks


def _book_with_wall(wall_usd: float = 2_000_000.0, wall_distance: float = 0.002,
                    side: str = "bid"):
    bids, asks = _uniform_book()
    price = MID * (1 - wall_distance) if side == "bid" else MID * (1 + wall_distance)
    level = (price, wall_usd / price)
    if side == "bid":
        bids.append(level)
    else:
        asks.append(level)
    return bids, asks


class DetectWallsTests(unittest.TestCase):
    def test_uniform_book_has_no_walls(self):
        bids, asks = _uniform_book()
        self.assertEqual(detect_walls(bids, asks, CFG), [])

    def test_big_bid_wall_detected(self):
        bids, asks = _book_with_wall(2_000_000.0, 0.002, "bid")
        walls = detect_walls(bids, asks, CFG)
        self.assertTrue(walls)
        wall = max(walls, key=lambda w: w.notional_usd)
        self.assertEqual(wall.side, "bid")
        self.assertGreaterEqual(wall.notional_usd, 500_000.0)
        self.assertAlmostEqual(wall.distance_pct, 0.002, delta=0.001)

    def test_big_ask_wall_detected(self):
        bids, asks = _book_with_wall(3_000_000.0, 0.003, "ask")
        walls = detect_walls(bids, asks, CFG)
        self.assertTrue(any(w.side == "ask" for w in walls))

    def test_small_wall_below_absolute_threshold_ignored(self):
        # 300k$ < 500k$ mutlak eşik (medyanın 8 katı da aşmıyor: 300k/20k=15x
        # ama bant birleşimi nedeniyle mutlak eşik belirleyici)
        bids, asks = _book_with_wall(300_000.0, 0.002, "bid")
        walls = detect_walls(bids, asks, CFG)
        self.assertFalse(any(w.notional_usd >= 500_000.0 for w in walls))

    def test_far_wall_outside_scan_range_ignored(self):
        bids, asks = _uniform_book()
        far_price = MID * 0.99  # %1 uzakta > %0.5 tarama aralığı
        bids.append((far_price, 5_000_000.0 / far_price))
        self.assertEqual(detect_walls(bids, asks, CFG), [])

    def test_empty_or_invalid_book(self):
        self.assertEqual(detect_walls([], [], CFG), [])
        self.assertEqual(detect_walls([(0, 1)], [(0, 1)], CFG), [])
        self.assertEqual(detect_walls([(101, 1)], [(99, 1)], CFG), [])  # crossed


class SweepGuardGateTests(unittest.TestCase):
    def test_wall_near_price_blocks_entry(self):
        guard = SweepGuard(CFG)
        bids, asks = _book_with_wall(2_000_000.0, 0.002, "bid")
        guard.update_book("okx:BTC-USDT-SWAP", bids, asks, NOW)
        reason = guard.entry_block("okx:BTC-USDT-SWAP", "LONG", NOW + 5_000)
        self.assertIsNotNone(reason)
        self.assertIn("SWEEP_GUARD", reason)
        # Her iki yön de engellenir (mıknatıs riski yön bağımsız)
        self.assertIsNotNone(
            guard.entry_block("okx:BTC-USDT-SWAP", "SHORT", NOW + 5_000)
        )

    def test_uniform_book_allows_entry(self):
        guard = SweepGuard(CFG)
        bids, asks = _uniform_book()
        guard.update_book("okx:BTC-USDT-SWAP", bids, asks, NOW)
        self.assertIsNone(
            guard.entry_block("okx:BTC-USDT-SWAP", "LONG", NOW + 5_000)
        )

    def test_wall_outside_block_distance_allows(self):
        guard = SweepGuard(CFG)
        # %0.45 uzakta: tespit edilir ama blok mesafesi %0.35 dışı
        bids, asks = _book_with_wall(2_000_000.0, 0.0045, "ask")
        walls = guard.update_book("okx:BTC-USDT-SWAP", bids, asks, NOW)
        self.assertTrue(walls)
        self.assertIsNone(
            guard.entry_block("okx:BTC-USDT-SWAP", "LONG", NOW + 5_000)
        )

    def test_stale_book_ignored(self):
        guard = SweepGuard(CFG)
        bids, asks = _book_with_wall()
        guard.update_book("okx:BTC-USDT-SWAP", bids, asks, NOW)
        future = NOW + int((CFG.book_ttl_seconds + 5) * 1000)
        self.assertIsNone(
            guard.entry_block("okx:BTC-USDT-SWAP", "LONG", future)
        )

    def test_unknown_symbol_fail_open(self):
        guard = SweepGuard(CFG)
        self.assertIsNone(guard.entry_block("okx:X-USDT-SWAP", "LONG", NOW))

    def test_status_counters(self):
        guard = SweepGuard(CFG)
        bids, asks = _book_with_wall()
        guard.update_book("okx:BTC-USDT-SWAP", bids, asks, NOW)
        guard.entry_block("okx:BTC-USDT-SWAP", "LONG", NOW)
        status = guard.status()
        self.assertEqual(status["books_tracked"], 1)
        self.assertEqual(status["books_updated"], 1)
        self.assertGreaterEqual(status["blocks_count"], 1)
        self.assertGreaterEqual(status["active_walls"], 1)


if __name__ == "__main__":
    unittest.main()
