# -*- coding: utf-8 -*-
"""sinyaller.py — 4 dedektör + oy birliği komitesi.

Dedektörler arşivdeki 2.414 dosyadan çıkan tekrar eden fikirlerin *ölçülebilir*
hâlleridir; hiçbiri tek başına "kenar" iddiası taşımaz:
  hacim_kirilim     : hacmin 3x üstü + pencerenin kırılması
  parabolik_tukenis : oynaklığın 2.2 katı tek yönlü hareket → dönüş
  biyik_donus       : pencere ucunda alıcı/satıcı tükenmesi
  vwap_donus        : VWAP'a geri çekilip yönü sürdürme

Komite kuralı: aynı sembolde zıt yönde iki sinyal varsa **işlem yok**.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bot.v8.types import Yon
from .rejim import Hafiza, REJIM_KAPISI, Rejim, RejimSonucu


@dataclass(frozen=True)
class Aday:
    baz: str
    yon: Yon
    skor: float
    motor: str
    gerekce: str
    ts: float


def _k(skor: float) -> float:
    return round(max(0.0, min(1.0, skor)), 4)


def hacim_kirilim(h: Hafiza, r: RejimSonucu, ts: float, hacim_esigi: float = 3.0) -> Aday | None:
    if "hacim_kirilim" not in REJIM_KAPISI[r.rejim] or not h.hazir:
        return None
    ust, alt = h.kirilim()
    ho = h.hacim_orani
    if ho < hacim_esigi:
        return None
    taban = 0.50 + 0.10 * math.log2(max(1.0, ho)) + 0.10 * min(1.0, r.guc / 2)
    if h.fiyat > ust and h.delta_orani >= 0.55:
        return Aday(h.baz, Yon.LONG, _k(taban), "hacim_kirilim",
                    f"üst kırılım {h.fiyat:.6g}>{ust:.6g}, hacim {ho:.1f}x", ts)
    if h.fiyat < alt and h.delta_orani <= 0.45:
        return Aday(h.baz, Yon.SHORT, _k(taban), "hacim_kirilim",
                    f"alt kırılım {h.fiyat:.6g}<{alt:.6g}, hacim {ho:.1f}x", ts)
    return None


def parabolik_tukenis(h: Hafiza, r: RejimSonucu, ts: float, kat: float = 2.2) -> Aday | None:
    if "parabolik_tukenis" not in REJIM_KAPISI[r.rejim] or not h.hazir or h.oynaklik <= 0:
        return None
    sapma = abs(h.ema_hizli / h.ema_yavas - 1.0) / h.oynaklik
    if sapma < kat:
        return None
    skor = _k(0.55 + 0.08 * min(3.0, sapma - kat))
    if h.ema_hizli > h.ema_yavas and h.delta_orani < 0.48:
        return Aday(h.baz, Yon.SHORT, skor, "parabolik_tukenis",
                    f"sapma {sapma:.2f}x oynaklık, delta {h.delta_orani:.2f}", ts)
    if h.ema_hizli < h.ema_yavas and h.delta_orani > 0.52:
        return Aday(h.baz, Yon.LONG, skor, "parabolik_tukenis",
                    f"sapma {sapma:.2f}x oynaklık, delta {h.delta_orani:.2f}", ts)
    return None


def biyik_donus(h: Hafiza, r: RejimSonucu, ts: float, esik: float = 0.0015) -> Aday | None:
    if "biyik_donus" not in REJIM_KAPISI[r.rejim] or not h.hazir:
        return None
    ust, alt = h.kirilim()
    if ust <= 0 or alt <= 0:
        return None
    tepeye = (ust - h.fiyat) / ust
    dibe = (h.fiyat - alt) / alt
    if tepeye <= esik and h.delta_orani < 0.40:
        return Aday(h.baz, Yon.SHORT, _k(0.52 + (0.40 - h.delta_orani)), "biyik_donus",
                    f"tepede tükenme, delta {h.delta_orani:.2f}", ts)
    if dibe <= esik and h.delta_orani > 0.60:
        return Aday(h.baz, Yon.LONG, _k(0.52 + (h.delta_orani - 0.60)), "biyik_donus",
                    f"dipte tükenme, delta {h.delta_orani:.2f}", ts)
    return None


def vwap_donus(h: Hafiza, r: RejimSonucu, ts: float, mesafe: float = 0.0015) -> Aday | None:
    if "vwap_donus" not in REJIM_KAPISI[r.rejim] or not h.hazir or h.vwap <= 0:
        return None
    sapma = h.fiyat / h.vwap - 1.0
    if abs(sapma) > mesafe or h.hacim_orani < 1.2:
        return None
    skor = _k(0.50 + 0.15 * min(1.0, r.guc))
    if r.rejim is Rejim.TREND_YUKARI and sapma >= 0:
        return Aday(h.baz, Yon.LONG, skor, "vwap_donus", f"VWAP üstü trend devamı ({sapma:+.3%})", ts)
    if r.rejim is Rejim.TREND_ASAGI and sapma <= 0:
        return Aday(h.baz, Yon.SHORT, skor, "vwap_donus", f"VWAP altı trend devamı ({sapma:+.3%})", ts)
    return None


DEDEKTORLER = (hacim_kirilim, parabolik_tukenis, biyik_donus, vwap_donus)


@dataclass(frozen=True)
class KomiteKarari:
    aday: Aday | None
    oylar: tuple[str, ...]
    celiski: bool


def komite(h: Hafiza, r: RejimSonucu, ts: float, min_skor: float = 0.55) -> KomiteKarari:
    # RVOL Filtresi: Düşük hacimli sahte kırılımları engellemek için hacim teyidi şarttır
    if h.hacim_orani < 1.5:
        return KomiteKarari(None, (), False)
    adaylar = [a for a in (f(h, r, ts) for f in DEDEKTORLER) if a is not None]
    if not adaylar:
        return KomiteKarari(None, (), False)
    if len({a.yon for a in adaylar}) > 1:
        return KomiteKarari(None, tuple(a.motor for a in adaylar), True)
    toplam = 0.0
    for a in adaylar:
        toplam = 1.0 - (1.0 - toplam) * (1.0 - a.skor * 0.85)
    en = max(adaylar, key=lambda a: a.skor)
    birlesik = Aday(en.baz, en.yon, _k(toplam), "+".join(a.motor for a in adaylar),
                    "; ".join(a.gerekce for a in adaylar), ts)
    if birlesik.skor < min_skor:
        return KomiteKarari(None, tuple(a.motor for a in adaylar), False)
    return KomiteKarari(birlesik, tuple(a.motor for a in adaylar), False)
