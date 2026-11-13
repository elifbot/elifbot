#!/usr/bin/env python3
"""
analiz.py — SİNYAL KALİTESİ ANALİZİ

Soruyu yanıtlar: "Sinyal doğru yöne mi gitti?" — pozisyon açılsın ya da açılmasın.

Yöntem: her sinyal için borsadan 1 dakikalık mumlar çekilir, sinyalden sonraki
+1, +2, +5, +10 dakikadaki fiyat ölçülür ve sinyalin yönüyle karşılaştırılır.

    python3 analiz.py                      # son koşunun dosyaları
    python3 analiz.py --dosya logs/ws_olay.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp

TABAN = os.path.dirname(os.path.abspath(__file__))
OLAY = os.path.join(TABAN, "logs", "ws_olay.csv")
ISLEM = os.path.join(TABAN, "live_trades.csv")

OKX_CANDLE = "https://www.okx.com/api/v5/market/candles"
BN_CANDLE = "https://www.binance.com/fapi/v1/klines"
UFUKLAR = (60, 120, 300, 600)          # saniye


def ms(ts_utc: str) -> int:
    d = datetime.strptime(ts_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000) + int(ts_utc[20:23] or 0)


async def okx_mumlar(oturum, sembol: str, merkez_ms: int) -> list[tuple[int, float]]:
    # 1 dk mumlar; sinyalden 3 dk önce + 12 dk sonrası
    bas = merkez_ms - 180_000
    try:
        async with oturum.get(OKX_CANDLE, params={"instId": sembol, "bar": "1m", "limit": "40"},
                              timeout=aiohttp.ClientTimeout(total=15)) as r:
            d = await r.json()
        cikti = [(int(k[0]), float(k[4])) for k in d.get("data", [])]
        return sorted(x for x in cikti if x[0] >= bas)
    except Exception:
        return []


async def bn_mumlar(oturum, sembol: str, merkez_ms: int) -> list[tuple[int, float]]:
    bas = merkez_ms - 180_000
    bit = merkez_ms + 720_000
    try:
        async with oturum.get(BN_CANDLE, params={"symbol": sembol, "interval": "1m",
                                                 "startTime": bas, "endTime": bit, "limit": 40},
                              timeout=aiohttp.ClientTimeout(total=15)) as r:
            d = await r.json()
        if not isinstance(d, list):
            return []
        return sorted((int(k[0]), float(k[4])) for k in d)
    except Exception:
        return []


def fiyat_anki(mumlar: list[tuple[int, float]], hedef_ms: int) -> float | None:
    """hedef_ms'e en yakın (>=) mum kapanışı; o mum yoksa sonuncusu."""
    for ts, c in mumlar:
        if ts >= hedef_ms:
            return c
    return mumlar[-1][1] if mumlar else None


def sinyal_esles(sinyaller, islemler):
    """Sinyal → işlem eşleştirmesi (sembol aynı, açılış ±8 sn)."""
    sonuc = []
    for s in sinyaller:
        ts = ms(s["ts_utc"])
        eslesti = False
        for t in islemler:
            if t["exchange"] != s["exchange"]:
                continue
            if t["symbol"] != s["symbol"]:
                continue
            if abs(int(t["opened_at"]) - ts) <= 8000:
                eslesti = True
                break
        sonuc.append((s, ts, eslesti))
    return sonuc


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dosya", default=OLAY)
    ap.add_argument("--islem", default=ISLEM)
    a = ap.parse_args()

    try:
        sinyaller = list(csv.DictReader(open(a.dosya, encoding="utf-8")))
    except FileNotFoundError:
        print(f"sinyal dosyası yok: {a.dosya}")
        return 1
    try:
        islemler = list(csv.DictReader(open(a.islem, encoding="utf-8")))
    except FileNotFoundError:
        islemler = []

    print(f"\n{len(sinyaller)} sinyal · {len(islemler)} işlem · "
          f"borsadan mumlar çekiliyor...\n")

    eslesmeler = sinyal_esles(sinyaller, islemler)
    kayitlar = []

    async with aiohttp.ClientSession() as oturum:
        for i, (s, ts, alindi) in enumerate(eslesmeler, 1):
            if s["exchange"] == "okx":
                mumlar = await okx_mumlar(oturum, s["symbol"], ts)
            else:
                mumlar = await bn_mumlar(oturum, s["symbol"], ts)
            giris = float(s["fiyat"])
            yon = 1 if s["yon"] == "LONG" else -1
            getiriler = {}
            for ufuk in UFUKLAR:
                f = fiyat_anki(mumlar, ts + ufuk * 1000)
                if f is None:
                    getiriler[ufuk] = None
                else:
                    getiriler[ufuk] = (f - giris) / giris * 100 * yon
            kayitlar.append({
                "s": s, "ts": ts, "alindi": alindi, "getiriler": getiriler,
                "mum_sayisi": len(mumlar),
            })
            if i % 10 == 0:
                print(f"  {i}/{len(eslesmeler)} işlendi...", flush=True)

    # ------------------------------------------------------------ rapor
    gecerli = [k for k in kayitlar if k["getiriler"][300] is not None]
    print(f"\n{'='*74}")
    print(f" SİNYAL KALİTESİ — {len(gecerli)}/{len(kayitlar)} sinyal ölçülebildi")
    print(f"{'='*74}\n")

    if not gecerli:
        print(" Hiçbir sinyal için mum verisi alınamadı.")
        return 1

    print(" HER SİNYAL İÇİN ORTALAMA GETİRİ (sinyalin yönünde)\n")
    print(f" {'ufuk':<8}{'ort %':>10}{'medyan %':>11}{'doğru yön':>12}{'n':>5}")
    for ufuk in UFUKLAR:
        v = [k["getiriler"][ufuk] for k in gecerli if k["getiriler"][ufuk] is not None]
        if not v:
            continue
        dogru = sum(1 for x in v if x > 0)
        print(f" +{ufuk//60} dk{'':<3}{statistics.mean(v):>+9.3f}{statistics.median(v):>+11.3f}"
              f"{dogru/len(v)*100:>11.1f}%{len(v):>5}")

    # alınan vs engellenen
    for etiket, secim in (("POZİSYON AÇILAN", True), ("ENGELLENEN", False)):
        grup = [k for k in gecerli if k["alindi"] is secim]
        if not grup:
            continue
        print(f"\n {etiket} — {len(grup)} sinyal\n")
        print(f" {'ufuk':<8}{'ort %':>10}{'medyan %':>11}{'doğru yön':>12}")
        for ufuk in UFUKLAR:
            v = [k["getiriler"][ufuk] for k in grup if k["getiriler"][ufuk] is not None]
            if not v:
                continue
            dogru = sum(1 for x in v if x > 0)
            print(f" +{ufuk//60} dk{'':<3}{statistics.mean(v):>+9.3f}{statistics.median(v):>+11.3f}"
                  f"{dogru/len(v)*100:>11.1f}%")

    # borsa bazında
    print(f"\n BORSA BAZINDA (+5 dk)\n")
    for b in ("okx", "binance"):
        v = [k["getiriler"][300] for k in gecerli
             if k["s"]["exchange"] == b and k["getiriler"][300] is not None]
        if not v:
            continue
        dogru = sum(1 for x in v if x > 0)
        print(f" {b.upper():<9} ort={statistics.mean(v):+.3f}%  "
              f"doğru={dogru/len(v)*100:.1f}%  n={len(v)}")

    # rvol kovası
    print(f"\n RVOL KOVASINA GÖRE (+5 dk)\n")
    print(f" {'rvol':<12}{'n':>5}{'ort %':>10}{'doğru yön':>12}")
    for lo, hi in ((0, 2), (2, 3), (3, 5), (5, 8), (8, 999)):
        v = [k["getiriler"][300] for k in gecerli
             if lo <= float(k["s"]["rvol"]) < hi and k["getiriler"][300] is not None]
        if not v:
            continue
        dogru = sum(1 for x in v if x > 0)
        print(f" {lo}-{hi if hi<999 else '∞':<10}{len(v):>5}{statistics.mean(v):>+9.3f}"
              f"{dogru/len(v)*100:>11.1f}%")

    # hareket büyüklüğü kovası
    print(f"\n HAREKET BÜYÜKLÜĞÜNE GÖRE (+5 dk)\n")
    print(f" {'|ret|':<12}{'n':>5}{'ort %':>10}{'doğru yön':>12}")
    for lo, hi in ((0, .4), (.4, .6), (.6, 1.0), (1.0, 99)):
        v = [k["getiriler"][300] for k in gecerli
             if lo <= abs(float(k["s"]["ret_pct"])) < hi and k["getiriler"][300] is not None]
        if not v:
            continue
        dogru = sum(1 for x in v if x > 0)
        print(f" %{lo}-{hi if hi<99 else '∞':<9}{len(v):>5}{statistics.mean(v):>+9.3f}"
              f"{dogru/len(v)*100:>11.1f}%")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
