#!/usr/bin/env python3
"""
simulasyon.py — TP/SL SİMÜLATÖRÜ

Kaydedilmiş sinyalleri alır, her biri için borsadan fiyat yolunu (mum yüksek/
düşük) çeker ve farklı strateji ayarlarını gerçekçi biçimde dener.

    python3 simulasyon.py                 # ızgara taraması
    python3 simulasyon.py --detay         # sinyal bazında döküm

Muhafazakâr kural: bir mum içinde hem TP hem SL seviyesine değilirse SL kazanır.
Komisyon: giriş + çıkış = %0,05 x 2 = %0,10 nominal (500 USDT'de 0,50 USDT).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import statistics
from datetime import datetime, timezone

import aiohttp

TABAN = os.path.dirname(os.path.abspath(__file__))
OLAY = os.path.join(TABAN, "logs", "ws_olay.csv")

OKX_CANDLE = "https://www.okx.com/api/v5/market/candles"
BN_CANDLE = "https://www.binance.com/fapi/v1/klines"
MARJ, KALDIRAC = 100.0, 5.0
NOMINAL = MARJ * KALDIRAC          # 500 USDT
KOMISYON = NOMINAL * 0.0005 * 2    # 0.50 USDT


def ms(ts_utc: str) -> int:
    d = datetime.strptime(ts_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000) + int(ts_utc[20:23] or 0)


async def yol_okx(oturum, sembol: str, ts: int):
    try:
        async with oturum.get(OKX_CANDLE, params={"instId": sembol, "bar": "1m", "limit": "40"},
                              timeout=aiohttp.ClientTimeout(total=15)) as r:
            d = await r.json()
        return [(int(k[0]), float(k[2]), float(k[3])) for k in d.get("data", [])]  # ts, high, low
    except Exception:
        return []


async def yol_bn(oturum, sembol: str, ts: int):
    try:
        async with oturum.get(BN_CANDLE, params={"symbol": sembol, "interval": "1m",
                                                 "startTime": ts - 60_000,
                                                 "endTime": ts + 1_200_000, "limit": 25},
                              timeout=aiohttp.ClientTimeout(total=15)) as r:
            d = await r.json()
        if not isinstance(d, list):
            return []
        return [(int(k[0]), float(k[2]), float(k[3])) for k in d]
    except Exception:
        return []


def simule(yon_isaret: int, tp: float, sl: float, azami_dk: int,
           giris: float, yol: list) -> tuple[str, float]:
    """(sonuç, yüzde_getiri) döndürür. yol: [(ts, high, low)] gelecekteki mumlar."""
    if not yol or giris <= 0:
        return "veri_yok", 0.0
    if yon_isaret > 0:                       # LONG
        tp_f = giris * (1 + tp / 100)
        sl_f = giris * (1 - sl / 100)
    else:                                    # SHORT
        tp_f = giris * (1 - tp / 100)
        sl_f = giris * (1 + sl / 100)

    for i, (_, hi, lo) in enumerate(yol):
        if i >= azami_dk:
            break
        if yon_isaret > 0:
            tp_vurdu, sl_vurdu = hi >= tp_f, lo <= sl_f
        else:
            tp_vurdu, sl_vurdu = lo <= tp_f, hi >= sl_f
        if sl_vurdu:                          # muhafazakâr: aynı mumda ikisi de varsa SL
            return "SL", -sl
        if tp_vurdu:
            return "TP", tp
    return "sure", 0.0


async def topla(sinyaller):
    kayit = []
    async with aiohttp.ClientSession() as oturum:
        for i, s in enumerate(sinyaller, 1):
            ts = ms(s["ts_utc"])
            if s["exchange"] == "okx":
                yol = await yol_okx(oturum, s["symbol"], ts)
            else:
                yol = await yol_bn(oturum, s["symbol"], ts)
            yol = [y for y in yol if y[0] >= ts - 60_000]
            kayit.append({**s, "ts_ms": ts, "yol": yol,
                          "yon": 1 if s["yon"] == "LONG" else -1})
            if i % 25 == 0:
                print(f"  {i}/{len(sinyaller)}", flush=True)
    return kayit


def degerlendir(kayit, yon_modu, tp, sl, azami_dk):
    sonuc = []
    for k in kayit:
        if not k["yol"]:
            continue
        y = k["yon"] if yon_modu == "momentum" else -k["yon"]
        durum, yuzde = simule(y, tp, sl, azami_dk, float(k["fiyat"]), k["yol"])
        if durum == "veri_yok":
            continue
        brut = yuzde / 100 * NOMINAL
        net = brut - KOMISYON
        sonuc.append({"durum": durum, "yuzde": yuzde, "brut": brut, "net": net})
    return sonuc


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dosya", default=OLAY)
    ap.add_argument("--detay", action="store_true")
    a = ap.parse_args()

    try:
        sinyaller = list(csv.DictReader(open(a.dosya, encoding="utf-8")))
    except FileNotFoundError:
        print("sinyal dosyası yok")
        return 1
    if not sinyaller:
        print("sinyal yok")
        return 1

    print(f"\n{len(sinyaller)} sinyal için fiyat yolu çekiliyor...\n")
    kayit = await topla(sinyaller)
    gecerli = [k for k in kayit if k["yol"]]
    print(f"\n{len(gecerli)}/{len(kayit)} sinyal için yol alındı\n")

    print("=" * 86)
    print(f" IZGARA TARAMASI — {len(gecerli)} sinyal · komisyon {KOMISYON:.2f} USDT/işlem")
    print("=" * 86)
    print(f" {'yön':<10}{'TP':>6}{'SL':>6}{'tut':>6}{'n':>6}{'isabet':>9}"
          f"{'ort brüt':>11}{'ort NET':>10}{'TOPLAM NET':>12}")
    print("-" * 86)

    en_iyi = []
    for yon_modu in ("momentum", "fade"):
        for tp in (0.3, 0.5, 0.8, 1.2):
            for sl in (0.3, 0.5, 0.8):
                for tut in (2, 5, 10, 20):
                    r = degerlendir(gecerli, yon_modu, tp, sl, tut)
                    if len(r) < 10:
                        continue
                    isabet = sum(1 for x in r if x["net"] > 0) / len(r) * 100
                    ort_b = statistics.mean(x["brut"] for x in r)
                    ort_n = statistics.mean(x["net"] for x in r)
                    top = sum(x["net"] for x in r)
                    en_iyi.append((top, yon_modu, tp, sl, tut, len(r), isabet, ort_b, ort_n))

    en_iyi.sort(reverse=True)
    for top, ym, tp, sl, tut, n, isa, ob, on in en_iyi[:18]:
        print(f" {ym:<10}{tp:>6.1f}{sl:>6.1f}{tut:>6}{n:>6}{isa:>8.1f}%"
              f"{ob:>+11.2f}{on:>+10.2f}{top:>+12.2f}")

    # --- eğitim / test ayrımı -------------------------------------------
    # Izgara taraması 96 kombinasyon deniyor; en iyi hücre neredeyse her zaman
    # şans eseri iyi çıkar. Bu yüzden ilk %70'te seçip son %30'da sınıyoruz.
    if len(gecerli) >= 120:
        gecerli.sort(key=lambda k: k["ts_ms"])
        kes = int(len(gecerli) * 0.7)
        egitim, test = gecerli[:kes], gecerli[kes:]
        print("\n" + "=" * 86)
        print(f" EĞİTİM / TEST — eğitim {len(egitim)} · test {len(test)}")
        print("=" * 86)

        adaylar = []
        for ym in ("momentum", "fade"):
            for tp in (0.3, 0.5, 0.8, 1.2):
                for sl in (0.3, 0.5, 0.8):
                    for tut in (2, 5, 10, 20):
                        r = degerlendir(egitim, ym, tp, sl, tut)
                        if len(r) < 30:
                            continue
                        adaylar.append((sum(x["net"] for x in r), ym, tp, sl, tut))
        adaylar.sort(reverse=True)

        print(f" {'yön':<10}{'TP':>6}{'SL':>6}{'tut':>6}"
              f"{'eğitim NET':>13}{'TEST NET':>11}{'test/işlem':>12}{'test n':>8}")
        for _, ym, tp, sl, tut in adaylar[:8]:
            r_test = degerlendir(test, ym, tp, sl, tut)
            if len(r_test) < 10:
                continue
            print(f" {ym:<10}{tp:>6.1f}{sl:>6.1f}{tut:>6}"
                  f"{_:>+13.2f}{sum(x['net'] for x in r_test):>+11.2f}"
                  f"{statistics.mean(x['net'] for x in r_test):>+12.2f}{len(r_test):>8}")
        print("\n > Test sütunu pozitif DEĞİLSE o ayar ezberlenmiştir, güvenmeyin.")

    if not en_iyi:
        print(" yeterli sinyal yok (her ayar için en az 10 gerekli)")

    print("\n" + "=" * 86)
    print(" MEVCUT AYAR (momentum, TP 0.8 / SL 0.5 / 2 dk)")
    print("=" * 86)
    r = degerlendir(gecerli, "momentum", 0.8, 0.5, 2)
    if r:
        print(f"  n={len(r)}  isabet={sum(1 for x in r if x['net']>0)/len(r)*100:.1f}%  "
              f"ort NET={statistics.mean(x['net'] for x in r):+.2f} USDT  "
              f"TOPLAM={sum(x['net'] for x in r):+.2f} USDT")
        from collections import Counter
        print(f"  sonuçlar: {dict(Counter(x['durum'] for x in r))}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
