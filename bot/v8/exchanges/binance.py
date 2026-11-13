# -*- coding: utf-8 -*-
"""binance.py — Binance USDT-M vadeli (fapi) adaptörü.

Kritik ayrıntılar
-----------------
* `marginType=CROSSED` — kullanıcı kuralı: izole DEĞİL.
* `leverage=10`.
* Stop emri: `STOP_MARKET` + `reduceOnly=true` + `workingType=MARK_PRICE`.
  `closePosition=true` kullanılmaz; çünkü kısmi kapatmalarda miktar uyuşmazlığı
  sahipsiz emir bırakır.
* `newClientOrderId` idempotency: ağ hatasında aynı id ile tekrar denenebilir.

Ağ çağrıları `oturum` nesnesine devredilir; testler `SahteOturum` ile imza ve
parametreleri ağa çıkmadan doğrular.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from ..types import EmirIstegi, EmirSonucu, EmirDurumu, EmirTipi, Enstruman, Yon

BASE = "https://fapi.binance.com"
WS = "wss://fstream.binance.com/stream"


def imzala(sir: str, sorgu: str) -> str:
    """Binance: HMAC-SHA256(query, secret) hex."""
    return hmac.new(sir.encode(), sorgu.encode(), hashlib.sha256).hexdigest()


def sorgu_olustur(params: dict[str, Any], sir: str, ts_ms: int | None = None) -> str:
    p = {k: v for k, v in params.items() if v is not None}
    p["timestamp"] = ts_ms if ts_ms is not None else int(time.time() * 1000)
    p.setdefault("recvWindow", 5000)
    govde = urllib.parse.urlencode(p)
    return f"{govde}&signature={imzala(sir, govde)}"


def emir_tipi(istek: EmirIstegi) -> dict[str, Any]:
    """EmirIstegi -> Binance order parametreleri (saf fonksiyon, test edilebilir)."""
    p: dict[str, Any] = {
        "symbol": istek.sembol,
        "side": "BUY" if istek.yon is Yon.LONG else "SELL",
        "newClientOrderId": istek.istemci_id or None,
    }
    if istek.tip is EmirTipi.MARKET:
        p.update(type="MARKET", quantity=istek.adet)
    elif istek.tip is EmirTipi.LIMIT:
        p.update(type="LIMIT", quantity=istek.adet, price=istek.fiyat,
                 timeInForce="GTX" if istek.post_only else "GTC")
    elif istek.tip is EmirTipi.STOP_MARKET:
        p.update(type="STOP_MARKET", quantity=istek.adet, stopPrice=istek.fiyat,
                 workingType="MARK_PRICE")
    elif istek.tip is EmirTipi.TAKE_PROFIT_MARKET:
        p.update(type="TAKE_PROFIT_MARKET", quantity=istek.adet, stopPrice=istek.fiyat,
                 workingType="MARK_PRICE")
    if istek.reduce_only:
        p["reduceOnly"] = "true"
    return p


def filtre_coz(sembol: dict) -> Enstruman:
    f = {x["filterType"]: x for x in sembol.get("filters", [])}
    return Enstruman(
        borsa="binance",
        sembol=sembol["symbol"],
        baz=sembol.get("baseAsset", sembol["symbol"].replace("USDT", "")),
        fiyat_adimi=float(f.get("PRICE_FILTER", {}).get("tickSize", 0.01)),
        miktar_adimi=float(f.get("LOT_SIZE", {}).get("stepSize", 0.001)),
        min_miktar=float(f.get("LOT_SIZE", {}).get("minQty", 0.001)),
        min_notional_usd=float(f.get("MIN_NOTIONAL", {}).get("notional", 5.0)),
        kontrat_carpani=1.0,
        max_kaldirac=125,
        durum="live" if sembol.get("status") == "TRADING" else "durduruldu",
    )


@dataclass
class BinanceAdaptoru:
    api_key: str
    api_secret: str
    oturum: Any                      # aiohttp.ClientSession benzeri

    ad: str = "binance"

    async def _imzali(self, metod: str, yol: str, params: dict | None = None) -> dict:
        q = sorgu_olustur(params or {}, self.api_secret)
        url = f"{BASE}{yol}?{q}"
        async with self.oturum.request(metod, url,
                                       headers={"X-MBX-APIKEY": self.api_key}) as r:
            return await r.json()

    async def _public(self, yol: str, params: dict | None = None) -> dict:
        url = f"{BASE}{yol}"
        async with self.oturum.request("GET", url, params=params) as r:
            return await r.json()

    # ------------------------------------------------------------ arayüz
    async def enstrumanlar(self) -> dict[str, Enstruman]:
        veri = await self._public("/fapi/v1/exchangeInfo")
        cikti = {}
        for s in veri.get("symbols", []):
            if s.get("quoteAsset") != "USDT" or s.get("contractType") != "PERPETUAL":
                continue
            if s.get("status") != "TRADING":
                continue
            e = filtre_coz(s)
            cikti[e.sembol] = e
        return cikti

    async def bakiye(self):
        from .base import Bakiye
        d = await self._imzali("GET", "/fapi/v2/balance")
        for b in d if isinstance(d, list) else d.get("data", []):
            if b.get("asset") == "USDT":
                return Bakiye(float(b.get("balance", 0)), float(b.get("availableBalance", 0)),
                              float(b.get("balance", 0)) - float(b.get("availableBalance", 0)))
        return Bakiye(0, 0, 0)

    async def marjin_kur(self, sembol: str) -> bool:
        try:
            await self._imzali("POST", "/fapi/v1/marginType",
                               {"symbol": sembol, "marginType": "CROSSED"})
        except Exception:
            pass  # -4046: zaten CROSS, hata değil
        d = await self._imzali("POST", "/fapi/v1/leverage", {"symbol": sembol, "leverage": 10})
        return int(d.get("leverage", 0) or 0) == 10

    async def emir_gonder(self, istek: EmirIstegi) -> EmirSonucu:
        d = await self._imzali("POST", "/fapi/v1/order", emir_tipi(istek))
        if "orderId" not in d:
            return EmirSonucu(False, hata=str(d.get("msg") or d))
        durum = {"NEW": EmirDurumu.YENI, "FILLED": EmirDurumu.DOLDU,
                 "PARTIALLY_FILLED": EmirDurumu.KISMI, "REJECTED": EmirDurumu.RED,
                 "EXPIRED": EmirDurumu.GECERSIZ}.get(d.get("status", "NEW"), EmirDurumu.YENI)
        return EmirSonucu(True, emir_id=str(d["orderId"]), durum=durum,
                          dolen_adet=float(d.get("executedQty", 0) or 0),
                          ort_fiyat=float(d.get("avgPrice", 0) or 0), ham=d)

    async def emir_iptal(self, sembol: str, emir_id: str) -> bool:
        d = await self._imzali("DELETE", "/fapi/v1/order", {"symbol": sembol, "orderId": emir_id})
        return d.get("status") in ("CANCELED", "NEW")

    async def pozisyonlar(self) -> dict[str, dict]:
        d = await self._imzali("GET", "/fapi/v2/positionRisk")
        cikti = {}
        for p in d if isinstance(d, list) else []:
            if float(p.get("positionAmt", 0)) != 0:
                cikti[p["symbol"]] = {
                    "adet": abs(float(p["positionAmt"])),
                    "giris": float(p["entryPrice"]),
                    "yon": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                    "marj": p.get("marginType", "").lower(),
                    "kaldirac": int(float(p.get("leverage", 0))),
                }
        return cikti

    def ws_url(self) -> str:
        return WS

    def ws_abonelik(self, semboller: list[str]) -> list[dict]:
        akislar = [f"{s.lower()}@aggTrade" for s in semboller]
        return [{"url": f"{WS}?streams={'/'.join(akislar)}"}]

    def tick_normalize(self, mesaj: dict) -> list[dict]:
        d = mesaj.get("data") or mesaj
        if d.get("e") != "aggTrade":
            return []
        fiyat = float(d.get("p", 0))
        adet = float(d.get("q", 0))
        alici = not bool(d.get("m", False))   # m=true -> alıcı maker, yani satış agresif
        return [{
            "sembol": d.get("s", ""), "baz": str(d.get("s", "")).replace("USDT", ""),
            "fiyat": fiyat, "delta_usd": adet * fiyat,
            "alis_usd": adet * fiyat if alici else 0.0,
            "ts": float(d.get("T", 0)) / 1000.0, "hacim24_usd": 0.0,
        }]
