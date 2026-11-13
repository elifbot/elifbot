# -*- coding: utf-8 -*-
"""olcum.py — konsey yamasının etkisini ÖLÇER.

Bir yamayı geçici bir kopyada uygular, aynı seed ile iki koşu yapar
(yamasız / yamalı) ve metrikleri karşılaştırır. Amaç: "şu değişiklik iyi olur"
cümlesini ölçüme çevirmek; etkisi sıfır olan yamayı da dürüstçe sıfır demek.

Kullanım:
    python3 -m kadro.konsey.olcum --kararlar konsey/<etiket>/kararlar.json
    python3 -m kadro.konsey.olcum --dosya bot/v9/sinyaller.py \
        --eski "..." --yeni "..."
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
YOK_SAY = shutil.ignore_patterns(".git", "runs", "__pycache__", "yedek", "*.pyc",
                                 "node_modules", ".venv")


def _kos(cwd: Path, etiket: str, dakika: float, sembol: int) -> dict:
    subprocess.run([sys.executable, "-m", "bot.v9.cli", "paper", "--dakika", str(dakika),
                    "--sembol", str(sembol), "--etiket", etiket],
                   cwd=cwd, check=True, capture_output=True, text=True)
    return json.loads((cwd / "runs" / etiket / "rapor.json").read_text(encoding="utf-8"))


def _metrik(rap: dict) -> dict:
    """rapor.json üst düzey alanlarından karşılaştırılabilir metrik seti."""
    return {"kapanan": rap.get("kapanan"), "wr": rap.get("wr"), "pf": rap.get("pf"),
            "realize": rap.get("realize_usd"), "maks_dd": rap.get("maks_dd_usd"),
            "komisyon": rap.get("komisyon_usd"), "kasa": rap.get("kasa_usd"),
            "acik_pnl": rap.get("acik_pnl_usd"), "red": rap.get("redler")}


def ab(dosya: str, eski: str, yeni: str, dakika: float = 3.0, sembol: int = 40) -> dict:
    gecici = Path(tempfile.mkdtemp(prefix="konsey_ab_"))
    try:
        hedef = gecici / "depo"
        shutil.copytree(KOK, hedef, ignore=YOK_SAY)
        p = hedef / dosya
        metin = p.read_text(encoding="utf-8")
        # yama çalışma ağacında zaten uygulanmışsa önce geri al (taban = yamasız hâl)
        if metin.count(eski) != 1:
            if metin.count(yeni) == 1:
                metin = metin.replace(yeni, eski, 1)
                p.write_text(metin, encoding="utf-8")
            else:
                return {"hata": f"eski_kod {metin.count(eski)} / yeni_kod {metin.count(yeni)} kez geçiyor"}
        taban = _metrik(_kos(hedef, "ab_taban", dakika, sembol))
        metin = p.read_text(encoding="utf-8")
        p.write_text(metin.replace(eski, yeni, 1), encoding="utf-8")
        yamali = _metrik(_kos(hedef, "ab_yamali", dakika, sembol))
        fark = {k: (None if taban.get(k) in (None, 0) or yamali.get(k) is None
                    else round(yamali[k] - taban[k], 3)) for k in taban}
        etkili = any(v not in (None, 0) for v in fark.values() if v is not None)
        return {"taban": taban, "yamali": yamali, "fark": fark,
                "etkili": bool(etkili), "dosya": dosya}
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="konsey yamasının etkisini ölç")
    ap.add_argument("--kararlar", help="kararlar.json yolu")
    ap.add_argument("--dosya")
    ap.add_argument("--eski")
    ap.add_argument("--yeni")
    ap.add_argument("--dakika", type=float, default=3.0)
    ap.add_argument("--sembol", type=int, default=40)
    a = ap.parse_args(argv)

    isler: list[dict] = []
    if a.kararlar:
        veri = json.loads(Path(a.kararlar).read_text(encoding="utf-8"))
        for k in veri.get("kararlar", []):
            if k.get("uygulanabilir") and k.get("eski_kod"):
                isler.append(k)
    elif a.dosya and a.eski and a.yeni:
        isler.append({"baslik": "elle", "dosya": a.dosya, "eski_kod": a.eski, "yeni_kod": a.yeni})
    if not isler:
        print("ölçülecek yama yok")
        return 1

    for k in isler:
        print(f"== {k.get('baslik', '?')} ({k['dosya']})")
        r = ab(k["dosya"], k["eski_kod"], k["yeni_kod"], a.dakika, a.sembol)
        if r.get("hata"):
            print(f"   ! {r['hata']}")
            continue
        print(f"   taban  : {r['taban']}")
        print(f"   yamalı : {r['yamali']}")
        print(f"   fark   : {r['fark']}")
        print(f"   etki   : {'ÖLÇÜLDÜ' if r['etkili'] else 'SIFIR (yama bağlamıyor)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
