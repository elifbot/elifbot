# -*- coding: utf-8 -*-
"""digest.py — konu başına 8K token'a sığan kanıt demeti.

Kural: her satırın kaynağı `dosya:satır` olarak yazılır. Model bir iddiada bulunursa
kaynağı göstermek zorunda kalır; biz de sonradan doğrulayabiliriz.

Kullanım:
  python3 -m havuz.digest                # 6 demet üretir
  python3 -m havuz.digest --konu risk --butce 20000
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from .indeks import ETIKETLER, KOK

VARSAYILAN_BUTCE = 22_000          # karakter (~6-7K token, 8K sınırının altında)

KONULAR: dict[str, dict] = {
    "giris": {"etiket": "giris", "yan": ("hacim", "rejim"),
              "soru": "Giriş sinyalleri: hangi kurulum gerçekten tekrar edilebilir? "
                      "Hangileri gürültüden ibaret ve neden?"},
    "cikis": {"etiket": "stop", "yan": ("trailing",),
              "soru": "Çıkış ve zarar kes: stop bütçesi (-10 $ net) korunurken kâr nasıl taşınır? "
                      "BE/trailing eşikleri kayma ve komisyonla nasıl uyumlu olur?"},
    "risk": {"etiket": "risk", "yan": ("stop",),
             "soru": "50 $ teminat / 10x / CROSS dünyasında portföy düzeyi risk nedir? "
                     "Eşzamanlı pozisyon, korelasyon ve tasfiye mesafesi nasıl yönetilir?"},
    "veri": {"etiket": "veri", "yan": ("hacim",),
             "soru": "Veri hattı: tick kalitesi, boşluk, saat kayması ve replay tutarlılığı. "
                     "Sentetik ile gerçek veri arasındaki farkı ölçümde nasıl ayırırız?"},
    "icra": {"etiket": "icra", "yan": ("risk",),
             "soru": "Emir icrası: post-only, kısmi dolum, amend, idempotency ve kayma. "
                     "Hangi hata sınıfı gerçek parada pahalıya patlar?"},
    "ops": {"etiket": "ops", "yan": ("veri",),
            "soru": "Operasyon: log, gözlem, kopma, yeniden başlatma ve silah bırakma (kill switch). "
                    "Bir botu 7/24 ayakta tutmak için asgari ne gerekir?"},
}


def _skor(kayit: dict, ana: str, yan: tuple[str, ...]) -> float:
    e = kayit["etiket"]
    # log ölçek: 5.000 kez "stop" geçen bir JSON, 40 kez geçen bir tasarım notunu ezmesin
    s = math.log1p(e.get(ana, 0)) + 0.35 * sum(math.log1p(e.get(y, 0)) for y in yan)
    if kayit["yol"].endswith(".py"):
        s *= 1.6                      # kod, dokümandan daha somut kanıt
    if kayit["yol"].endswith((".patch", ".diff")):
        s *= 1.2
    if kayit["bayt"] < 400:
        s *= 0.5                      # tek satırlık dosya kanıt sayılmaz
    if kayit["yol"].endswith((".json", ".html", ".txt")):
        s *= 0.45                     # veri/gömleç dosyaları anlatı taşımaz
    return s


def _pencereler(metin: str, desen: re.Pattern, en_fazla: int = 3,
                baglam: int = 3) -> list[tuple[int, int, str]]:
    """En yoğun (etiket geçişi en çok) pencereleri seçer — ilk rastlananı değil."""
    satirlar = metin.splitlines()
    kucuk = [x.lower() for x in satirlar]
    isabet = [1 if desen.search(x) else 0 for x in kucuk]
    adaylar: list[tuple[float, int, int]] = []
    for i in range(len(satirlar)):
        lo, hi = max(0, i - baglam), min(len(satirlar), i + baglam + 1)
        yogunluk = sum(isabet[lo:hi])
        if yogunluk == 0:
            continue
        metin_uzunluk = sum(len(satirlar[j].strip()) for j in range(lo, hi))
        if metin_uzunluk < 60:
            continue
        adaylar.append((yogunluk + metin_uzunluk / 400.0, lo, hi))
    adaylar.sort(reverse=True)

    secilen: list[tuple[int, int, str]] = []
    kullanilan: set[int] = set()
    for _, lo, hi in adaylar:
        if any(j in kullanilan for j in range(lo, hi)):
            continue
        kullanilan.update(range(lo, hi))
        parca = "\n".join(satirlar[lo:hi]).strip("\n")
        if len(parca.strip()) < 40:
            continue
        secilen.append((lo + 1, hi, parca))
        if len(secilen) >= en_fazla:
            break
    secilen.sort(key=lambda x: x[0])
    return secilen


def demet(konu: str, kayitlar: list[dict], butce: int = VARSAYILAN_BUTCE) -> str:
    ayar = KONULAR[konu]
    desen = ETIKETLER[ayar["etiket"]]
    adaylar = sorted(kayitlar, key=lambda k: -_skor(k, ayar["etiket"], ayar["yan"]))
    govde: list[str] = []
    boy = 0
    gorulen: set[str] = set()
    for k in adaylar[:40]:
        if k["sha256"] in gorulen:      # aynı dosya birden fazla arşivde: bir kez
            continue
        gorulen.add(k["sha256"])
        p = KOK / k["yol"]
        try:
            metin = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        en_fazla_pencere = 3 if k["yol"].endswith(".py") else 2
        for lo, hi, parca in _pencereler(metin, desen, en_fazla=en_fazla_pencere):
            blok = f"\n#### {k['yol']}:{lo}-{hi}\n```\n{parca}\n```\n"
            if boy + len(blok) > butce:
                break
            govde.append(blok)
            boy += len(blok)
        if boy >= butce:
            break
    baslik = (f"# HAVUZ DEMETİ · {konu.upper()}\n\n"
              f"**Soru:** {ayar['soru']}\n\n"
              f"Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; "
              f"kanıt yoksa 'veri yok' de, uydurma.\n")
    return baslik + "".join(govde)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="havuz.digest")
    ap.add_argument("--konu", default="hepsi")
    ap.add_argument("--butce", type=int, default=VARSAYILAN_BUTCE)
    a = ap.parse_args(argv)

    kayitlar = [json.loads(s) for s in (KOK / "havuz" / "indeks.jsonl").read_text(
        encoding="utf-8").splitlines() if s.strip()]
    konular = list(KONULAR) if a.konu == "hepsi" else [a.konu]
    cikti_dir = KOK / "havuz" / "digest"
    cikti_dir.mkdir(exist_ok=True)

    for konu in konular:
        metin = demet(konu, kayitlar, a.butce)
        (cikti_dir / f"{konu}.md").write_text(metin, encoding="utf-8")
        kaynak = len(re.findall(r"^#### ", metin, flags=re.M))
        print(f"{konu:<8} {len(metin):>7,} karakter  ~{len(metin)//3.5:>6,.0f} token  "
              f"{kaynak:>3} kanıt parçası")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
