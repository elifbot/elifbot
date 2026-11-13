#!/usr/bin/env python3
"""
derin_analiz.py — FADE KENARININ HARİTASI

Her sinyal için fiyat yolu çekilir, fade yönünde ileri getiriler hesaplanır ve
kaydedilir. Sonra bu tek veri kümesi birçok açıdan kesilir: zaman kararlılığı,
yön, borsa, rvol, hareket büyüklüğü, saat.

    python3 derin_analiz.py --kaydet /home/user/fade_veri.json
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
from datetime import datetime, timezone

import aiohttp

TABAN = os.path.dirname(os.path.abspath(__file__))
OLAY = os.path.join(TABAN, "logs", "ws_olay.csv")
OKX_CANDLE = "https://www.okx.com/api/v5/market/candles"
BN_CANDLE = "https://www.binance.com/fapi/v1/klines"
UFUK = (1, 2, 5, 10, 20)


def ms(t: str) -> int:
    d = datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000) + int(t[20:23] or 0)


async def yol(oturum, borsa, sembol, ts):
    if borsa == "okx":
        try:
            async with oturum.get(OKX_CANDLE, params={"instId": sembol, "bar": "1m", "limit": "40"},
                                  timeout=aiohttp.ClientTimeout(total=15)) as r:
                d = await r.json()
            return sorted((int(k[0]), float(k[4])) for k in d.get("data", []))
        except Exception:
            return []
    try:
        async with oturum.get(BN_CANDLE, params={"symbol": sembol, "interval": "1m",
                                                 "startTime": ts - 60_000,
                                                 "endTime": ts + 1_300_000, "limit": 25},
                              timeout=aiohttp.ClientTimeout(total=15)) as r:
            d = await r.json()
        return sorted((int(k[0]), float(k[4])) for k in d) if isinstance(d, list) else []
    except Exception:
        return []


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dosya", default=OLAY)
    ap.add_argument("--kaydet", default="")
    a = ap.parse_args()

    sinyaller = list(csv.DictReader(open(a.dosya, encoding="utf-8")))
    print(f"{len(sinyaller)} sinyal için yol çekiliyor...\n")

    kayit = []
    async with aiohttp.ClientSession() as oturum:
        for i, s in enumerate(sinyaller, 1):
            ts = ms(s["ts_utc"])
            y = await yol(oturum, s["exchange"], s["symbol"], ts)
            giris = float(s["fiyat"])
            yon = 1 if s["yon"] == "LONG" else -1
            f = {}
            for u in UFUK:
                hedef = ts + u * 60_000
                kapanis = next((c for t, c in y if t >= hedef), None)
                if kapanis is None:
                    f[u] = None
                else:
                    mom = (kapanis - giris) / giris * 100 * yon      # momentum yönü
                    f[u] = -mom                                       # FADE yönü
            if f[5] is None:
                continue
            kayit.append({
                "ts": ts, "sembol": s["symbol"], "borsa": s["exchange"],
                "yon": s["yon"], "rvol": float(s["rvol"]),
                "ret": float(s["ret_pct"]), "hacim": float(s["hacim_usd"]),
                "fade": f,
            })
            if i % 40 == 0:
                print(f"  {i}/{len(sinyaller)}", flush=True)

    print(f"\n{len(kayit)} sinyal ölçüldü\n")
    if a.kaydet:
        json.dump(kayit, open(a.kaydet, "w"), ensure_ascii=False)
        print(f"kaydedildi: {a.kaydet}\n")

    def ozet(ad, grup):
        if len(grup) < 15:
            return
        v = [x["fade"][5] for x in grup if x["fade"][5] is not None]
        if not v:
            return
        d = sum(1 for z in v if z > 0) / len(v) * 100
        ort = statistics.mean(v)
        # 0.10% taker komisyon sonrası net
        net = ort - 0.10
        # 0.04% maker komisyon sonrası net
        netm = ort - 0.04
        print(f"  {ad:<26}{len(v):>5}{ort:>+9.3f}{d:>8.1f}%{net:>+9.3f}{netm:>+9.3f}")

    print(f"  {'grup':<26}{'n':>5}{'brüt %':>9}{'doğru':>9}{'net(taker)':>11}{'net(maker)':>11}")
    print("  " + "-" * 70)

    print("\n  [ZAMAN KARARLILIĞI]")
    kayit.sort(key=lambda x: x["ts"])
    n = len(kayit)
    for i in range(4):
        dilim = kayit[i * n // 4:(i + 1) * n // 4]
        ozet(f"çeyrek {i+1}", dilim)

    print("\n  [YÖN]")
    for y in ("LONG", "SHORT"):
        ozet(f"{y} sinyali fade", [x for x in kayit if x["yon"] == y])

    print("\n  [BORSA]")
    for b in ("okx", "binance"):
        ozet(b.upper(), [x for x in kayit if x["borsa"] == b])

    print("\n  [RVOL]")
    for lo, hi in ((0, 2), (2, 3), (3, 5), (5, 8), (8, 15), (15, 1e9)):
        ozet(f"rvol {lo}-{hi if hi<1e8 else '∞'}",
             [x for x in kayit if lo <= x["rvol"] < hi])

    print("\n  [HAREKET]")
    for lo, hi in ((0, .3), (.3, .5), (.5, .8), (.8, 2), (2, 99)):
        ozet(f"|ret| %{lo}-{hi if hi<99 else '∞'}",
             [x for x in kayit if lo <= abs(x["ret"]) < hi])

    print("\n  [BİRLEŞİK: rvol ≥ 2 ve |ret| ≥ 0.3]")
    for rl in (2, 3, 5, 8):
        for ml in (0.3, 0.5):
            ozet(f"rvol≥{rl} & |ret|≥{ml}%",
                 [x for x in kayit if x["rvol"] >= rl and abs(x["ret"]) >= ml])

    print("\n  [UFUK]")
    for u in UFUK:
        v = [x["fade"][u] for x in kayit if x["fade"][u] is not None]
        if v:
            print(f"  +{u} dk{'':<20}{len(v):>5}{statistics.mean(v):>+9.3f}"
                  f"{sum(1 for z in v if z>0)/len(v)*100:>8.1f}%"
                  f"{statistics.mean(v)-0.10:>+11.3f}{statistics.mean(v)-0.04:>+11.3f}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
