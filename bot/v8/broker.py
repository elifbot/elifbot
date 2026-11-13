# -*- coding: utf-8 -*-
"""broker.py — simülasyon borsası. Borsanın **fiziğini** uygular, hayal kurmaz.

Eski 6-bot paketinin en büyük yapısal hatası: `enforce_free_equity_check=False` ile
1.000 $ kasada 8.700 $ teminat kullanılmış gibi 174 pozisyon açması. Gerçek borsada
bu emirlerin %85'i "insufficient margin" ile reddedilir.

Bu broker üç şeyi zorunlu kılar:
  1. Serbest teminat yetmiyorsa emir REDDEDİLİR.
  2. Stop emri borsada **duran** bir emirdir; tick'te kontrol edilmez, tetiklendiğinde
     market olarak dolar (kayma dahil). Bu yüzden "kâr kilidi" zarara dönüşemez.
  3. CROSS marj: bakım marjı biterse pozisyon(lar) tasfiye edilir, kasa eksiye düşebilir.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .config import KasaKurallari
from .types import (EmirDurumu, EmirIstegi, EmirSonucu, EmirTipi, Enstruman,
                    KasaDurumu, Yon)


@dataclass
class Dolum:
    sembol: str
    yon: Yon
    adet: float
    fiyat: float
    komisyon_usd: float
    ts: float
    istemci_id: str
    kismi: bool = False


@dataclass
class BorsaPozisyonu:
    sembol: str
    baz: str
    yon: Yon
    adet: float
    giris: float
    teminat_usd: float
    komisyon_usd: float
    acilis_ts: float


@dataclass
class DuranEmir:
    emir_id: str
    istemci_id: str
    sembol: str
    baz: str
    yon: Yon
    tip: EmirTipi
    adet: float
    tetik: float
    reduce_only: bool
    olusturma_ts: float
    gecerlilik_sn: float = 0.0   # 0 = süresiz


@dataclass
class SimuleBorsa:
    """Tek borsa örneği. Binance ve OKX için ayrı ayrı kurulur (kasa bölünmez)."""

    ad: str
    kurallar: KasaKurallari
    kasa_usd: float = 1000.0
    bakim_marj_orani: float = 0.005
    kayma_bps_taban: float = 2.0
    enstrumanlar: dict[str, Enstruman] = field(default_factory=dict)
    pozisyonlar: dict[str, BorsaPozisyonu] = field(default_factory=dict)
    duran: dict[str, DuranEmir] = field(default_factory=dict)
    dolumlar: list[Dolum] = field(default_factory=list)
    son_fiyat: dict[str, float] = field(default_factory=dict)
    hacim24: dict[str, float] = field(default_factory=dict)
    realize_usd: float = 0.0
    komisyonlar_usd: float = 0.0
    tasfiye_sayisi: int = 0
    emir_sayaci: int = 0

    # ------------------------------------------------------------- yardımcı
    def _fiyat(self, sembol: str) -> float:
        return self.son_fiyat.get(sembol, 0.0)

    def _kayma(self, sembol: str, notional: float) -> float:
        """Hacme göre kayma oranı: taban + (emir/24s hacim)^0.5 ölçekli etki."""
        h = max(1.0, self.hacim24.get(sembol, 1.0))
        etki = math.sqrt(max(0.0, notional) / h) * 0.002
        return (self.kayma_bps_taban / 10_000.0) + min(0.004, etki)

    def kullanilan_teminat(self) -> float:
        return sum(p.teminat_usd for p in self.pozisyonlar.values())

    def acik_pnl(self) -> float:
        toplam = 0.0
        for p in self.pozisyonlar.values():
            px = self._fiyat(p.sembol) or p.giris
            toplam += p.yon.value * (px / p.giris - 1.0) * (p.adet * p.giris
                                                             * (self.enstrumanlar[p.sembol].kontrat_carpani
                                                                if p.sembol in self.enstrumanlar else 1.0))
        return toplam

    def kasa_durumu(self) -> KasaDurumu:
        acik = self.acik_pnl()
        return KasaDurumu(
            kasa_usd=round(self.kasa_usd, 4), realize_usd=round(self.realize_usd, 4),
            acik_pnl_usd=round(acik, 4), kullanilan_teminat_usd=round(self.kullanilan_teminat(), 4),
            serbest_teminat_usd=round(self.kasa_usd - self.kullanilan_teminat(), 4),
            acik_pozisyon=len(self.pozisyonlar),
        )

    def serbest_teminat(self) -> float:
        return self.kasa_usd - self.kullanilan_teminat()

    # ---------------------------------------------------------------- emir
    def emir_gonder(self, istek: EmirIstegi, ts: float | None = None) -> EmirSonucu:
        ts = ts if ts is not None else time.time()
        px = self._fiyat(istek.sembol)
        if px <= 0:
            return EmirSonucu(False, hata="FIYAT_YOK")

        if istek.tip in (EmirTipi.STOP_MARKET, EmirTipi.TAKE_PROFIT_MARKET):
            self.emir_sayaci += 1
            eid = f"{self.ad}-{self.emir_sayaci}"
            self.duran[eid] = DuranEmir(
                emir_id=eid, istemci_id=istek.istemci_id or eid, sembol=istek.sembol,
                baz=istek.meta.get("baz", istek.sembol), yon=istek.yon, tip=istek.tip,
                adet=istek.adet, tetik=float(istek.fiyat or 0.0),
                reduce_only=istek.reduce_only, olusturma_ts=ts,
                gecerlilik_sn=float(istek.meta.get("gecerlilik_sn", 0.0)),
            )
            return EmirSonucu(True, emir_id=eid, durum=EmirDurumu.YENI)

        # --- market / limit dolumu
        poz = self.pozisyonlar.get(istek.sembol)
        if istek.reduce_only and (poz is None or poz.adet <= 0):
            return EmirSonucu(False, hata="AZALTACAK_POZISYON_YOK")

        if not istek.reduce_only:
            teminat = istek.adet * px * self.enstrumanlar[istek.sembol].kontrat_carpani \
                / self.kurallar.kaldirac
            if teminat > self.serbest_teminat() + 1e-9:
                return EmirSonucu(False, hata=f"TEMINAT_YETERSIZ (gerek {teminat:.2f}$)")

        kayma = self._kayma(istek.sembol, istek.adet * px)
        if istek.tip is EmirTipi.LIMIT and istek.post_only:
            # post-only: sadece pasif tarafta dolar; basit model, iyileştirme yoksa dolmaz
            limit = float(istek.fiyat or px)
            uygun = (istek.yon is Yon.LONG and limit <= px * (1 - kayma)) or \
                    (istek.yon is Yon.SHORT and limit >= px * (1 + kayma))
            if not uygun:
                return EmirSonucu(False, hata="POST_ONLY_AGRESIF")
            dolum_px = limit
            oran = self.kurallar.maker_fee_orani
        else:
            dolum_px = px * (1 + kayma) if istek.yon is Yon.LONG else px * (1 - kayma)
            oran = self.kurallar.taker_fee_orani

        self.emir_sayaci += 1
        eid = f"{self.ad}-{self.emir_sayaci}"
        komisyon = istek.adet * dolum_px * self.enstrumanlar[istek.sembol].kontrat_carpani * oran
        self.komisyonlar_usd += komisyon
        self.kasa_usd -= komisyon

        if istek.reduce_only and poz is not None:
            self._pozisyon_kapat(poz, dolum_px, komisyon, ts)
        else:
            carpan = self.enstrumanlar[istek.sembol].kontrat_carpani
            notional = istek.adet * dolum_px * carpan
            self.pozisyonlar[istek.sembol] = BorsaPozisyonu(
                sembol=istek.sembol, baz=istek.meta.get("baz", istek.sembol), yon=istek.yon,
                adet=istek.adet, giris=dolum_px, teminat_usd=notional / self.kurallar.kaldirac,
                komisyon_usd=komisyon, acilis_ts=ts,
            )
            # marj, kasada kilitlenir: kasa_usd serbest bakiye değil, toplam özkaynak
        self.dolumlar.append(Dolum(istek.sembol, istek.yon, istek.adet, dolum_px,
                                   komisyon, ts, istek.istemci_id))
        return EmirSonucu(True, emir_id=eid, durum=EmirDurumu.DOLDU, dolen_adet=istek.adet,
                          ort_fiyat=round(dolum_px, 10))

    def emir_iptal(self, emir_id: str) -> bool:
        return self.duran.pop(emir_id, None) is not None

    def emir_degistir(self, emir_id: str, yeni_tetik: float) -> bool:
        e = self.duran.get(emir_id)
        if e is None:
            return False
        e.tetik = yeni_tetik
        return True

    # ---------------------------------------------------------------- tick
    def tick_islet(self, sembol: str, fiyat: float, hacim24_usd: float = 0.0) -> list[Dolum]:
        """Fiyatı günceller, duran stop emirlerini tetikler, tasfiyeyi kontrol eder."""
        if fiyat <= 0:
            return []
        self.son_fiyat[sembol] = fiyat
        if hacim24_usd > 0:
            self.hacim24[sembol] = hacim24_usd
        yeni: list[Dolum] = []

        for eid, e in list(self.duran.items()):
            if e.sembol != sembol or not e.reduce_only:
                continue
            tetiklendi = (e.yon is Yon.LONG and fiyat <= e.tetik) or \
                         (e.yon is Yon.SHORT and fiyat >= e.tetik)
            if not tetiklendi:
                continue
            poz = self.pozisyonlar.get(e.sembol)
            if poz is None:
                self.duran.pop(eid, None)
                continue
            kayma = self._kayma(e.sembol, poz.adet * fiyat)
            dolum = fiyat * (1 - kayma) if e.yon is Yon.LONG else fiyat * (1 + kayma)
            komisyon = poz.adet * dolum * self.enstrumanlar[e.sembol].kontrat_carpani \
                * self.kurallar.taker_fee_orani
            self.komisyonlar_usd += komisyon
            self.kasa_usd -= komisyon
            self._pozisyon_kapat(poz, dolum, komisyon, e.olusturma_ts)
            self.duran.pop(eid, None)
            yeni.append(Dolum(e.sembol, e.yon, poz.adet, dolum, komisyon,
                              e.olusturma_ts, e.istemci_id))

        if self._tasfiye_kontrol(fiyat):
            self.tasfiye_sayisi += 1
        return yeni

    # ------------------------------------------------------------- iç işleyiş
    def _pozisyon_kapat(self, poz: BorsaPozisyonu, cikis: float, komisyon: float,
                        ts: float) -> float:
        carpan = self.enstrumanlar[poz.sembol].kontrat_carpani
        brut = poz.yon.value * (cikis / poz.giris - 1.0) * (poz.adet * poz.giris * carpan)
        net = brut - komisyon
        self.realize_usd += net
        self.kasa_usd += net
        self.pozisyonlar.pop(poz.sembol, None)
        return net

    def _tasfiye_kontrol(self, son_fiyat: float) -> bool:
        """CROSS: özkaynak bakım marjının altına düşerse tüm pozisyonlar kapanır."""
        if not self.pozisyonlar:
            return False
        notional = sum(p.adet * (self._fiyat(p.sembol) or p.giris)
                       * self.enstrumanlar[p.sembol].kontrat_carpani
                       for p in self.pozisyonlar.values())
        bakim = notional * self.bakim_marj_orani
        ozkaynak = self.kasa_usd + self.acik_pnl()
        if ozkaynak > bakim:
            return False
        for sembol, p in list(self.pozisyonlar.items()):
            px = self._fiyat(sembol) or p.giris
            kayma = self._kayma(sembol, p.adet * px) * 3.0   # tasfiyede likidite kötü
            dolum = px * (1 - kayma) if p.yon is Yon.LONG else px * (1 + kayma)
            komisyon = p.adet * dolum * self.enstrumanlar[sembol].kontrat_carpani \
                * self.kurallar.taker_fee_orani
            self.kasa_usd -= komisyon
            net = self._pozisyon_kapat(p, dolum, komisyon, p.acilis_ts)
            self.dolumlar.append(Dolum(sembol, p.yon, p.adet, dolum, komisyon,
                                       p.acilis_ts, "TASFIYE", kismi=True))
            _ = net
        return True
