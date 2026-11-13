# -*- coding: utf-8 -*-
"""risk.py — işlem öncesi kontroller, operasyonel durdurucular, kasa raporu.

İki ayrı şeyi karıştırmamak gerekir:

1) TİCARET KURALI (kullanıcının kararı): 1000 $ kasa, 50 $ teminat, 10x, CROSS,
   pozisyon limiti YOK, -10 $ stop. v8 bunları uygular, tartışmaz.

2) BORSANIN FİZİĞİ (pazarlık edilemez): bakiyede olmayan teminatla emir kabul
   edilmez; bakım marjı bitince pozisyon tasfiye edilir; stop emri market
   tetiklenir ve kayma yer. v8 bunları da uygular.

Eski 6-bot paketi (2) numarayı modellemediği için 1.000 $ kasayla 8.700 $ teminat
kullanılmış gibi görünüyordu. O tabloda kasa kâğıt üzerinde artıyordu; gerçek
borsada o emirlerin %85'i reddedilirdi.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from .config import KasaKurallari, MotorAyarlari
from .sizing import tasfiye_mesafesi_pct
from .types import Yon


@dataclass
class Karar:
    izin: bool
    nedenler: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.izin


@dataclass
class FiyatHafizasi:
    """Sembol başına son fiyat + kovalama yasağı için kısa geçmiş."""

    pencere: deque = field(default_factory=lambda: deque(maxlen=240))

    def ekle(self, ts: float, fiyat: float) -> None:
        self.pencere.append((ts, fiyat))

    def degisim(self, simdi: float, saniye: float) -> float | None:
        eski = None
        for ts, px in self.pencere:
            if ts >= simdi - saniye:
                eski = px
                break
        if eski is None or eski <= 0:
            return None
        return (self.pencere[-1][1] / eski - 1.0) * 100.0


class RiskYoneticisi:
    def __init__(self, ayar: MotorAyarlari | None = None,
                 kurallar: KasaKurallari | None = None) -> None:
        self.ayar = ayar or MotorAyarlari()
        self.kurallar = kurallar or KasaKurallari()
        self.fiyatlar: dict[str, FiyatHafizasi] = {}
        self.soguma: dict[str, float] = {}
        self.son_tick_ts: float = 0.0
        self.redler: deque = deque(maxlen=self.ayar.red_penceresi)
        self.durduruldu = False
        self.durdurma_nedeni = ""

    # ------------------------------------------------------------- durum
    def tick_gordu(self, ts: float) -> None:
        self.son_tick_ts = max(self.son_tick_ts, ts)

    def veri_bayat(self, simdi: float) -> bool:
        return (simdi - self.son_tick_ts) > self.ayar.veri_bayat_sn if self.son_tick_ts else False

    def durdur(self, neden: str) -> None:
        if not self.durduruldu:
            self.durduruldu = True
            self.durdurma_nedeni = neden

    def emir_sonucu(self, basarili: bool) -> None:
        self.redler.append(0 if basarili else 1)
        if len(self.redler) >= self.ayar.red_penceresi:
            oran = sum(self.redler) / len(self.redler)
            if oran >= self.ayar.red_orani_durdur:
                self.durdur(f"emir red oranı %{oran*100:.0f} — borsa/anahtar sorunu")

    # ---------------------------------------------------------- işlem öncesi
    def giris_izni(
        self,
        baz: str,
        yon: Yon,
        fiyat: float,
        simdi: float,
        kasa_usd: float,
        kullanilan_teminat_usd: float,
        acik_semboller: set[str],
        hacim24_usd: float,
        enstruman_durum: str = "live",
        sinyal_yasi: float = 0.0,
        spread_bps: float = 0.0,
    ) -> Karar:
        neden: list[str] = []

        if self.durduruldu:
            neden.append(f"SISTEM_DURDU: {self.durdurma_nedeni}")
        if self.veri_bayat(simdi):
            neden.append("VERI_BAYAT")
        if enstruman_durum != "live":
            neden.append(f"ENSTRUMAN_{enstruman_durum}")
        if sinyal_yasi > self.ayar.max_sinyal_yasi_sn:
            neden.append(f"SINYAL_ESKI ({sinyal_yasi:.1f}s)")
        if fiyat <= 0:
            neden.append("FIYAT_GECERSIZ")
        if hacim24_usd < self.ayar.min_24s_hacim_usd:
            neden.append(f"LIKIDITE_DUSUK ({hacim24_usd/1e6:.2f}M$)")
        if spread_bps > self.ayar.max_kayma_bps * 2:
            neden.append(f"SPREAD_GENIS ({spread_bps:.0f}bps)")
        if baz in acik_semboller:
            neden.append("AYNI_SEMBOLDE_POZISYON")
        if self.soguma.get(baz, 0.0) > simdi:
            neden.append(f"SOGUMA ({self.soguma[baz]-simdi:.0f}s)")

        # kovalama yasağı: son 30 sn'de %1.2'den fazla hareket varsa, o yöne girme
        hafiza = self.fiyatlar.get(baz)
        if hafiza is not None:
            degisim = hafiza.degisim(simdi, self.ayar.kovalama_pencere_sn)
            if degisim is not None and abs(degisim) >= self.ayar.kovalama_esik_pct:
                if (degisim > 0 and yon is Yon.LONG) or (degisim < 0 and yon is Yon.SHORT):
                    neden.append(f"KOVALAMA_YASAGI ({degisim:+.2f}%/30s)")

        # borsanın teminat fiziği: serbest teminat 50 $'dan azsa emir gitmez
        serbest = kasa_usd - kullanilan_teminat_usd
        gerekli = self.kurallar.teminat_per_pozisyon_usd
        if serbest < gerekli:
            neden.append(f"TEMINAT_YETERSIZ (serbest {serbest:.0f}$ < {gerekli:.0f}$)")

        return Karar(not neden, neden)

    # ------------------------------------------------------------ kayıt
    def fiyat_besle(self, baz: str, ts: float, fiyat: float) -> None:
        self.fiyatlar.setdefault(baz, FiyatHafizasi()).ekle(ts, fiyat)
        self.tick_gordu(ts)

    def sogut(self, baz: str, simdi: float) -> None:
        self.soguma[baz] = simdi + self.ayar.sembol_soguma_sn

    # ------------------------------------------------------------- rapor
    def kasa_raporu(self, kasa_usd: float, acik: int, kullanilan_teminat: float) -> dict:
        return {
            "kasa_usd": round(kasa_usd, 2),
            "acik_pozisyon": acik,
            "kullanilan_teminat_usd": round(kullanilan_teminat, 2),
            "serbest_teminat_usd": round(kasa_usd - kullanilan_teminat, 2),
            "kaldirac": round(10.0 * kullanilan_teminat / max(1e-9, kasa_usd), 2),
            "tasfiye_mesafesi_pct": round(100 * tasfiye_mesafesi_pct(
                kasa_usd, acik, self.kurallar), 2) if acik else None,
            "kural_limiti": "yok (kullanıcı kuralı)",
            "borsa_limiti": self.kurallar.max_es_zamanli_pozisyon(kasa_usd),
        }
