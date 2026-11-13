"""Taranacak coin listesi: likit USDT-marjinli surekli (perpetual) kontratlar.
Sembol formati her yerde ccxt standardi: BASE/USDT:USDT"""
from __future__ import annotations

import asyncio
import json
import urllib.request

from .config import ExchangeCfg


def _get_json(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"User-Agent": "tradebot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - sabit https adresleri
        return json.loads(r.read())


def canon(base: str) -> str:
    return f"{base}/USDT:USDT"


def base_of(symbol: str) -> str:
    return symbol.split("/")[0]


async def binance_universe(ec: ExchangeCfg) -> list[str]:
    info = await asyncio.to_thread(_get_json, "https://fapi.binance.com/fapi/v1/exchangeInfo")
    tick = await asyncio.to_thread(_get_json, "https://fapi.binance.com/fapi/v1/ticker/24hr")
    ok = {s["symbol"] for s in info["symbols"]
          if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"}
    rows = sorted(((float(t["quoteVolume"]), t["symbol"]) for t in tick if t["symbol"] in ok), reverse=True)
    rows = [r for r in rows if r[0] >= ec.min_24h_volume_usd][: ec.max_symbols]
    return [canon(sym[:-4]) for _, sym in rows]


async def okx_universe(ec: ExchangeCfg) -> tuple[list[str], dict[str, float]]:
    """Doner: (semboller, kontrat degeri ctVal: 1 kontrat kac coin)"""
    inst = (await asyncio.to_thread(_get_json, "https://www.okx.com/api/v5/public/instruments?instType=SWAP"))["data"]
    ct = {i["instId"]: float(i["ctVal"]) for i in inst
          if i["instId"].endswith("-USDT-SWAP") and i.get("state") == "live" and i.get("ctType") == "linear"}
    tick = (await asyncio.to_thread(_get_json, "https://www.okx.com/api/v5/market/tickers?instType=SWAP"))["data"]
    rows = []
    for t in tick:
        if t["instId"] in ct:
            usd = float(t.get("volCcy24h") or 0) * float(t.get("last") or 0)   # volCcy24h: baz coin cinsinden
            if usd >= ec.min_24h_volume_usd:
                rows.append((usd, t["instId"]))
    rows = sorted(rows, reverse=True)[: ec.max_symbols]
    symbols = [canon(i.split("-")[0]) for _, i in rows]
    ctval = {canon(i.split("-")[0]): ct[i] for _, i in rows}
    return symbols, ctval
