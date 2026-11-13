#!/usr/bin/env python3
"""
teshis.py — BAĞLANTI TEŞHİSİ

Farklı bir sunucuda "neden çalışmıyor?" sorusunu yanıtlar. Hiçbir şeyi
değiştirmez; sadece her uç noktayı dener ve tablo basar.

    python3 teshis.py
"""
from __future__ import annotations

import asyncio
import sys
import time

import aiohttp

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; S = "\033[0m"; D = "\033[2m"


def _isaret(kod) -> str:
    if kod == 200:
        return f"{G}✓ 200{S}"
    if kod in (301, 302, 307, 308):
        return f"{Y}↪ {kod}{S}"
    if kod == 451:
        return f"{R}✗ 451 bölgesel engel{S}"
    if kod in (0, None):
        return f"{R}✗ bağlanamadı{S}"
    return f"{R}✗ {kod}{S}"


async def http_dene(oturum, ad, url, bekle=10):
    t0 = time.time()
    try:
        async with oturum.get(url, timeout=aiohttp.ClientTimeout(total=bekle)) as r:
            ms = (time.time() - t0) * 1000
            return ad, url, _isaret(r.status), f"{ms:.0f} ms"
    except Exception as e:
        return ad, url, _isaret(0), type(e).__name__


async def ws_dene(oturum, ad, url, abonelik=None):
    t0 = time.time()
    try:
        async def _():
            async with oturum.ws_connect(url, max_msg_size=1 << 20) as ws:
                if abonelik:
                    await ws.send_json(abonelik)
                # abonelik varsa yalnızca VERİ mesajını bekle (olay mesajlarını atla)
                for _ in range(12):
                    msg = await ws.receive()
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        return False
                    import json as _j
                    d = _j.loads(msg.data)
                    if abonelik is None or ("event" not in d and "data" in d):
                        return True
                return False
        ok = await asyncio.wait_for(_(), timeout=10)
        ms = (time.time() - t0) * 1000
        return ad, url, (f"{G}✓ veri geliyor{S}" if ok else f"{Y}bağlandı, veri yok{S}"), f"{ms:.0f} ms"
    except asyncio.TimeoutError:
        return ad, url, f"{R}✗ zaman aşımı{S}", "—"
    except Exception as e:
        return ad, url, f"{R}✗ {type(e).__name__}{S}", str(e)[:28]


async def main() -> int:
    print("\n" + "=" * 78)
    print(" BAĞLANTI TEŞHİSİ")
    print("=" * 78)

    basliklar = []
    async with aiohttp.ClientSession() as s:
        print(f"\n{D}— OKX REST —{S}")
        for ad, url in [
            ("OKX enstrümanlar", "https://www.okx.com/api/v5/public/instruments?instType=SWAP"),
            ("OKX saat", "https://www.okx.com/api/v5/public/time"),
        ]:
            satir = await http_dene(s, ad, url)
            basliklar.append(satir)
            print(f"  {satir[0]:<22} {satir[2]:<26} {satir[3]}")

        print(f"\n{D}— Binance REST (vadeli) —{S}")
        for ad, url in [
            ("fapi.binance.com", "https://fapi.binance.com/fapi/v1/ping"),
            ("fapi1.binance.com", "https://fapi1.binance.com/fapi/v1/ping"),
            ("www.binance.com", "https://www.binance.com/fapi/v1/ping"),
            ("testnet (vadeli)", "https://testnet.binancefuture.com/fapi/v1/ping"),
            ("data-api.binance.vision", "https://data-api.binance.vision/api/v3/ping"),
        ]:
            satir = await http_dene(s, ad, url)
            basliklar.append(satir)
            print(f"  {satir[0]:<22} {satir[2]:<26} {satir[3]}")

        print(f"\n{D}— WebSocket —{S}")
        for ad, url, ab in [
            ("OKX public", "wss://ws.okx.com:443/ws/v5/public",
             {"op": "subscribe", "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]}),
            ("OKX business", "wss://ws.okx.com:443/ws/v5/business",
             {"op": "subscribe", "args": [{"channel": "candle1m", "instId": "BTC-USDT-SWAP"}]}),
            ("Binance fstream", "wss://fstream.binance.com/ws/btcusdt@ticker", None),
            ("Binance www", "wss://www.binance.com/ws/btcusdt@ticker", None),
        ]:
            satir = await ws_dene(s, ad, url, ab)
            basliklar.append(satir)
            print(f"  {satir[0]:<22} {satir[2]:<26} {satir[3]}")

        print(f"\n{D}— Paketler —{S}")
        for mod in ("aiohttp", "websockets", "certifi"):
            try:
                __import__(mod)
                print(f"  {mod:<22} {G}✓ kurulu{S}")
            except ImportError:
                print(f"  {mod:<22} {Y}kurulu değil{S}")

    # --- özet ---
    print("\n" + "=" * 78)
    calisan = [b for b in basliklar if "✓" in b[2]]
    print(f" Çalışan uç nokta: {len(calisan)}/{len(basliklar)}")

    binance_ok = any("binance" in b[1] and "fapi" in b[1] and "✓" in b[2] for b in basliklar)
    ws_binance = any(b[0].startswith("Binance") and "✓" in b[2] for b in basliklar)

    print()
    if ws_binance:
        print(f" {G}Binance WebSocket açık → --binance ws kullan (milisaniye){S}")
    elif binance_ok:
        print(f" {Y}Binance WebSocket kapalı, REST açık → --binance rest{S}")
    else:
        print(f" {R}Binance hiçbir şekilde erişilemiyor → sadece OKX çalışır{S}")

    print("=" * 78 + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
