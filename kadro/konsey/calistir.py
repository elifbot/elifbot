# -*- coding: utf-8 -*-
"""calistir.py — `python3 -m kadro.konsey.calistir --gorev "..."`

Örnek:
  python3 -m kadro.konsey.calistir --gorev "v9'un kenarını artır" --saglayici github
  python3 -m kadro.konsey.calistir --kuru-kosu            # ağsız boru hattı testi
"""
from __future__ import annotations

import argparse
import os
import sys

from . import cikti
from .saglayici import SAGLAYICILAR, Butce
from .tartisma import Oturum, kos


def _hazir_saglayicilar(istenen: list[str]) -> list[str]:
    secili = []
    for ad in istenen:
        s = SAGLAYICILAR.get(ad)
        if s is None:
            continue
        if s.anahtar_env is None or os.environ.get(s.anahtar_env):
            secili.append(ad)
    return secili


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kadro.konsey.calistir")
    ap.add_argument("--gorev", default="Botun ölçülebilir kenarını artır: en yüksek etkili 5 değişiklik.")
    ap.add_argument("--saglayici", action="append", default=[],
                    help="github | nvidia | ollama (birden fazla verilebilir)")
    ap.add_argument("--model", action="append", default=[], help="sağlayıcı=model")
    ap.add_argument("--butce", type=int, default=24, help="azami model çağrısı")
    ap.add_argument("--tur", type=int, default=3)
    ap.add_argument("--etiket", default="")
    ap.add_argument("--kuru-kosu", action="store_true", help="ağ olmadan boru hattını dene")
    a = ap.parse_args(argv)

    istenen = a.saglayici or ["github", "nvidia", "ollama"]
    saglayicilar = ["github"] if a.kuru_kosu else _hazir_saglayicilar(istenen)
    if not saglayicilar:
        print("Hiçbir sağlayıcı hazır değil. GITHUB_TOKEN ya da NVIDIA_API_KEY gerekli.",
              file=sys.stderr)
        return 2

    modeller: dict[str, list[str | None]] = {s: [None] for s in saglayicilar}
    for m in a.model:
        if "=" in m:
            s, model = m.split("=", 1)
            modeller.setdefault(s, []).append(model)

    o = Oturum(gorev=a.gorev, saglayicilar=saglayicilar, modeller=modeller,
               butce=Butce(azami_cagri=a.butce))
    kos(o, kuru=a.kuru_kosu, turlar=a.tur)
    d = cikti.klasor(a.etiket or None)
    ozet = cikti.yaz(o, d)

    print(f"sağlayıcı : {', '.join(saglayicilar)}")
    print(f"çağrı     : {ozet['cagri']} (hata: {ozet['hata']})")
    print(f"karar     : {ozet['karar']}  düşen: {ozet['dusen']}")
    print(f"çıktı     : {ozet['klasor']}")
    return 0 if ozet["karar"] or a.kuru_kosu else 3


if __name__ == "__main__":
    raise SystemExit(main())
