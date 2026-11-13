"""Gerçek kamu akışından ÖLÇÜLEN bağlam: CVD, piyasa genişliği, 15dk uyumu,
taker maliyeti.

NEDEN
  Maildeki V10 raporu üç kez şunu yazıyordu:
    "Akış ve piyasa genişliği bilinmiyor; varsayılan sıfır nötr değer,
     15dk yön teyidi ölçülmedi; bunlar gözlemlenmiş veri değildir."
  Yani konseyin 6 denetim boyutundan 3'ü ELDE VERİ OLMADAN, nötr varsayımla
  çalışıyordu — fail-closed görünümlü ama aslında sabit girdili bir denetim.
  Bu modül o üç boyutu gerçek kamu verisinden ölçer:

    flow      → son N saniyenin agresif alış/satış hacmi (CVD) ve baskı oranı
    breadth   → aynı anda izlenen sözleşmelerin yüzde kaçı aynı yönde
    mtf       → 15dk kapanmış mumdaki EMA yönü, 5dk sinyalle uyumlu mu
    cost      → gerçek makas + gerçek funding oranıyla gidiş-dönüş maliyeti

DÜRÜSTLÜK
  · Taker-agresör işaretleri borsanın KENDİ alanından gelir:
      Binance aggTrade `m` (isBuyerMaker), Gate `futures.trades` `size` işareti,
      OKX `trades` `side` (buy/sell).
  · Veri yoksa `available=False` döner ve konsey o boyutu "ölçülmedi"
    olarak işaretler; sıfır/nötr varsayım YAPILMAZ.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from omnistudio.core.types import Candle, Tick

UA = {"User-Agent": "Mozilla/5.0 (ACARBOT-OmniStudio research; paper only)"}

AGG_TRADES_PATH = {
    "binance_usdm": "/fapi/v1/aggTrades?symbol={s}&limit=1000",
    "binance_coinm": "/dapi/v1/aggTrades?symbol={s}&limit=1000",
    "okx_swap": "/api/v5/market/trades?instId={s}&limit=100",
    "okx_futures": "/api/v5/market/trades?instId={s}&limit=100",
    "gateio_usdt": "/api/v4/futures/usdt/trades?contract={s}&limit=1000",
    "gateio_btc": "/api/v4/futures/btc/trades?contract={s}&limit=1000",
}


def _to_base(qty_contracts: float, price: float, face: float, kind: str) -> float:
    """Sözleşme adedini BAZ varlık miktarına çevir (quote = baz × fiyat).

    · linear : 1 kontrat = `face` baz birim (Binance USD-M face=1)
    · inverse: 1 kontrat = `face` USD değer → baz = face / fiyat
    Böylece CVD quote cinsinden karşılaştırılabilir olur; birim karışmaz.
    """
    if kind == "inverse":
        return qty_contracts * face / price if price > 0 else 0.0
    return qty_contracts * face


def parse_ticks(market: str, payload: Any, symbol: str,
                face: float = 1.0, kind: str = "linear") -> list[Tick]:
    out: list[Tick] = []
    if market.startswith("binance"):
        if not isinstance(payload, list):
            raise ValueError("aggTrades yanıtı geçersiz")
        for r in payload:
            price, q = float(r["p"]), float(r["q"])
            out.append(Tick(exchange=market, symbol=symbol, price=price,
                            qty=_to_base(q, price, face, kind), ts_ms=int(r["T"]),
                            is_buyer_maker=bool(r.get("m"))))
    elif market.startswith("okx"):
        if str(payload.get("code")) != "0":
            raise ValueError("OKX trades yanıtı geçersiz")
        for r in payload.get("data", []):
            # side=buy → alıcı agresif  → is_buyer_maker=False
            price = float(r["px"])
            out.append(Tick(exchange=market, symbol=symbol, price=price,
                            qty=_to_base(float(r["sz"]), price, face, kind),
                            ts_ms=int(r["ts"]),
                            is_buyer_maker=str(r.get("side")) == "sell"))
    else:
        if not isinstance(payload, list):
            raise ValueError("Gate trades yanıtı geçersiz")
        for r in payload:
            size = float(r["size"])
            ts_raw = float(r["create_time_ms"])
            # Gate bu alanı saniye.ondalık olarak döndürür (ör. 1793909137.002).
            ts = int(ts_raw * 1000) if ts_raw < 1e11 else int(ts_raw)
            price = float(r["price"])
            out.append(Tick(exchange=market, symbol=symbol, price=price,
                            qty=_to_base(abs(size), price, face, kind), ts_ms=ts,
                            is_buyer_maker=size < 0))
    out.sort(key=lambda t: t.ts_ms)
    return out


@dataclass
class FlowWindow:
    """Kayan pencerede agresif alış/satış hacmi."""
    window_ms: int = 300_000
    ticks: deque = field(default_factory=lambda: deque(maxlen=4000))
    available: bool = False
    last_ms: int = 0

    def add(self, ticks: list[Tick]) -> None:
        for t in ticks:
            self.ticks.append(t)
        if ticks:
            self.available = True
            self.last_ms = ticks[-1].ts_ms

    def measure(self, now_ms: int) -> dict[str, Any]:
        cutoff = now_ms - self.window_ms
        buy = sell = 0.0
        n = 0
        for t in reversed(self.ticks):
            if t.ts_ms < cutoff:
                break
            n += 1
            if t.is_buyer_maker:
                sell += t.quote
            else:
                buy += t.quote
        total = buy + sell
        if not self.available or total <= 0:
            return {"available": False, "cvd_quote": 0.0, "buy_quote": buy,
                    "sell_quote": sell, "pressure": 0.0, "ticks": n,
                    "age_ms": (now_ms - self.last_ms) if self.last_ms else None}
        return {"available": True, "cvd_quote": buy - sell, "buy_quote": buy,
                "sell_quote": sell, "pressure": (buy - sell) / total, "ticks": n,
                "age_ms": now_ms - self.last_ms}


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def mtf_alignment(candles_5m: list[Candle], side: str,
                  now_ms: int, interval_ms: int = 300_000) -> dict[str, Any]:
    """5dk kapanmış mumlardan 15dk kapanmış mum üret, EMA20/50 yönüne bak.

    `side` ile uyum: LONG için 15dk kapanış > EMA20 > EMA50.
    """
    closed = [c for c in candles_5m
              if c.closed and c.open_ms + interval_ms <= now_ms]
    closed = sorted(closed, key=lambda c: c.open_ms)
    buckets: dict[int, list[Candle]] = {}
    for c in closed:
        key = c.open_ms - (c.open_ms % (3 * interval_ms))
        buckets.setdefault(key, []).append(c)
    agg: list[Candle] = []
    for key in sorted(buckets):
        rows = buckets[key]
        if len(rows) < 3:
            continue  # tamamlanmamış 15dk kutusu
        agg.append(Candle(symbol=rows[0].symbol, exchange=rows[0].exchange,
                          open_ms=key, open=rows[0].open, high=max(r.high for r in rows),
                          low=min(r.low for r in rows), close=rows[-1].close,
                          quote_volume=sum(r.quote_volume for r in rows), closed=True))
    if len(agg) < 55:
        return {"available": False, "aligned": None, "bars": len(agg),
                "reason": "15dk mum serisi < 55"}
    closes = [c.close for c in agg]
    e20, e50 = ema(closes, 20)[-1], ema(closes, 50)[-1]
    up = closes[-1] > e20 > e50
    down = closes[-1] < e20 < e50
    if side == "LONG":
        aligned = up
    elif side == "SHORT":
        aligned = down
    else:
        aligned = up or down
    return {"available": True, "aligned": bool(aligned), "bars": len(agg),
            "close": closes[-1], "ema20": e20, "ema50": e50,
            "regime": "UP" if up else "DOWN" if down else "MIXED"}


def breadth(all_candles: dict[str, list[Candle]], now_ms: int,
            interval_ms: int = 300_000) -> dict[str, Any]:
    """İzlenen evrende son kapanmış mumu pozitif olanların oranı."""
    up = down = 0
    for cs in all_candles.values():
        closed = [c for c in cs if c.closed and c.open_ms + interval_ms <= now_ms]
        if len(closed) < 2:
            continue
        chg = closed[-1].close / closed[-2].close - 1
        if chg > 0:
            up += 1
        elif chg < 0:
            down += 1
    total = up + down
    if total < 8:
        return {"available": False, "up": up, "down": down, "ratio": None,
                "sample": total}
    return {"available": True, "up": up, "down": down,
            "ratio": up / total, "sample": total}


def roundtrip_cost_bps(spread_bps: float, taker_fee_bps: float = 5.0,
                       slippage_bps: float = 2.0,
                       funding_rate: float | None = None,
                       expected_hold_hours: float = 0.25,
                       funding_interval_h: float = 8.0) -> dict[str, float]:
    """Gidiş-dönüş maliyet. Funding, pozisyon tutma süresine ORANLANARAK eklenir.

    DÜRÜSTLÜK: funding oranı gelecekte değişebilir; bu bir nokta tahminidir ve
    rapor `funding_assumed_flat=True` olarak işaretlenir.
    """
    fee = 2 * taker_fee_bps
    slip = 2 * slippage_bps
    funding = 0.0
    if funding_rate is not None and funding_interval_h > 0:
        funding = abs(funding_rate) * 10_000 * (expected_hold_hours / funding_interval_h)
    return {"spread": spread_bps, "fees": fee, "slippage": slip,
            "funding": funding, "total": spread_bps + fee + slip + funding,
            "funding_assumed_flat": 1.0 if funding_rate is not None else 0.0}


async def fetch_ticks(session: aiohttp.ClientSession, market: str,
                      symbol: str, face: float = 1.0, kind: str = "linear",
                      timeout: float = 10.0) -> list[Tick]:
    path = AGG_TRADES_PATH[market].format(s=symbol)
    base = ("https://www.binance.com" if market.startswith("binance")
            else "https://www.okx.com" if market.startswith("okx")
            else "https://api.gateio.ws")
    async with session.get(base + path, headers=UA,
                           timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        text = await r.text()
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        import json
        return parse_ticks(market, json.loads(text), symbol, face=face, kind=kind)
