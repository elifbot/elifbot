# -*- coding: utf-8 -*-
"""signals.py — sinyal motorları. v1..v7'nin ölçülmüş davranışından süzülmüş üç dedektör.

Neden bu üçü:
  * TURBO/OMEGA'nın kazandığı işlemlerin tamamı **hacim patlaması + yönlü ivme**
    (maildeki 25 dk dökümü: 15/17 kazanan işlem bu tetikleyiciyle açılmış).
  * DÖRT/BEŞ'in 30 sembolde 25 dakikada 0 işlem üretmesinin nedeni tek eşikli
    filtre: hacim çöktüğünde devam sinyali aranırken patlama eşiği de aranıyordu.
    Burada ikisi ayrı dedektör.
  * Kaskad dönüşü (liquidation flush) ayrı bir rejim: orada ivmeyi kovalamak
    değil, aşırı hareketin geri dönüşünü almak gerekir; stop aynı -10 $.

Her dedektör `Sinyal` döner; `SinyalKomitesi` bunları tek pozisyona indirger.
Kovalama yasağı burada değil `risk.RiskYoneticisi`'nde uygulanır (tek yer, tek kural).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .config import MotorAyarlari
from .types import Sinyal, Tick, Yon


@dataclass
class Tape:
    """Sembol başına kayan pencere (varsayılan 60 sn)."""

    baz: str
    pencere_sn: float = 60.0
    kova: deque = field(default_factory=lambda: deque(maxlen=600))

    def ekle(self, t: Tick) -> None:
        self.kova.append((t.ts, t.fiyat, t.delta_usd, t.alis_usd))
        while self.kova and self.kova[0][0] < t.ts - self.pencere_sn * 3:
            self.kova.popleft()

    def _dilim(self, simdi: float, saniye: float) -> list[tuple]:
        return [k for k in self.kova if k[0] >= simdi - saniye]

    def metrik(self, simdi: float, saniye: float) -> dict:
        d = self._dilim(simdi, saniye)
        if len(d) < 2:
            return {}
        hacim = sum(k[2] for k in d)
        alis = sum(k[3] for k in d)
        ilk, son = d[0][1], d[-1][1]
        ret = (son / ilk - 1.0) * 100.0 if ilk > 0 else 0.0
        bias = (2.0 * alis / hacim - 1.0) if hacim > 0 else 0.0

        # referans: aynı uzunlukta önceki pencerelerin ortalaması
        gecmis = [k for k in self.kova if k[0] < simdi - saniye]
        if gecmis:
            dilim_sn = max(1e-6, (gecmis[-1][0] - gecmis[0][0]) / max(1, len(gecmis)))
            pencere_sayisi = len(gecmis) / max(1.0, saniye / dilim_sn)
            referans = sum(k[2] for k in gecmis) / max(1.0, pencere_sayisi)
        else:
            referans = hacim
        vol_mult = hacim / referans if referans > 0 else 0.0

        # hacim çöküşü: son 3 sn'nin hacmi, pencerenin en yoğun 3 sn'sine oranı
        son3 = sum(k[2] for k in self._dilim(simdi, 3.0))
        en_yogun = 0.0
        for i in range(len(d)):
            j = i
            toplam = 0.0
            while j < len(d) and d[j][0] <= d[i][0] + 3.0:
                toplam += d[j][2]
                j += 1
            en_yogun = max(en_yogun, toplam)
        cokus = (son3 / en_yogun) if en_yogun > 0 else 1.0

        return {
            "hacim_usd": hacim, "alis_usd": alis, "ret_pct": ret,
            "bias": bias, "vol_mult": vol_mult, "cokus": cokus,
            "fiyat": son, "ilk_fiyat": ilk, "ornek": len(d),
        }


class Dedektor:
    ad = "temel"

    def __init__(self, ayar: MotorAyarlari) -> None:
        self.ayar = ayar

    def bak(self, baz: str, m: dict, simdi: float) -> Sinyal | None:  # pragma: no cover
        raise NotImplementedError


class HacimPatlamasi(Dedektor):
    """Hacim patlaması + yönlü ivme: patlama yönüne devam."""

    ad = "HACIM_PATLAMASI"

    def bak(self, baz, m, simdi):
        a = self.ayar
        if not m or m["vol_mult"] < a.hacim_carpan_esigi:
            return None
        if m["hacim_usd"] < a.min_patlama_usd:
            return None
        if abs(m["ret_pct"]) < a.min_hiz_pct:
            return None
        yon = Yon.LONG if m["ret_pct"] > 0 else Yon.SHORT
        if m["bias"] * yon.value < a.min_akim_biyasi:
            return None
        skor = min(1.0, 0.45 * min(m["vol_mult"] / (a.hacim_carpan_esigi * 2), 1.0)
                   + 0.30 * min(abs(m["ret_pct"]) / (a.min_hiz_pct * 3), 1.0)
                   + 0.25 * min(abs(m["bias"]) / 0.6, 1.0))
        return Sinyal(baz=baz, yon=yon, skor=round(skor, 3), motor=self.ad,
                      gerekce=f"{m['vol_mult']:.1f}x hacim | {m['ret_pct']:+.2f}% | "
                              f"bias {m['bias']:+.2f} | {m['hacim_usd']/1000:.0f}k$",
                      ts=simdi, giris_tipi="maker_sonra_taker")


class HacimCokusu(Dedektor):
    """Patlama sonrası hacim çöküşü: hareket bitti, trend devam ediyor."""

    ad = "HACIM_COKUSU"

    def bak(self, baz, m, simdi):
        a = self.ayar
        if not m or m["vol_mult"] < 2.0:
            return None
        if m["cokus"] > a.hacim_cokus_orani:
            return None
        if abs(m["ret_pct"]) < a.min_hiz_pct * 0.5:
            return None
        yon = Yon.LONG if m["ret_pct"] > 0 else Yon.SHORT
        skor = min(1.0, 0.5 * (1.0 - m["cokus"]) + 0.3 * min(m["vol_mult"] / 8.0, 1.0)
                   + 0.2 * min(abs(m["ret_pct"]) / 1.5, 1.0))
        return Sinyal(baz=baz, yon=yon, skor=round(skor, 3), motor=self.ad,
                      gerekce=f"çöküş {m['cokus']:.2f} | {m['vol_mult']:.1f}x | "
                              f"{m['ret_pct']:+.2f}%",
                      ts=simdi, giris_tipi="maker_sonra_taker")


class KaskadDonus(Dedektor):
    """Aşırı tek yönlü hacim patlaması + aşırı hareket: geri dönüş (fade)."""

    ad = "KASKAD_DONUS"

    def bak(self, baz, m, simdi):
        a = self.ayar
        if not m or m["vol_mult"] < a.hacim_carpan_esigi * 2.0:
            return None
        if abs(m["ret_pct"]) < max(1.2, a.min_hiz_pct * 3):
            return None
        # akış patlama yönündeyse (aşırı tek taraflı), ters yöne gir
        yon = Yon.SHORT if m["ret_pct"] > 0 else Yon.LONG
        if m["bias"] * (1 if m["ret_pct"] > 0 else -1) < 0.35:
            return None
        skor = min(1.0, 0.45 * min(m["vol_mult"] / 12.0, 1.0)
                   + 0.35 * min(abs(m["ret_pct"]) / 3.0, 1.0)
                   + 0.20 * min(abs(m["bias"]) / 0.8, 1.0))
        return Sinyal(baz=baz, yon=yon, skor=round(skor, 3), motor=self.ad,
                      gerekce=f"kaskad {m['ret_pct']:+.2f}% / {m['vol_mult']:.1f}x / "
                              f"bias {m['bias']:+.2f}",
                      ts=simdi, giris_tipi="market")


class SinyalKomitesi:
    """Dedektörleri çalıştırır, sembol başına en yüksek skoru seçer."""

    def __init__(self, ayar: MotorAyarlari | None = None, min_skor: float = 0.55) -> None:
        self.ayar = ayar or MotorAyarlari()
        self.min_skor = min_skor
        self.dedektorler = [HacimPatlamasi(self.ayar), HacimCokusu_(self.ayar), KaskadDonus(self.ayar)]

    def degerlendir(self, tape: Tape, baz: str, simdi: float) -> Sinyal | None:
        m = tape.metrik(simdi, self.ayar.patlama_pencere_sn)
        if not m:
            return None
        en_iyi = None
        for d in self.dedektorler:
            try:
                s = d.bak(baz, m, simdi)
            except Exception:
                s = None
            if s and s.skor >= self.min_skor and (en_iyi is None or s.skor > en_iyi.skor):
                en_iyi = s
        return en_iyi


HacimCokusu_ = HacimCokusu  # geriye dönük isim uyumu
