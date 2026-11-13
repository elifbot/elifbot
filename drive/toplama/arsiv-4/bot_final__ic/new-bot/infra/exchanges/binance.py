"""Binance public USDT-M Futures market-data client. No authenticated endpoints."""

from __future__ import annotations

import json
from math import isfinite
import time
from collections.abc import AsyncIterator, Sequence

from websockets.asyncio.client import connect

from infra.exchanges.base import (
    Market,
    PublicExchange,
    PublicMarketDataError,
    Ticker,
    validate_request,
)
from infra.market_data.models import Candle


class BinancePublic(PublicExchange):
    name = "Binance"
    base_url = "https://fapi.binance.com"
    websocket_url = "wss://fstream.binance.com/ws/!miniTicker@arr"
    _intervals = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                  "1h": "1h", "4h": "4h", "1d": "1d"}

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
                if (
                    item.get("status") != "TRADING"
                    or item.get("quoteAsset") != "USDT"
                    or item.get("contractType") not in {
                        "PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"
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
                    contract_type=item["contractType"],
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
            self.websocket_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            async for message in websocket:
                for ticker in self.parse_mini_tickers(message):
                    if allowed is None or ticker.symbol in allowed:
                        yield ticker
