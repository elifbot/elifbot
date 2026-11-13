# -*- coding: utf-8 -*-
"""GÖLGE HESAP — "ÜÇ'ün filtresi TURBO ile aynı olsaydı ne olurdu?"

Ana 3 saatlik koşuya DOKUNMAZ (ayrı süreç, ayrı WS, ayrı defter).
İki gölge bot aynı canlı beslemeyi alır, ÜÇ'ün ÇIKIŞ kurallarını birebir kullanır
(-10 $ stop · BE 3,5 $ / 1,3 kilit · trail 6,0 $ / %22 · sıkı taban · tükeniş TP ·
 parabolik 15 $ · zombi 8 dk · 30 dk stagnation), sadece GİRİŞ filtresi değişir:

  ÜÇ-T : giriş filtresi = TURBO'nun kendi filtresi. TURBO motoru pozisyon açtığı an
         gölge bot da girer (2/2 anlaşma yok, zayıf-LONG yasağı yok, ivme/trend
         kapısı yok, kâr-sonrası kilit yok). = "filtreyi TURBO ile aynı yap".
  ÜÇ-G : 2/2 anlaşma + trend + ivme kapıları DURUR, sadece "zayıf LONG patlaması
         (hacim < 4,5x) yasak" kuralı kaldırılır. = ÜÇ'ün bugün 200+ sinyali neden
         reddettiğini ölçen ara varyant.

Koşu:  python3 -u golge_uc.py --saat 1.25 --sembol 30
Çıktı: logs/rapor_golge.json + logs/durum_golge.json (panel: --etiket golge)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import canli_3bot as kosucu
from v3 import ortak
from v5 import birlesik
from v5.birlesik import UcBot, UcPoz, TEMINAT, MAKS_MARJIN_PCT


class UcT(UcBot):
    """Giriş = TURBO'nun filtresi (her TURBO sinyali), çıkış = ÜÇ."""

    AD = "GOLGE_UC_T"

    def __init__(self) -> None:
        super().__init__()
        self.dedektorler = {"TURBO": self.turbo}
        self._besleme = {"TURBO": "ingest_batch"}

    def _girisleri_dene(self, simdi: float) -> None:
        for anahtar in list(self.oylar.keys()):
            oylar = [o for o in self.oylar[anahtar] if simdi - o["ts"] <= birlesik.OY_PENCERE]
            if not oylar:
                self.oylar.pop(anahtar, None)
                continue
            self.oylar[anahtar] = oylar
            b, yon = anahtar
            if any(p.base == b for p in self.pozisyonlar.values()):
                continue
            if self.kullanilan_teminat() + TEMINAT > self.equity() * MAKS_MARJIN_PCT:
                self.veto["MARJIN_SINIRI"] += 1
                continue
            en = max(oylar, key=lambda o: (o["vol"], abs(o["ivme"])))
            sembol = self.sembol.get(b)
            px = self.fiyat.get(sembol or "", 0.0)
            if not sembol or px <= 0:
                continue
            tetik = "TURBO_FILTRE · %s · %.1fx" % (en["tetik"][:34], en["vol"])
            pos = UcPoz(sembol, yon, px, simdi, tetik, "TURBO")
            self.pozisyonlar[pos.id] = pos
            self.oylar.pop(anahtar, None)


class UcG(UcBot):
    """2/2 anlaşma + trend + ivme durur; sadece zayıf-LONG yasağı kaldırıldı."""

    AD = "GOLGE_UC_G"

    def _girisleri_dene(self, simdi: float) -> None:
        for anahtar in list(self.oylar.keys()):
            oylar = [o for o in self.oylar[anahtar] if simdi - o["ts"] <= birlesik.OY_PENCERE]
            if not oylar:
                self.oylar.pop(anahtar, None)
                continue
            self.oylar[anahtar] = oylar
            b, yon = anahtar
            if any(p.base == b for p in self.pozisyonlar.values()):
                continue
            if self.kullanilan_teminat() + TEMINAT > self.equity() * MAKS_MARJIN_PCT:
                self.veto["MARJIN_SINIRI"] += 1
                continue
            if self.kilit.get(b, 0.0) > simdi:
                self.veto["KAR_SONRASI_KILIT"] += 1
                continue
            verenler = {o["ad"] for o in oylar}
            en = max(oylar, key=lambda o: (o["vol"], abs(o["ivme"])))
            vol, akis, ivme, burst = en["vol"], en["akis"], en["ivme"], en["burst"]
            if len(verenler) >= 2:
                neden = "IKI_MOTOR_ANLASMA"
            elif yon < 0 and vol >= birlesik.GUCLU_SHORT_HACIM and akis <= birlesik.GUCLU_SHORT_AKIS:
                neden = "GUCLU_COKUS_SHORT"
            else:
                continue
            ok, _s = ortak.ivme_izni(self.AD, ivme, vol, akis, burst)
            if not ok:
                continue
            sembol = self.sembol.get(b)
            px = self.fiyat.get(sembol or "", 0.0)
            if not sembol or px <= 0:
                continue
            uyumlu, _s2 = ortak.TREND.uyum(sembol, yon)
            if not uyumlu:
                self.veto["TREND_TERS_GIRIS"] += 1
                continue
            tetik = "%s · %s %s · %.1fx" % (neden, en["ad"], en["tetik"][:30], vol)
            pos = UcPoz(sembol, yon, px, simdi, tetik, "+".join(sorted(verenler)))
            self.pozisyonlar[pos.id] = pos
            self.oylar.pop(anahtar, None)


def motorlari_kur():
    return [
        ("GOLGE_UC_T", "GÖLGE · ÜÇ-T (giriş = TURBO filtresi)", UcT(), "ingest_batch", "v5"),
        ("GOLGE_UC_G", "GÖLGE · ÜÇ-G (2/2, zayıf LONG serbest)", UcG(), "ingest_batch", "v5"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="ÜÇ gölge hesapları (filtre karşılaştırması)")
    ap.add_argument("--saat", type=float, default=None)
    ap.add_argument("--dakika", type=float, default=60.0)
    ap.add_argument("--saniye", type=float, default=None)
    ap.add_argument("--sembol", type=int, default=30)
    ap.add_argument("--json", default="logs/rapor_golge.json")
    ap.add_argument("--etiket", default="golge")
    a = ap.parse_args()
    saniye = a.saniye if a.saniye else (a.saat * 3600.0 if a.saat else a.dakika * 60.0)
    kosucu.motorlari_kur = motorlari_kur
    return asyncio.run(kosucu.kosu(a.sembol, saniye, a.json, a.etiket))


if __name__ == "__main__":
    sys.exit(main())
