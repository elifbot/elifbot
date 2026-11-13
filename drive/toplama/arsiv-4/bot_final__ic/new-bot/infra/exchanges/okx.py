"""OKX public linear USDT Futures/Swap market-data client."""

from __future__ import annotations

import asyncio
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


class OKXPublic(PublicExchange):
    name = "OKX"
    base_url = "https://www.okx.com"
    _bars = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
             "1h": "1H", "4h": "4H", "1d": "1D"}

    @staticmethod
    def parse_ticker_message(message: str) -> tuple[str | None, list[Ticker]]:
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                return None, []
            if payload.get("event") == "error":
                raise PublicMarketDataError(
                    f"OKX ticker subscription failed: {payload}"
                )
            arg = payload.get("arg", {})
            if not isinstance(arg, dict) or arg.get("channel") != "tickers":
                return None, []
            tickers = []
            for item in payload.get("data", []):
                if not isinstance(item, dict):
                    continue
                price = float(item["last"])
                open_24h = float(item.get("open24h", 0))
                volume_currency = float(item.get("volCcy24h", 0))
                volume_contracts = float(item.get("vol24h", 0))
                quote_volume = (
                    volume_currency * price
                    if volume_currency > 0
                    else volume_contracts * price
                )
                timestamp = int(item.get("ts", 0))
                symbol = str(item["instId"]).upper()
                if (
                    not symbol
                    or not isfinite(price) or price <= 0
                    or not isfinite(quote_volume) or quote_volume < 0
                    or not isfinite(open_24h) or open_24h < 0
                    or timestamp < 0
                ):
                    continue
                tickers.append(Ticker(symbol, quote_volume, price, timestamp))
            return "tickers", tickers
        except PublicMarketDataError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError(
                "OKX returned malformed ticker data"
            ) from exc

    @staticmethod
    def _instrument_id(symbol: str) -> str:
        normalized = symbol.upper().split(":")[0]
        if "/" in normalized:
            return normalized.replace("/", "-")
        if "-" in normalized:
            return normalized
        for quote in ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH"):
            if normalized.endswith(quote) and len(normalized) > len(quote):
                return f"{normalized[:-len(quote)]}-{quote}"
        return normalized

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        validate_request(symbol, timeframe, limit)
        inst_id = self._instrument_id(symbol)
        raw = self._get_json(
            "/api/v5/market/candles", {"instId": inst_id, "bar": self._bars[timeframe],
                                       "limit": limit},
        )
        if not isinstance(raw, dict) or raw.get("code") != "0":
            raise PublicMarketDataError("OKX returned an unexpected candle payload")
        try:
            rows = raw["data"]
            return [
                Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]),
                       float(row[4]), float(row[5]))
                for row in reversed(rows)
            ]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise PublicMarketDataError("OKX returned malformed candles") from exc

    def fetch_ticker(self, symbol: str) -> Ticker:
        requested_id = self._instrument_id(symbol)
        raw = self._get_json("/api/v5/market/ticker", {"instId": requested_id})
        if not isinstance(raw, dict) or raw.get("code") != "0":
            raise PublicMarketDataError("OKX returned an unexpected ticker payload")
        try:
            rows = raw["data"]
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise ValueError("missing ticker row")
            row = rows[0]
            returned_id = str(row["instId"]).upper()
            if returned_id != requested_id.upper():
                raise PublicMarketDataError(
                    f"OKX ticker symbol mismatch: requested={requested_id}, "
                    f"received={returned_id}"
                )
            price = float(row["last"])
            volume_currency = float(row.get("volCcy24h", 0))
            volume_contracts = float(row.get("vol24h", 0))
            volume = (
                volume_currency * price
                if volume_currency > 0 else volume_contracts * price
            )
            timestamp = int(row.get("ts", time.time() * 1000))
            if (
                not isfinite(price) or price <= 0
                or not isfinite(volume) or volume < 0
                or timestamp < 0
            ):
                raise ValueError("invalid ticker values")
            return Ticker(returned_id, volume, price, timestamp)
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError("OKX returned malformed ticker data") from exc

    def fetch_top_usdt_futures(self, limit: int = 100) -> list[Market]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        markets: list[Market] = []
        for instrument_type in ("SWAP", "FUTURES"):
            instruments = self._get_json(
                "/api/v5/public/instruments", {"instType": instrument_type}
            )
            tickers = self._get_json(
                "/api/v5/market/tickers", {"instType": instrument_type}
            )
            if (
                not isinstance(instruments, dict)
                or instruments.get("code") != "0"
                or not isinstance(tickers, dict)
                or tickers.get("code") != "0"
            ):
                raise PublicMarketDataError("OKX returned unexpected futures metadata")
            try:
                if (
                    not isinstance(instruments.get("data"), list)
                    or not isinstance(tickers.get("data"), list)
                    or any(not isinstance(item, dict) for item in instruments["data"])
                    or any(not isinstance(item, dict) for item in tickers["data"])
                ):
                    raise ValueError("invalid instrument or ticker rows")
                ticker_by_id = {
                    item["instId"]: item
                    for item in tickers["data"]
                    if isinstance(item, dict)
                }
                for instrument in instruments["data"]:
                    if (
                        instrument.get("state") != "live"
                        or instrument.get("settleCcy") != "USDT"
                        or instrument.get("ctType") != "linear"
                    ):
                        continue
                    ticker = ticker_by_id.get(instrument["instId"])
                    if ticker is None:
                        continue
                    last = float(ticker["last"])
                    open_24h = float(ticker.get("open24h", 0))
                    volume_currency = float(ticker.get("volCcy24h", 0))
                    volume_contracts = float(ticker.get("vol24h", 0))
                    # OKX expresses derivative volume in base currency/contracts;
                    # volCcy24h * last is its USDT turnover estimate for ranking.
                    volume = volume_currency * last if volume_currency > 0 else volume_contracts * last
                    percentage = (
                        (last / open_24h - 1.0) * 100.0
                        if open_24h > 0 else 0.0
                    )
                    if (
                        not isfinite(volume)
                        or volume < 0
                        or not isfinite(percentage)
                    ):
                        continue
                    tick_size = float(instrument.get("tickSz", 0))
                    if not isfinite(tick_size) or tick_size < 0:
                        raise ValueError("invalid instrument tick size")
                    markets.append(Market(
                        symbol=instrument["instId"],
                        base_asset=instrument["baseCcy"],
                        quote_volume_24h=volume,
                        contract_type=instrument_type,
                        tick_size=tick_size,
                        percentage_24h=percentage,
                    ))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise PublicMarketDataError("OKX returned malformed futures metadata") from exc
        markets.sort(
            key=lambda market: (
                market.quote_volume_24h,
                abs(market.percentage_24h),
            ),
            reverse=True,
        )
        # A symbol may appear in both datasets only if the venue reuses its instrument id.
        unique: dict[str, Market] = {}
        for market in markets:
            unique.setdefault(market.symbol, market)
        return list(unique.values())[:limit]

    async def stream_tickers(
        self, symbols: Sequence[str] | None = None
    ) -> AsyncIterator[Ticker]:
        if not symbols:
            raise ValueError("OKX ticker stream requires the futures instrument list")
        instrument_ids = sorted({self._instrument_id(symbol) for symbol in symbols})
        async with connect(
            "wss://ws.okx.com:8443/ws/v5/public",
            ping_interval=None,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            async def keepalive() -> None:
                while True:
                    await asyncio.sleep(20)
                    await websocket.send("ping")

            keepalive_task = asyncio.create_task(keepalive())
            try:
                for start in range(0, len(instrument_ids), 100):
                    args = [
                        {"channel": "tickers", "instId": instrument_id}
                        for instrument_id in instrument_ids[start:start + 100]
                    ]
                    await websocket.send(json.dumps({
                        "op": "subscribe",
                        "args": args,
                    }))
                async for message in websocket:
                    if message == "pong":
                        continue
                    _, tickers = self.parse_ticker_message(message)
                    for ticker in tickers:
                        yield ticker
            finally:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass
