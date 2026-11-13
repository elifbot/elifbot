# -*- coding: utf-8 -*-
"""BOT 3 v2 — HYBRID V2+.

v1'de 30 dakikada sadece 2 islem acti: hacim esigi 5,0x ve %0,60 kovalama tavani
testin en karli hareketlerini (AKE +%4,25 / +%5,46, BARD +%2,48) reddetti (58 veto).
Ayrica SOXL short -9,35 $ ile tepe kar gormeden surundu.

v2 degisiklikleri:
  1. min_vol_mult 5,0 -> 3,8 · max_ivme_pct 0,60 -> 1,60 (kovalama yasagi "asiri" bolgeye)
  2. FAST hat esikleri 3,8x · COUNCIL hat esigi 6,0x
  3. TrendMotor + KarKilidi + PozisyonDefteri kapilari
  4. Siki trailing (tepe karin %82-88'i kilitli), zaman sonumlenme 15 dk -> 5 dk
  5. Ters yon zaman asimi (4 dk)
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import cekirdek
import hybrid_bot
from v2 import ortak


class HybridV2Plus(hybrid_bot.HybridV2):
    AD = "BOT3_HYBRID_V2"

    def __init__(self) -> None:
        super().__init__()
        self.filtre = cekirdek.Filtre(cekirdek.FiltreKurallari(
            min_vol_mult=3.8,
            min_ivme_pct=0.15,
            max_ivme_pct=1.60,
            min_akis=0.15,
            min_burst_usd=8000.0,
            max_chop=70.0,
            baz_dedupe_sec=15.0,
            sembol_cooldown_sec=90.0,
        ))
        self.fast = {"vol": 3.8, "akis": 0.15, "burst": 8000.0}
        self.council = {"vol": 6.0, "akis": 0.30, "burst": 12000.0, "chop": 60.0, "skor": 0.56}
        self.edge_esigi = 1.6

        self.be_trigger = 3.80
        self.be_lock = 1.30
        self.trail_trigger = 6.00
        self.giveback = (0.22, 0.14, 0.10)
        self.exhaustion_min = 4.20
        self.stagnation_sec = 300.0
        self.stagnation_min = 2.00
        self.kuyruk_ttl = 30.0

    # ---------------------------------------------------------- giris kapisi
    def _giris_dene(self, key: str) -> int:
        try:
            tape = self.tapes.get(key)
            if tape is None:
                return 0
            m = tape.metrik(12.0)
            if not m:
                return 0
            yon, _tetik = self._tetik(m)
            if yon == 0:
                return 0
            ok, _sebep = ortak.giris_izni(self.AD, tape.symbol, yon, m.get("ts", time.time()))
            if not ok:
                return 0
        except Exception:
            return super()._giris_dene(key)
        return super()._giris_dene(key)

    # ---------------------------------------------------------- cikis kapisi
    def _yonet(self) -> None:
        super()._yonet()
        if not self.pozisyonlar:
            return
        simdi = time.time()
        for pid in list(self.pozisyonlar.keys()):
            pos = self.pozisyonlar.get(pid)
            if pos is None:
                continue
            px = self._fiyat(pos.key)
            if px <= 0:
                continue
            net = pos.net(px)
            taban = ortak.siki_taban(pos.zirve_net)
            if taban is not None and net <= taban:
                self._kapat(pos, px, "V2_SIKI_TRAILING_KAR_AL")
                continue
            if ortak.ters_zaman_asimi(pos.ts, pos.zirve_net, net, simdi):
                self._kapat(pos, px, "V2_TERS_YON_ZAMAN_ASIMI")

    def ek_snapshot(self) -> Dict[str, Any]:
        ek = super().ek_snapshot()
        ek["koruma_veto"] = dict(ortak.VETO.get(self.AD, {}))
        return ek


if __name__ == "__main__":
    h = HybridV2Plus()
    print("HybridV2Plus hazir:", h.AD, h.filtre.k)
