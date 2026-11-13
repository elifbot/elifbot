"""Emir katmanı: KAĞIT (simülasyon) / Binance Futures / OKX Swap.

Modlar:
  kagit   → hiçbir borsaya bağlanmaz; sanal bakiye, canlı piyasa fiyatıyla
            simüle dolum (para riski yok — önerilen başlangıç modu)
  testnet → Binance Futures testnet ağı veya OKX demo trading
            (sahte para, ama gerçek API akışı)
  gercek  → GERÇEK EMİRLER — kullanıcının kendi API anahtarıyla, kendi paran

Tüm borsa sınıfları aynı arayüzü sunar:
  bakiye() / fiyat() / kaldirac_ayarla() / market_ac() / market_kapat() /
  pozisyonlar()
"""
import asyncio
import base64
import hashlib
import hmac
import json
import math
import time
from datetime import datetime, timezone

import httpx

import config
import database as db
import market_data as md


class EmirHatasi(Exception):
    """Emir reddedildi / kurulamadı — kullanıcıya okunur mesaj."""


# ---------------------------------------------------------------- yardımcılar
def _fmt_qty(q: float) -> str:
    """Miktarı bilimsel gösterimden arındırıp stringe çevir (0.005 gibi)."""
    s = f"{q:.10f}".rstrip("0").rstrip(".")
    return s or "0"


def _yuvarla_adim(x: float, step: float) -> float:
    """Verilen adım boyutuna (0.001 gibi) AŞAĞI yuvarla."""
    if step <= 0:
        return x
    return round(math.floor(x / step) * step, 12)


def pozisyon_buyuklugu(bakiye: float, fiyat: float, kaldirac: int,
                       min_notional: float = 5.0) -> tuple[float, float]:
    """Risk yüzdesine göre pozisyon büyüklüğü → (miktar_coin, notional).

    Marjin = bakiye * RISK_POS_PCT% ; notional = marjin * kaldıraç.
    Notional borsanın minimumu (varsayılan 5 USDT) aşmalıdır.
    """
    if bakiye <= 0 or fiyat <= 0:
        raise EmirHatasi("Bakiye veya fiyat geçersiz")
    marjin = bakiye * config.RISK_POS_PCT / 100
    notional = marjin * max(1, kaldirac)
    if notional < min_notional:
        raise EmirHatasi(
            f"Pozisyon büyüklüğü ({notional:.2f} USDT) borsa minimumunun "
            f"({min_notional:.0f} USDT) altında — bakiye veya RISK_POS_PCT yükselt")
    return notional / fiyat, notional


def _yon_birimi(taraf: str) -> int:
    return 1 if taraf.upper() == "LONG" else -1


# ---------------------------------------------------------------- KAĞIT borsa
class KagitBorsasi:
    """Simülasyon borsası: bakiye SQLite'ta, pozisyonlar DB'de, dolum canlı fiyatla."""
    ad = "KAĞIT (simülasyon)"
    mod = "kagit"

    def __init__(self):
        if db.ayar_getir("paper_bakiye") is None:
            db.ayar_koy("paper_bakiye", str(config.PAPER_BALANCE))

    async def bakiye(self) -> float:
        try:
            return float(db.ayar_getir("paper_bakiye") or config.PAPER_BALANCE)
        except (TypeError, ValueError):
            return config.PAPER_BALANCE

    async def fiyat(self, sembol: str) -> float:
        snap = await md.fetch_snapshot(sembol)
        return float(snap.get("fiyat") or 0)

    async def kaldirac_ayarla(self, sembol: str, lev: int) -> None:
        return None  # simülasyonda kaldıraç serbest

    async def market_ac(self, sembol: str, taraf: str, miktar: float,
                        kaldirac: int) -> dict:
        fiyat = await self.fiyat(sembol)
        if fiyat <= 0:
            raise EmirHatasi(f"{sembol}: fiyat alınamadı")
        return {"giris": fiyat, "miktar": miktar,
                "emir_id": f"paper-{int(time.time() * 1000)}"}

    async def market_kapat(self, sembol: str, taraf: str, miktar: float) -> dict:
        fiyat = await self.fiyat(sembol)
        if fiyat <= 0:
            raise EmirHatasi(f"{sembol}: fiyat alınamadı")
        return {"cikis": fiyat, "emir_id": f"paper-{int(time.time() * 1000)}"}

    async def pozisyonlar(self) -> list[dict]:
        # kağıt pozisyonları DB'de yaşar (oto_trader doğrudan DB'den okur)
        return []

    def bakiye_artir(self, miktar: float) -> None:
        db.ayar_koy("paper_bakiye", str(round(self._bakiye_senk() + miktar, 6)))

    def _bakiye_senk(self) -> float:
        try:
            return float(db.ayar_getir("paper_bakiye") or 0)
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------- Binance Futures
class BinanceFutures:
    ad = "BINANCE"
    mod = "binance"

    def __init__(self, testnet: bool = False):
        self.testnet = testnet
        self.base = ("https://testnet.binancefuture.com" if testnet
                     else "https://fapi.binance.com")
        self.key = config.BINANCE_API_KEY
        self.secret = config.BINANCE_API_SECRET
        if not self.key or not self.secret:
            raise EmirHatasi(
                "Binance API anahtarları eksik. .env dosyasına BINANCE_API_KEY "
                "ve BINANCE_API_SECRET yaz (Futures Trading izni açık, "
                "Withdrawals izni kapalı olmalı).")
        self._lot: dict[str, tuple[float, float, float]] = {}
        self._lot_yuklu = False

    def _imza(self, query: str) -> str:
        return hmac.new(self.secret.encode(), query.encode(),
                        hashlib.sha256).hexdigest()

    async def _imzali(self, method: str, yol: str, params: dict | None = None):
        p = dict(params or {})
        p["timestamp"] = str(int(time.time() * 1000))
        p["recvWindow"] = "10000"
        query = "&".join(f"{k}={v}" for k, v in p.items() if v is not None)
        url = f"{self.base}{yol}?{query}&signature={self._imza(query)}"
        headers = {"X-MBX-APIKEY": self.key}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.request(method, url, headers=headers)
            if r.status_code >= 400:
                try:
                    msg = r.json().get("msg", r.text)
                except Exception:
                    msg = r.text
                raise EmirHatasi(f"Binance {r.status_code}: {str(msg)[:200]}")
            return r.json()

    async def _lot_yukle(self) -> None:
        if self._lot_yuklu:
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base}/fapi/v1/exchangeInfo")
            r.raise_for_status()
            d = r.json()
        for s in d.get("symbols", []):
            if s.get("quoteAsset") != "USDT":
                continue
            step, minq, notional = 0.001, 0.001, 100.0
            for f in s.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
                    minq = float(f["minQty"])
                elif f["filterType"] == "MIN_NOTIONAL":
                    notional = float(f.get("notional", 100))
            self._lot[s["symbol"]] = (step, minq, notional)
        self._lot_yuklu = True

    async def bakiye(self) -> float:
        d = await self._imzali("GET", "/fapi/v2/balance")
        for a in d:
            if a.get("asset") == "USDT":
                return float(a.get("availableBalance") or 0)
        return 0.0

    async def fiyat(self, sembol: str) -> float:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base}/fapi/v1/premiumIndex",
                            params={"symbol": sembol})
            r.raise_for_status()
            d = r.json()
        return float(d.get("markPrice") or 0)

    async def kaldirac_ayarla(self, sembol: str, lev: int) -> None:
        await self._imzali("POST", "/fapi/v1/leverage",
                           {"symbol": sembol, "leverage": str(lev)})

    async def market_ac(self, sembol: str, taraf: str, miktar: float,
                        kaldirac: int) -> dict:
        await self._lot_yukle()
        step, minq, min_notional = self._lot.get(sembol, (0.001, 0.001, 100.0))
        fiyat = await self.fiyat(sembol)
        qty = _yuvarla_adim(miktar, step)
        if qty < minq or qty * fiyat < min_notional:
            raise EmirHatasi(
                f"{sembol}: miktar borsa minimumunun altında "
                f"(min {minq}, min notional {min_notional:.0f} USDT) — "
                f"RISK_POS_PCT veya bakiyeyi yükselt")
        side = "BUY" if taraf.upper() == "LONG" else "SELL"
        d = await self._imzali("POST", "/fapi/v1/order", {
            "symbol": sembol, "side": side, "type": "MARKET",
            "quantity": _fmt_qty(qty), "newOrderRespType": "RESULT",
        })
        avg = float(d.get("avgPrice") or 0) or fiyat
        return {"giris": avg, "miktar": qty,
                "emir_id": str(d.get("orderId", ""))}

    async def market_kapat(self, sembol: str, taraf: str, miktar: float) -> dict:
        await self._lot_yukle()
        side = "SELL" if taraf.upper() == "LONG" else "BUY"
        d = await self._imzali("POST", "/fapi/v1/order", {
            "symbol": sembol, "side": side, "type": "MARKET",
            "closePosition": "true", "newOrderRespType": "RESULT",
        })
        avg = float(d.get("avgPrice") or 0) or await self.fiyat(sembol)
        return {"cikis": avg, "emir_id": str(d.get("orderId", ""))}

    async def pozisyonlar(self) -> list[dict]:
        d = await self._imzali("GET", "/fapi/v2/positionRisk")
        out = []
        for p in d:
            amt = float(p.get("positionAmt") or 0)
            if amt == 0:
                continue
            out.append({
                "sembol": p.get("symbol", ""),
                "taraf": "LONG" if amt > 0 else "SHORT",
                "miktar": abs(amt),
                "giris": float(p.get("entryPrice") or 0),
                "pnl": float(p.get("unRealizedProfit") or 0),
            })
        return out


# ---------------------------------------------------------------- OKX Swap
class OkxSwap:
    ad = "OKX"
    mod = "okx"

    def __init__(self, demo: bool | None = None):
        self.key = config.OKX_API_KEY
        self.secret = config.OKX_API_SECRET
        self.passphrase = config.OKX_PASSPHRASE
        if not (self.key and self.secret and self.passphrase):
            raise EmirHatasi(
                "OKX API anahtarları eksik. .env dosyasına OKX_API_KEY, "
                "OKX_API_SECRET ve OKX_PASSPHRASE yaz.")
        # demo=None → .env'deki OKX_DEMO'ya bak; açıkça True/False geçilebilir
        self.demo = config.OKX_DEMO if demo is None else demo
        self.base = config.OKX_BASE
        self._insts: dict[str, dict] = {}
        self._insts_yuklu = False

    def _imza(self, ts: str, method: str, yol: str, body: str = "") -> str:
        mesaj = f"{ts}{method}{yol}{body}"
        return base64.b64encode(hmac.new(
            self.secret.encode(), mesaj.encode(),
            hashlib.sha256).digest()).decode()

    async def _imzali(self, method: str, yol: str, body: dict | None = None,
                      query: str = ""):
        ts = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        path = yol + (("?" + query.lstrip("?")) if query else "")
        b = json.dumps(body) if body else ""
        headers = {
            "OK-ACCESS-KEY": self.key,
            "OK-ACCESS-SIGN": self._imza(ts, method.upper(), path, b),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            headers["x-simulated-trading"] = "1"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.request(method.upper(), self.base + path,
                                headers=headers,
                                content=b if b else None)
            if r.status_code >= 400:
                raise EmirHatasi(f"OKX HTTP {r.status_code}: {r.text[:200]}")
            d = r.json()
        if str(d.get("code")) != "0":
            raise EmirHatasi(f"OKX: {str(d.get('msg') or d.get('data'))[:200]}")
        return d

    async def _instler(self) -> None:
        if self._insts_yuklu:
            return
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base}/api/v5/public/instruments",
                            params={"instType": "SWAP"})
            r.raise_for_status()
            d = r.json()
        for s in d.get("data", []):
            if s.get("settleCcy") == "USDT":
                self._insts[s["instId"]] = {
                    "ctVal": float(s.get("ctVal") or 1),
                    "lotSz": float(s.get("lotSz") or 1),
                    "minSz": float(s.get("minSz") or 1),
                }
        self._insts_yuklu = True

    @staticmethod
    def _inst(sembol: str) -> str:
        return sembol.replace("USDT", "") + "-USDT-SWAP"

    async def bakiye(self) -> float:
        d = await self._imzali("GET", "/api/v5/account/balance",
                               query="ccy=USDT")
        try:
            det = d["data"][0]["details"]
            for a in det:
                if a.get("ccy") == "USDT":
                    return float(a.get("availEq") or a.get("availBal") or 0)
        except (KeyError, IndexError, TypeError):
            pass
        return 0.0

    async def fiyat(self, sembol: str) -> float:
        snap = await md.fetch_snapshot(sembol)
        return float(snap.get("fiyat") or 0)

    async def kaldirac_ayarla(self, sembol: str, lev: int) -> None:
        await self._imzali("POST", "/api/v5/account/set-leverage", {
            "instId": self._inst(sembol), "lever": str(lev),
            "mgnMode": "isolated"})

    async def market_ac(self, sembol: str, taraf: str, miktar: float,
                        kaldirac: int) -> dict:
        inst = self._inst(sembol)
        await self._instler()
        info = self._insts.get(inst)
        if not info:
            raise EmirHatasi(f"{sembol}: OKX swap listesinde yok")
        fiyat = await self.fiyat(sembol)
        if fiyat <= 0:
            raise EmirHatasi(f"{sembol}: fiyat alınamadı")
        sz = _yuvarla_adim(miktar / info["ctVal"], info["lotSz"])
        if sz < info["minSz"] or sz * info["ctVal"] * fiyat < 5:
            raise EmirHatasi(
                f"{sembol}: kontrakt miktarı OKX minimumunun altında "
                f"(min {info['minSz']} kontrakt) — RISK_POS_PCT veya "
                f"bakiyeyi yükselt")
        await self.kaldirac_ayarla(sembol, kaldirac)
        govde = {
            "instId": inst, "tdMode": "isolated", "ordType": "market",
            "side": "buy" if taraf.upper() == "LONG" else "sell",
            "sz": _fmt_qty(sz),
        }
        try:
            cfg = await self._imzali("GET", "/api/v5/account/config")
            pos_mode = cfg["data"][0].get("posMode", "net_mode")
        except Exception:
            pos_mode = "net_mode"
        if pos_mode == "long_short_mode":
            govde["posSide"] = "long" if taraf.upper() == "LONG" else "short"
        d = await self._imzali("POST", "/api/v5/trade/order", govde)
        ord_id = d["data"][0].get("ordId", "")
        avg = await self._ort_fiyat(inst, ord_id)
        return {"giris": avg or fiyat, "miktar": sz * info["ctVal"],
                "emir_id": ord_id}

    async def _ort_fiyat(self, inst: str, ord_id: str) -> float:
        for _ in range(5):
            await asyncio.sleep(0.6)
            try:
                d = await self._imzali("GET", "/api/v5/trade/order",
                                       query=f"instId={inst}&ordId={ord_id}")
                o = d["data"][0]
                if o.get("state") in ("filled", "partially_filled") and o.get("avgPx"):
                    return float(o["avgPx"])
            except Exception:
                pass
        return 0.0

    async def market_kapat(self, sembol: str, taraf: str, miktar: float) -> dict:
        cikis_tahmin = await self.fiyat(sembol)
        govde = {"instId": self._inst(sembol), "mgnMode": "isolated",
                 "autoCxl": "true"}
        try:
            cfg = await self._imzali("GET", "/api/v5/account/config")
            pos_mode = cfg["data"][0].get("posMode", "net_mode")
        except Exception:
            pos_mode = "net_mode"
        if pos_mode == "long_short_mode":
            govde["posSide"] = "long" if taraf.upper() == "LONG" else "short"
        await self._imzali("POST", "/api/v5/trade/close-position", govde)
        return {"cikis": cikis_tahmin, "emir_id": ""}

    async def pozisyonlar(self) -> list[dict]:
        await self._instler()
        d = await self._imzali("GET", "/api/v5/account/positions",
                               query="instType=SWAP")
        out = []
        for p in d.get("data", []):
            pos = float(p.get("pos") or 0)
            if pos == 0:
                continue
            inst = p.get("instId", "")
            info = self._insts.get(inst, {})
            posside = p.get("posSide", "net")
            if posside == "net":
                t = "LONG" if pos > 0 else "SHORT"
            else:
                t = "LONG" if posside in ("long", "buy") else "SHORT"
            sembol = inst.replace("-USDT-SWAP", "") + "USDT"
            out.append({"sembol": sembol, "taraf": t,
                        "miktar": abs(pos) * info.get("ctVal", 1),
                        "giris": float(p.get("avgPx") or 0),
                        "pnl": float(p.get("upl") or 0)})
        return out


# ---------------------------------------------------------------- fabrika
def borsa_olustur():
    """config.TRADE_MODE + TRADE_EXCHANGE'e göre uygun borsayı kurar."""
    mod = (config.TRADE_MODE or "kagit").lower()
    borsa = (config.TRADE_EXCHANGE or "binance").lower()

    if mod == "kagit":
        return KagitBorsasi()
    if borsa == "okx":
        if mod == "testnet":
            return OkxSwap(demo=True)
        if mod == "gercek":
            return OkxSwap(demo=False)
    elif borsa == "binance":
        if mod == "testnet":
            return BinanceFutures(testnet=True)
        if mod == "gercek":
            return BinanceFutures(testnet=False)
    raise EmirHatasi(
        f"Bilinmeyen ayar: TRADE_MODE={mod}, TRADE_EXCHANGE={borsa}")
