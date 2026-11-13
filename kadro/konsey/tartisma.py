# -*- coding: utf-8 -*-
"""tartisma.py — 3 tur: öneri → itiraz → sekreter/oy.

Tur 1: her rol (ve istenirse her model) kendi demetinden öneri üretir.
Tur 2: her rol diğerlerinin önerisini eleştirir.
Tur 3: sekreter JSON karar listesi üretir; kural ihlali içeren kararlar kodla düşürülür.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import saglayici as sg
from .roller import ROLLER, itiraz_istemi, oneri_istemi, sekreter_istemi, yama_istemi

HAVUZ = Path(__file__).resolve().parents[2] / "havuz" / "digest"

# kural sayılarını değiştirmeye çalışan kararları yakalayan desen
KURAL_IHLALI = re.compile(
    r"(kasa(yı|sı)?\s*(1\s*\.?000|2000|200\s*\.?000)|"
    r"teminat\w*\s*(art|yükselt|100|25)\b|"
    r"kaldıra\w*\s*(art|yükselt|\b(20|25|50|100)x)|"
    r"stop\w*\s*(gevşet|kaldır|[-–]?\s*(20|30|50)\s*\$)|"
    r"pozisyon\s*(limiti|sınırı)\s*(koy|ekle))",
    re.IGNORECASE)


@dataclass
class Oturum:
    gorev: str
    saglayicilar: list[str]
    modeller: dict[str, list[str]]
    butce: sg.Butce
    oneriler: dict[str, str] = field(default_factory=dict)
    itirazlar: dict[str, str] = field(default_factory=dict)
    kararlar: list[dict] = field(default_factory=list)
    dusen: list[dict] = field(default_factory=list)
    hatalar: list[str] = field(default_factory=list)


def _demet_oku(konu: str) -> str:
    p = HAVUZ / f"{konu}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _paralel(fn, isler: list) -> list:
    """İşleri sınırlı eşzamanlılıkla çalıştırır (yavaş tek modelde süre kazanır)."""
    n = max(1, int(os.environ.get("ACARBOT_PARALEL") or 3))
    if n == 1 or len(isler) <= 1:
        return [fn(i) for i in isler]
    with ThreadPoolExecutor(max_workers=n) as havuz:
        return list(havuz.map(fn, isler))


def oneri_turu(o: Oturum, kuru: bool) -> None:
    roller = []
    for rol in ROLLER:
        demet = _demet_oku(rol.konu)
        if not demet:
            o.hatalar.append(f"demet yok: {rol.konu}")
            continue
        roller.append((rol, demet))

    def _bir(is_):
        rol, demet = is_
        parcalar = []
        for sag in o.saglayicilar:
            for model in o.modeller.get(sag, [None])[:1]:
                metin = sg.cagir(sag, oneri_istemi(rol, demet, o.gorev), model=model,
                                 butce=o.butce, rol=rol.ad, tur=1, kuru_kosu=kuru)
                if metin:
                    parcalar.append(metin.strip())
        return rol.ad, "\n\n".join(parcalar) if parcalar else ""

    for ad, metin in _paralel(_bir, roller):
        o.oneriler[ad] = metin


def itiraz_turu(o: Oturum, kuru: bool) -> None:
    isler = []
    for rol in ROLLER:
        kendi = o.oneriler.get(rol.ad, "")
        if not kendi:
            continue
        digerleri = {ad: m for ad, m in o.oneriler.items() if ad != rol.ad and m}
        if not digerleri:
            continue
        isler.append((rol, kendi, digerleri))

    def _bir(is_):
        rol, kendi, digerleri = is_
        metin = sg.cagir(o.saglayicilar[0], itiraz_istemi(rol, kendi, digerleri),
                         butce=o.butce, rol=rol.ad, tur=2, kuru_kosu=kuru)
        return rol.ad, (metin or "").strip()

    for ad, metin in _paralel(_bir, isler):
        if metin:
            o.itirazlar[ad] = metin


def _json_ayikla(metin: str) -> dict:
    m = re.search(r"\{.*\}", metin, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def sekreter_turu(o: Oturum, kuru: bool) -> None:
    if not o.oneriler:
        return
    from . import yama as ym
    sag = o.saglayicilar[0]
    istem = sekreter_istemi(o.oneriler, o.itirazlar, ym.indeks_metni())
    veri = {}
    for deneme in range(2):                    # sekreter tek hata noktası: bir kez daha dene
        if o.butce.bitti():
            break
        metin = sg.cagir(sag, istem, butce=o.butce, rol="sekreter", tur=3,
                         sicaklik=0.1, kuru_kosu=kuru)
        veri = _json_ayikla(metin)
        if veri.get("kararlar"):
            break
    for k in veri.get("kararlar", [])[:4]:
        metin_k = " ".join(str(k.get(x, "")) for x in ("baslik", "gerekce", "etki"))
        if KURAL_IHLALI.search(metin_k):
            o.dusen.append({**k, "neden": "değişmez kural ihlali"})
            continue
        if kuru:                                  # kuru koşuda kod doğrulaması atlanır
            o.kararlar.append({**k, "uygulanabilir": None, "yama": ""})
            continue
        dosya = str(k.get("dosya", ""))
        diff, hata = ym.yama_uret(dosya, str(k.get("eski_kod", "")), str(k.get("yeni_kod", "")))
        if hata:                              # onarım: dosyanın gerçek kaynağıyla tekrar dene
            yol = ym.KOK / dosya
            if yol.exists() and yol.suffix == ".py" and not o.butce.bitti():
                kaynak = yol.read_text(encoding="utf-8", errors="ignore")
                ham = sg.cagir(sag, yama_istemi(k, dosya, kaynak), butce=o.butce,
                               rol="yama", tur=3, sicaklik=0.0, kuru_kosu=kuru)
                v = _json_ayikla(ham) if ham else {}
                parcalar = v.get("degisiklikler") or []
                if parcalar:
                    diff, hata = ym.yama_uret_coklu(dosya, parcalar)
                    if not hata:
                        k = {**k, "degisiklikler": parcalar,
                             "eski_kod": parcalar[0].get("eski_kod", ""),
                             "yeni_kod": parcalar[0].get("yeni_kod", ""),
                             "aciklama": v.get("ozet", "")}
        if hata:
            o.dusen.append({**k, "neden": hata})
            continue
        gecerli, hata2 = ym.diff_uygula_denemesi(diff)
        if not gecerli:
            o.dusen.append({**k, "neden": hata2})
            continue
        o.kararlar.append({**k, "uygulanabilir": True, "yama": diff})


def kos(o: Oturum, kuru: bool = False, turlar: int = 3) -> Oturum:
    oneri_turu(o, kuru)
    if turlar >= 2:
        itiraz_turu(o, kuru)
    if turlar >= 3:
        sekreter_turu(o, kuru)
    return o
