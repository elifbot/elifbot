"""Komut satırı: geçmiş CSV ile simülasyon + kova analizi + kapı kontrolü.

Örnek:
  python -m bot.v11.cli --veri BTC.csv ETH.csv --dakika 15 --strateji kanit --cikti runs/v11_kanit
  python -m bot.v11.cli --sentetik 4 --dakika 15 --strateji kanit --cikti runs/v11_sentetik   (yalnız yazılım testi)

Kapı: OOS (ikinci yarı) işlem sayısı ≥ 100 ve beklenen net > 0 ise GEÇTİ, aksi halde KANIT YOK.
Canlıya geçiş yolu bu kodda yoktur.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from . import analiz
from .kurallar import Kurallar
from .motor import simule
from .strateji import STRATEJILER
from .veri import Bar, Seri, oku_csv, yeniden_ornekle


def sentetik(n_sembol: int, n_bar: int, seed: int = 7) -> list[Seri]:
    """Yalnızca yazılım testi için rastgele yürüyüş. Kenar ölçümü DEĞİLDİR."""
    rnd = random.Random(seed)
    out = []
    for k in range(n_sembol):
        p = 100.0
        bars = []
        for i in range(n_bar):
            o = p
            p = max(0.01, p * (1 + rnd.gauss(0, 0.002)))
            h = max(o, p) * (1 + abs(rnd.gauss(0, 0.0005)))
            l = min(o, p) * (1 - abs(rnd.gauss(0, 0.0005)))
            bars.append(Bar(ts=1_700_000_000 + i * 60, o=o, h=h, l=l, c=p, v=1.0,
                            funding=rnd.gauss(0, 0.0003), oi=1e6 * (1 + 0.01 * rnd.random())))
        out.append(Seri(sembol=f"SYN{k}-USDT-SWAP", bars=bars))
    return out


def ozet(islemler) -> dict:
    n = len(islemler)
    if n == 0:
        return {"n": 0}
    kazan = [t.net for t in islemler if t.net > 0]
    kayip = [t.net for t in islemler if t.net <= 0]
    gp, gl = sum(kazan), -sum(kayip)
    return {
        "n": n, "wr": len(kazan) / n, "net": sum(t.net for t in islemler),
        "pf": (gp / gl) if gl > 0 else float("inf"),
        "ort_net": sum(t.net for t in islemler) / n,
        "en_kotu": min(t.net for t in islemler),
    }


def ana(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ACARBOT v11 simülasyon")
    ap.add_argument("--veri", nargs="*", default=[])
    ap.add_argument("--sentetik", type=int, default=0)
    ap.add_argument("--dakika", type=int, default=15)
    ap.add_argument("--strateji", choices=sorted(STRATEJILER), default="kanit")
    ap.add_argument("--ileri", type=int, default=30)
    ap.add_argument("--cikti", default="runs/v11")
    a = ap.parse_args(argv)

    Kurallar().dogrula()
    if a.sentetik:
        seriler = sentetik(a.sentetik, 4000)
        besleme = "SENTETIK"
    else:
        if not a.veri:
            ap.error("--veri ya da --sentetik gerekli")
        seriler = [yeniden_ornekle(oku_csv(p, Path(p).stem), a.dakika) for p in a.veri]
        besleme = "GERCEK_CSV"
    seriler = [yeniden_ornekle(s, a.dakika) if besleme == "SENTETIK" and a.dakika > 1 else s for s in seriler]

    st = STRATEJILER[a.strateji]
    sonuc = simule(seriler, st)
    islemler = sorted(sonuc.islemler, key=lambda t: t.giris_ts)
    if islemler:
        orta = islemler[len(islemler) // 2].giris_ts
    else:
        orta = 0
    oos = [t for t in islemler if t.giris_ts >= orta]
    is_ = [t for t in islemler if t.giris_ts < orta]
    m_tum, m_is, m_oos = ozet(islemler), ozet(is_), ozet(oos)
    kapi = "GEÇTİ" if (m_oos.get("n", 0) >= 100 and m_oos.get("ort_net", -1) > 0) else "KANIT YOK"
    kova = analiz.kova_tablosu(seriler, st, a.ileri)

    out = Path(a.cikti)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "islemler.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sembol", "yon", "giris_ts", "cikis_ts", "giris", "cikis", "bar", "neden", "brut", "net", "ozellik"])
        for t in islemler:
            w.writerow([t.sembol, t.yon, t.giris_ts, t.cikis_ts, t.giris, t.cikis, t.bar_sayisi,
                        t.neden, round(t.brut, 4), round(t.net, 4), json.dumps(t.ozellik)])
    with open(out / "kova.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["indikator", "kova", "n", "ort_net_yuzde", "isabet_yuzde"])
        w.writeheader()
        for r in kova:
            w.writerow(r)
    rapor = {"besleme": besleme, "strateji": a.strateji, "dakika": a.dakika, "kurallar": Kurallar().__dict__,
             "tum": m_tum, "is": m_is, "oos": m_oos, "kapi": kapi, "kasa_son": sonuc.kasa_son}
    (out / "rapor.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    satir = [
        f"# v11 koşu özeti — strateji `{a.strateji}`, {a.dakika} dk",
        "",
        f"**BESLEME: {besleme}**" + ("  (kenar ölçümü DEĞİL, yalnız yazılım testi)" if besleme == "SENTETIK" else ""),
        f"**KAPI: {kapi}** (OOS işlem ≥ 100 ve ort_net > 0 gerekir)",
        "",
        "| dilim | n | WR | PF | net $ | ort net $ | en kötü $ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for ad, m in (("tümü", m_tum), ("IS (ilk yarı)", m_is), ("OOS (ikinci yarı)", m_oos)):
        if m.get("n", 0) == 0:
            satir.append(f"| {ad} | 0 | - | - | - | - | - |")
        else:
            satir.append(f"| {ad} | {m['n']} | {m['wr']:.1%} | {m['pf']:.2f} | {m['net']:.2f} | {m['ort_net']:.2f} | {m['en_kotu']:.2f} |")
    satir += ["", "Kova analizi: `kova.csv` (ileri getiri, maliyet düşülmüş, yüzde)."]
    (out / "ozet.md").write_text("\n".join(satir) + "\n", encoding="utf-8")
    print("\n".join(satir))
    return 0


if __name__ == "__main__":
    raise SystemExit(ana())
