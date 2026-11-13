"""Piyasa veri katmanı: Bybit v5 (birincil) + OKX (yedek) — anahtarsız kamu uçları.

Tüm fonksiyonlar async'tir ve ham (dict) veri döndürür. Sembol formatı: BTCUSDT.
"""
import httpx

from config import BYBIT_BASE, OKX_BASE, HTTP_TIMEOUT

# Bybit aralığı -> OKX bar eşlemesi
_INTERVAL_OKX = {"15": "15m", "60": "1H", "240": "4H", "D": "1D"}


def _okx_inst(symbol: str) -> str:
    """BTCUSDT -> BTC-USDT-SWAP"""
    return symbol.replace("USDT", "-USDT-SWAP")


async def _get(url: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- klines
async def fetch_klines(symbol: str, interval: str = "60", limit: int = 200) -> list[dict]:
    """Mum verisi (artan zaman sırası). Her eleman: ts,o,h,l,c,v (float)."""
    # 1) Bybit
    try:
        data = await _get(
            f"{BYBIT_BASE}/v5/market/kline",
            {"category": "linear", "symbol": symbol,
             "interval": interval, "limit": min(limit, 1000)},
        )
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            rows = data["result"]["list"][::-1]  # Bybit DESC -> ASC
            return [
                {"ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]), "v": float(r[5])}
                for r in rows
            ]
    except Exception:
        pass

    # 2) OKX yedek
    data = await _get(
        f"{OKX_BASE}/api/v5/market/candles",
        {"instId": _okx_inst(symbol), "bar": _INTERVAL_OKX.get(interval, "1H"),
         "limit": str(min(limit, 300))},
    )
    rows = data["data"][::-1]
    return [
        {"ts": int(r[0]), "o": float(r[1]), "h": float(r[2]),
         "l": float(r[3]), "c": float(r[4]), "v": float(r[5])}
        for r in rows
    ]


# ---------------------------------------------------------------- snapshot
async def fetch_snapshot(symbol: str) -> dict:
    """Anlık durum: fiyat, 24s değişim, funding, açık pozisyon (OI)."""
    # 1) Bybit
    try:
        data = await _get(f"{BYBIT_BASE}/v5/market/tickers",
                          {"category": "linear", "symbol": symbol})
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            t = data["result"]["list"][0]
            return {
                "kaynak": "Bybit",
                "fiyat": float(t["lastPrice"]),
                "deg24": float(t.get("price24hPcnt", 0)) * 100,
                "yuksek24": float(t.get("highPrice24h", 0)),
                "dusuk24": float(t.get("lowPrice24h", 0)),
                "funding": float(t.get("fundingRate", 0)),
                "oi": float(t.get("openInterest", 0)),
                "oi_deger": float(t.get("openInterestValue", 0)),
                "hacim_usdt": float(t.get("turnover24h", 0)),
            }
    except Exception:
        pass

    # 2) OKX yedek
    inst = _okx_inst(symbol)
    t = (await _get(f"{OKX_BASE}/api/v5/market/ticker", {"instId": inst}))["data"][0]
    snap = {
        "kaynak": "OKX",
        "fiyat": float(t["last"]),
        "deg24": (float(t["last"]) / float(t["open24h"]) - 1) * 100,
        "yuksek24": float(t["high24h"]),
        "dusuk24": float(t["low24h"]),
        "funding": 0.0,
        "oi": 0.0,
        "oi_deger": 0.0,
        "hacim_usdt": float(t.get("volCcy24h", 0)),
    }
    try:
        f = (await _get(f"{OKX_BASE}/api/v5/public/funding-rate",
                        {"instId": inst}))["data"][0]
        snap["funding"] = float(f["fundingRate"])
        oi = (await _get(f"{OKX_BASE}/api/v5/public/open-interest",
                         {"instId": inst, "instType": "SWAP"}))["data"][0]
        snap["oi"] = float(oi.get("oiCcy") or 0)
        snap["oi_deger"] = float(oi.get("oiUsd") or 0)
    except Exception:
        pass
    return snap


# ---------------------------------------------------------------- OI serisi
async def fetch_oi_series(symbol: str, limit: int = 25) -> list[tuple[int, float]]:
    """Saatlik açık pozisyon serisi (artan). [(ts, oi), ...] — olamazsa []."""
    try:
        data = await _get(
            f"{BYBIT_BASE}/v5/market/open-interest",
            {"category": "linear", "symbol": symbol,
             "intervalTime": "1h", "limit": min(limit, 200)},
        )
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            rows = data["result"]["list"][::-1]
            return [(int(r["timestamp"]), float(r["openInterest"])) for r in rows]
    except Exception:
        pass
    return []  # OKX'te kamu OI geçmişi sınırlı; motor eksik veriyle çalışır


async def check_symbol(symbol: str) -> bool:
    """Sembol vadeli piyasada işlem görüyor mu?"""
    try:
        snap = await fetch_snapshot(symbol)
        return snap["fiyat"] > 0
    except Exception:
        return False
