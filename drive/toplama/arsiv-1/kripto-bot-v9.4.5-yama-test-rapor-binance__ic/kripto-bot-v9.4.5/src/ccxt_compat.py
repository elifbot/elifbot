"""CCXT Async Uyumluluk Katmanı (Canlı Binance USDⓈ-M + OKX USDT-SWAP `aiohttp` İstemcili).

Sistemde `ccxt` kuruluysa doğrudan `ccxt.async_support` modülünü kullanır.
`ccxt` kurulu değilse `aiohttp` üzerinden Binance (`fapiPublic` / `www.binance.com/fapi/v1`)
ve OKX (`/api/v5/market` & `/api/v5/public`) gerçek canlı borsa verisi uçlarını çalıştırır.
"""
from __future__ import annotations

import copy
from typing import Any

try:
    import ccxt.async_support as _real_ccxt  # type: ignore

    HAS_NATIVE_CCXT = True
except ImportError:
    _real_ccxt = None
    HAS_NATIVE_CCXT = False


class NetworkError(ConnectionError):
    """CCXT uyumlu ağ hatası."""


class RequestTimeout(TimeoutError):
    """CCXT uyumlu zaman aşımı hatası."""


class ExchangeError(RuntimeError):
    """CCXT uyumlu genel borsa hatası."""


class AuthenticationError(ExchangeError):
    """CCXT uyumlu kimlik doğrulama hatası."""


def _base_coin(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if "/" in raw:
        return raw.split("/")[0]
    if "-" in raw:
        return raw.split("-")[0]
    if raw.endswith("USDT") and len(raw) > 4:
        return raw[:-4]
    return raw


class _BaseAsyncCompatExchange:
    id: str = "generic"

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = copy.deepcopy(config or {})
        self.apiKey: str = str(cfg.get("apiKey") or "")
        self.secret: str = str(cfg.get("secret") or "")
        self.password: str = str(cfg.get("password") or "")
        self.enableRateLimit: bool = bool(cfg.get("enableRateLimit", True))
        self.options: dict[str, Any] = copy.deepcopy(cfg.get("options") or {})
        self.sandbox: bool = False
        self.markets: dict[str, dict] = {}
        self._session = None
        self.urls: dict[str, Any] = {"api": {}}

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox = bool(enabled)

    async def _get_session(self):
        if self._session is None or getattr(self._session, "closed", False):
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10.0),
                headers={"User-Agent": "KriptoBotV8/1.0"},
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not getattr(self._session, "closed", False):
            await self._session.close()
        self._session = None

    async def load_markets(self, reload: bool = False) -> dict[str, dict]:
        if self.markets and not reload:
            return self.markets
        rows = await self.fetch_markets()
        self.markets = {m["symbol"]: m for m in rows if isinstance(m, dict) and "symbol" in m}
        return self.markets

    async def fetch_markets(self) -> list[dict]:
        return []

    async def fetch_balance(self, params: dict | None = None) -> dict:
        raise AuthenticationError(f"{self.id}: API anahtarı olmadan bakiye sorgulanamaz")

    async def fetch_positions(self, symbols: list[str] | None = None, params: dict | None = None) -> list:
        raise AuthenticationError(f"{self.id}: API anahtarı olmadan pozisyon sorgulanamaz")

    async def set_leverage(self, leverage: int, symbol: str, params: dict | None = None) -> dict:
        return {"symbol": symbol, "leverage": int(leverage)}

    async def set_margin_mode(self, marginMode: str, symbol: str, params: dict | None = None) -> dict:
        return {"symbol": symbol, "marginMode": marginMode}


class _CompatBinance(_BaseAsyncCompatExchange):
    id = "binance"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.urls = {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
                "sapi": "https://api.binance.com/sapi/v1",
                "fapiPublic": "https://fapi.binance.com/fapi/v1",
                "fapiPublicV2": "https://fapi.binance.com/fapi/v2",
                "fapiPublicV3": "https://fapi.binance.com/fapi/v3",
                "fapiPrivate": "https://fapi.binance.com/fapi/v1",
                "fapiPrivateV2": "https://fapi.binance.com/fapi/v2",
                "fapiPrivateV3": "https://fapi.binance.com/fapi/v3",
                "fapiData": "https://fapi.binance.com/futures/data",
                "dapiPublic": "https://dapi.binance.com/dapi/v1",
                "dapiPrivate": "https://dapi.binance.com/dapi/v1",
            },
            "test": {
                "fapiPublic": "https://testnet.binancefuture.com/fapi/v1",
                "fapiPrivate": "https://testnet.binancefuture.com/fapi/v1",
            },
        }

    def set_sandbox_mode(self, enabled: bool) -> None:
        super().set_sandbox_mode(enabled)
        if enabled:
            self.urls["api"]["fapiPublic"] = "https://testnet.binancefuture.com/fapi/v1"
            self.urls["api"]["fapiPrivate"] = "https://testnet.binancefuture.com/fapi/v1"

    def _raw_sym(self, symbol: str) -> str:
        return f"{_base_coin(symbol)}USDT"

    async def _fapi_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        session = await self._get_session()
        primary = self.urls["api"]["fapiPublic"].rstrip("/")
        candidates = [primary]
        if primary.startswith("https://fapi.binance.com"):
            candidates.append(primary.replace("https://fapi.binance.com", "https://www.binance.com", 1))
        last_exc: Exception | None = None
        for base in candidates:
            try:
                async with session.get(f"{base}{path}", params=params) as resp:
                    if resp.status == 451 and base != candidates[-1]:
                        continue
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as exc:
                last_exc = exc
        raise NetworkError(f"binance GET {path} hatası: {last_exc}") from last_exc

    async def fetch_markets(self) -> list[dict]:
        payload = await self._fapi_get("/exchangeInfo")
        markets = []
        for item in payload.get("symbols", []):
            if item.get("quoteAsset") == "USDT" and item.get("contractType") == "PERPETUAL":
                base_asset = item.get("baseAsset", "")
                markets.append(
                    {
                        "id": item.get("symbol"),
                        "symbol": f"{base_asset}/USDT:USDT",
                        "base": base_asset,
                        "quote": "USDT",
                        "settle": "USDT",
                        "type": "swap",
                        "swap": True,
                        "linear": True,
                        "contract": True,
                        "contractSize": 1.0,
                        "active": item.get("status") == "TRADING",
                        "limits": {"leverage": {"max": 50}},
                        "info": item,
                    }
                )
        return markets

    async def fetch_ticker(self, symbol: str) -> dict:
        raw_sym = self._raw_sym(symbol)
        book = await self._fapi_get("/ticker/bookTicker", {"symbol": raw_sym})
        bid = float(book.get("bidPrice") or 0.0)
        ask = float(book.get("askPrice") or 0.0)
        mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (bid or ask)
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": mid,
            "close": mid,
            "timestamp": int(book.get("time") or 0),
            "info": book,
        }

    async def fetch_order_book(self, symbol: str, limit: int = 5) -> dict:
        raw_sym = self._raw_sym(symbol)
        data = await self._fapi_get("/depth", {"symbol": raw_sym, "limit": min(max(int(limit), 5), 20)})
        return {
            "symbol": symbol,
            "bids": [[float(p), float(q)] for p, q in data.get("bids", [])],
            "asks": [[float(p), float(q)] for p, q in data.get("asks", [])],
            "timestamp": int(data.get("T") or 0),
        }

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "5m", since: int | None = None, limit: int = 210
    ) -> list[list[float]]:
        params: dict[str, Any] = {
            "symbol": self._raw_sym(symbol),
            "interval": timeframe,
            "limit": min(max(int(limit), 1), 1000),
        }
        if since is not None:
            params["startTime"] = int(since)
        rows = await self._fapi_get("/klines", params)
        return [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in rows
            if isinstance(r, list) and len(r) >= 6
        ]

    async def fetch_funding_rate(self, symbol: str) -> dict:
        data = await self._fapi_get("/premiumIndex", {"symbol": self._raw_sym(symbol)})
        return {
            "symbol": symbol,
            "fundingRate": float(data.get("lastFundingRate") or 0.0),
            "markPrice": float(data.get("markPrice") or 0.0),
            "timestamp": int(data.get("time") or 0),
            "info": data,
        }


class _CompatOkx(_BaseAsyncCompatExchange):
    id = "okx"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.urls = {
            "api": {
                "rest": "https://www.okx.com",
                "public": "https://www.okx.com/api/v5/public",
                "private": "https://www.okx.com/api/v5/trade",
                "market": "https://www.okx.com/api/v5/market",
            }
        }

    def _inst_id(self, symbol: str) -> str:
        return f"{_base_coin(symbol)}-USDT-SWAP"

    async def _okx_get(self, path: str, params: dict[str, Any] | None = None) -> list:
        session = await self._get_session()
        base = self.urls["api"]["rest"].rstrip("/")
        try:
            async with session.get(f"{base}{path}", params=params) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception as exc:
            raise NetworkError(f"okx GET {path} hatası: {exc}") from exc
        if str(payload.get("code", "0")) != "0":
            raise ExchangeError(f"okx hata: {payload.get('msg')}")
        return payload.get("data", [])

    async def fetch_markets(self) -> list[dict]:
        rows = await self._okx_get("/api/v5/public/instruments", {"instType": "SWAP"})
        markets = []
        for item in rows:
            inst_id = str(item.get("instId") or "")
            parts = inst_id.split("-")
            if len(parts) == 3 and parts[1] == "USDT" and parts[2] == "SWAP":
                ct_val = float(item.get("ctVal") or 1.0)
                max_lev = float(item.get("lever") or 50.0)
                markets.append(
                    {
                        "id": inst_id,
                        "symbol": f"{parts[0]}/USDT:USDT",
                        "base": parts[0],
                        "quote": "USDT",
                        "settle": "USDT",
                        "type": "swap",
                        "swap": True,
                        "linear": True,
                        "contract": True,
                        "contractSize": ct_val,
                        "active": item.get("state") == "live",
                        "limits": {"leverage": {"max": max_lev}},
                        "info": item,
                    }
                )
        return markets

    async def fetch_ticker(self, symbol: str) -> dict:
        rows = await self._okx_get("/api/v5/market/ticker", {"instId": self._inst_id(symbol)})
        item = rows[0] if rows else {}
        bid = float(item.get("bidPx") or 0.0)
        ask = float(item.get("askPx") or 0.0)
        last = float(item.get("last") or (bid + ask) / 2.0)
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": last,
            "timestamp": int(item.get("ts") or 0),
            "info": item,
        }

    async def fetch_order_book(self, symbol: str, limit: int = 5) -> dict:
        rows = await self._okx_get("/api/v5/market/books", {"instId": self._inst_id(symbol), "sz": str(limit)})
        item = rows[0] if rows else {}
        return {
            "symbol": symbol,
            "bids": [[float(r[0]), float(r[1])] for r in item.get("bids", [])],
            "asks": [[float(r[0]), float(r[1])] for r in item.get("asks", [])],
            "timestamp": int(item.get("ts") or 0),
        }

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "5m", since: int | None = None, limit: int = 210
    ) -> list[list[float]]:
        bar_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}
        bar = bar_map.get(timeframe, timeframe)
        rows = await self._okx_get(
            "/api/v5/market/candles",
            {"instId": self._inst_id(symbol), "bar": bar, "limit": str(min(max(int(limit), 1), 300))},
        )
        parsed = [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6] if len(r) > 6 else r[5])]
            for r in rows
            if isinstance(r, list) and len(r) >= 6
        ]
        parsed.sort(key=lambda x: x[0])
        if since is not None:
            parsed = [x for x in parsed if x[0] >= int(since)]
        return parsed

    async def fetch_funding_rate(self, symbol: str) -> dict:
        rows = await self._okx_get("/api/v5/public/funding-rate", {"instId": self._inst_id(symbol)})
        item = rows[0] if rows else {}
        return {
            "symbol": symbol,
            "fundingRate": float(item.get("fundingRate") or 0.0),
            "timestamp": int(item.get("fundingTime") or 0),
            "info": item,
        }


if HAS_NATIVE_CCXT:
    binance = _real_ccxt.binance
    okx = _real_ccxt.okx
else:
    binance = _CompatBinance
    okx = _CompatOkx
