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
    ap.add_argument("--teshis", action="store_true",
                    help="sağlayıcı model listelerini yaz ve çık (ucuz, 1-2 çağrı)")
    a = ap.parse_args(argv)

    istenen = a.saglayici or ["github", "nvidia", "ollama"]
    saglayicilar = ["github"] if a.kuru_kosu else _hazir_saglayicilar(istenen)
    if not saglayicilar:
        print("Hiçbir sağlayıcı hazır değil. GITHUB_TOKEN ya da NVIDIA_API_KEY gerekli.",
              file=sys.stderr)
        return 2

    if a.teshis:
        from .saglayici import _tek_cagri, modeller_listele, SAGLAYICILAR as SP
        import json as _json
        from pathlib import Path as _Path
        d = _Path(__file__).resolve().parents[2] / "konsey" / (a.etiket or "teshis")
        d.mkdir(parents=True, exist_ok=True)
        rapor: dict[str, dict] = {}
        for s_ in saglayicilar:
            sp = SP[s_]
            katalog = modeller_listele(s_)
            sonuc = []
            # kataloğun tamamını değil, sohbet olabilecek ilk N tanesini dene
            import re as _re
            kok = _re.compile(r"instruct|chat|nemotron|deepseek|qwen|mistral|llama|gpt|phi|gemma", _re.I)
            adaylar = [m for m in katalog if kok.search(m)][:12] or katalog[:12]
            for m in adaylar:
                b = Butce(azami_cagri=1, azami_saniye=60)
                metin, hata = _tek_cagri(sp, m, [{"role": "user", "content": "ping"}],
                                         b, "teshis", 0, 0.0, 8, 20)
                sonuc.append({"model": m, "ok": bool(metin),
                              "hata": hata[:220], "yanit": (metin or "")[:40]})
                if metin:
                    break
            rapor[s_] = {"anahtar": bool(sp.anahtar()), "katalog": len(katalog),
                         "denenen": sonuc,
                         "calisan": next((x["model"] for x in sonuc if x["ok"]), None)}
            print(f"{s_}: katalog={len(katalog)} çalışan={rapor[s_]['calisan']}")
            for x in sonuc[:6]:
                print(f"   {'✓' if x['ok'] else '✗'} {x['model']}  {x['hata'][:110]}")
        (d / "teshis.json").write_text(_json.dumps(rapor, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        return 0

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

    hatalar = [c for c in o.butce.kayitlar if c.hata]
    print(f"sağlayıcı : {', '.join(saglayicilar)}")
    print(f"çağrı     : {ozet['cagri']} (hatalı: {len(hatalar)})")
    print(f"karar     : {ozet['karar']}  düşen: {ozet['dusen']}")
    print(f"çıktı     : {ozet['klasor']}")
    for h in hatalar[:5]:
        print(f"  ! {h.saglayici}/{h.model} tur{h.tur}: {h.hata}")
    # Karar çıkmasa bile oturum kaydı değerlidir (teşhis); CI'ı kırmayız.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
