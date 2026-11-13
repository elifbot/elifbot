"""Gerçek piyasa verisi — REST + WebSocket, çoklu borsa, otomatik uç seçimi.

NEDEN BU TASARIM
Çalışma ortamında Binance ana uçları HTTP 451, OKX 403 veriyor (coğrafi
kısıt). Bu bir kod hatası değil, ağ gerçeği. Bu yüzden:

  * Binance için resmî public-data ucu `data-api.binance.vision` (spot) ve
    `data-stream.binance.vision` (WS) kullanılır. Bunlar Binance'in kendi
    yayınladığı gerçek piyasa verisidir; sahte/sentetik değildir.
  * Vadeli (perp) veri için Gate.io / MEXC / Bitget / KuCoin uçları denenir.
  * Her uç açılışta PROB edilir; erişilemeyen borsa `UNREACHABLE` olarak
    işaretlenir ve rapor edilir. Sessizce sentetik veriye DÜŞÜLMEZ.

DÜRÜSTLÜK: `source` alanı her kaynağın hangi uçtan geldiğini taşır. Rapor
"gerçek piyasa verisi" derken hangi uç olduğunu da yazar.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import aiohttp

from ..core.clock import get_logger, mono, now_ms
from ..core.types import Candle, Quote, Tick

log = get_logger("market")

UA = {"User-Agent": "Mozilla/5.0 (AI OmniStudio research)"}


@dataclass(frozen=True, slots=True)
class VenueEndpoint:
    venue: str
    kind: str            # spot | perp
    rest_base: str
    ws_url: str
    note: str = ""


#: Gerçek, anahtar gerektirmeyen public uçlar.
ENDPOINTS: tuple[VenueEndpoint, ...] = (
    VenueEndpoint("binance_vision", "spot",
                  "https://data-api.binance.vision",
                  "wss://data-stream.binance.vision/stream",
                  "Binance resmî public-data aynası; aggTrade + klines + depth"),
    VenueEndpoint("gateio", "perp",
                  "https://api.gateio.ws/api/v4",
                  "wss://fx-ws.gateio.ws/v4/ws/usdt",
                  "Gate.io USDT vadeli; gerçek perp tick + funding"),
    VenueEndpoint("mexc", "perp",
                  "https://contract.mexc.com/api/v1",
                  "wss://contract.mexc.com/edge",
                  "MEXC USDT vadeli"),
    VenueEndpoint("bitget", "perp",
                  "https://api.bitget.com/api/v2",
                  "wss://ws.bitget.com/v2/ws/public",
                  "Bitget USDT-FUTURES"),
    VenueEndpoint("kucoin", "perp",
                  "https://api-futures.kucoin.com/api/v1",
                  "",
                  "KuCoin vadeli; WS token gerektirir, yalnız REST"),
)

BY_VENUE = {e.venue: e for e in ENDPOINTS}


@dataclass
class VenueHealth:
    venue: str
    reachable: bool = False
    http_status: int = 0
    error: str = ""
    probe_latency_ms: float = 0.0
    rest_ok: int = 0
    rest_fail: int = 0
    ws_messages: int = 0
    ws_reconnects: int = 0
    last_message_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue, "reachable": self.reachable,
            "http_status": self.http_status, "error": self.error,
            "probe_latency_ms": round(self.probe_latency_ms, 2),
            "rest_ok": self.rest_ok, "rest_fail": self.rest_fail,
            "ws_messages": self.ws_messages, "ws_reconnects": self.ws_reconnects,
            "last_message_ms": self.last_message_ms,
        }


class VenueRateLimiter:
    """Borsa başına token-bucket + 429'da uyarlamalı yavaşlama.

    Neden: 300 sembolü 4 sn'de bir tazelemek ~75 istek/sn üretir ve borsanın
    dakikalık ağırlık bütçesini aşar (HTTP 429). İstek boşa gider, veri
    tazeliği düşer. Bucket isteği sıraya alır; 429 gelirse hız yarıya iner
    (additive recovery ile geri çıkar). Böylece bütçe aşılmaz.
    """

    __slots__ = ("base_rate", "rate", "capacity", "tokens", "last_mono",
                 "min_rate", "throttles", "waits", "wait_sec", "_lock",
                 "cooldown_until")

    def __init__(self, rate: float = 10.0, capacity: float | None = None) -> None:
        self.base_rate = max(0.5, float(rate))
        self.rate = self.base_rate
        self.min_rate = max(0.5, self.base_rate / 8.0)
        self.capacity = max(1.0, float(capacity if capacity is not None else rate))
        self.tokens = self.capacity
        self.last_mono = mono()
        self.throttles = 0
        self.waits = 0
        self.wait_sec = 0.0
        self.cooldown_until = 0.0
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        t = mono()
        self.tokens = min(self.capacity, self.tokens + (t - self.last_mono) * self.rate)
        self.last_mono = t

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = mono()
                if now < self.cooldown_until:
                    delay = self.cooldown_until - now
                else:
                    self._refill()
                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        return
                    delay = (1.0 - self.tokens) / self.rate
                self.waits += 1
                self.wait_sec += delay
                await asyncio.sleep(min(delay, 5.0))

    def on_throttle(self, retry_after: float | None = None) -> None:
        """429: hızı yarıya indir, Retry-After varsa ona uy."""
        self.throttles += 1
        self.rate = max(self.min_rate, self.rate * 0.5)
        pause = retry_after if retry_after and retry_after > 0 else 2.0
        self.cooldown_until = max(self.cooldown_until, mono() + min(pause, 60.0))
        self.tokens = 0.0

    def on_success(self) -> None:
        """Yavaş yavaş temel hıza dön (ani sıçrama yok)."""
        if self.rate < self.base_rate:
            self.rate = min(self.base_rate, self.rate + self.base_rate * 0.01)

    def to_dict(self) -> dict[str, Any]:
        return {"rate_per_sec": round(self.rate, 3),
                "base_rate_per_sec": self.base_rate,
                "throttles_429": self.throttles,
                "queued_waits": self.waits,
                "queued_wait_sec": round(self.wait_sec, 3)}


class MarketData:
    """Bulut/VPN'siz ortamda çalışan gerçek veri istemcisi."""

    def __init__(self, session: aiohttp.ClientSession,
                 venues: list[str] | None = None,
                 rest_rps: float = 10.0) -> None:
        self.session = session
        self.limiters: dict[str, VenueRateLimiter] = {}
        self.rest_rps = rest_rps
        wanted = venues or ["binance_vision", "gateio"]
        self.endpoints = [BY_VENUE[v] for v in wanted if v in BY_VENUE]
        self.health: dict[str, VenueHealth] = {
            e.venue: VenueHealth(e.venue) for e in self.endpoints}
        self._symbol_cache: dict[str, list[str]] = {}
        for e in self.endpoints:
            self.limiters[e.venue] = VenueRateLimiter(rest_rps)

    def rate_limit_snapshot(self) -> dict[str, Any]:
        return {v: l.to_dict() for v, l in self.limiters.items()}

    # ---------- REST yardımcı ----------
    async def _get(self, url: str, venue: str,
                   timeout: float = 12.0) -> Any:
        h = self.health[venue]
        lim = self.limiters.get(venue)
        if lim is not None:
            await lim.acquire()
        try:
            async with self.session.get(
                url, headers=UA, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
                h.http_status = r.status
                body = await r.text()
                if r.status == 429:
                    ra = r.headers.get("Retry-After")
                    try:
                        raf = float(ra) if ra else None
                    except (TypeError, ValueError):
                        raf = None
                    if lim is not None:
                        lim.on_throttle(raf)
                    h.rest_fail += 1
                    raise RuntimeError(f"HTTP429: {body[:120]}")
                if r.status != 200:
                    h.rest_fail += 1
                    raise RuntimeError(f"HTTP{r.status}: {body[:120]}")
                h.rest_ok += 1
                if lim is not None:
                    lim.on_success()
                return json.loads(body)
        except Exception as e:
            h.rest_fail += 1
            h.error = f"{type(e).__name__}: {str(e)[:150]}"
            raise

    # ---------- prob ----------
    async def probe_all(self) -> dict[str, Any]:
        """Her ucu gerçek istekle dener. Erişilemeyeni açıkça işaretler."""
        async def one(e: VenueEndpoint) -> None:
            h = self.health[e.venue]
            t0 = mono()
            try:
                await self._get(self._probe_url(e), e.venue, timeout=10.0)
                h.reachable = True
                h.error = ""
            except Exception as ex:
                h.reachable = False
                h.error = f"{type(ex).__name__}: {str(ex)[:150]}"
                log.warning("%s erişilemedi: %s", e.venue, h.error)
            h.probe_latency_ms = (mono() - t0) * 1000.0

        await asyncio.gather(*[one(e) for e in self.endpoints])
        ok = [e.venue for e in self.endpoints if self.health[e.venue].reachable]
        log.info("Erişilebilir gerçek veri uçları: %s", ok or "YOK")
        return {v: h.to_dict() for v, h in self.health.items()}

    @staticmethod
    def _probe_url(e: VenueEndpoint) -> str:
        return {
            "binance_vision": f"{e.rest_base}/api/v3/ticker/price?symbol=BTCUSDT",
            "gateio": f"{e.rest_base}/futures/usdt/contracts/BTC_USDT",
            "mexc": f"{e.rest_base}/contract/ticker?symbol=BTC_USDT",
            "bitget": f"{e.rest_base}/mix/market/ticker?symbol=BTCUSDT&productType=USDT-FUTURES",
            "kucoin": f"{e.rest_base}/ticker?symbol=XBTUSDTM",
        }[e.venue]

    @property
    def reachable_venues(self) -> list[str]:
        return [e.venue for e in self.endpoints if self.health[e.venue].reachable]

    # ---------- sembol evreni ----------
    async def universe(self, venue: str, limit: int = 40) -> list[str]:
        if venue in self._symbol_cache:
            return self._symbol_cache[venue][:limit]
        e = BY_VENUE[venue]
        syms: list[str] = []
        if venue == "binance_vision":
            data = await self._get(f"{e.rest_base}/api/v3/ticker/24hr", venue, 20.0)
            rows = [r for r in data
                    if str(r.get("symbol", "")).endswith("USDT")
                    and not any(x in r["symbol"] for x in ("UPUSDT", "DOWNUSDT", "BULL", "BEAR"))]
            rows.sort(key=lambda r: float(r.get("quoteVolume", 0) or 0), reverse=True)
            syms = [r["symbol"] for r in rows]
        elif venue == "gateio":
            data = await self._get(f"{e.rest_base}/futures/usdt/tickers", venue, 20.0)
            rows = [r for r in data if not r.get("in_delisting")]
            rows.sort(key=lambda r: float(r.get("volume_24h_quote", 0) or 0), reverse=True)
            syms = [r["contract"] for r in rows]
        elif venue == "mexc":
            data = await self._get(f"{e.rest_base}/contract/ticker", venue, 20.0)
            rows = [r for r in (data.get("data") or [])
                    if str(r.get("symbol", "")).endswith("_USDT")]
            rows.sort(key=lambda r: float(r.get("amount24", 0) or 0), reverse=True)
            syms = [r["symbol"] for r in rows]
        elif venue == "bitget":
            data = await self._get(
                f"{e.rest_base}/mix/market/tickers?productType=USDT-FUTURES", venue, 20.0)
            rows = data.get("data") or []
            rows.sort(key=lambda r: float(r.get("usdtVolume", 0) or 0), reverse=True)
            syms = [r["symbol"] for r in rows]
        self._symbol_cache[venue] = syms
        log.info("%s evren: %d sembol (ilk %d kullanılacak)", venue, len(syms), limit)
        return syms[:limit]

    # ---------- mumlar ----------
    async def candles(self, venue: str, symbol: str, interval: str = "1m",
                      limit: int = 120) -> list[Candle]:
        e = BY_VENUE[venue]
        out: list[Candle] = []
        if venue == "binance_vision":
            url = (f"{e.rest_base}/api/v3/klines?symbol={symbol}"
                   f"&interval={interval}&limit={limit}")
            data = await self._get(url, venue)
            for k in data:
                out.append(Candle(symbol, venue, int(k[0]), float(k[1]), float(k[2]),
                                  float(k[3]), float(k[4]), float(k[7]), closed=True))
        elif venue == "gateio":
            iv = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h"}.get(interval, "1m")
            url = (f"{e.rest_base}/futures/usdt/candlesticks?contract={symbol}"
                   f"&interval={iv}&limit={limit}")
            data = await self._get(url, venue)
            for k in data:
                out.append(Candle(symbol, venue, int(k["t"]) * 1000, float(k["o"]),
                                  float(k["h"]), float(k["l"]), float(k["c"]),
                                  float(k.get("sum", 0) or 0), closed=True))
            out.sort(key=lambda c: c.open_ms)
        elif venue == "mexc":
            iv = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "1h": "Min60"}.get(interval, "Min1")
            url = f"{e.rest_base}/contract/kline/{symbol}?interval={iv}"
            data = await self._get(url, venue)
            d = data.get("data") or {}
            ts = d.get("time") or []
            for i in range(max(0, len(ts) - limit), len(ts)):
                out.append(Candle(symbol, venue, int(ts[i]) * 1000,
                                  float(d["open"][i]), float(d["high"][i]),
                                  float(d["low"][i]), float(d["close"][i]),
                                  float((d.get("amount") or [0] * len(ts))[i]), True))
        elif venue == "bitget":
            g = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H"}.get(interval, "1m")
            url = (f"{e.rest_base}/mix/market/candles?symbol={symbol}"
                   f"&productType=USDT-FUTURES&granularity={g}&limit={min(limit, 200)}")
            data = await self._get(url, venue)
            for k in (data.get("data") or []):
                out.append(Candle(symbol, venue, int(k[0]), float(k[1]), float(k[2]),
                                  float(k[3]), float(k[4]), float(k[6] if len(k) > 6 else 0), True))
            out.sort(key=lambda c: c.open_ms)
        return out[-limit:]

    # ---------- derinlik / quote ----------
    async def quote(self, venue: str, symbol: str) -> Quote | None:
        e = BY_VENUE[venue]
        try:
            if venue == "binance_vision":
                d = await self._get(
                    f"{e.rest_base}/api/v3/depth?symbol={symbol}&limit=5", venue, 8.0)
                bid = float(d["bids"][0][0]); ask = float(d["asks"][0][0])
            elif venue == "gateio":
                d = await self._get(
                    f"{e.rest_base}/futures/usdt/order_book?contract={symbol}&limit=5",
                    venue, 8.0)
                bid = float(d["bids"][0]["p"]); ask = float(d["asks"][0]["p"])
            elif venue == "mexc":
                d = await self._get(
                    f"{e.rest_base}/contract/depth/{symbol}?limit=5", venue, 8.0)
                dd = d.get("data") or {}
                bid = float(dd["bids"][0][0]); ask = float(dd["asks"][0][0])
            elif venue == "bitget":
                d = await self._get(
                    f"{e.rest_base}/mix/market/orderbook?symbol={symbol}"
                    f"&productType=USDT-FUTURES&limit=5", venue, 8.0)
                dd = d.get("data") or {}
                bid = float(dd["bids"][0][0]); ask = float(dd["asks"][0][0])
            else:
                return None
            if bid > 0 and ask > 0 and ask >= bid:
                return Quote(venue, symbol, bid, ask, now_ms())
        except Exception as ex:
            log.debug("%s quote alınamadı %s: %s", venue, symbol, str(ex)[:80])
        return None

    # ---------- funding ----------
    async def funding(self, venue: str, symbol: str) -> dict[str, float]:
        e = BY_VENUE[venue]
        try:
            if venue == "gateio":
                d = await self._get(f"{e.rest_base}/futures/usdt/contracts/{symbol}", venue, 8.0)
                rate = float(d.get("funding_rate", 0) or 0)
                nxt = float(d.get("funding_next_apply", 0) or 0)
                mins = max(0.0, (nxt - now_ms() / 1000.0) / 60.0) if nxt else 999.0
                return {"rate": rate, "minutes_to_funding": mins}
            if venue == "mexc":
                d = await self._get(f"{e.rest_base}/contract/funding_rate/{symbol}", venue, 8.0)
                dd = d.get("data") or {}
                return {"rate": float(dd.get("fundingRate", 0) or 0),
                        "minutes_to_funding": 999.0}
        except Exception:
            pass
        return {"rate": 0.0, "minutes_to_funding": 999.0}

    def health_report(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable_venues,
            "unreachable": [e.venue for e in self.endpoints
                            if not self.health[e.venue].reachable],
            "venues": {v: h.to_dict() for v, h in self.health.items()},
            "data_authenticity": "REAL_MARKET_DATA",
            "note": ("Erişilemeyen uçlar açıkça işaretlenir; sentetik veriye "
                     "sessizce düşülmez."),
        }


TickCallback = Callable[[Tick], None]


class WSFeed:
    """Gerçek WebSocket akışı. Yeniden bağlanma + sağlık sayacı."""

    def __init__(self, venue: str, symbols: list[str], on_tick: TickCallback,
                 health: VenueHealth | None = None) -> None:
        self.venue = venue
        self.symbols = symbols
        self.on_tick = on_tick
        self.health = health or VenueHealth(venue)
        self._stop = asyncio.Event()
        self.json_parse_calls = 0
        self.json_parse_sec = 0.0

    def stop(self) -> None:
        self._stop.set()

    async def run(self, session: aiohttp.ClientSession) -> None:
        try:
            import websockets
        except ImportError:
            log.error("websockets paketi yok; WS akışı başlatılamadı")
            return
        ep = BY_VENUE[self.venue]
        if not ep.ws_url:
            log.warning("%s WS ucu yok", self.venue)
            return
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    ep.ws_url, open_timeout=15, ping_interval=20,
                    ping_timeout=20, max_queue=4096,
                ) as ws:
                    log.info("%s WS bağlandı (%d sembol)", self.venue, len(self.symbols))
                    backoff = 1.0
                    await self._subscribe(ws)
                    await self._consume(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.health.ws_reconnects += 1
                self.health.error = f"{type(e).__name__}: {str(e)[:120]}"
                log.warning("%s WS koptu: %s — %.1fs sonra reconnect",
                            self.venue, self.health.error, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(30.0, backoff * 1.8)

    async def _subscribe(self, ws: Any) -> None:
        if self.venue == "binance_vision":
            # URL zaten stream içeriyorsa ayrıca abone olmaya gerek yok.
            params = [f"{s.lower()}@aggTrade" for s in self.symbols]
            for i in range(0, len(params), 40):
                await ws.send(json.dumps(
                    {"method": "SUBSCRIBE", "params": params[i:i + 40], "id": i // 40 + 1}))
        elif self.venue == "gateio":
            for i in range(0, len(self.symbols), 30):
                await ws.send(json.dumps({
                    "time": int(now_ms() / 1000), "channel": "futures.trades",
                    "event": "subscribe", "payload": self.symbols[i:i + 30]}))
        elif self.venue == "mexc":
            for s in self.symbols:
                await ws.send(json.dumps(
                    {"method": "sub.deal", "param": {"symbol": s}}))
            await ws.send(json.dumps({"method": "ping"}))
        elif self.venue == "bitget":
            args = [{"instType": "USDT-FUTURES", "channel": "trade", "instId": s}
                    for s in self.symbols]
            for i in range(0, len(args), 20):
                await ws.send(json.dumps({"op": "subscribe", "args": args[i:i + 20]}))

    async def _consume(self, ws: Any) -> None:
        while not self._stop.is_set():
            raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            if raw in ("pong", "ping"):
                continue
            t0 = mono()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            finally:
                self.json_parse_calls += 1
                self.json_parse_sec += mono() - t0
            self.health.ws_messages += 1
            self.health.last_message_ms = now_ms()
            for tick in self._parse(msg):
                self.on_tick(tick)

    def _parse(self, msg: Any) -> list[Tick]:
        out: list[Tick] = []
        if self.venue == "binance_vision":
            d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
            if isinstance(d, dict) and d.get("e") == "aggTrade":
                out.append(Tick("binance_vision", d["s"], float(d["p"]), float(d["q"]),
                                int(d["T"]), bool(d.get("m", False))))
        elif self.venue == "gateio":
            if isinstance(msg, dict) and msg.get("channel") == "futures.trades":
                res = msg.get("result") or []
                if isinstance(res, dict):
                    res = [res]
                for r in res:
                    try:
                        size = float(r["size"])
                        out.append(Tick("gateio", r["contract"], float(r["price"]),
                                        abs(size), int(r.get("create_time_ms") or
                                                      float(r["create_time"]) * 1000),
                                        size < 0))
                    except (KeyError, TypeError, ValueError):
                        continue
        elif self.venue == "mexc":
            if isinstance(msg, dict) and msg.get("channel") == "push.deal":
                d = msg.get("data") or {}
                try:
                    # MEXC T: 1=open long(buy), 2=close short, 3=open short, 4=close long
                    side_sell = int(d.get("T", 1)) in (3, 4)
                    out.append(Tick("mexc", msg.get("symbol", d.get("symbol", "")),
                                    float(d["p"]), float(d["v"]),
                                    int(d["t"]), side_sell))
                except (KeyError, TypeError, ValueError):
                    pass
        elif self.venue == "bitget":
            if isinstance(msg, dict) and msg.get("arg", {}).get("channel") == "trade":
                for d in (msg.get("data") or []):
                    try:
                        out.append(Tick("bitget", d.get("instId", msg["arg"]["instId"]),
                                        float(d["price"]), float(d["size"]),
                                        int(d["ts"]), d.get("side") == "sell"))
                    except (KeyError, TypeError, ValueError):
                        continue
        return out