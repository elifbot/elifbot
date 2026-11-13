# -*- coding: utf-8 -*-
"""BOT 4 v2 — APEX V2.

HYBRID V2+ ile ayni giris mantigi; fark risk tavani ve daha siki kar yonetimidir:
  - portfoy acik risk tavani kasanin %25'i (max 12 pozisyon) korunur
  - giveback %20 / %13 / %9 (v1: %25 / %16 / %12)
  - trail 6,0 $ · BE 3,8 $ · zaman sonumlenme 5 dk
"""
from __future__ import annotations

import time
from typing import Any, Dict

import cekirdek
import apex_bot
from v2 import ortak


class ApexV2(apex_bot.Apex):
    AD = "BOT4_APEX_V2"

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
        self.max_open_risk_pct = 0.25
        self.be_trigger = 3.80
        self.be_lock = 1.30
        self.trail_trigger = 6.00
        self.giveback = (0.20, 0.13, 0.09)
        self.exhaustion_min = 4.20
        self.stagnation_sec = 300.0
        self.stagnation_min = 2.00

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
    a = ApexV2()
    print("ApexV2 hazir:", a.AD)
