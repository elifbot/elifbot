# -*- coding: utf-8 -*-
"""BOT 4 v3 — APEX V3.

HYBRID V3+ ile ayni duzeltilmiş giris kapisi (ivme tavani kazanan degerine dondu),
fark risk tavani ve daha siki kar yonetimi:
  - portfoy acik risk tavani kasanin %25'i
  - giveback %20 / %13 / %9 · trail 6,00 $ · BE 3,80 $ / kilit 1,30 $
  - stagnation 900 sn (FIX 4) · min hacim 4,5x (FIX 3) · kosullu ivme tavani (FIX 2)
"""
from __future__ import annotations

import time
from typing import Any, Dict

import cekirdek
import apex_bot
from v3 import ortak


class ApexV3(apex_bot.Apex):
    AD = "BOT12_APEX_V3"

    def __init__(self) -> None:
        super().__init__()
        self.filtre = cekirdek.Filtre(cekirdek.FiltreKurallari(
            min_vol_mult=4.5,
            min_ivme_pct=0.18,
            max_ivme_pct=1.60,
            min_akis=0.15,
            min_burst_usd=8000.0,
            max_chop=64.0,
            baz_dedupe_sec=15.0,
            sembol_cooldown_sec=90.0,
        ))
        self.max_open_risk_pct = 0.25
        self.be_trigger = 3.80
        self.be_lock = 1.30
        self.trail_trigger = 6.00
        self.giveback = (0.20, 0.13, 0.09)
        self.exhaustion_min = 4.20
        self.stagnation_sec = 900.0
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
            ok, _s = ortak.ivme_izni(self.AD, m.get("ret_burst_pct", 0.0),
                                     m.get("vol_mult", 0.0), m.get("orderflow_bias", 0.0),
                                     m.get("burst_usd", 0.0))
            if not ok:
                return 0
            ok, _sebep = ortak.giris_izni(self.AD, tape.symbol, yon,
                                          m.get("ts", time.time()), m.get("px"))
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
                self._kapat(pos, px, "V3_SIKI_TRAILING_KAR_AL")
                continue
            kes, sebep = ortak.ters_yon_asimi(pos.symbol, int(pos.yon), pos.ts,
                                              pos.zirve_net, net, simdi)
            if kes:
                self._kapat(pos, px, sebep)

    def ek_snapshot(self) -> Dict[str, Any]:
        ek = super().ek_snapshot()
        ek["koruma_veto"] = dict(ortak.VETO.get(self.AD, {}))
        return ek


if __name__ == "__main__":
    a = ApexV3()
    print("ApexV3 hazir:", a.AD)
