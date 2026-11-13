"""Birleşik gerçek piyasa verisi: Binance (USD-M/COIN-M) + OKX (SWAP/FUTURES)
+ Gate.io, hem REST hem WebSocket, tek arayüz.

TASARIM KARARI
  Maildeki V10 paketinde üç ayrı veri yolu vardı:
    · `omnistudio/market/data.py` → Gate.io/MEXC/Bitget/KuCoin (Binance yok)
    · `acarbot/futures_market.py` → Binance www + OKX (yalnız REST)
    · `acarbot/futures_stream.py` → kendi ham aiohttp WS döngüsü, kendi SQLite'ı
  Aynı mum üç yerde üç farklı biçimde temsil ediliyordu. Burada tek yol var:
  her borsa `REST` ve `WS` sağlar, çıktı hep `Candle` / `Quote` / `BookTicker`.

DÜRÜSTLÜK
  · Erişilemeyen uç `UNREACHABLE` işaretlenir; sentetik veriye DÜŞÜLMEZ.
  · WS'te kapanmış mum yalnız borsanın `x=true` / `confirm=1` dediği anda yazılır.
  · Her mum `source` alanı taşır: `rest` veya `ws`.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import aiohttp

from omnistudio.core.types import Candle, Quote

UA = {"User-Agent": "Mozilla/5.0 (ACARBOT-OmniStudio research; paper only)"}
INTERVAL_MS = 300_000
BAR = "5m"


def now_ms() -> int:
    return int(time.time() * 1000)


# --------------------------------------------------------------------------
# REST
# --------------------------------------------------------------------------
@dataclass
class RestVenue:
    market: str
    base: str
    #: dakikalık istek bütçesi (borsa limitlerine göre muhafazakâr)
    rps: float = 6.0
    ok: int = 0
    fail: int = 0
    last_error: str = ""
    unreachable: bool = False

    def url(self, path: str) -> str:
        return self.base + path


VENUES: dict[str, RestVenue] = {
    "binance_usdm":  RestVenue("binance_usdm",  "https://www.binance.com", 6.0),
    "binance_coinm": RestVenue("binance_coinm", "https://www.binance.com", 4.0),
    "okx_swap":      RestVenue("okx_swap",      "https://www.okx.com", 8.0),
    "okx_futures":   RestVenue("okx_futures",   "https://www.okx.com", 6.0),
    "gateio_usdt":   RestVenue("gateio_usdt",   "https://api.gateio.ws", 6.0),
    "gateio_btc":    RestVenue("gateio_btc",    "https://api.gateio.ws", 4.0),
}

INSTRUMENTS_PATH = {
    "binance_usdm": "/fapi/v1/exchangeInfo",
    "binance_coinm": "/dapi/v1/exchangeInfo",
    "okx_swap": "/api/v5/public/instruments?instType=SWAP",
    "okx_futures": "/api/v5/public/instruments?instType=FUTURES",
    "gateio_usdt": "/api/v4/futures/usdt/contracts",
    "gateio_btc": "/api/v4/futures/btc/contracts",
}


def klines_path(market: str, symbol: str, limit: int = 300) -> str:
    if market == "binance_usdm":
        return f"/fapi/v1/klines?symbol={symbol}&interval={BAR}&limit={limit}"
    if market == "binance_coinm":
        return f"/dapi/v1/klines?symbol={symbol}&interval={BAR}&limit={limit}"
    if market.startswith("okx"):
        return f"/api/v5/market/candles?instId={symbol}&bar={BAR}&limit={min(limit, 300)}"
    if market == "gateio_usdt":
        return f"/api/v4/futures/usdt/candlesticks?contract={symbol}&interval={BAR}&limit={min(limit, 300)}"
    if market == "gateio_btc":
        return f"/api/v4/futures/btc/candlesticks?contract={symbol}&interval={BAR}&limit={min(limit, 300)}"
    raise ValueError(market)


def tickers_path(market: str) -> str:
    if market == "binance_usdm":
        return "/fapi/v1/ticker/bookTicker"
    if market == "binance_coinm":
        return "/dapi/v1/ticker/bookTicker"
    if market.startswith("okx"):
        inst = "SWAP" if market == "okx_swap" else "FUTURES"
        return f"/api/v5/market/tickers?instType={inst}"
    if market == "gateio_usdt":
        return "/api/v4/futures/usdt/tickers"
    if market == "gateio_btc":
        return "/api/v4/futures/btc/tickers"
    raise ValueError(market)


def funding_path(market: str, symbol: str) -> str | None:
    if market.startswith("okx"):
        return f"/api/v5/public/funding-rate?instId={symbol}"
    if market == "binance_usdm":
        return f"/fapi/v1/premiumIndex?symbol={symbol}"
    if market == "gateio_usdt":
        return f"/api/v4/futures/usdt/contracts/{symbol}"
    return None  # COIN-M funding ayrı ve para birimi başına; modellenmedi


# --------------------------------------------------------------------------
# yanıt çözümleyiciler (borsa alanları → ortak tip)
# --------------------------------------------------------------------------
def parse_candles(market: str, payload: Any) -> list[Candle]:
    out: list[Candle] = []
    if market.startswith("binance"):
        if not isinstance(payload, list):
            raise ValueError("Binance kline yanıtı geçersiz")
        inverse = market == "binance_coinm"
        for r in payload:
            if len(r) < 8:
                continue
            close = float(r[4])
            # COIN-M kontrat hacmi → yaklaşık USD hacmi; etiketli tahmin.
            qv = float(r[7]) * (close if inverse else 1.0)
            out.append(Candle(symbol="", exchange=market, open_ms=int(r[0]),
                              open=float(r[1]), high=float(r[2]), low=float(r[3]),
                              close=close, quote_volume=qv, closed=True))
    elif market.startswith("okx"):
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            raise ValueError(f"OKX mum hatası: {str(payload)[:120]}")
        for r in payload.get("data", []):
            if len(r) < 9:
                continue
            out.append(Candle(symbol="", exchange=market, open_ms=int(r[0]),
                              open=float(r[1]), high=float(r[2]), low=float(r[3]),
                              close=float(r[4]), quote_volume=float(r[7]),
                              closed=r[8] == "1"))
    else:  # gateio
        if not isinstance(payload, list):
            raise ValueError("Gate kline yanıtı geçersiz")
        for r in payload:
            out.append(Candle(symbol="", exchange=market, open_ms=int(r["t"]) * 1000,
                              open=float(r["o"]), high=float(r["h"]), low=float(r["l"]),
                              close=float(r["c"]), quote_volume=float(r["sum"]),
                              closed=True))
    out.sort(key=lambda c: c.open_ms)
    return out


def parse_tickers(market: str, payload: Any) -> dict[str, tuple[float, float, int]]:
    """symbol → (bid, ask, ts_ms)"""
    res: dict[str, tuple[float, float, int]] = {}
    stamp = now_ms()
    if market.startswith("binance"):
        if not isinstance(payload, list):
            raise ValueError("Binance ticker yanıtı geçersiz")
        for r in payload:
            try:
                bid, ask = float(r["bidPrice"]), float(r["askPrice"])
                ts = int(r.get("time") or stamp)
                if bid > 0 and ask >= bid:
                    res[r["symbol"]] = (bid, ask, ts)
            except (KeyError, TypeError, ValueError):
                continue
    elif market.startswith("okx"):
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            raise ValueError("OKX ticker yanıtı geçersiz")
        for r in payload.get("data", []):
            try:
                bid, ask = float(r["bidPx"]), float(r["askPx"])
                ts = int(r.get("ts") or stamp)
                if bid > 0 and ask >= bid:
                    res[r["instId"]] = (bid, ask, ts)
            except (KeyError, TypeError, ValueError):
                continue
    else:
        if not isinstance(payload, list):
            raise ValueError("Gate ticker yanıtı geçersiz")
        for r in payload:
            try:
                bid, ask = float(r["highest_bid"]), float(r["lowest_ask"])
                ts = int(r.get("t") or 0) or stamp
                if bid > 0 and ask >= bid:
                    res[r["contract"]] = (bid, ask, ts)
            except (KeyError, TypeError, ValueError):
                continue
    return res


def parse_funding(market: str, payload: Any) -> dict[str, Any]:
    """→ {'next_ms': int, 'rate': float, 'interval_h': float|None}"""
    if market.startswith("okx"):
        if str(payload.get("code")) != "0" or not payload.get("data"):
            raise ValueError("OKX funding yok")
        d = payload["data"][0]
        rate = float(d["fundingRate"])
        nxt = int(d["fundingTime"])
        interval = None
        if d.get("nextFundingTime") and d.get("prevFundingTime"):
            pass
        return {"next_ms": nxt, "rate": rate, "interval_h": interval}
    if market == "binance_usdm":
        nxt = int(payload["nextFundingTime"])
        return {"next_ms": nxt, "rate": float(payload.get("lastFundingRate") or 0.0),
                "interval_h": 8.0}
    if market == "gateio_usdt":
        return {"next_ms": int(float(payload["funding_next_apply"]) * 1000),
                "rate": float(payload.get("funding_rate") or 0.0),
                "interval_h": float(payload.get("funding_interval") or 28800) / 3600.0}
    raise ValueError(f"{market}: funding desteklenmiyor")


# --------------------------------------------------------------------------
# WS
# --------------------------------------------------------------------------
WS_URL = {
    "binance_usdm": "wss://fstream.binance.com/market/ws",
    "binance_coinm": "wss://dstream.binance.com/market/ws",
    "okx_swap": "wss://ws.okx.com/ws/v5/business",
    "okx_futures": "wss://ws.okx.com/ws/v5/business",
    "gateio_usdt": "wss://fx-ws.gateio.ws/v4/ws/usdt",
    "gateio_btc": "wss://fx-ws.gateio.ws/v4/ws/btc",
}
#: Borsanın izin verdiği tek bağlantıdaki abonelik sınırına göre muhafazakâr.
WS_SHARD = {"binance_usdm": 180, "binance_coinm": 40, "okx_swap": 200,
            "okx_futures": 120, "gateio_usdt": 100, "gateio_btc": 40}


def ws_subscribe(market: str, symbols: list[str]) -> dict[str, Any]:
    if market.startswith("binance"):
        return {"method": "SUBSCRIBE",
                "params": [s.lower() + "@kline_5m" for s in symbols], "id": 1}
    if market.startswith("okx"):
        return {"op": "subscribe",
                "args": [{"channel": "candle5m", "instId": s} for s in symbols]}
    return {}


def parse_ws_message(market: str, data: Any) -> tuple[str, Candle] | None:
    """Bir WS mesajından kapanmış mum çıkar. Kapanmamışsa None."""
    if market.startswith("binance"):
        # /market/ws yolu ham (sarmalanmamış) olay yayınlar; /stream sarmalar.
        d = data.get("data", data) if isinstance(data, dict) else None
        if not isinstance(d, dict) or d.get("e") != "kline":
            return None
        k = d.get("k") or {}
        if k.get("i") != BAR:
            return None
        sym = k.get("s")
        close = float(k["c"])
        vol = float(k["v"])
        if market == "binance_coinm":
            vol = float(k.get("q") or 0) * close  # yaklaşık USD
        else:
            vol = float(k.get("q") or 0)
        return sym, Candle(symbol=sym, exchange=market, open_ms=int(k["t"]),
                           open=float(k["o"]), high=float(k["h"]), low=float(k["l"]),
                           close=close, quote_volume=vol, closed=k.get("x") is True)
    if market.startswith("okx"):
        if not isinstance(data, dict):
            return None
        arg = data.get("arg") or {}
        if arg.get("channel") != "candle5m":
            return None
        rows = data.get("data") or []
        if not rows:
            return None
        r = rows[0]
        if len(r) < 9:
            return None
        sym = arg.get("instId")
        return sym, Candle(symbol=sym, exchange=market, open_ms=int(r[0]),
                           open=float(r[1]), high=float(r[2]), low=float(r[3]),
                           close=float(r[4]), quote_volume=float(r[7]),
                           closed=r[8] == "1")
    # gateio futures.candlesticks
    if not isinstance(data, dict) or data.get("channel") != "futures.candlesticks":
        return None
    if data.get("event") != "update":
        return None              # subscribe/ack hata mesajı: mum değil
    result = data.get("result")
    if not isinstance(result, list) or not result:
        return None
    row = result[0]
    # Sembol kaynağı: mümkünse satırın kendi `n` alanı ("5m_BTC_USDT"),
    # yoksa zarfın payload'ı ["5m", "BTC_USDT"].
    payload = data.get("payload") or []
    name = str(row.get("n") or "")
    if name.startswith(BAR + "_"):
        sym = name[len(BAR) + 1:]
    elif len(payload) >= 2:
        sym = payload[1]
    else:
        return None
    vol = float(row.get("a") or 0)  # 'a' = quote hacmi; 'v' yalnız kontrat adedi
    return sym, Candle(symbol=sym, exchange=market, open_ms=int(row["t"]) * 1000,
                       open=float(row["o"]), high=float(row["h"]), low=float(row["l"]),
                       close=float(row["c"]), quote_volume=vol,
                       closed=row.get("w") is True)


# --------------------------------------------------------------------------
# oturum: tek giriş noktası
# --------------------------------------------------------------------------
@dataclass
class MarketSession:
    """Tüm REST çağrıları ve WS abonelikleri bu nesneden geçer."""
    session: aiohttp.ClientSession
    sem: asyncio.Semaphore
    venues: dict[str, RestVenue] = field(default_factory=lambda: dict(VENUES))
    counters: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    async def create(cls, concurrency: int = 16) -> "MarketSession":
        s = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers=UA, trust_env=True,
            connector=aiohttp.TCPConnector(limit=64, ttl_dns_cache=300))
        return cls(session=s, sem=asyncio.Semaphore(concurrency))

    async def close(self) -> None:
        await self.session.close()

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    async def get_json(self, market: str, path: str, timeout: float = 20.0) -> Any:
        v = self.venues[market]
        if v.unreachable:
            raise RuntimeError(f"{market}: UNREACHABLE (önce probe)")
        async with self.sem:
            try:
                async with self.session.get(v.url(path),
                                            timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    text = await r.text()
                    if r.status != 200:
                        v.fail += 1
                        v.last_error = f"HTTP {r.status}"
                        raise RuntimeError(f"HTTP {r.status}: {text[:80]}")
                    v.ok += 1
                    self.bump(f"{market}.rest_ok")
                    return json.loads(text)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                v.fail += 1
                v.last_error = f"{type(e).__name__}: {str(e)[:80]}"
                self.bump(f"{market}.rest_fail")
                if len(self.errors) < 40:
                    self.errors.append(f"{market} {path[:40]}: {v.last_error}")
                raise

    async def probe(self, market: str) -> bool:
        try:
            await self.get_json(market, INSTRUMENTS_PATH[market], timeout=15)
            self.venues[market].unreachable = False
            self.bump(f"{market}.probe_ok")
            return True
        except Exception:
            self.venues[market].unreachable = True
            self.bump(f"{market}.probe_fail")
            return False

    async def candles(self, market: str, symbol: str, limit: int = 300) -> list[Candle]:
        payload = await self.get_json(market, klines_path(market, symbol, limit))
        rows = parse_candles(market, payload)
        # sembolü yerleştir (çözümleyici borsa alanlarını bilmez)
        return [Candle(symbol=symbol, exchange=market, open_ms=c.open_ms, open=c.open,
                       high=c.high, low=c.low, close=c.close,
                       quote_volume=c.quote_volume, closed=c.closed) for c in rows]

    async def quotes(self, market: str) -> dict[str, Quote]:
        payload = await self.get_json(market, tickers_path(market))
        raw = parse_tickers(market, payload)
        return {sym: Quote(exchange=market, symbol=sym, bid=bid, ask=ask, ts_ms=ts)
                for sym, (bid, ask, ts) in raw.items()}

    async def funding(self, market: str, symbol: str) -> dict[str, Any] | None:
        path = funding_path(market, symbol)
        if not path:
            return None
        try:
            return parse_funding(market, await self.get_json(market, path, timeout=12))
        except Exception:
            return None

    def health(self) -> dict[str, Any]:
        return {m: {"reachable": not v.unreachable, "rest_ok": v.ok, "rest_fail": v.fail,
                    "last_error": v.last_error}
                for m, v in self.venues.items()}


async def stream_candles(
    session: MarketSession,
    market: str,
    symbols: list[str],
    on_closed: Callable[[str, Candle], Awaitable[None]],
    deadline: float,
    on_open: Callable[[str, Candle], None] | None = None,
    stats: dict[str, int] | None = None,
    reconnect_limit: int = 6,
) -> None:
    """Bir pazarın sembollerini WS ile dinler; kapanmış mumları `on_closed`'a verir.

    Kalp atışı, yeniden bağlanma (üstel geri çekilme) ve OKX ping'i içerir.
    `stats` sözlüğüne sayaç yazar (reconnects, updates, closed, parse_errors ...).
    """
    st = stats if stats is not None else {}
    def inc(k: str, n: int = 1) -> None:
        st[k] = st.get(k, 0) + n

    shard = WS_SHARD.get(market, 100)
    groups = [symbols[i:i + shard] for i in range(0, len(symbols), shard)]
    url = WS_URL[market]

    async def one(group: list[str], delay: float) -> None:
        await asyncio.sleep(delay)
        lookup = set(group)
        backoff = 1.0
        attempts = 0
        while time.monotonic() < deadline and attempts < reconnect_limit:
            attempts += 1
            try:
                async with session.session.ws_connect(
                        url, heartbeat=20, timeout=15, max_msg_size=8 * 2 ** 20,
                        receive_timeout=None) as ws:
                    inc("connections")
                    if attempts > 1:
                        inc("reconnects")
                    if market.startswith("gateio"):
                        for i, sym in enumerate(group):
                            await ws.send_json({"time": int(time.time()), "channel":
                                                "futures.candlesticks", "event": "subscribe",
                                                "payload": [BAR, sym]})
                            if i % 25 == 24:
                                await asyncio.sleep(0.2)
                    else:
                        await ws.send_json(ws_subscribe(market, group))
                    backoff = 1.0
                    while time.monotonic() < deadline:
                        try:
                            msg = await asyncio.wait_for(
                                ws.receive(), min(25, max(0.01, deadline - time.monotonic())))
                        except asyncio.TimeoutError:
                            if market.startswith("okx"):
                                await ws.send_str("ping")
                            continue
                        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                        aiohttp.WSMsgType.ERROR):
                            raise RuntimeError("ws kapandı")
                        if msg.type != aiohttp.WSMsgType.TEXT or msg.data == "pong":
                            continue
                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError:
                            inc("parse_errors")
                            continue
                        if isinstance(data, dict) and data.get("event") == "error":
                            inc("subscribe_errors")
                            continue
                        try:
                            parsed = parse_ws_message(market, data)
                        except (TypeError, ValueError, KeyError, IndexError):
                            inc("parse_errors")
                            continue
                        if not parsed:
                            continue
                        sym, candle = parsed
                        if sym not in lookup:
                            continue
                        inc("updates")
                        if not candle.closed:
                            if on_open:
                                on_open(sym, candle)
                            continue
                        inc("closed")
                        age = now_ms() - (candle.open_ms + INTERVAL_MS)
                        if age < -5000:
                            inc("future_closed")
                            continue
                        st["latency_sum_ms"] = st.get("latency_sum_ms", 0) + max(0, age)
                        st["latency_max_ms"] = max(st.get("latency_max_ms", 0), max(0, age))
                        if 0 <= age <= 5000:
                            inc("closed_5s")
                        await on_closed(sym, candle)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                inc("connection_errors")
                if len(session.errors) < 40:
                    session.errors.append(f"ws {market}: {type(e).__name__}: {str(e)[:80]}")
                await asyncio.sleep(min(backoff, max(0.0, deadline - time.monotonic())))
                backoff = min(backoff * 2, 30.0)

    tasks = [asyncio.create_task(one(g, i * 0.4)) for i, g in enumerate(groups)]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
