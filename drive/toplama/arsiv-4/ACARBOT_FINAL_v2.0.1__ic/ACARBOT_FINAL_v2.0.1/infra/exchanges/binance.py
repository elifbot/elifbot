"""Binance public USDT-M Futures market-data client. No authenticated endpoints.

FINAL v1.2 — otomatik veri kaynağı yedeği:
  Futures API bölgesel engelle (HTTP 451/403) dönerse resmî mainnet spot
  veri aynasına geçilir (data-api.binance.vision + data-stream.binance.vision).
  Fiyatlar SPOT kaynaklı olur (perp'e çok yakın); paper funding/likidasyon
  modeli simüle edilmeye devam eder. Geçiş bir kez loglanır.
  Proxy/VPN kullanıcıları için BINANCE_BASE_URL / BINANCE_WS_URL ortam
  değişkenleriyle uç nokta geçersiz kılınabilir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from math import isfinite
import time
from collections.abc import AsyncIterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

from infra.exchanges.base import (
    Market,
    OrderBook,
    PublicExchange,
    PublicMarketDataError,
    PublicTrade,
    Ticker,
    validate_request,
)
from infra.market_data.models import Candle

logger = logging.getLogger(__name__)


class BinancePublic(PublicExchange):
    name = "Binance"
    base_url = "https://fapi.binance.com"
    websocket_url = "wss://fstream.binance.com/ws/!miniTicker@arr"
    mirror_base_url = "https://data-api.binance.vision"
    mirror_websocket_url = "wss://data-stream.binance.vision/ws/!miniTicker@arr"
    _intervals = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                  "1h": "1h", "4h": "4h", "1d": "1d"}
    # Binance depth geçerli limit değerleri (futures ve spot ortak kümesi)
    _DEPTH_LIMITS = (5, 10, 20, 50, 100, 500, 1000)

    def __init__(self) -> None:
        env_base = os.environ.get("BINANCE_BASE_URL", "").strip()
        env_ws = os.environ.get("BINANCE_WS_URL", "").strip()
        if env_base:
            self.base_url = env_base.rstrip("/")
        if env_ws:
            self.websocket_url = env_ws
        self.mirror_mode = False

    # ------------------------------------------------------------------
    # FINAL v1.2: bölgesel engel → resmî spot veri aynası
    # ------------------------------------------------------------------

    def _enable_mirror(self, status: object) -> None:
        self.mirror_mode = True
        logger.warning(
            "Binance futures API engelli (HTTP %s) → resmî mainnet SPOT veri "
            "aynası aktif: %s (paper fiyatlar spot kaynaklı; funding/likidasyon "
            "modeli simülasyon olarak sürer)", status, self.mirror_base_url,
        )

    @staticmethod
    def _mirror_path(path: str) -> str:
        return path.replace("/fapi/v1/", "/api/v3/")

    def _mirror_get_json(self, path: str, params: dict[str, object]) -> object:
        params = dict(params)
        mirror_path = self._mirror_path(path)
        if mirror_path.endswith("/depth") and "limit" in params:
            params["limit"] = self._clamp_depth_limit(int(params["limit"]))
        url = f"{self.mirror_base_url}{mirror_path}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise PublicMarketDataError(
                f"Binance mirror market-data request failed: {exc}"
            ) from exc

    def _get_json(self, path: str, params: dict[str, object]) -> object:
        if self.mirror_mode:
            return self._mirror_get_json(path, params)
        try:
            return super()._get_json(path, params)
        except PublicMarketDataError as exc:
            status = getattr(exc.__cause__, "code", None)
            if status in (403, 451):
                self._enable_mirror(status)
                return self._mirror_get_json(path, params)
            raise

    @classmethod
    def _clamp_depth_limit(cls, limit: int) -> int:
        """400 gibi geçersiz değerleri üstteki geçerli değere yuvarlar (→500)."""
        for valid in cls._DEPTH_LIMITS:
            if limit <= valid:
                return valid
        return cls._DEPTH_LIMITS[-1]

    @property
    def _active_websocket_url(self) -> str:
        return self.mirror_websocket_url if self.mirror_mode else self.websocket_url

    @property
    def _active_stream_host(self) -> str:
        return "data-stream.binance.vision" if self.mirror_mode else "fstream.binance.com"

    @staticmethod
    def parse_mini_tickers(message: str) -> list[Ticker]:
        try:
            payload = json.loads(message)
            if not isinstance(payload, list):
                raise ValueError("expected miniTicker array")
            tickers = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("s", "")).upper()
                price = float(item["c"])
                volume = float(item["q"])
                timestamp = int(item.get("E", 0))
                if (
                    not symbol or not isfinite(price) or price <= 0
                    or not isfinite(volume) or volume < 0
                    or timestamp < 0
                ):
                    continue
                tickers.append(Ticker(symbol, volume, price, timestamp))
            return tickers
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError(
                "Binance returned malformed miniTicker data"
            ) from exc

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        validate_request(symbol, timeframe, limit)
        raw = self._get_json(
            "/fapi/v1/klines",
            {"symbol": symbol.upper().split(":")[0].replace("/", "").replace("-", ""),
             "interval": self._intervals[timeframe],
             "limit": limit},
        )
        if not isinstance(raw, list):
            raise PublicMarketDataError("Binance returned an unexpected candle payload")
        try:
            return [
                Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]),
                       float(row[4]), float(row[5]))
                for row in raw
            ]
        except (TypeError, ValueError, IndexError) as exc:
            raise PublicMarketDataError("Binance returned malformed candles") from exc

    def fetch_ticker(self, symbol: str) -> Ticker:
        requested_symbol = symbol.upper().split(":")[0].replace("/", "").replace("-", "")
        raw = self._get_json("/fapi/v1/ticker/price", {"symbol": requested_symbol})
        if not isinstance(raw, dict):
            raise PublicMarketDataError("Binance returned an unexpected ticker payload")
        try:
            returned_symbol = str(raw["symbol"]).upper()
            price = float(raw["price"])
            if returned_symbol != requested_symbol:
                raise PublicMarketDataError(
                    f"Binance ticker symbol mismatch: requested={requested_symbol}, "
                    f"received={returned_symbol}"
                )
            if not isfinite(price) or price <= 0:
                raise ValueError("invalid ticker price")
            return Ticker(returned_symbol, 0.0, price, int(time.time() * 1000))
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError("Binance returned malformed ticker data") from exc

    def fetch_open_interest(self, symbol: str) -> float | None:
        """v2.0: açık pozisyon (OI) — GERÇEK futures verisi.

        Binance: /fapi/v1/openInterest (baz varlık cinsinden). Ayna (spot)
        modunda OI YOKTUR → None döner ("uygulanmadı" raporlanır, uydurulmaz).
        """
        requested_symbol = symbol.upper().split(":")[0].replace("/", "").replace("-", "")
        if self.mirror_mode:
            return None  # spot veri aynasında açık pozisyon verisi yoktur
        try:
            raw = self._get_json(
                "/fapi/v1/openInterest", {"symbol": requested_symbol},
            )
        except PublicMarketDataError:
            return None
        if not isinstance(raw, dict):
            return None
        try:
            value = float(raw["openInterest"])
        except (KeyError, TypeError, ValueError):
            return None
        if not isfinite(value) or value < 0:
            return None
        return value

    def fetch_order_book(self, symbol: str, limit: int = 100) -> OrderBook:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("order book limit must be between 1 and 1000")
        # FINAL v1.2: Binance yalnızca belirli limitleri kabul eder (400 DEĞİL);
        # üstteki geçerli değere yuvarla (400 → 500). Önceki sürümde 400 ile
        # çağrı Binance'te hata verirdi (OKX 400'ü kabul ediyor).
        limit = self._clamp_depth_limit(limit)
        requested_symbol = symbol.upper().split(":")[0].replace("/", "").replace("-", "")
        raw = self._get_json(
            "/fapi/v1/depth", {"symbol": requested_symbol, "limit": limit}
        )
        if not isinstance(raw, dict):
            raise PublicMarketDataError("Binance returned an unexpected order book")
        try:
            bids = self._parse_book_side(raw["bids"])
            asks = self._parse_book_side(raw["asks"])
            if not bids or not asks:
                raise ValueError("empty order book")
            return OrderBook(
                requested_symbol,
                tuple(bids),
                tuple(asks),
                int(raw.get("E", time.time() * 1000)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError("Binance returned malformed order book") from exc

    @staticmethod
    def _parse_book_side(rows: object) -> list[tuple[float, float]]:
        if not isinstance(rows, list):
            raise ValueError("invalid order book side")
        levels = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise ValueError("invalid order book level")
            price, amount = float(row[0]), float(row[1])
            if not isfinite(price) or price <= 0 or not isfinite(amount) or amount < 0:
                raise ValueError("invalid order book price or size")
            levels.append((price, amount))
        return levels

    def fetch_top_usdt_futures(self, limit: int = 100) -> list[Market]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        exchange_info = self._get_json("/fapi/v1/exchangeInfo", {})
        tickers = self._get_json("/fapi/v1/ticker/24hr", {})
        if (
            not isinstance(exchange_info, dict)
            or not isinstance(exchange_info.get("symbols"), list)
            or not isinstance(tickers, list)
        ):
            raise PublicMarketDataError("Binance returned unexpected futures metadata")
        try:
            if any(not isinstance(row, dict) for row in tickers):
                raise ValueError("invalid ticker row")
            ticker_data = {
                row["symbol"]: (
                    float(row["quoteVolume"]),
                    float(row.get("priceChangePercent", 0.0)),
                )
                for row in tickers
                if isinstance(row, dict)
            }
            markets = []
            for item in exchange_info["symbols"]:
                if not isinstance(item, dict):
                    raise ValueError("invalid instrument row")
                contract = item.get("contractType")
                if self.mirror_mode and contract is None:
                    contract = "SPOT"  # ayna modunda spot enstrümanlar
                if (
                    item.get("status") != "TRADING"
                    or item.get("quoteAsset") != "USDT"
                    or contract not in {
                        "PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER", "SPOT"
                    }
                ):
                    continue
                volume, percentage = ticker_data.get(item["symbol"], (0.0, 0.0))
                if (
                    not isfinite(volume)
                    or volume < 0
                    or not isfinite(percentage)
                ):
                    continue
                filters = item.get("filters", [])
                if not isinstance(filters, list):
                    raise ValueError("invalid instrument filters")
                price_filter = next(
                    (
                        entry for entry in filters
                        if isinstance(entry, dict)
                        and entry.get("filterType") == "PRICE_FILTER"
                    ),
                    None,
                )
                tick_size = float(price_filter["tickSize"]) if price_filter else 0.0
                if not isfinite(tick_size) or tick_size < 0:
                    raise ValueError("invalid instrument tick size")
                markets.append(Market(
                    symbol=item["symbol"],
                    base_asset=item["baseAsset"],
                    quote_volume_24h=volume,
                    contract_type=contract,
                    tick_size=tick_size,
                    percentage_24h=percentage,
                ))
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError("Binance returned malformed futures metadata") from exc
        return sorted(
            markets,
            key=lambda market: (
                market.quote_volume_24h,
                abs(market.percentage_24h),
            ),
            reverse=True,
        )[:limit]

    async def stream_tickers(
        self, symbols: Sequence[str] | None = None
    ) -> AsyncIterator[Ticker]:
        allowed = {symbol.upper() for symbol in symbols} if symbols else None
        async with connect(
            self._active_websocket_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            async for message in websocket:
                for ticker in self.parse_mini_tickers(message):
                    if allowed is None or ticker.symbol in allowed:
                        yield ticker

    @staticmethod
    def parse_aggregate_trade(message: str) -> PublicTrade:
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                raise ValueError("expected an aggregate-trade object")
            data = payload.get("data", payload)
            if not isinstance(data, dict) or data.get("e") != "aggTrade":
                raise ValueError("unexpected Binance stream event")
            symbol = str(data["s"]).upper()
            price = float(data["p"])
            quantity = float(data["q"])
            timestamp = int(data.get("T", data.get("E", 0)))
            if (
                not symbol or not isfinite(price) or price <= 0
                or not isfinite(quantity) or quantity <= 0 or timestamp < 0
            ):
                raise ValueError("invalid aggregate-trade values")
            return PublicTrade(symbol, price * quantity, price, timestamp)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError(
                "Binance returned malformed aggregate-trade data"
            ) from exc

    async def stream_trades(
        self, symbols: Sequence[str] | None = None
    ) -> AsyncIterator[PublicTrade]:
        if not symbols:
            raise ValueError("Binance trade stream requires the futures instrument list")
        stream_names = sorted({
            symbol.upper().split(":")[0].replace("/", "").replace("-", "").lower()
            + "@aggTrade"
            for symbol in symbols
        })
        if not stream_names:
            raise ValueError("Binance trade stream requires at least one instrument")
        queue: asyncio.Queue[PublicTrade] = asyncio.Queue(maxsize=10_000)

        async def pump(names: Sequence[str]) -> None:
            streams = "/".join(names)
            url = f"wss://{self._active_stream_host}/stream?streams={streams}"
            async with connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=4 * 1024 * 1024,
            ) as websocket:
                async for message in websocket:
                    await queue.put(self.parse_aggregate_trade(message))

        async with asyncio.TaskGroup() as task_group:
            for start in range(0, len(stream_names), 100):
                task_group.create_task(pump(stream_names[start:start + 100]))
            while True:
                yield await queue.get()
