# -*- coding: utf-8 -*-
"""cli.py — `python3 -m bot.v9.cli paper --dakika 60 --sembol 120`

Çıktı: runs/<etiket>/rapor.json, islemler.csv, ozet.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
if str(KOK / "bot" / "tools") not in sys.path:
    sys.path.insert(0, str(KOK / "bot" / "tools"))

from bot.v8.broker import SimuleBorsa                      # noqa: E402
from bot.v8.cli import _evren_isimleri, sentetik_evren     # noqa: E402
from bot.v8.config import KasaKurallari                    # noqa: E402
from bot.v8.feed import SentetikBesleme                    # noqa: E402
from bot.v9.motor import MotorV9, V9Ayarlari               # noqa: E402


def paper(dakika: float, sembol: int, seed: int, etiket: str,
          ayar: V9Ayarlari | None = None) -> dict:
    kurallar = KasaKurallari()
    isimler = _evren_isimleri(sembol)
    sim = SimuleBorsa(ad="okx", kurallar=kurallar, kasa_usd=kurallar.baslangic_kasa_usd)
    besleme = SentetikBesleme(isimler, seed=seed, bucket_sn=0.5, baslangic_ts=1_791_000_000.0)
    sim.enstrumanlar = sentetik_evren(isimler, besleme.fiyatlar())
    motor = MotorV9(borsa=sim, kurallar=kurallar, ayar=ayar or V9Ayarlari())

    egri, tepe, maks_dd, asiri_teminat = [], 0.0, 0.0, 0.0
    adim = int(dakika * 60 / 0.5)
    t0 = time.perf_counter()
    for i in range(adim):
        for t in besleme.sonraki():
            motor.tick(t)
        ozkaynak = sim.kasa_usd + sim.acik_pnl()
        tepe = max(tepe, ozkaynak)
        maks_dd = min(maks_dd, ozkaynak - tepe)
        asiri_teminat = max(asiri_teminat, sim.kullanilan_teminat() - ozkaynak)
        if i % 60 == 0:
            egri.append({"dk": round(i * 0.5 / 60, 2), "kasa": round(ozkaynak, 2),
                         "acik": len(sim.pozisyonlar)})
    duvar = time.perf_counter() - t0

    rapor = motor.ozet()
    rapor.update({
        "etiket": etiket, "mod": "paper", "dakika": dakika, "seed": seed,
        "sembol_sayisi": len(isimler), "duvar_suresi_sn": round(duvar, 1),
        "maks_dusus_usd": round(maks_dd, 2),
        "asiri_teminat_usd": round(asiri_teminat, 4),
        "kasa_egrisi": egri,
        "kural": {"kasa": kurallar.baslangic_kasa_usd,
                  "teminat": kurallar.teminat_per_pozisyon_usd,
                  "kaldirac": kurallar.kaldirac,
                  "notional": kurallar.notional_per_pozisyon_usd,
                  "stop_usd": kurallar.stop_net_usd,
                  "marjin": kurallar.marjin_modu,
                  "max_pozisyon": kurallar.max_pozisyon},
        "besleme": "SENTETIK (borsa agi kapali) — kenar olcumu DEGIL, davranis olcumu",
        "islemler": [{"sembol": k.sembol, "yon": k.yon.value, "giris": k.giris, "cikis": k.cikis,
                      "net_usd": k.net_usd, "neden": k.neden, "motor": k.motor,
                      "ts": k.ts, "sure_sn": round(k.ts - k.acilis_ts, 1)}
                     for k in motor.kapananlar],
    })
    _yaz(rapor, etiket)
    return rapor


def _yaz(rapor: dict, etiket: str) -> None:
    d = KOK / "runs" / etiket
    d.mkdir(parents=True, exist_ok=True)
    (d / "rapor.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(d / "islemler.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "sembol", "yon", "giris", "cikis", "net_usd", "neden", "motor", "sure_sn"])
        for k in rapor["islemler"]:
            w.writerow([k["ts"], k["sembol"], k["yon"], k["giris"], k["cikis"],
                        k["net_usd"], k["neden"], k["motor"], k["sure_sn"]])
    (d / "ozet.md").write_text(_md(rapor), encoding="utf-8")


def _md(r: dict) -> str:
    return f"""# v9 ORTAK AKIL — {r['etiket']}

| Metrik | Değer |
|---|---|
| Kasa | {r['kasa_usd']} $ |
| Realize | {r['realize_usd']} $ |
| Açık PnL | {r['acik_pnl_usd']} $ ({r['acik_pozisyon']} pozisyon) |
| Kapanan | {r['kapanan']} |
| WR | {r['wr']:.1%} |
| PF | {r['pf']} |
| Ort. kazanç / kayıp | {r['ort_kazanc']} / {r['ort_kayip']} |
| En iyi / en kötü | {r['en_iyi']} / {r['en_kotu']} |
| MaksDD | {r['maks_dusus_usd']} $ |
| Teminat / hesap kaldıracı | {r['teminat_usd']} $ / {r['hesap_kaldiraci'] if 'hesap_kaldiraci' in r else r['hesap_kaldirac']}x |
| Tasfiye | {r['tasfiye']} |
| Komisyon | {r['komisyon_usd']} $ |

Çıkış nedenleri: {r['cikis_nedeni']}
Rejim dağılımı: {r['rejim']}
Redler: {r['red']}

> {r['besleme']}
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bot.v9.cli")
    alt = ap.add_subparsers(dest="komut", required=True)
    p = alt.add_parser("paper", help="sentetik piyasada koşu")
    p.add_argument("--dakika", type=float, default=60)
    p.add_argument("--sembol", type=int, default=120)
    p.add_argument("--seed", type=int, default=20261113)
    p.add_argument("--etiket", default="v9_paper")
    p.add_argument("--min-skor", type=float, default=0.58)
    a = ap.parse_args(argv)
    if a.komut == "paper":
        r = paper(a.dakika, a.sembol, a.seed, a.etiket, V9Ayarlari(min_skor=a.min_skor))
        print(_md(r))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
