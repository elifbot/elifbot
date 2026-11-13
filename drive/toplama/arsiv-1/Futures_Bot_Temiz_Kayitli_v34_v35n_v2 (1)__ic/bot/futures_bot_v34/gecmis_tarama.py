#!/usr/bin/env python3
"""
gecmis_tarama.py — GEÇMİŞ VERİDEN SİNYAL TARAMASI

Canlı botun mantığını geçmiş 1 dakikalık mumlar üzerinde çalıştırır ve her
sinyal için ileriye dönük getiriyi ölçer. Amaç: "sinyal doğru yöne mi gidiyor?"
sorusunu binlerce örnekle yanıtlamak.

    python3 gecmis_tarama.py --saat 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from collections import defaultdict

import aiohttp

OKX_CANDLE = "https://www.okx.com/api/v5/market/history-candles"
OKX_INSTR = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
ESZAMANLI = 6


async def enstrumanlar(oturum) -> list[str]:
    async with oturum.get(OKX_INSTR, timeout=aiohttp.ClientTimeout(total=25)) as r:
        d = await r.json()
    return [i["instId"] for i in d.get("data", [])
            if i.get("settleCcy") == "USDT" and i.get("state") == "live"
            and str(i.get("instCategory")) == "1"]


async def mumlar(oturum, sembol: str, sayfa: int) -> list[list]:
    """sayfa x 100 adet 1dk mum, yeniden eskiye doğru sayfalanır."""
    hepsi: list[list] = []
    after = ""
    for _ in range(sayfa):
        p = {"instId": sembol, "bar": "1m", "limit": "100"}
        if after:
            p["after"] = after
        try:
            async with oturum.get(OKX_CANDLE, params=p,
                                  timeout=aiohttp.ClientTimeout(total=20)) as r:
                d = await r.json()
            veri = d.get("data", [])
            if not veri:
                break
            hepsi.extend(veri)
            after = veri[-1][0]
        except Exception:
            break
        await asyncio.sleep(0.06)
    return hepsi


def analiz_et(sembol: str, mumlar: list[list], ayar: dict, cikti: list) -> None:
    """mumlar yeniden-eskiye sıralı; eskiden-yeniye çevir."""
    k = list(reversed(mumlar))
    if len(k) < 40:
        return
    try:
        ts = [int(x[0]) for x in k]
        c = [float(x[4]) for x in k]
        qv = [float(x[7]) for x in k]      # volCcyQuote = USD hacim
    except (ValueError, IndexError):
        return

    geri = ayar["geri"]                    # kaç mum geriye fiyat değişimi
    taban = ayar["taban"]                  # taban hacim için kaç mum
    ret_min = ayar["ret_min"]
    rvol_min = ayar["rvol_min"]
    ufuklar = ayar["ufuklar"]

    for i in range(max(geri, taban), len(k) - max(ufuklar)):
        gecmis = c[i - geri]
        if gecmis <= 0:
            continue
        ret = (c[i] - gecmis) / gecmis * 100.0
        if abs(ret) < ret_min:
            continue
        govde = qv[i - taban:i]
        if not govde:
            continue
        tab = statistics.median(govde)
        if tab <= 0:
            continue
        rvol = qv[i] / tab
        if rvol < rvol_min:
            continue

        yon = 1 if ret > 0 else -1
        fwd = {}
        for u in ufuklar:
            fwd[u] = (c[i + u] - c[i]) / c[i] * 100.0 * yon

        cikti.append({
            "sembol": sembol, "ts": ts[i], "ret": ret, "rvol": rvol,
            "yon": "LONG" if yon > 0 else "SHORT", "fwd": fwd,
            "hacim_usd": qv[i],
        })


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saat", type=int, default=10, help="kaç saatlik geçmiş")
    ap.add_argument("--geri", type=int, default=2, help="kaç mumluk fiyat değişimi")
    ap.add_argument("--taban", type=int, default=20, help="taban hacim penceresi (mum)")
    ap.add_argument("--ret-min", type=float, default=0.35)
    ap.add_argument("--rvol-min", type=float, default=2.0)
    ap.add_argument("--kaydet", default="", help="json dosyasına yaz")
    a = ap.parse_args()

    sayfa = max(1, a.saat * 60 // 100)
    ayar = {"geri": a.geri, "taban": a.taban, "ret_min": a.ret_min,
            "rvol_min": a.rvol_min, "ufuklar": (1, 2, 5, 10, 20)}

    async with aiohttp.ClientSession() as oturum:
        semboller = await enstrumanlar(oturum)
        print(f"{len(semboller)} kripto sembol · {a.saat} saatlik geçmiş · "
              f"sayfa={sayfa}\n")

        cikti: list[dict] = []
        kilit = asyncio.Semaphore(ESZAMANLI)
        sayac = {"n": 0}

        async def isle(sembol: str):
            async with kilit:
                m = await mumlar(oturum, sembol, sayfa)
                analiz_et(sembol, m, ayar, cikti)
                sayac["n"] += 1
                if sayac["n"] % 40 == 0:
                    print(f"  {sayac['n']}/{len(semboller)} sembol · "
                          f"{len(cikti)} sinyal", flush=True)

        await asyncio.gather(*(isle(s) for s in semboller))

    print(f"\n{'='*78}")
    print(f" GEÇMİŞ TARAMA — {len(cikti)} sinyal · {len(semboller)} sembol")
    print(f"{'='*78}\n")

    if not cikti:
        print(" sinyal bulunamadı")
        return 1

    if a.kaydet:
        with open(a.kaydet, "w", encoding="utf-8") as fh:
            json.dump(cikti, fh)
        print(f" ham veri: {a.kaydet}\n")

    ufuklar = ayar["ufuklar"]

    def tablo(baslik, grup):
        print(f" {baslik}\n")
        print(f" {'grup':<16}{'n':>7}", end="")
        for u in ufuklar:
            print(f"{'+'+str(u)+'dk':>10}", end="")
        print()
        for ad, sec in grup:
            v = sec()
            if len(v) < 5:
                continue
            print(f" {ad:<16}{len(v):>7}", end="")
            for u in ufuklar:
                print(f"{statistics.mean(x['fwd'][u] for x in v):>+10.3f}", end="")
            print()
        print()

    # 1) yön doğruluğu
    print(" YÖN DOĞRULUĞU (sinyalin yönünde tutulursa)\n")
    print(f" {'ufuk':<10}{'ort %':>10}{'medyan %':>11}{'doğru':>9}{'n':>8}")
    for u in ufuklar:
        v = [x["fwd"][u] for x in cikti]
        print(f" +{u}dk{'':<5}{statistics.mean(v):>+9.3f}{statistics.median(v):>+11.3f}"
              f"{sum(1 for z in v if z>0)/len(v)*100:>8.1f}%{len(v):>8}")

    # 2) rvol kovası
    tablo("RVOL KOVASINA GÖRE (momentum yönünde)", [
        (f"{lo}-{hi}", (lambda lo=lo, hi=hi: [x for x in cikti
                                              if lo <= x["rvol"] < hi]))
        for lo, hi in ((2, 3), (3, 5), (5, 8), (8, 15), (15, 1e9))
    ])

    # 3) hareket kovası
    tablo("HAREKET BÜYÜKLÜĞÜNE GÖRE (momentum yönünde)", [
        (f"%{lo}-{hi}", (lambda lo=lo, hi=hi: [x for x in cikti
                                               if lo <= abs(x["ret"]) < hi]))
        for lo, hi in ((0.35, 0.5), (0.5, 0.8), (0.8, 1.2), (1.2, 2.0), (2.0, 1e9))
    ])

    # 4) ters yön (fade)
    print(" TERS YÖN (fade) — aynı sinyallerde karşı taraf\n")
    print(f" {'ufuk':<10}{'ort %':>10}{'doğru':>9}")
    for u in ufuklar:
        v = [-x["fwd"][u] for x in cikti]
        print(f" +{u}dk{'':<5}{statistics.mean(v):>+9.3f}"
              f"{sum(1 for z in v if z>0)/len(v)*100:>8.1f}%")

    # 5) en iyi kombinasyon
    print("\n RVOL + HAREKET KOMBİNASYONU (+5 dk)\n")
    print(f" {'rvol':<10}{'|ret|':<12}{'n':>7}{'momentum':>12}{'fade':>10}")
    for rl, rh in ((2, 3), (3, 5), (5, 9), (9, 1e9)):
        for ml, mh in ((0.35, 0.5), (0.5, 0.8), (0.8, 1e9)):
            v = [x for x in cikti if rl <= x["rvol"] < rh and ml <= abs(x["ret"]) < mh]
            if len(v) < 20:
                continue
            m = statistics.mean(x["fwd"][5] for x in v)
            print(f" {rl}-{rh if rh<1e8 else '∞':<8}{'%'+str(ml)+'-'+str(mh if mh<1e8 else '∞'):<12}"
                  f"{len(v):>7}{m:>+12.3f}{-m:>+10.3f}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
