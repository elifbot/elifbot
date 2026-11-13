"""NOVA-BOT — tek dosyalık, bağımsız PAPER vadeli işlem botu.

TASARIM KARARI: NEDEN BAŞKA BİR BOT
  Bu bot ne ACARBOT'tan ne MEGA-BOT'tan kod devralır; yalnız Python standart
  kütüphanesi + `aiohttp` kullanır (pandas/numpy/ccxt YOK). Böylece 15 dakikalık
  canlı testte "hangi katman ne kadar yer kaplıyor" sorusu ölçülebilir kalır.

DEĞİŞMEZ KURALLAR (kodda zorlanır, ayarla kapatılamaz)
  1. PAPER: borsaya EMİR GÖNDERİLMEZ. Özel API anahtarı okunmaz, imza atılmaz.
     Yalnız kamu (public) uçları kullanılır. `real_orders` daima 0'dır.
  2. Kârlılık iddiası yoktur. Rapor bunu her bölümde yazar.
  3. Sinyal YALNIZ kapanmış mumdan üretilir; açık mum karar üretmez.
  4. Karar anındaki makas ve tazelik doğrulanmadan pozisyon açılmaz.
  5. Funding oranı bilinmiyorsa veya funding anına 3 dakikadan az kaldıysa
     giriş reddedilir (bedava funding varsayımı yapılmaz).
  6. Likidasyon mesafesi %10'un altındaysa giriş reddedilir.

MİMARİ
  veri (REST+WS) → mum kapanışı → strateji (skor) → risk kapıları →
  PAPER defter (Decimal) → SQLite + JSONL kanıt → rapor

KOMUTLAR
  python3 nova.py live    --symbols 40 --minutes 15 --out runs/live-1
  python3 nova.py rejim   --minutes 15 --out runs/rejim-1     (emir yok, yalnız gözlem)
  python3 nova.py backtest --symbols 60 --bars 1500 --out runs/bt-1
  python3 nova.py doctor                                     (bağlantı tanısı)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlencode

import aiohttp

VERSION = "1.0.0"
UA = {"User-Agent": f"NOVA-BOT/{VERSION} (paper-only research)"}
BAR_MS = 60_000          # 1 dakikalık mum
TF_NAME = "1m"

#: Borsa başına kamu uçları. Hepsi anahtarsız ve yalnız OKUMA.
#: Asgari ürün yaşı (gün). Ölçüm: yeni listelenen sözleşmelerde makas sürekli
#: >6 bps kalıyor (fiyat keşfi oturmamış) ve sinyallerin neredeyse tamamı
#: SPREAD kapısında reddediliyordu. Gate.io `listing_age` alanı bu filtreyi
#: denetlenebilir kılar; alan yoksa (Binance/OKX) ürün yaşı bilinmiyordur ve
#: filtre uygulanmaz — bilinmeyen yaş "eski" sayılmaz.
MIN_LISTING_AGE_DAYS = 7

#: Likidite sıralamasında kullanılan asgari 24s quote hacmi (USDT).
MIN_TURNOVER_USD = 2_000_000.0

#: Kripto olmayan tokenize ürün adları (PAPER dışı bırakılır).
NON_CRYPTO_NAMES = (
    "ANTHROPIC", "OPENAI", "NVIDIA", "TESLA", "APPLE", "MICROSOFT", "GOOGLE",
    "META-", "AMAZON", "XAU", "XAG", "SPX", "SPY", "QQQ", "AAPL", "MSFT",
)

VENUES: dict[str, dict[str, str]] = {
    "binance_usdm": {
        "rest": "https://www.binance.com",
        "candles": "/fapi/v1/klines?symbol={s}&interval=1m&limit={n}",
        "tickers": "/fapi/v1/ticker/24hr",
        "funding": "/fapi/v1/premiumIndex?symbol={s}",
        "instruments": "/fapi/v1/exchangeInfo",
        "ws": "wss://fstream.binance.com/market/ws",
    },
    "okx_swap": {
        "rest": "https://www.okx.com",
        "candles": "/api/v5/market/candles?instId={s}&bar=1m&limit={n}",
        "tickers": "/api/v5/market/tickers?instType=SWAP",
        "funding": "/api/v5/public/funding-rate?instId={s}",
        "instruments": "/api/v5/public/instruments?instType=SWAP",
        "ws": "wss://ws.okx.com/ws/v5/business",
    },
    "gateio_usdt": {
        "rest": "https://api.gateio.ws",
        "candles": "/api/v4/futures/usdt/candlesticks?contract={s}&interval=1m&limit={n}",
        "tickers": "/api/v4/futures/usdt/tickers",
        "funding": "/api/v4/futures/usdt/contracts/{s}",
        "instruments": "/api/v4/futures/usdt/contracts",
        "ws": "wss://fx-ws.gateio.ws/v4/ws/usdt",
    },
}


# ==========================================================================
# yardımcılar
# ==========================================================================
def now_ms() -> int:
    return int(time.time() * 1000)


def utc_iso(ms: int | None = None) -> str:
    dt = datetime.fromtimestamp((ms if ms is not None else now_ms()) / 1000, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pct(a: float, b: float) -> float:
    return ((a / b) - 1.0) * 100.0 if b else 0.0


# ==========================================================================
# 1) VERİ KATMANI
# ==========================================================================
@dataclass(frozen=True)
class Bar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float          # quote (USDT) hacmi
    closed: bool = True

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3.0


@dataclass(frozen=True)
class Inst:
    """Borsanın KENDİ alanlarından doğrulanmış sözleşme."""
    venue: str
    market: str
    symbol: str
    settlement: str
    kind: str              # linear | inverse
    face: D                # 1 kontratın baz varlık karşılığı (linear)
    lot_step: D
    min_qty: D
    min_notional: D
    tick: D
    mmr_hint: D            # bakım marjı İPUCU (yoksa 0)
    listing_age_days: int = 0  # borsanın bildirdiği ürün yaşı (gün; 0 = bilinmiyor)
    max_lev: D | None = None
    reason: str = ""       # "" ise işlem yapılabilir
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.market}:{self.symbol}"

    @property
    def tradable(self) -> bool:
        return self.reason == ""


def parse_instruments(market: str, payload: Any) -> list[Inst]:
    out: list[Inst] = []
    if market == "binance_usdm":
        for r in payload.get("symbols", []):
            if str(r.get("contractType")) != "PERPETUAL":
                continue
            f = {x.get("filterType"): x for x in r.get("filters", []) or []}
            lot = f.get("LOT_SIZE", {})
            pr = f.get("PRICE_FILTER", {})
            no = f.get("MIN_NOTIONAL", {})
            settlement = str(r.get("marginAsset") or "")
            reason = ""
            if str(r.get("status")) != "TRADING":
                reason = f"durum={r.get('status')}"
            elif settlement != "USDT":
                reason = f"settlement={settlement}"
            out.append(Inst(
                venue="binance", market=market, symbol=str(r["symbol"]),
                settlement=settlement, kind="linear", face=D("1"),
                lot_step=D(str(lot.get("stepSize") or "0.001")),
                min_qty=D(str(lot.get("minQty") or "0.001")),
                min_notional=D(str(no.get("notional") or "5")),
                tick=D(str(pr.get("tickSize") or "0.0000001")),
                mmr_hint=D(str(r.get("requiredMarginPercent") or "0")) / 100,
                max_lev=None, reason=reason,
                extra={"liq_fee": r.get("liquidationFee")},
            ))
    elif market == "okx_swap":
        for r in payload.get("data", []):
            sym = str(r.get("instId") or "")
            settle = str(r.get("settleCcy") or "")
            ct = str(r.get("ctType") or "")
            reason = ""
            if str(r.get("state")) != "live":
                reason = f"durum={r.get('state')}"
            elif ct != "linear":
                reason = f"ctType={ct}"
            elif settle != "USDT":
                reason = f"settlement={settle}"
            elif "XPERP" in sym:
                reason = "X-PERP"
            elif any(t in sym.upper() for t in NON_CRYPTO_NAMES):
                reason = "kripto dışı dayanak"
            out.append(Inst(
                venue="okx", market=market, symbol=sym, settlement=settle,
                kind=ct or "unknown", face=D(str(r.get("ctVal") or "1")),
                lot_step=D(str(r.get("lotSz") or "1")),
                min_qty=D(str(r.get("minSz") or "1")),
                min_notional=D("0"),
                tick=D(str(r.get("tickSz") or "0.0000001")),
                mmr_hint=D("0"), max_lev=D(str(r.get("lever") or "0")) or None,
                reason=reason, extra={"ctValCcy": r.get("ctValCcy")},
            ))
    elif market == "gateio_usdt":
        for r in payload if isinstance(payload, list) else []:
            sym = str(r.get("name") or "")
            reason = ""
            if str(r.get("status")) != "trading":
                reason = f"durum={r.get('status')}"
            elif r.get("in_delisting"):
                reason = "delist"
            elif sym.endswith("_USDC"):
                reason = "USDC marjlı"
            out.append(Inst(
                venue="gateio", market=market, symbol=sym, settlement="USDT",
                kind="linear", face=D(str(r.get("quanto_multiplier") or "1")),
                lot_step=D("1"),
                min_qty=D(str(r.get("order_size_min") or "1")),
                min_notional=D("0"),
                tick=D(str(r.get("order_price_round") or "0.0000001")),
                mmr_hint=D(str(r.get("maintenance_rate") or "0")),
                max_lev=D(str(r.get("leverage_max") or "0")) or None,
                reason=reason, listing_age_days=int(r.get("listing_age") or 0),
            ))
    return out


def base_asset(market: str, symbol: str) -> str:
    """Sembolden taban varlık: BTCUSDT -> BTC, BTC-USDT-SWAP -> BTC, BTC_USDT -> BTC."""
    if market == "okx_swap":
        return symbol.split("-")[0].upper()
    if market == "gateio_usdt":
        return symbol.split("_")[0].upper()
    return symbol[:-4] if symbol.upper().endswith("USDT") else symbol.upper()


def cross_venue_bases(insts: Iterable[Inst]) -> set[str]:
    """Binance **ve** OKX'te birlikte listelenen taban varlık kümesi.

    ÖLÇÜLEN SORUN: Gate.io'nun USDT vadeli listesinde kripto dışı *hisse/endeks*
    sözleşmeleri var (ör. SNDK, INTC, SOXS) ve likidite filtresini geçiyorlar.
    Bunlar 7/24 işlem görse de dayanak varlık seans dışında fiyatlanmıyor; mum
    serisi kripto piyasasıyla aynı davranışı göstermiyor. Bu yüzden bir ürünün
    PAPER evrenine girmesi için dayanağının **hem Binance hem OKX** listesinde
    bulunması şartı eklendi (denetlenebilir, ek istek gerektirmez). Ölçüm: SNDK
    ve SOXL OKX'te de var, ama Binance'te yok → referans kümesi iki borsanın
    KESİŞİMİ alınarak bu ürünler her iki borsada da elenir.
    """
    per_venue: dict[str, set[str]] = {"binance_usdm": set(), "okx_swap": set()}
    for i in insts:
        if i.market in per_venue and i.tradable:
            per_venue[i.market].add(base_asset(i.market, i.symbol))
    return per_venue["binance_usdm"] & per_venue["okx_swap"]


def parse_candles(market: str, payload: Any) -> list[Bar]:
    bars: list[Bar] = []
    if market == "binance_usdm":
        for r in payload:
            bars.append(Bar(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                            float(r[4]), float(r[7]) if len(r) > 7 else 0.0, True))
    elif market == "okx_swap":
        if str(payload.get("code")) != "0":
            raise ValueError("okx candles")
        for r in payload.get("data", []):
            if len(r) >= 9:
                bars.append(Bar(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                                float(r[4]), float(r[7]), r[8] == "1"))
    else:
        for r in payload:
            bars.append(Bar(int(r["t"]) * 1000, float(r["o"]), float(r["h"]),
                            float(r["l"]), float(r["c"]), float(r.get("sum") or 0),
                            True))
    bars.sort(key=lambda b: b.open_ms)
    return bars


def parse_tickers(market: str, payload: Any) -> dict[str, tuple[float, float, int]]:
    """symbol → (bid, ask, ts_ms)"""
    out: dict[str, tuple[float, float, int]] = {}
    stamp = now_ms()
    if market == "binance_usdm":
        for r in payload:
            try:
                bid, ask = float(r["bidPrice"]), float(r["askPrice"])
                if bid > 0 and ask >= bid:
                    out[str(r["symbol"])] = (bid, ask, int(r.get("time") or stamp))
            except (KeyError, TypeError, ValueError):
                continue
    elif market == "okx_swap":
        for r in payload.get("data", []):
            try:
                bid, ask = float(r["bidPx"]), float(r["askPx"])
                if bid > 0 and ask >= bid:
                    out[str(r["instId"])] = (bid, ask, int(r.get("ts") or stamp))
            except (KeyError, TypeError, ValueError):
                continue
    else:
        for r in payload:
            try:
                bid, ask = float(r["highest_bid"]), float(r["lowest_ask"])
                if bid > 0 and ask >= bid:
                    out[str(r["contract"])] = (bid, ask, int(r.get("t") or 0) or stamp)
            except (KeyError, TypeError, ValueError):
                continue
    return out


def parse_funding(market: str, payload: Any) -> dict[str, float] | None:
    try:
        if market == "binance_usdm":
            return {"rate": float(payload.get("lastFundingRate") or 0.0),
                    "next_ms": float(payload["nextFundingTime"]),
                    "interval_h": 8.0}
        if market == "okx_swap":
            d = (payload.get("data") or [None])[0]
            if not d:
                return None
            return {"rate": float(d["fundingRate"]),
                    "next_ms": float(d["fundingTime"]), "interval_h": 8.0}
        if market == "gateio_usdt":
            return {"rate": float(payload.get("funding_rate") or 0.0),
                    "next_ms": float(payload["funding_next_apply"]) * 1000,
                    "interval_h": float(payload.get("funding_interval") or 28800) / 3600}
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return None


class Feed:
    """Kamu verisi okuyucu. Erişilemeyen borsa açıkça UNREACHABLE işaretlenir."""

    def __init__(self, concurrency: int = 16):
        self.session: aiohttp.ClientSession | None = None
        self.sem = asyncio.Semaphore(concurrency)
        self.ok: Counter = Counter()
        self.err: Counter = Counter()
        self.last_error: dict[str, str] = {}
        self.down: set[str] = set()

    async def __aenter__(self) -> "Feed":
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20), headers=UA,
            connector=aiohttp.TCPConnector(limit=64, ttl_dns_cache=300))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self.session:
            await self.session.close()

    async def get(self, market: str, path: str, timeout: float = 20.0) -> Any:
        if market in self.down:
            raise RuntimeError(f"{market} UNREACHABLE")
        assert self.session is not None
        url = VENUES[market]["rest"] + path
        async with self.sem:
            try:
                async with self.session.get(
                        url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    txt = await r.text()
                    if r.status != 200:
                        self.err[market] += 1
                        self.last_error[market] = f"HTTP {r.status}"
                        raise RuntimeError(f"HTTP {r.status}: {txt[:70]}")
                    self.ok[market] += 1
                    return json.loads(txt)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.err[market] += 1
                self.last_error[market] = f"{type(e).__name__}: {str(e)[:70]}"
                raise

    async def instruments(self, market: str) -> list[Inst]:
        payload = await self.get(market, VENUES[market]["instruments"], 30)
        return parse_instruments(market, payload)

    async def candles(self, market: str, symbol: str, n: int = 400) -> list[Bar]:
        path = VENUES[market]["candles"].format(s=symbol, n=min(n, 1000))
        return parse_candles(market, await self.get(market, path))

    async def candles_range(self, market: str, symbol: str, n: int = 1000) -> list[Bar]:
        """n kapanmış 1m mumu sayfa sayfa geriye doğru toplar (1000'lik dilimler)."""
        got: dict[int, Bar] = {}
        want = max(120, n)
        end: int | None = None
        for _ in range(40):
            need = min(1000, want - len(got) + 5)
            if need <= 5:
                break
            path = VENUES[market]["candles"].format(s=symbol, n=need)
            if end is not None:
                path += f"&endTime={end}" if market == "binance_usdm" else (
                    f"&after={end}" if market == "okx_swap" else f"&to={end // 1000}")
            page = parse_candles(market, await self.get(market, path, 25))
            new = 0
            for b in page:
                if b.closed and b.open_ms not in got:
                    got[b.open_ms] = b
                    new += 1
            if not page or new == 0:
                break
            end = min(b.open_ms for b in page)
            if len(got) >= want:
                break
        bars = sorted(got.values(), key=lambda b: b.open_ms)
        return bars[-want:]

    async def tickers(self, market: str) -> dict[str, tuple[float, float, int]]:
        return parse_tickers(market, await self.get(market, VENUES[market]["tickers"]))

    async def turnover(self, market: str) -> dict[str, float]:
        """Borsanın KENDİ bildirdiği 24 saatlik quote hacmi (USDT).

        Ölçülen hata: gate.io ticker'ında `volume_24h_usd` diye bir alan yok;
        sessizce 0 okunuyordu ve Gate havuzu tamamen eleniyordu. Artık her borsa
        kendi gerçek alanından okunur ve okunamayan alan 0 olarak raporlanır.
        """
        raw = await self.get(market, VENUES[market]["tickers"])
        out: dict[str, float] = {}

        def num(v: Any) -> float:
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        if market == "binance_usdm":
            for row in raw:
                out[str(row.get("symbol"))] = max(num(row.get("quoteVolume")),
                                                  num(row.get("volume")) * num(row.get("lastPrice")))
        elif market == "okx_swap":
            for row in raw.get("data", []):
                # volCcy24h: 24s hacim (coin) — USDT karşılığı son fiyatla tahmin edilir
                out[str(row.get("instId"))] = num(row.get("volCcy24h")) * num(row.get("last"))
        else:
            for row in raw:
                out[str(row.get("contract"))] = num(row.get("volume_24h_quote")) or (
                    num(row.get("volume_24h_settle")))
        return out

    async def funding(self, market: str, symbol: str) -> dict[str, float] | None:
        path = VENUES[market]["funding"].format(s=symbol)
        try:
            return parse_funding(market, await self.get(market, path, 12))
        except Exception:
            return None

    def health(self) -> dict[str, Any]:
        return {m: {"ok": self.ok[m], "err": self.err[m],
                    "down": m in self.down,
                    "last_error": self.last_error.get(m, "")} for m in VENUES}


# ==========================================================================
# 2) GÖSTERGELER (saf Python; hiçbir grafikte ileriye bakış yok)
# ==========================================================================
def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if len(values) < period + 2:
        return None
    up = dn = 0.0
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        ch = b - a
        up += max(ch, 0.0)
        dn += max(-ch, 0.0)
    if up + dn == 0:
        return 50.0
    return 100.0 * up / (up + dn)


def atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    if len(bars) < period + 2:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1:-1], bars[-period:]):
        trs.append(max(cur.high - cur.low,
                       abs(cur.high - prev.close),
                       abs(cur.low - prev.close)))
    return sum(trs) / len(trs)


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def adx(bars: Sequence[Bar], period: int = 14) -> float | None:
    if len(bars) < period * 2:
        return None
    plus = minus = 0.0
    trs = []
    for p, c in zip(bars[-(period + 1):-1], bars[-period:]):
        up = c.high - p.high
        dn = p.low - c.low
        plus += up if (up > dn and up > 0) else 0.0
        minus += dn if (dn > up and dn > 0) else 0.0
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    atr_v = sum(trs) / len(trs) if trs else 0.0
    if atr_v <= 0:
        return None
    pdi = 100.0 * (plus / period) / atr_v
    mdi = 100.0 * (minus / period) / atr_v
    if pdi + mdi == 0:
        return 0.0
    return 100.0 * abs(pdi - mdi) / (pdi + mdi)


def choppiness(bars: Sequence[Bar], period: int = 14) -> float | None:
    """0-100; yüksek = testere piyasa. ADX'in tamamlayıcısı."""
    if len(bars) < period + 1:
        return None
    w = bars[-period:]
    trs = []
    for p, c in zip(bars[-(period + 1):-1], w):
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    tr_sum = sum(trs)
    rng = max(b.high for b in w) - min(b.low for b in w)
    if tr_sum <= 0 or rng <= 0:
        return 100.0
    return 100.0 * math.log10(tr_sum / rng) / math.log10(period)


# ==========================================================================
# 3) STRATEJİ: 5 bağımsız oy → skor
# ==========================================================================
@dataclass
class Signal:
    side: str            # long | short
    score: float         # -5..+5 (işaret yön)
    votes: dict[str, int]
    atr: float
    close: float
    bar_ms: int
    note: str = ""


def strategi_skoru(bars: Sequence[Bar], params: dict) -> Signal | None:
    """5 bağımsız oydan oluşan skor. Hepsi kapanmış mumlardan hesaplanır.

    Oy 1 · Trend      : EMA9 > EMA21 > EMA55 (tersi short)
    Oy 2 · Momentum   : MACD çizgisi sinyalin doğru tarafında ve sıfırın aynı tarafında
    Oy 3 · RSI        : 52-72 arası long, 28-48 arası short (aşırı bölge dışı)
    Oy 4 · Yapı       : ADX>20 ve +DI/-DI yönü
    Oy 5 · Hacim      : son mum hacmi 20 mum ortalamasının >1.2 katı ve yönde
    Ek kapı: ATR yeterli, choppiness < 62 (testere değil).
    """
    need = 60
    if len(bars) < need:
        return None
    closes = [b.close for b in bars]
    e9, e21, e55 = ema(closes, 9), ema(closes, 21), ema(closes, 55)
    if len(e55) < len(closes):
        return None
    macd_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    macd_sig = ema(macd_line, 9)
    a = atr(bars)
    ch = choppiness(bars)
    ax = adx(bars)
    r = rsi(closes)
    if not a or a <= 0 or ch is None or ax is None or r is None:
        return None
    if ch > float(params.get("max_chop", 62.0)):
        return None
    last = bars[-1]
    vol_ma = sum(b.volume for b in bars[-21:-1]) / 20.0
    votes: dict[str, int] = {}
    votes["trend"] = (1 if e9[-1] > e21[-1] > e55[-1]
                      else -1 if e9[-1] < e21[-1] < e55[-1] else 0)
    # Momentum oyu: MACD çizgisi sinyalin doğru tarafında VE sıfırın aynı tarafında.
    # ("histogram genişliyor" kuralı ölçüldü: sabit eğimli trendde histogram
    #  sabit kalır, bu yüzden genişleme şartı sağlıklı trendleri de eliyordu.)
    votes["macd"] = (1 if macd_line[-1] > macd_sig[-1] and macd_line[-1] > 0
                     else -1 if macd_line[-1] < macd_sig[-1] and macd_line[-1] < 0 else 0)
    votes["rsi"] = (1 if 52 <= r <= 72 else -1 if 28 <= r <= 48 else 0)
    votes["adx"] = (1 if ax > 20 and e9[-1] > e55[-1]
                    else -1 if ax > 20 and e9[-1] < e55[-1] else 0)
    up_bar = last.close > last.open
    votes["hacim"] = (1 if vol_ma > 0 and last.volume > 1.2 * vol_ma and up_bar
                      else -1 if vol_ma > 0 and last.volume > 1.2 * vol_ma and not up_bar
                      else 0)
    score = float(sum(votes.values()))
    th = float(params.get("min_score", 3))
    if score >= th:
        return Signal("long", score, votes, a, last.close, last.open_ms, "skor≥eşik")
    if score <= -th:
        return Signal("short", score, votes, a, last.close, last.open_ms, "skor≤-eşik")
    return None


# ==========================================================================
# 4) PAPER DEFTER (Decimal; borsa kuralları uygulanır)
# ==========================================================================
@dataclass
class Config:
    equity: float = 1000.0
    risk_pct: float = 0.5              # işlem başına sermaye riski %
    max_positions: int = 4
    max_per_market: int = 2
    max_same_side: int = 3
    max_gross: float = 1200.0
    max_notional_trade: float = 250.0
    stop_atr: float = 1.2
    tp_atr: float = 2.4
    trail_at_r: float = 1.0
    breakeven_at_r: float = 0.8
    max_hold_sec: int = 1800
    daily_loss_pct: float = 2.0
    max_consec_loss: int = 4
    taker_bps: float = 5.0
    slip_bps: float = 2.0
    max_spread_bps: float = 6.0
    min_liq_dist_pct: float = 10.0
    leverage_for_liq: float = 3.0
    stop_window_ms: float = 90_000     # karar anındaki mum kapanışından bu kadar sonra
    funding_guard_min: float = 3.0


@dataclass
class Position:
    key: str
    market: str
    symbol: str
    side: str
    qty: D
    face: D
    entry: D
    stop: D
    tp: D
    notional: D
    open_fee: D
    funding: D
    opened_ms: int
    signal_id: str
    risk: D
    lev: D
    liq: D | None
    be: bool = False
    peak_fav: D = D("0")


@dataclass
class Trade:
    key: str
    market: str
    symbol: str
    side: str
    qty: str
    entry: str
    exit: str
    stop: str
    tp: str
    gross: str
    fees: str
    funding: str
    net: str
    reason: str
    opened_ms: int
    closed_ms: int
    hold_sec: float
    r: float
    equity_after: str


class Book:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.equity = D(str(cfg.equity))
        self.peak = self.equity
        self.dd = D("0")
        self.pos: dict[str, Position] = {}
        self.closed: list[Trade] = []
        self.rejects: Counter = Counter()
        self.fees = D("0")
        self.funding = D("0")
        self.losses_in_row = 0
        self.halt = ""
        self.marks: list[tuple[int, str]] = []

    # ---- kapılar ----
    def _reject(self, why: str) -> None:
        self.rejects[why] += 1

    def exposure(self) -> D:
        return sum((p.notional for p in self.pos.values()), D("0"))

    def plan(self, inst: Inst, bid: float, ask: float, side: str,
             atr_v: float, quote_ts: int) -> dict | None:
        cfg = self.cfg
        px = D(str(ask if side == "long" else bid))
        if px <= 0:
            self._reject("BAD_PRICE")
            return None
        dist = D(str(atr_v)) * D(str(cfg.stop_atr))
        if dist <= 0:
            self._reject("ATR_ZERO")
            return None
        lev = min(D(str(cfg.leverage_for_liq)), inst.max_lev) if inst.max_lev else D(str(cfg.leverage_for_liq))
        mmr = inst.mmr_hint if inst.mmr_hint and inst.mmr_hint > 0 else D("0.005")
        if mmr >= D("0.5"):
            mmr = mmr / 100
        if mmr >= D("1") / lev:
            self._reject("MMR_INVALID")
            return None
        liq_dist = (D("1") / lev - mmr) * 100
        if float(liq_dist) < cfg.min_liq_dist_pct:
            self._reject("LIQ_TOO_CLOSE")
            return None
        risk_amount = self.equity * D(str(cfg.risk_pct)) / 100
        notional = risk_amount / (dist / px)
        notional = min(notional, D(str(cfg.max_notional_trade)))
        unit = inst.face * px
        if unit <= 0:
            self._reject("CONTRACT_INVALID")
            return None
        raw_qty = notional / unit
        step = inst.lot_step if inst.lot_step > 0 else D("1")
        qty = (raw_qty / step).to_integral_value(rounding=ROUND_DOWN) * step
        if qty <= 0 or qty < inst.min_qty:
            self._reject("QTY_BELOW_MIN")
            return None
        notional = qty * unit
        if inst.min_notional > 0 and notional < inst.min_notional:
            self._reject("EXCHANGE_MIN_NOTIONAL")
            return None
        # tick hizası: stop/hedef borsanın fiyat adımına yuvarlanır
        tick = inst.tick if inst.tick > 0 else D("0.0000001")
        def snap(v: D) -> D:
            return (v / tick).to_integral_value() * tick
        sign = D("1") if side == "long" else D("-1")
        stop = snap(px - sign * dist)
        tp = snap(px + sign * dist * D(str(cfg.tp_atr / cfg.stop_atr)))
        if stop <= 0 or tp <= 0:
            self._reject("STOP_INVALID")
            return None
        fee = notional * D(str(cfg.taker_bps)) / 10000
        return {"qty": qty, "entry": px, "notional": notional, "stop": stop,
                "tp": tp, "fee": fee, "risk": dist * qty * inst.face,
                "lev": lev, "liq": snap(px * (1 - sign * liq_dist / 100))}

    def open(self, inst: Inst, bid: float, ask: float, side: str, atr_v: float,
             ts: int, signal_id: str, quote_ts: int) -> Position | None:
        cfg = self.cfg
        if self.halt:
            self._reject("HALTED_" + self.halt)
            return None
        if inst.key in self.pos:
            self._reject("ALREADY_OPEN")
            return None
        if len(self.pos) >= cfg.max_positions:
            self._reject("MAX_POSITIONS")
            return None
        if sum(1 for p in self.pos.values() if p.market == inst.market) >= cfg.max_per_market:
            self._reject("MAX_PER_MARKET")
            return None
        if sum(1 for p in self.pos.values() if p.side == side) >= cfg.max_same_side:
            self._reject("MAX_SAME_SIDE")
            return None
        plan = self.plan(inst, bid, ask, side, atr_v, quote_ts)
        if not plan:
            return None
        if self.exposure() + plan["notional"] > D(str(cfg.max_gross)):
            self._reject("MAX_GROSS")
            return None
        p = Position(key=inst.key, market=inst.market, symbol=inst.symbol,
                     side=side, qty=plan["qty"], face=inst.face,
                     entry=plan["entry"], stop=plan["stop"], tp=plan["tp"],
                     notional=plan["notional"], open_fee=plan["fee"],
                     funding=D("0"), opened_ms=ts, signal_id=signal_id,
                     risk=plan["risk"], lev=plan["lev"], liq=plan["liq"])
        self.pos[inst.key] = p
        return p

    def mark(self, key: str, bid: float, ask: float, ts: int) -> D:
        p = self.pos.get(key)
        if not p:
            return D("0")
        px = D(str(bid if p.side == "long" else ask))
        sign = D("1") if p.side == "long" else D("-1")
        p.peak_fav = max(p.peak_fav, (px - p.entry) * sign)
        return (px - p.entry) * sign * p.qty * p.face

    def funding_event(self, key: str, rate: float, mark: float) -> D:
        p = self.pos.get(key)
        if not p:
            return D("0")
        value = p.qty * p.face * D(str(mark))
        delta = -D(str(1 if p.side == "long" else -1)) * value * D(str(rate))
        p.funding += delta
        self.funding += delta
        self.equity += delta
        return delta

    def check_exit(self, key: str, bid: float, ask: float, ts: int) -> Trade | None:
        p = self.pos.get(key)
        if not p:
            return None
        cfg = self.cfg
        sign = D("1") if p.side == "long" else D("-1")
        px = D(str(bid if p.side == "long" else ask))
        if (px - p.stop) * sign <= 0:
            return self._close(p, px, ts, "STOP")
        if (px - p.tp) * sign >= 0:
            return self._close(p, px, ts, "TAKE_PROFIT")
        if p.liq is not None and (px - p.liq) * sign <= 0:
            return self._close(p, px, ts, "LIQ_ESTIMATE")
        if (px - p.entry) * sign >= p.risk / (p.qty * p.face) * D(str(cfg.breakeven_at_r)):
            fee_pct = D(str((cfg.taker_bps * 2 + cfg.slip_bps * 2))) / 10000
            be = p.entry * (1 + sign * fee_pct)
            trail = px - sign * p.risk / (p.qty * p.face) * D(str(cfg.trail_at_r))
            p.stop = max(p.stop, be, trail) if p.side == "long" else min(p.stop, be, trail)
            p.be = True
        if (ts - p.opened_ms) / 1000 > cfg.max_hold_sec:
            return self._close(p, px, ts, "MAX_HOLD")
        return None

    def _close(self, p: Position, px: D, ts: int, reason: str) -> Trade:
        cfg = self.cfg
        sign = D("1") if p.side == "long" else D("-1")
        slip = px * D(str(cfg.slip_bps)) / 10000
        exit_px = px - sign * slip
        gross = (exit_px - p.entry) * sign * p.qty * p.face
        close_fee = p.notional * (exit_px / p.entry) * D(str(cfg.taker_bps)) / 10000
        fees = p.open_fee + close_fee
        net = gross - fees - p.funding
        self.equity += net
        self.fees += fees
        self.peak = max(self.peak, self.equity)
        self.dd = max(self.dd, self.peak - self.equity)
        if net > 0:
            self.losses_in_row = 0
        else:
            self.losses_in_row += 1
        t = Trade(key=p.key, market=p.market, symbol=p.symbol, side=p.side,
                  qty=str(p.qty), entry=str(p.entry), exit=str(exit_px),
                  stop=str(p.stop), tp=str(p.tp), gross=str(gross),
                  fees=str(fees), funding=str(p.funding), net=str(net),
                  reason=reason, opened_ms=p.opened_ms, closed_ms=ts,
                  hold_sec=round((ts - p.opened_ms) / 1000, 1),
                  r=float(net / p.risk) if p.risk > 0 else 0.0,
                  equity_after=str(self.equity))
        self.closed.append(t)
        del self.pos[p.key]
        floor = D(str(cfg.equity)) * (1 - D(str(cfg.daily_loss_pct)) / 100)
        if self.equity <= floor:
            self.halt = "DAILY_LOSS"
        elif self.losses_in_row >= cfg.max_consec_loss:
            self.halt = "CONSEC_LOSSES"
        return t

    def summary(self) -> dict[str, Any]:
        nets = [float(t.net) for t in self.closed]
        wins = [x for x in nets if x > 0]
        losses = [x for x in nets if x < 0]
        gw = sum(wins)
        gl = abs(sum(losses))
        per_market: dict[str, dict[str, float]] = defaultdict(
            lambda: {"trades": 0, "net": 0.0, "wins": 0})
        for t in self.closed:
            d = per_market[t.market]
            d["trades"] += 1
            d["net"] = round(d["net"] + float(t.net), 6)
            if float(t.net) > 0:
                d["wins"] += 1
        return {
            "equity_start": str(self.cfg.equity),
            "equity_now": str(self.equity.quantize(D("0.000001"))),
            "realized_net": str(sum((D(t.net) for t in self.closed), D("0")).quantize(D("0.000001"))),
            "trades": len(self.closed),
            "open": len(self.pos),
            "win_rate": round(len(wins) / len(nets) * 100, 2) if nets else 0.0,
            "profit_factor": round(gw / gl, 3) if gl > 0 else None,
            "avg_r": round(sum(t.r for t in self.closed) / len(self.closed), 3) if self.closed else 0.0,
            "fees": str(self.fees.quantize(D("0.000001"))),
            "funding": str(self.funding.quantize(D("0.000001"))),
            "max_dd": str(self.dd.quantize(D("0.000001"))),
            "halt": self.halt,
            "rejects": dict(self.rejects.most_common(14)),
            "per_market": {k: dict(v) for k, v in per_market.items()},
            "open_positions": [{k: str(v) for k, v in asdict(p).items()}
                               for p in self.pos.values()],
        }


# ==========================================================================
# 5) KALICILIK (SQLite + JSONL)
# ==========================================================================
class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS bars(
            market TEXT, symbol TEXT, open_ms INTEGER,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            closed INTEGER, PRIMARY KEY(market,symbol,open_ms));
        CREATE TABLE IF NOT EXISTS signals(
            id TEXT PRIMARY KEY, ts_ms INTEGER, market TEXT, symbol TEXT,
            side TEXT, score REAL, votes TEXT, atr REAL, close REAL, bar_ms INTEGER);
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, market TEXT, symbol TEXT,
            side TEXT, qty TEXT, entry TEXT, exit_px TEXT, stop TEXT, tp TEXT,
            gross TEXT, fees TEXT, funding TEXT, net TEXT, reason TEXT,
            opened_ms INTEGER, closed_ms INTEGER, r REAL);
        CREATE TABLE IF NOT EXISTS events(ts_ms INTEGER, kind TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS equity(ts_ms INTEGER, equity TEXT);
        """)
        self.buf: list[tuple] = []

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        self.db.execute("INSERT INTO events VALUES(?,?,?)",
                        (now_ms(), kind, json.dumps(payload, ensure_ascii=False, default=str)))

    def bar(self, market: str, symbol: str, b: Bar) -> None:
        self.buf.append((market, symbol, b.open_ms, b.open, b.high, b.low, b.close,
                         b.volume, int(b.closed)))
        if len(self.buf) >= 400:
            self.flush()

    def flush(self) -> None:
        if not self.buf:
            return
        self.db.executemany("INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?)",
                            self.buf)
        self.buf.clear()

    def signal(self, sig: Signal, sid: str, market: str, symbol: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO signals VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (sid, now_ms(), market, symbol, sig.side, sig.score,
                         json.dumps(sig.votes), sig.atr, sig.close, sig.bar_ms))

    def trade(self, t: Trade) -> None:
        self.db.execute(
            "INSERT INTO trades(key,market,symbol,side,qty,entry,exit_px,stop,tp,"
            "gross,fees,funding,net,reason,opened_ms,closed_ms,r) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.key, t.market, t.symbol, t.side, t.qty, t.entry, t.exit, t.stop,
             t.tp, t.gross, t.fees, t.funding, t.net, t.reason, t.opened_ms,
             t.closed_ms, t.r))

    def equity_point(self, eq: D) -> None:
        self.db.execute("INSERT INTO equity VALUES(?,?)", (now_ms(), str(eq)))

    def integrity(self) -> str:
        try:
            return self.db.execute("PRAGMA integrity_check").fetchone()[0]
        except Exception as e:  # pragma: no cover
            return f"error: {e}"

    def close(self) -> None:
        self.flush()
        self.db.close()


# ==========================================================================
# 6) CANLI DÖNGÜ (15 dakikalık test buradan çıkar)
# ==========================================================================
async def bars_from_ws(feed: Feed, market: str, symbols: list[str],
                       on_close, deadline: float, stats: Counter) -> None:
    """Borsanın kendi `x=true`/`confirm=1` dediği ANDA kapanmış 1m mumu teslim eder."""
    url = VENUES[market]["ws"]
    shard = 150 if market != "gateio_usdt" else 60
    groups = [symbols[i:i + shard] for i in range(0, len(symbols), shard)]

    async def one(group: list[str], delay: float) -> None:
        await asyncio.sleep(delay)
        lookup = set(group)
        backoff = 1.0
        tries = 0
        while time.monotonic() < deadline and tries < 5:
            tries += 1
            try:
                assert feed.session is not None
                async with feed.session.ws_connect(url, heartbeat=20, timeout=15,
                                                   max_msg_size=8 * 2 ** 20) as ws:
                    stats["ws_connections"] += 1
                    if tries > 1:
                        stats["ws_reconnects"] += 1
                    if market == "gateio_usdt":
                        for i, s in enumerate(group):
                            await ws.send_json({"time": int(time.time()),
                                                "channel": "futures.candlesticks",
                                                "event": "subscribe",
                                                "payload": [TF_NAME, s]})
                            if i % 20 == 19:
                                await asyncio.sleep(0.2)
                    elif market == "okx_swap":
                        await ws.send_json({"op": "subscribe",
                                            "args": [{"channel": "candle1m", "instId": s}
                                                     for s in group]})
                    else:
                        await ws.send_json({"method": "SUBSCRIBE",
                                            "params": [s.lower() + "@kline_1m" for s in group],
                                            "id": 1})
                    backoff = 1.0
                    while time.monotonic() < deadline:
                        try:
                            msg = await asyncio.wait_for(
                                ws.receive(), min(25, max(0.01, deadline - time.monotonic())))
                        except asyncio.TimeoutError:
                            if market == "okx_swap":
                                await ws.send_str("ping")
                            continue
                        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                        aiohttp.WSMsgType.ERROR):
                            raise RuntimeError("ws kapandı")
                        if msg.type != aiohttp.WSMsgType.TEXT or msg.data == "pong":
                            continue
                        try:
                            d = json.loads(msg.data)
                        except json.JSONDecodeError:
                            stats["ws_parse_err"] += 1
                            continue
                        parsed = _ws_bar(market, d)
                        if not parsed:
                            continue
                        sym, bar = parsed
                        if sym not in lookup:
                            continue
                        stats["ws_updates"] += 1
                        if not bar.closed:
                            continue
                        age = now_ms() - (bar.open_ms + BAR_MS)
                        if age < -2000:
                            stats["ws_future"] += 1
                            continue
                        stats["ws_closed"] += 1
                        stats["ws_latency_sum"] += max(0, age)
                        stats["ws_latency_max"] = max(stats["ws_latency_max"], max(0, age))
                        if age <= 5000:
                            stats["ws_closed_5s"] += 1
                        await on_close(market, sym, bar)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                stats["ws_errors"] += 1
                feed.last_error[f"ws:{market}"] = f"{type(e).__name__}: {str(e)[:60]}"
                await asyncio.sleep(min(backoff, max(0.0, deadline - time.monotonic())))
                backoff = min(backoff * 2, 20.0)

    tasks = [asyncio.create_task(one(g, i * 0.4)) for i, g in enumerate(groups)]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _ws_bar(market: str, d: Any) -> tuple[str, Bar] | None:
    if market == "binance_usdm":
        data = d.get("data", d) if isinstance(d, dict) else None
        if not isinstance(data, dict) or data.get("e") != "kline":
            return None
        k = data.get("k") or {}
        if k.get("i") != TF_NAME:
            return None
        return str(k.get("s")), Bar(int(k["t"]), float(k["o"]), float(k["h"]),
                                    float(k["l"]), float(k["c"]),
                                    float(k.get("q") or 0), k.get("x") is True)
    if market == "okx_swap":
        if not isinstance(d, dict):
            return None
        arg = d.get("arg") or {}
        if arg.get("channel") != "candle1m":
            return None
        rows = d.get("data") or []
        if not rows:
            return None
        r = rows[0]
        if len(r) < 9:
            return None
        return str(arg.get("instId")), Bar(int(r[0]), float(r[1]), float(r[2]),
                                           float(r[3]), float(r[4]), float(r[7]),
                                           r[8] == "1")
    if not isinstance(d, dict) or d.get("channel") != "futures.candlesticks":
        return None
    if d.get("event") != "update":
        return None
    res = d.get("result")
    if not isinstance(res, list) or not res:
        return None
    row = res[0]
    name = str(row.get("n") or "")
    pl = d.get("payload") or []
    sym = name.split("_", 1)[1] if name.startswith(TF_NAME + "_") else (
        pl[1] if len(pl) >= 2 else "")
    if not sym:
        return None
    return sym, Bar(int(row["t"]) * 1000, float(row["o"]), float(row["h"]),
                    float(row["l"]), float(row["c"]), float(row.get("a") or 0),
                    row.get("w") is True)


async def run_live(out: Path, minutes: float, n_symbols: int, cfg: Config,
                   params: dict, mode: str = "live") -> dict[str, Any]:
    """15 dakikalık canlı PAPER testi. mode="rejim" ise hiç pozisyon açılmaz."""
    out.mkdir(parents=True, exist_ok=True)
    lock = out / "run.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().split()[0])
        except (ValueError, IndexError):
            pid = 0
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
                alive = b"nova" in cmd
            except (OSError, FileNotFoundError):
                alive = False
        if alive:
            raise RuntimeError(f"{out} klasöründe hâlâ çalışan bir koşu var (pid={pid}); "
                               f"önce onu bitir ya da durdur")
    lock.write_text(f"{os.getpid()} {utc_iso()}", encoding="utf-8")
    store = Store(out / "nova.sqlite")
    book = Book(cfg)
    stats: Counter = Counter()
    log_path = out / "events.jsonl"
    started = time.monotonic()
    deadline = started + minutes * 60

    def log(kind: str, payload: dict[str, Any]) -> None:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": utc_iso(), "kind": kind, **payload},
                               ensure_ascii=False, default=str) + "\n")
        store.event(kind, payload)

    history: dict[str, list[Bar]] = {}
    quotes: dict[str, dict[str, tuple[float, float, int]]] = {}
    funding: dict[str, dict[str, float]] = {}
    last_decision: dict[str, int] = {}
    trade_log: list[dict[str, Any]] = []
    status = "FAILED"
    error = ""

    async with Feed() as feed:
        try:
            log("START", {"mode": mode, "minutes": minutes, "version": VERSION,
                          "config": asdict(cfg), "params": params})
            # 1) sözleşme evreni
            insts: list[Inst] = []
            for market in VENUES:
                try:
                    got = await feed.instruments(market)
                    stats[f"{market}.total"] = len(got)
                    stats[f"{market}.tradable"] = sum(1 for i in got if i.tradable)
                    insts.extend([i for i in got if i.tradable])
                except Exception as e:
                    feed.down.add(market)
                    log("VENUE_DOWN", {"market": market, "error": str(e)[:120]})
            if not insts:
                raise RuntimeError("Hiçbir borsadan işlem yapılabilir sözleşme alınamadı")
            # 2) ısınma: 1m mum geçmişi (karar için ≥60 kapanmış mum)
            # Aday seçimi: borsa başına 3× kota kadar aday ısıtılır, sonra
            # ÖLÇÜLEN 1m quote hacmine göre en likit olanlar seçilir. Alfabetik
            # sıralama ince likit / kripto dışı ürünleri öne çıkarıyordu.
            per_market = max(6, n_symbols // max(1, len({i.market for i in insts})))
            turnover: dict[str, float] = {}
            for market in {i.market for i in insts}:
                try:
                    turnover.update(await feed.turnover(market))
                except Exception:
                    pass
            bases = cross_venue_bases(insts)
            picked: list[Inst] = []
            for market in sorted({i.market for i in insts}):
                lst = [i for i in insts if i.market == market
                       and base_asset(market, i.symbol) in bases
                       and (i.listing_age_days == 0
                            or i.listing_age_days >= MIN_LISTING_AGE_DAYS)
                       and turnover.get(i.symbol, 0.0) >= MIN_TURNOVER_USD]
                lst.sort(key=lambda i: turnover.get(i.symbol, 0.0), reverse=True)
                stats[f"pool_{market}"] = len(lst)
                picked.extend(lst[:per_market])
            stats["turnover_known"] = sum(1 for i in picked if turnover.get(i.symbol))
            sem = asyncio.Semaphore(12)

            async def warm(inst: Inst) -> None:
                async with sem:
                    try:
                        bars = await feed.candles(inst.market, inst.symbol, 200)
                        closed = [b for b in bars if b.closed
                                  and b.open_ms + BAR_MS <= now_ms()]
                        if len(closed) >= 60:
                            history[inst.key] = closed[-200:]
                            for b in closed[-200:]:
                                store.bar(inst.market, inst.symbol, b)
                            stats["warm_ok"] += 1
                        else:
                            stats["warm_short"] += 1
                    except Exception:
                        stats["warm_err"] += 1

            await asyncio.gather(*(warm(i) for i in picked))
            stats["warm_candidates"] = len(history)

            def liquidity(key: str) -> float:
                bars = history.get(key) or []
                if not bars:
                    return 0.0
                tail = bars[-60:]
                return sum(b.volume for b in tail) / max(1, len(tail))

            by_mkt: dict[str, list[str]] = defaultdict(list)
            for key in history:
                by_mkt[key.split(":", 1)[0]].append(key)
            keep: dict[str, list[Bar]] = {}
            for m, keys in by_mkt.items():
                for key in sorted(keys, key=liquidity, reverse=True)[:per_market]:
                    keep[key] = history[key]
            dropped = len(history) - len(keep)
            history = keep
            picked = [i for i in picked if i.key in history]
            stats["dropped_illiquid"] = dropped
            stats["symbols"] = len(history)
            log("WARM", {"symbols": len(history), "requested": len(picked)})
            if not history:
                raise RuntimeError("Hiçbir sembol için mum geçmişi alınamadı")
            by_key = {i.key: i for i in picked}
            symbols_by_market: dict[str, list[str]] = defaultdict(list)
            for key in history:
                market, sym = key.split(":", 1)
                symbols_by_market[market].append(sym)

            async def quotes_loop() -> None:
                while time.monotonic() < deadline:
                    for market in symbols_by_market:
                        try:
                            quotes[market] = await feed.tickers(market)
                        except Exception:
                            stats["ticker_err"] += 1
                    # açık pozisyonları işaretle ve çıkışları kontrol et
                    for key in list(book.pos):
                        market, sym = key.split(":", 1)
                        q = quotes.get(market, {}).get(sym)
                        if not q:
                            continue
                        bid, ask, ts = q
                        book.mark(key, bid, ask, now_ms())
                        t = book.check_exit(key, bid, ask, now_ms())
                        if t:
                            store.trade(t)
                            trade_log.append(asdict(t))
                            stats["closed"] += 1
                            stats[f"exit_{t.reason}"] += 1
                            log("CLOSE", asdict(t))
                    store.equity_point(book.equity)
                    await asyncio.sleep(3)

            async def funding_loop() -> None:
                while time.monotonic() < deadline:
                    for key in list(book.pos) + [i.key for i in picked[:40]]:
                        inst = by_key.get(key)
                        if not inst:
                            continue
                        f = await feed.funding(inst.market, inst.symbol)
                        if f:
                            funding[key] = f
                            stats["funding_ok"] += 1
                        else:
                            stats["funding_missing"] += 1
                    # funding anı geçtiyse deftere yaz
                    now = now_ms()
                    for key in list(book.pos):
                        f = funding.get(key)
                        if not f:
                            continue
                        q = quotes.get(key.split(":", 1)[0], {}).get(key.split(":", 1)[1])
                        if q and now >= f["next_ms"] > 0:
                            delta = book.funding_event(key, f["rate"], (q[0] + q[1]) / 2)
                            stats["funding_events"] += 1
                            log("FUNDING", {"key": key, "rate": f["rate"],
                                            "delta": str(delta)})
                            await feed.funding(*key.split(":", 1))  # yenile
                            f2 = await feed.funding(key.split(":", 1)[0], key.split(":", 1)[1])
                            if f2:
                                funding[key] = f2
                    await asyncio.sleep(30)

            async def decide(market: str, sym: str, bar: Bar) -> None:
                key = f"{market}:{sym}"
                inst = by_key.get(key)
                if inst is None:
                    return
                if last_decision.get(key) == bar.open_ms:
                    stats["dup_bar"] += 1
                    return
                last_decision[key] = bar.open_ms
                bars = history.setdefault(key, [])
                if bars and bar.open_ms == bars[-1].open_ms:
                    bars[-1] = bar
                elif not bars or bar.open_ms > bars[-1].open_ms:
                    bars.append(bar)
                store.bar(market, sym, bar)
                stats["bars"] += 1
                age = now_ms() - (bar.open_ms + BAR_MS)
                if age > cfg.stop_window_ms:
                    stats["skip_stale"] += 1
                    return
                if mode == "rejim":
                    return
                sig = strategi_skoru(bars, params)
                if not sig:
                    stats["no_signal"] += 1
                    return
                stats["signals"] += 1
                sid = f"{market}-{sym}-{bar.open_ms}"
                store.signal(sig, sid, market, sym)
                log("SIGNAL", {"key": key, "side": sig.side, "score": sig.score,
                               "votes": sig.votes, "bar": bar.open_ms})
                q = quotes.get(market, {}).get(sym)
                if not q:
                    try:
                        quotes[market] = await feed.tickers(market)
                        q = quotes.get(market, {}).get(sym)
                    except Exception:
                        q = None
                reasons: list[str] = []
                if not q:
                    reasons.append("NO_QUOTE")
                else:
                    bid, ask, ts = q
                    mid = (bid + ask) / 2
                    spread_bps = (ask - bid) / mid * 10_000 if mid > 0 else 9e9
                    if spread_bps > cfg.max_spread_bps:
                        reasons.append("SPREAD")
                    if now_ms() - ts > 15_000:
                        reasons.append("STALE_QUOTE")
                    if abs(mid / bar.close - 1) * 10_000 > 25:
                        reasons.append("PRICE_DRIFT")
                f = funding.get(key)
                if not f:
                    reasons.append("FUNDING_UNKNOWN")
                elif f["next_ms"] > 0 and (f["next_ms"] - now_ms()) / 60000 < cfg.funding_guard_min:
                    reasons.append("FUNDING_SOON")
                if reasons:
                    for r in reasons:
                        stats[f"reject_{r}"] += 1
                    log("REJECT", {"key": key, "reasons": reasons})
                    return
                bid, ask, ts = q
                pos = book.open(inst, bid, ask, sig.side, sig.atr, now_ms(), sid, ts)
                if pos:
                    stats["opened"] += 1
                    stats[f"opened_{market}"] += 1
                    log("OPEN", {"key": key, "side": sig.side, "qty": str(pos.qty),
                                 "entry": str(pos.entry), "stop": str(pos.stop),
                                 "tp": str(pos.tp), "notional": str(pos.notional),
                                 "risk": str(pos.risk), "liq": str(pos.liq),
                                 "score": sig.score})
                else:
                    stats["reject_BOOK"] += 1

            async def on_close(market: str, sym: str, bar: Bar) -> None:
                await decide(market, sym, bar)

            tasks = [asyncio.create_task(quotes_loop()),
                     asyncio.create_task(funding_loop())]
            for market, syms in symbols_by_market.items():
                tasks.append(asyncio.create_task(
                    bars_from_ws(feed, market, sorted(syms), on_close, deadline, stats)))
            log("ACTIVE", {"symbols": len(history), "duration_sec": minutes * 60,
                           "mode": mode})
            print(f"[aktif] {len(history)} sembol, {minutes:.0f} dk, mod={mode}", flush=True)
            while time.monotonic() < deadline:
                await asyncio.sleep(min(10, max(0.5, deadline - time.monotonic())))
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # kapanış: açık pozisyonlar TAZE quote ile kapatılır, yoksa açık bırakılır
            for market in symbols_by_market:
                try:
                    quotes[market] = await feed.tickers(market)
                except Exception:
                    pass
            for key in list(book.pos):
                market, sym = key.split(":", 1)
                q = quotes.get(market, {}).get(sym)
                if q and now_ms() - q[2] <= 15_000:
                    t = book._close(book.pos[key], D(str(q[0] if book.pos[key].side == "long" else q[1])),
                                    now_ms(), "RUN_END")
                    store.trade(t)
                    trade_log.append(asdict(t))
                    stats["closed"] += 1
                    stats["exit_RUN_END"] += 1
                    log("CLOSE", asdict(t))
                else:
                    stats["left_open"] += 1
            status = "COMPLETED" if stats["bars"] > 0 else "INCOMPLETE"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log("ERROR", {"error": error})
        finally:
            store.flush()
            lock.unlink(missing_ok=True)
            active = time.monotonic() - started
            equity_curve = [tuple(r) for r in store.db.execute(
                "SELECT ts_ms, equity FROM equity ORDER BY ts_ms")]
            result = {
                "status": status,
                "mode": mode,
                "version": VERSION,
                "error": error,
                "started_utc": utc_iso(int((time.time() - active) * 1000)),
                "finished_utc": utc_iso(),
                "active_sec": round(active, 1),
                "requested_sec": round(minutes * 60, 1),
                "config": asdict(cfg),
                "params": params,
                "symbols": len(history),
                "stats": dict(stats),
                "book": book.summary(),
                "trades": trade_log,
                "venue_health": feed.health(),
                "db_integrity": store.integrity(),
                "equity_points": len(equity_curve),
                "real_orders": 0,
                "paper_only": True,
                "council_or_llm": "YOK — bu bot hiçbir dil modeli veya dış servis çağırmaz",
            }
            store.close()
            (out / "SONUC.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            from .report import yaz_rapor
            (out / "RAPOR.md").write_text(yaz_rapor(result), encoding="utf-8")
    return result


# ==========================================================================
# 7) BACKTEST (aynı strateji, aynı maliyet modeli, gerçek mumlar)
# ==========================================================================
def backtest(bars_by_symbol: dict[str, list[Bar]], insts: dict[str, Inst],
             cfg: Config, params: dict, funding_rate: float = 0.0001) -> dict[str, Any]:
    """Her sembol bağımsız, tek pozisyon; stop/hedef önce hangisi vurulursa.

    KÖTÜMSER VARSAYIM: aynı mumda hem stop hem hedef görülürse STOP kazanır.
    Giriş: sinyalden SONRAKİ mumun açılışı (ileriye bakış yok).
    """
    trades: list[dict[str, Any]] = []
    equity = cfg.equity
    peak = equity
    dd = 0.0
    cooldown = 5            # çıkıştan sonra aynı sembolde bekleme (mum)
    for key, bars in bars_by_symbol.items():
        inst = insts.get(key)
        if not inst or len(bars) < 120:
            continue
        i = 60
        while i < len(bars) - 1:
            sig = strategi_skoru(bars[:i + 1], params)
            if not sig:
                i += 1
                continue
            nxt = bars[i + 1]
            sign = 1 if sig.side == "long" else -1
            slip = cfg.slip_bps / 10000
            entry = nxt.open * (1 + sign * slip)
            dist = sig.atr * cfg.stop_atr
            stop = entry - sign * dist
            tp = entry + sign * dist * (cfg.tp_atr / cfg.stop_atr)
            risk_usd = equity * cfg.risk_pct / 100
            notional = min(risk_usd / (dist / entry), cfg.max_notional_trade)
            qty = notional / (float(inst.face) * entry)
            step = float(inst.lot_step)
            if step > 0:
                qty = int(qty / step) * step
            if qty <= 0 or qty < float(inst.min_qty):
                i += 1
                continue
            notional = qty * float(inst.face) * entry
            exit_px = None
            reason = ""
            exit_i = i + 1
            fee_rate = cfg.taker_bps / 10000
            funding_paid = 0.0
            for j in range(i + 1, min(len(bars), i + 1 + cfg.max_hold_sec // 60)):
                b = bars[j]
                held_min = (b.open_ms - bars[i + 1].open_ms) / 60000
                funding_paid += -sign * notional * funding_rate * (1 / 60 / 8)
                if (b.low <= stop) if sign > 0 else (b.high >= stop):
                    exit_px, reason, exit_i = stop, "STOP", j
                    break
                if (b.high >= tp) if sign > 0 else (b.low <= tp):
                    exit_px, reason, exit_i = tp, "TAKE_PROFIT", j
                    break
            if exit_px is None:
                exit_i = min(len(bars) - 1, i + 1 + cfg.max_hold_sec // 60)
                exit_px, reason = bars[exit_i].close, "MAX_HOLD"
            gross = (exit_px - entry) * sign * qty * float(inst.face)
            fees = (notional + qty * float(inst.face) * exit_px) * fee_rate
            net = gross - fees - funding_paid
            equity += net
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
            trades.append({"key": key, "side": sig.side, "net": round(net, 6),
                           "r": round(net / risk_usd, 4) if risk_usd else 0.0,
                           "reason": reason,
                           "hold_min": round((bars[exit_i].open_ms -
                                              bars[i + 1].open_ms) / 60000, 1)})
            # Pozisyon kapanana kadar yeni sinyal aranmaz; üstüne bekleme eklenir.
            i = exit_i + cooldown
            if equity <= cfg.equity * 0.5:      # sermayenin yarısı bitti → koşu durur
                trades.append({"key": key, "side": "halt", "net": 0.0, "r": 0.0,
                               "reason": "EQUITY_HALT", "hold_min": 0.0})
                break
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] < 0]
    gw = sum(t["net"] for t in wins)
    gl = abs(sum(t["net"] for t in losses))
    return {
        "trades": len(trades),
        "net": round(sum(t["net"] for t in trades), 4),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gw / gl, 3) if gl > 0 else None,
        "avg_r": round(sum(t["r"] for t in trades) / len(trades), 3) if trades else 0.0,
        "max_dd": round(dd, 4),
        "equity_start": cfg.equity,
        "equity_end": round(equity, 4),
        "exits": dict(Counter(t["reason"] for t in trades)),
        "per_symbol": dict(Counter(t["key"] for t in trades)),
        "sample": trades[:40],
    }


# ==========================================================================
# 8) CLI
# ==========================================================================
DEFAULT_PARAMS = {"min_score": 3, "max_chop": 62.0}


def _parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser("nova", description="NOVA-BOT — PAPER only")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="bağlantı ve veri tanısı")
    d.add_argument("--symbols", type=int, default=3)

    live = sub.add_parser("live", help="canlı PAPER testi (dakika)")
    live.add_argument("--minutes", type=float, default=15)
    live.add_argument("--symbols", type=int, default=40)
    live.add_argument("--out", required=True)
    live.add_argument("--min-score", type=int, default=3)
    live.add_argument("--risk-pct", type=float, default=0.5)
    live.add_argument("--equity", type=float, default=1000)

    rej = sub.add_parser("rejim", help="emir yok, yalnız 1m rejim gözlemi")
    rej.add_argument("--minutes", type=float, default=15)
    rej.add_argument("--symbols", type=int, default=40)
    rej.add_argument("--out", required=True)

    bt = sub.add_parser("backtest", help="geçmiş 1m mumlarla test")
    bt.add_argument("--symbols", type=int, default=60)
    bt.add_argument("--bars", type=int, default=1000)
    bt.add_argument("--out", required=True)
    bt.add_argument("--min-score", type=int, default=3)

    return ap.parse_args(argv)


async def _cmd_doctor(args: argparse.Namespace) -> int:
    async with Feed() as feed:
        print(f"NOVA-BOT {VERSION} — tanı")
        for market in VENUES:
            try:
                insts = await feed.instruments(market)
                good = [i for i in insts if i.tradable]
                print(f"  {market:14s} sözleşme={len(insts):5d} işlem-uygun={len(good):5d}")
                if good:
                    i0 = good[0]
                    bars = await feed.candles(market, i0.symbol, 5)
                    q = (await feed.turnover(market)).get(i0.symbol)
                    f = await feed.funding(market, i0.symbol)
                    print(f"                 örnek {i0.symbol}: mum={len(bars)} "
                          f"son={bars[-1].close if bars else '—'} "
                          f"24s_hacim={'var' if q else 'YOK'} funding={'var' if f else 'YOK'}")
            except Exception as e:
                print(f"  {market:14s} HATA {type(e).__name__}: {str(e)[:80]}")
    return 0


async def _cmd_backtest(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        print(f"UYARI: {out} dolu — sonuç dosyaları yenilenecek", flush=True)
    cfg = Config()
    params = dict(DEFAULT_PARAMS, min_score=args.min_score)
    async with Feed() as feed:
        insts: list[Inst] = []
        for market in VENUES:
            try:
                insts.extend([i for i in await feed.instruments(market) if i.tradable])
            except Exception:
                pass
        by_market: dict[str, list[Inst]] = defaultdict(list)
        for i in insts:
            by_market[i.market].append(i)
        turnover: dict[str, float] = {}
        for market in VENUES:
            try:
                turnover.update(await feed.turnover(market))
            except Exception:
                pass
        bases = cross_venue_bases(insts)
        pick: list[Inst] = []
        for m, lst in by_market.items():
            lst = [i for i in lst if base_asset(m, i.symbol) in bases
                   if (i.listing_age_days == 0
                       or i.listing_age_days >= MIN_LISTING_AGE_DAYS)
                   and turnover.get(i.symbol, 0.0) >= MIN_TURNOVER_USD]
            lst.sort(key=lambda i: turnover.get(i.symbol, 0.0), reverse=True)
            per = max(5, args.symbols // max(1, len(by_market)))
            pick.extend(lst[:per])
        bars_by_symbol: dict[str, list[Bar]] = {}
        inst_by_key: dict[str, Inst] = {}
        for inst in pick:
            try:
                bars = [b for b in await feed.candles_range(inst.market, inst.symbol,
                                                            args.bars)
                        if b.closed and b.open_ms + BAR_MS <= now_ms()]
                if len(bars) >= 120:
                    bars_by_symbol[inst.key] = bars
                    inst_by_key[inst.key] = inst
            except Exception:
                continue
        res = backtest(bars_by_symbol, inst_by_key, cfg, params)
        span_min = min((len(b) for b in bars_by_symbol.values()), default=0)
        payload = {
            "status": "COMPLETED",
            "symbols": len(bars_by_symbol),
            "bars_per_symbol": span_min,
            "span_hours": round(span_min / 60, 2),
            "params": params,
            "config": asdict(cfg),
            "result": {k: v for k, v in res.items() if k != "sample"},
            "real_orders": 0,
            "limits": [
                "Tek pozisyon/sembol, aynı mumda stop+hedef çakışırsa STOP varsayıldı.",
                "Funding sabit 0,01%/8saat varsayımı (geçmiş oran arşivi yok).",
                "Kısa pencere kârlılık kanıtı değildir.",
                "Gerçek emir, kısmi dolum ve likidasyon motoru yok.",
            ],
        }
        (out / "BACKTEST.json").write_text(json.dumps(payload, ensure_ascii=False,
                                                      indent=2), encoding="utf-8")
        from .report import yaz_backtest
        (out / "RAPOR.md").write_text(yaz_backtest(payload), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k not in ("config",)},
                     ensure_ascii=False, indent=1)[:1500])
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)
    if args.cmd == "doctor":
        return asyncio.run(_cmd_doctor(args))
    if args.cmd == "backtest":
        return asyncio.run(_cmd_backtest(args))
    cfg = Config(equity=getattr(args, "equity", 1000.0),
                 risk_pct=getattr(args, "risk_pct", 0.5))
    params = dict(DEFAULT_PARAMS, min_score=getattr(args, "min_score", 3))
    mode = "rejim" if args.cmd == "rejim" else "live"
    res = asyncio.run(run_live(Path(args.out), args.minutes, args.symbols, cfg,
                               params, mode=mode))
    print(json.dumps({k: res[k] for k in ("status", "active_sec", "symbols", "stats")},
                     ensure_ascii=False, indent=1)[:1400])
    return 0 if res["status"] in {"COMPLETED", "INCOMPLETE"} else 1


if __name__ == "__main__":
    sys.exit(main())
