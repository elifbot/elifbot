# -*- coding: utf-8 -*-
"""okx.py — OKX v5 USDT-SWAP adaptörü.

Kritik ayrıntılar
-----------------
* `tdMode="cross"` — izole değil (kullanıcı kuralı).
* `lever=10`, `mgnMode="cross"`.
* Stop emri **algo emri** olarak kurulur: `ordType="conditional"`,
  `slTriggerPx=<fiyat>`, `slOrdPx="-1"` (tetiklenince market), `reduceOnly=true`.
* `clOrdId` idempotency (alfanümerik, ≤32 karakter).
* Sembol formatı: `BTC-USDT-SWAP`; kontrat çarpanı `ctVal` ile gelir — 1 kontrat
  her zaman 1 coin değildir. Yanlış çarpan = 10 kat yanlış pozisyon.

İmza: `base64(hmac_sha256(timestamp + method + requestPath + body, secret))`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from ..types import EmirIstegi, EmirSonucu, EmirDurumu, EmirTipi, Enstruman, Yon

BASE = "https://www.okx.com"
WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"


def zaman_damgasi(ms: int | None = None) -> str:
    ms = ms if ms is not None else int(time.time() * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + f".{ms % 1000:03d}Z"


def imzala(sir: str, zaman: str, metod: str, yol: str, govde: str = "") -> str:
    mesaj = f"{zaman}{metod.upper()}{yol}{govde}"
    return base64.b64encode(
        hmac.new(sir.encode(), mesaj.encode(), hashlib.sha256).digest()).decode()


def emir_govdesi(istek: EmirIstegi) -> dict[str, Any]:
    """EmirIstegi -> OKX order gövdesi (saf fonksiyon)."""
    govde: dict[str, Any] = {
        "instId": istek.sembol,
        "tdMode": "cross",
        "side": "buy" if istek.yon is Yon.LONG else "sell",
        "sz": str(istek.adet),
        "clOrdId": istek.istemci_id[:32],
    }
    if istek.tip is EmirTipi.MARKET:
        govde["ordType"] = "market"
    elif istek.tip is EmirTipi.LIMIT:
        govde.update(ordType="limit", px=str(istek.fiyat))
    elif istek.tip is EmirTipi.STOP_MARKET:
        govde.update(ordType="conditional", slTriggerPx=str(istek.fiyat), slOrdPx="-1",
                     reduceOnly="true")
    if istek.reduce_only and "reduceOnly" not in govde:
        govde["reduceOnly"] = "true"
    return govde


def enstruman_coz(i: dict) -> Enstruman:
    return Enstruman(
        borsa="okx",
        sembol=i["instId"],
        baz=i.get("uly", i["instId"]).split("-")[0],
        fiyat_adimi=float(i.get("tickSz", 0.0001)),
        miktar_adimi=float(i.get("lotSz", 1)),
        min_miktar=float(i.get("minSz", 1)),
        min_notional_usd=5.0,
        kontrat_carpani=float(i.get("ctVal") or 1.0) * float(i.get("ctMult") or 1.0),
        max_kaldirac=int(float(i.get("lever") or 100)),
        durum="live" if i.get("state") == "live" else "durduruldu",
    )


@dataclass
class OkxAdaptoru:
    api_key: str
    api_secret: str
    passphrase: str
    oturum: Any
    demo: bool = False
    ad: str = "okx"

    def _basliklar(self, metod: str, yol: str, govde: str) -> dict[str, str]:
        ts = zaman_damgasi()
        h = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": imzala(self.api_secret, ts, metod, yol, govde),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            h["x-simulated-trading"] = "1"
        return h

    async def _istek(self, metod: str, yol: str, govde: dict | None = None) -> dict:
        ham = json.dumps(govde or {}, separators=(",", ":")) if metod != "GET" else ""
        sorgu = ("?" + "&".join(f"{k}={v}" for k, v in (govde or {}).items())) if metod == "GET" else ""
        tam_yol = yol + sorgu
        async with self.oturum.request(metod, BASE + tam_yol,
                                       headers=self._basliklar(metod, tam_yol, ham),
                                       data=ham if metod != "GET" else None) as r:
            return await r.json()

    # ------------------------------------------------------------ arayüz
    async def enstrumanlar(self) -> dict[str, Enstruman]:
        d = await self._istek("GET", "/api/v5/public/instruments",
                              {"instType": "SWAP"})
        cikti = {}
        for i in d.get("data", []):
            if i.get("settleCcy") != "USDT" or i.get("state") != "live":
                continue
            e = enstruman_coz(i)
            cikti[e.sembol] = e
        return cikti

    async def bakiye(self):
        from .base import Bakiye
        d = await self._istek("GET", "/api/v5/account/balance", {"ccy": "USDT"})
        try:
            detay = d["data"][0]["details"][0]
            return Bakiye(float(detay.get("eq", 0)), float(detay.get("availBal", 0)),
                          float(detay.get("frozenBal", 0)))
        except (KeyError, IndexError):
            return Bakiye(0, 0, 0)

    async def marjin_kur(self, sembol: str) -> bool:
        d = await self._istek("POST", "/api/v5/account/set-leverage",
                              {"instId": sembol, "lever": "10", "mgnMode": "cross"})
        return d.get("code") == "0"

    async def emir_gonder(self, istek: EmirIstegi) -> EmirSonucu:
        if istek.tip is EmirTipi.STOP_MARKET:
            d = await self._istek("POST", "/api/v5/trade/order-algo", emir_govdesi(istek))
            if d.get("code") != "0":
                return EmirSonucu(False, hata=str(d.get("data") or d.get("msg")))
            return EmirSonucu(True, emir_id=d["data"][0].get("algoId", ""), durum=EmirDurumu.YENI)
        d = await self._istek("POST", "/api/v5/trade/order", emir_govdesi(istek))
        if d.get("code") != "0":
            return EmirSonucu(False, hata=str(d.get("data") or d.get("msg")))
        kayit = d["data"][0]
        durum = {"filled": EmirDurumu.DOLDU, "partially_filled": EmirDurumu.KISMI,
                 "live": EmirDurumu.YENI, "canceled": EmirDurumu.IPTAL}.get(
            kayit.get("sCode") and "live" or "live", EmirDurumu.YENI)
        return EmirSonucu(True, emir_id=kayit.get("ordId", ""), durum=durum,
                          dolen_adet=float(kayit.get("accFillSz") or 0),
                          ort_fiyat=float(kayit.get("avgPx") or 0))

    async def emir_iptal(self, sembol: str, emir_id: str) -> bool:
        d = await self._istek("POST", "/api/v5/trade/cancel-algos",
                              [{"instId": sembol, "algoId": emir_id}])
        return d.get("code") == "0"

    async def pozisyonlar(self) -> dict[str, dict]:
        d = await self._istek("GET", "/api/v5/account/positions", {"instType": "SWAP"})
        cikti = {}
        for p in d.get("data", []):
            if float(p.get("pos", 0)) == 0:
                continue
            cikti[p["instId"]] = {
                "adet": abs(float(p["pos"])), "giris": float(p.get("avgPx", 0)),
                "yon": "LONG" if float(p["pos"]) > 0 else "SHORT",
                "marj": p.get("mgnMode", ""), "kaldirac": int(float(p.get("lever", 0))),
            }
        return cikti

    def ws_url(self) -> str:
        return WS_PUBLIC

    def ws_abonelik(self, semboller: list[str]) -> list[dict]:
        return [{"op": "subscribe",
                 "args": [{"channel": "trades", "instId": s} for s in semboller]}]

    def tick_normalize(self, mesaj: dict) -> list[dict]:
        if mesaj.get("arg", {}).get("channel") != "trades":
            return []
        cikti = []
        for d in mesaj.get("data", []):
            fiyat = float(d.get("px", 0))
            adet = float(d.get("sz", 0))
            alis = d.get("side") == "buy"
            cikti.append({
                "sembol": mesaj["arg"]["instId"],
                "baz": str(mesaj["arg"]["instId"]).split("-")[0],
                "fiyat": fiyat, "delta_usd": adet * fiyat,
                "alis_usd": adet * fiyat if alis else 0.0,
                "ts": float(d.get("ts", 0)) / 1000.0, "hacim24_usd": 0.0,
            })
        return cikti
