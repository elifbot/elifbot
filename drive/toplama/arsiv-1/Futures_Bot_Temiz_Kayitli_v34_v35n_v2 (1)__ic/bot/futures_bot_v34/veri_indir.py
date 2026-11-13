#!/usr/bin/env python3
"""
veri_indir.py — 7 günlük 1 dakikalık OKX mumlarını önbelleğe indirir.

Hız sınırı: /market/history-candles dakikada ~1200 istek. 289 sembol × ~102
sayfa = ~29.500 istek. 429 gelirse bekleyip yeniden dener. Her sembol biter
bitmez diske yazılır; betik kesilirse kaldığı yerden devam eder.

Çıktı: /home/user/okx_onbellek.npz
        anahtar = sembol, değer = Nx6 float64
        kolonlar: [ts_ms, open, high, low, close, volume_quote]
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import os
import time

import aiohttp
import numpy as np

OKX_CANDLE = "https://www.okx.com/api/v5/market/history-candles"
OKX_INSTR = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
PARCA = "/home/user/.veri_parca"


async def enstrumanlar(oturum) -> list[str]:
    async with oturum.get(OKX_INSTR, timeout=aiohttp.ClientTimeout(total=30)) as r:
        d = await r.json()
    return sorted(i["instId"] for i in d.get("data", [])
                  if i.get("settleCcy") == "USDT"
                  and i.get("state") == "live"
                  and str(i.get("instCategory")) == "1")


async def sembol_mumlari(oturum, sembol: str, sayfa: int,
                         kilit, hata_kutusu: list) -> np.ndarray | None:
    hepsi: list[list] = []
    after = ""
    async with kilit:
        for _ in range(sayfa):
            p = {"instId": sembol, "bar": "1m", "limit": "100"}
            if after:
                p["after"] = after
            veri = None
            for deneme in range(4):
                try:
                    async with oturum.get(OKX_CANDLE, params=p,
                                          timeout=aiohttp.ClientTimeout(total=25)) as r:
                        if r.status == 429:
                            await asyncio.sleep(1.5 * (deneme + 1))
                            continue
                        d = await r.json()
                    kod = d.get("code")
                    if kod == "0":
                        veri = d.get("data", [])
                        break
                    if kod in ("50011", "50004"):      # hız sınırı
                        await asyncio.sleep(1.5 * (deneme + 1))
                        continue
                    break
                except Exception as e:                 # ağ hatası
                    hata_kutusu.append(f"{sembol}: {type(e).__name__}")
                    await asyncio.sleep(0.5 * (deneme + 1))
            if not veri:
                break
            hepsi.extend(veri)
            after = veri[-1][0]
            await asyncio.sleep(0.10)
    if len(hepsi) < 500:
        return None
    try:
        return np.array([[int(k[0]), float(k[1]), float(k[2]), float(k[3]),
                          float(k[4]), float(k[7])] for k in hepsi], dtype=np.float64)
    except (ValueError, IndexError):
        return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gun", type=int, default=7)
    ap.add_argument("--cikti", default="/home/user/okx_onbellek.npz")
    ap.add_argument("--eszamanli", type=int, default=4)
    ap.add_argument("--gecikme", type=float, default=0.10)
    a = ap.parse_args()

    os.makedirs(PARCA, exist_ok=True)
    sayfa = int(a.gun * 1440 / 100) + 2
    hatalar: list[str] = []

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as oturum:
        semboller = await enstrumanlar(oturum)
        var_olan = {os.path.basename(p)[:-4] for p in glob.glob(f"{PARCA}/*.npy")}
        kalan = [s for s in semboller if s not in var_olan]
        print(f"{len(semboller)} sembol · {len(var_olan)} zaten var · "
              f"{len(kalan)} indirilecek · {sayfa} sayfa × 100 mum", flush=True)

        kilit = asyncio.Semaphore(a.eszamanli)
        t0 = time.time()
        sayac = {"n": 0}

        async def bir(s: str):
            arr = await sembol_mumlari(oturum, s, sayfa, kilit, hatalar)
            if arr is not None:
                np.save(f"{PARCA}/{s}.npy", arr)
            sayac["n"] += 1
            if sayac["n"] % 20 == 0:
                gecen = time.time() - t0
                hiz = sayac["n"] / gecen if gecen else 0
                print(f"  {sayac['n']}/{len(kalan)} · {gecen/60:.1f} dk · "
                      f"{hiz*60:.1f} sembol/dk · kalan ~{(len(kalan)-sayac['n'])/hiz/60:.0f} dk",
                      flush=True)

        await asyncio.gather(*(bir(s) for s in kalan))

    parcalar = glob.glob(f"{PARCA}/*.npy")
    sonuc = {}
    for p in parcalar:
        sonuc[os.path.basename(p)[:-4]] = np.load(p)
    np.savez_compressed(a.cikti, **sonuc)
    boy = os.path.getsize(a.cikti) / 1e6
    print(f"\n{len(sonuc)} sembol → {a.cikti} ({boy:.0f} MB)")
    if hatalar:
        print(f"uyarı: {len(hatalar)} geçici hata (ilk 5): {hatalar[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
