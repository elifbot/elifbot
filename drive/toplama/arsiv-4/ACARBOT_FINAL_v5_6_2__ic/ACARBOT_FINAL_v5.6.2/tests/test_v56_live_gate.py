"""v5.6 — Canlı giriş zaman dilimi kapısı.

Ölçüm: 5m ve 15m giriş kenarı istatistiksel olarak ELENDİ; 1h
YETERSIZ_ORNEKLEM. Bu yüzden hiçbiri canlıya açık olmamalı.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from core.config import SuperConfig
from core.gates import ENTRY_EDGE_VERDICTS, canli_giris_izinli


class TestLiveEntryGate(unittest.TestCase):
    def test_default_blocks_every_timeframe(self):
        cfg = SuperConfig().v2.live
        for tf in ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"):
            ok, why = canli_giris_izinli(tf, cfg)
            self.assertFalse(ok, f"{tf} canlıya açık olmamalı")
            self.assertIn("canlıya açık değil", why)

    def test_default_allow_list_is_empty(self):
        self.assertEqual(SuperConfig().v2.live.live_allowed_timeframes, ())

    def test_real_money_disabled_by_default(self):
        self.assertFalse(SuperConfig().v2.live.enabled)

    def test_measured_verdicts_are_not_positive(self):
        """Ölçülen hiçbir zaman dilimi pozitif kenar göstermiyor."""
        self.assertNotIn("GIRIS_KENARI_VAR", ENTRY_EDGE_VERDICTS.values())
        self.assertEqual(ENTRY_EDGE_VERDICTS["5m"], "GIRIS_KENARI_YOK")
        self.assertEqual(ENTRY_EDGE_VERDICTS["15m"], "GIRIS_KENARI_YOK")
        self.assertEqual(ENTRY_EDGE_VERDICTS["1h"], "YETERSIZ_ORNEKLEM")

    def test_listing_a_timeframe_is_not_enough_without_proof(self):
        cfg = SuperConfig().v2.live
        cfg = replace(cfg, live_allowed_timeframes=("5m",))
        ok, why = canli_giris_izinli("5m", cfg)
        self.assertFalse(ok)
        self.assertIn("kenar kanıtı yok", why)

    def test_unmeasured_timeframe_cannot_pass_even_if_listed(self):
        cfg = SuperConfig().v2.live
        cfg = replace(cfg, live_allowed_timeframes=("4h",))
        ok, why = canli_giris_izinli("4h", cfg)
        self.assertFalse(ok)
        self.assertIn("OLCULMEDI", why)

    def test_gate_can_be_bypassed_only_explicitly(self):
        """Kapı ancak iki ayar birlikte değiştirilirse açılır (bilinçli)."""
        cfg = SuperConfig().v2.live
        cfg = replace(cfg, live_allowed_timeframes=("5m",),
                      live_requires_edge_proof=False)
        ok, _ = canli_giris_izinli("5m", cfg)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
