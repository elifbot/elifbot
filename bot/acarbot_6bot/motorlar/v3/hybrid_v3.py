# -*- coding: utf-8 -*-
"""BOT 3 v3 — HYBRID V3+.

8 botluk testte HYBRID v2 (-9,40 $) v1'in (+21,89 $) gerisinde kaldi. Sebep net olculdu:
  1. ivme tavani 0,60 -> 1,60 gevsetilince BARD LONG +%1,54 giris yapildi -> -20,03 $
     (v1'in 0,60 tavani bu girisi reddediyordu ve v1 6/6 kazandi)
  2. stagnation hasadi 900 -> 300 sn yapilinca islem 6'dan 13'e cikti (churn)

v3 duzeltmeleri (yalniz bu iki bot icin, kazanan ayarlarina hizalandi):
  FIX 2  ivme tavani KAZANAN degerine dondu: %0,60. Ustu sadece "istisna" ile serbest:
         hacim >= 8x + akis >= 0,35 + burst >= 25.000 $ (v3/ortak.ivme_izni)
  FIX 3  min hacim kati 3,8x -> 4,5x (marjinal 4,2-4,3x girisler elenir)
  FIX 4  stagnation 300 -> 900 sn (kazanan v1 degeri; churn bitti)
         min ivme 0,15 -> 0,18 · COUNCIL hatti v1 kazanan degerleri (7x / chop 55)
  FIX 1  ters zaman asimi sadece trend dondugunde
  FIX 5  golge defteri
Kar yonetimi v2'nin iyilestirdigi degerlerde: be 3,80 / kilit 1,30 · trail 6,00 ·
giveback (0,22 / 0,14 / 0,10) + siki taban.
"""
from __future__ import annotations

import time
from typing import Any, Dict

import cekirdek
import hybrid_bot
from v3 import ortak


class HybridV3Plus(hybrid_bot.HybridV2):
    AD = "BOT11_HYBRID_V3"

    def __init__(self) -> None:
        super().__init__()
        self.filtre = cekirdek.Filtre(cekirdek.FiltreKurallari(
            min_vol_mult=4.5,
            min_ivme_pct=0.18,
            max_ivme_pct=1.60,          # sert tavan; 0,60 ustu icin ortak.ivme_izni istisnasi
            min_akis=0.15,
            min_burst_usd=8000.0,
            max_chop=64.0,
            baz_dedupe_sec=15.0,
            sembol_cooldown_sec=90.0,
        ))
        self.fast = {"vol": 4.5, "akis": 0.15, "burst": 8000.0}
        self.council = {"vol": 7.0, "akis": 0.30, "burst": 12000.0, "chop": 55.0, "skor": 0.56}
        self.edge_esigi = 1.6

        self.be_trigger = 3.80
        self.be_lock = 1.30
        self.trail_trigger = 6.00
        self.giveback = (0.22, 0.14, 0.10)
        self.exhaustion_min = 4.20
        self.stagnation_sec = 900.0     # FIX 4 — kazanan v1 degeri
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
            # FIX 2 — kosullu ivme tavani
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
    h = HybridV3Plus()
    print("HybridV3Plus hazir:", h.AD, h.filtre.k)
