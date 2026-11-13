# -*- coding: utf-8 -*-
"""cikti.py — oturum kayıtları: karar.md, oylar.json, yama.diff, oturum.json."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]


def klasor(etiket: str | None = None) -> Path:
    ad = etiket or time.strftime("%Y%m%d-%H%M%S")
    d = KOK / "konsey" / ad
    d.mkdir(parents=True, exist_ok=True)
    return d


def yaz(o, d: Path) -> dict:
    """Oturumu diske yazar; özet sözlük döndürür."""
    (d / "oneri.md").write_text(
        "\n\n".join(f"## {ad}\n{metin}" for ad, metin in o.oneriler.items()) or "(boş)",
        encoding="utf-8")
    (d / "itiraz.md").write_text(
        "\n\n".join(f"## {ad}\n{metin}" for ad, metin in o.itirazlar.items()) or "(boş)",
        encoding="utf-8")
    (d / "karar.md").write_text(_karar_md(o), encoding="utf-8")

    # yama yalnızca doğrulamadan geçen kararlardan üretilir (yama.py)
    yamalar = [k.get("yama", "") for k in o.kararlar if k.get("yama")]
    (d / "yama.diff").write_text("\n".join(yamalar), encoding="utf-8")
    (d / "kararlar.json").write_text(json.dumps(
        {"kararlar": o.kararlar, "dusen": o.dusen}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    from .saglayici import modeller_listele
    (d / "oturum.json").write_text(json.dumps({
        "gorev": o.gorev,
        "saglayici_modelleri": {s: modeller_listele(s)[:60] for s in o.saglayicilar},
        "saglayicilar": o.saglayicilar,
        "modeller": o.modeller,
        "cagri": [c.__dict__ for c in o.butce.kayitlar],
        "kullanilan_cagri": o.butce.kullanilan,
        "kararlar": o.kararlar,
        "dusen": o.dusen,
        "hatalar": o.hatalar,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    ozet = {"klasor": str(d.relative_to(KOK)), "karar": len(o.kararlar),
            "dusen": len(o.dusen), "cagri": o.butce.kullanilan,
            "hata": len([c for c in o.butce.kayitlar if c.hata])}
    (d / "ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=1), encoding="utf-8")
    return ozet


def _karar_md(o) -> str:
    satir = [f"# Konsey kararı · {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"**Görev:** {o.gorev}",
             f"**Sağlayıcılar:** {', '.join(o.saglayicilar)}",
             f"**Çağrı:** {o.butce.kullanilan}", ""]
    if not o.kararlar:
        satir += ["_Karar üretilemedi. `oturum.json` içindeki hatalara bak._", ""]
    for i, k in enumerate(o.kararlar, 1):
        durum = {True: "✅ kod doğrulandı", False: "—", None: "kuru koşu"}[k.get("uygulanabilir")]
        satir += [f"## {i}. {k.get('baslik', '(başlıksız)')}",
                  f"- **Dosya:** `{k.get('dosya', '—')}` · **Durum:** {durum}",
                  f"- **Gerekçe:** {k.get('gerekce', '—')}",
                  f"- **Kanıt:** `{k.get('kanit', '—')}`",
                  f"- **Etki / risk:** {k.get('etki', '—')} / {k.get('risk', '—')}", ""]
    if o.dusen:
        satir += ["## Kural gereği düşen öneriler", ""]
        for k in o.dusen:
            satir += [f"- ~~{k.get('baslik', '?')}~~ — {k.get('neden')}"]
        satir.append("")
    if o.hatalar:
        satir += ["## Hatalar", ""] + [f"- {h}" for h in o.hatalar]
    return "\n".join(satir) + "\n"
