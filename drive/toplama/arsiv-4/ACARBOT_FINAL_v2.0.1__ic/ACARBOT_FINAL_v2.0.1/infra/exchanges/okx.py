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
    OrderBook,
    PublicExchange,
    PublicMarketDataError,
    PublicTrade,
    Ticker,
    validate_request,
)
from infra.market_data.models import Candle


class OKXPublic(PublicExchange):
    name = "OKX"
    base_url = "https://www.okx.com"
    _bars = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
             "1h": "1H", "4h": "4H", "1d": "1D"}

    def fetch_open_interest(self, symbol: str) -> float | None:
        """v2.0: açık pozisyon (OI) — gerçek borsa verisi; yoksa None.

        OKX: /api/v5/public/open-interest (kontrat cinsinden) → kontığın
        çarpanıyla baz varlığa çevrilmez; kontrat değeri döner. CVD/alpha
        için GÖRELİ değişim (yüzde) kullanıldığından birim tutarlılığı yeterlidir.
        Ayna/spot modunda OI anlamsızdır → None ("uygulanmadı").
        """
        inst_id = self._instrument_id(symbol)
        raw = self._get_json(
            "/api/v5/public/open-interest", {"instId": inst_id},
        )
        if not isinstance(raw, dict) or raw.get("code") != "0":
            return None
        try:
            rows = raw["data"]
            if not isinstance(rows, list) or not rows:
                return None
            row = rows[0]
            value = float(row["oi"])
            if not isfinite(value) or value < 0:
                return None
            return value
        except (KeyError, TypeError, ValueError, IndexError):
            return None

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

    def fetch_order_book(self, symbol: str, limit: int = 100) -> OrderBook:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 400:
            raise ValueError("order book limit must be between 1 and 400")
        instrument_id = self._instrument_id(symbol)
        raw = self._get_json(
            "/api/v5/market/books", {"instId": instrument_id, "sz": limit}
        )
        if not isinstance(raw, dict) or raw.get("code") != "0":
            raise PublicMarketDataError("OKX returned an unexpected order book")
        try:
            rows = raw["data"]
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise ValueError("missing order book")
            result = rows[0]
            # FINAL v1.1 düzeltmesi: OKX /market/books yanıtı instId DÖNDÜRMEZ
            # (yalnızca asks/bids/ts). Alan yoksa istenen id kabul edilir.
            returned_id = str(result.get("instId", instrument_id)).upper()
            if returned_id != instrument_id.upper():
                raise PublicMarketDataError(
                    f"OKX order book symbol mismatch: requested={instrument_id}, "
                    f"received={returned_id}"
                )
            bids = self._parse_book_side(result["bids"])
            asks = self._parse_book_side(result["asks"])
            if not bids or not asks:
                raise ValueError("empty order book")
            instrument_type = "SWAP" if instrument_id.endswith("-SWAP") else "FUTURES"
            instruments = self._get_json(
                "/api/v5/public/instruments", {"instType": instrument_type}
            )
            if not isinstance(instruments, dict) or instruments.get("code") != "0":
                raise ValueError("invalid instrument metadata")
            metadata = next(
                (
                    item for item in instruments.get("data", [])
                    if isinstance(item, dict) and item.get("instId") == instrument_id
                ),
                None,
            )
            if metadata is None:
                raise ValueError("order book instrument metadata missing")
            contract_value = float(metadata.get("ctVal", 1.0))
            if not isfinite(contract_value) or contract_value <= 0:
                raise ValueError("invalid contract value")
            base_multiplier = (
                contract_value
                if metadata.get("ctValCcy") == metadata.get("baseCcy")
                else contract_value / bids[0][0]
            )
            bids = [(price, size * base_multiplier) for price, size in bids]
            asks = [(price, size * base_multiplier) for price, size in asks]
            return OrderBook(
                returned_id,
                tuple(bids),
                tuple(asks),
                int(result.get("ts", time.time() * 1000)),
            )
        except PublicMarketDataError:
            raise
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            raise PublicMarketDataError("OKX returned malformed order book") from exc

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
            pong_received = asyncio.Event()

            async def keepalive() -> None:
                while True:
                    await asyncio.sleep(20)
                    pong_received.clear()
                    await websocket.send("ping")
                    try:
                        await asyncio.wait_for(pong_received.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        await websocket.close(
                            code=1011, reason="OKX heartbeat timeout"
                        )
                        return

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
                        pong_received.set()
                        continue
                    _, tickers = self.parse_ticker_message(message)
                    for ticker in tickers:
                        yield ticker
            finally:
                keepalive_task.cancel()
                await asyncio.gather(keepalive_task, return_exceptions=True)

    @staticmethod
    def parse_trade_message(
        message: str, contract_multipliers: dict[str, tuple[float, str, str, str]]
    ) -> list[PublicTrade]:
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                raise ValueError("expected an OKX trades object")
            if payload.get("event") == "error":
                raise PublicMarketDataError(
                    f"OKX trade subscription failed: {payload}"
                )
            arg = payload.get("arg", {})
            if not isinstance(arg, dict) or arg.get("channel") != "trades":
                return []
            trades = []
            for item in payload.get("data", []):
                if not isinstance(item, dict):
                    continue
                instrument_id = str(item["instId"]).upper()
                multiplier = contract_multipliers.get(instrument_id)
                if multiplier is None:
                    raise ValueError(f"missing OKX contract metadata for {instrument_id}")
                contract_value, value_currency, base_currency, quote_currency = multiplier
                price = float(item["px"])
                size = float(item["sz"])
                timestamp = int(item["ts"])
                if (
                    not isfinite(contract_value) or contract_value <= 0
                    or not isfinite(price) or price <= 0
                    or not isfinite(size) or size <= 0 or timestamp < 0
                ):
                    raise ValueError("invalid OKX trade values")
                if value_currency == base_currency:
                    quote_volume = contract_value * size * price
                elif value_currency == quote_currency:
                    quote_volume = contract_value * size
                else:
                    raise ValueError(
                        f"unsupported OKX contract value currency {value_currency}"
                    )
                trades.append(PublicTrade(
                    instrument_id, quote_volume, price, timestamp
                ))
            return trades
        except PublicMarketDataError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PublicMarketDataError(
                "OKX returned malformed trade data"
            ) from exc

    async def stream_trades(
        self, symbols: Sequence[str] | None = None
    ) -> AsyncIterator[PublicTrade]:
        if not symbols:
            raise ValueError("OKX trade stream requires the futures instrument list")
        instrument_ids = sorted({self._instrument_id(symbol) for symbol in symbols})
        if not instrument_ids:
            raise ValueError("OKX trade stream requires at least one instrument")
        types = {
            "SWAP" if instrument_id.endswith("-SWAP") else "FUTURES"
            for instrument_id in instrument_ids
        }
        metadata: dict[str, tuple[float, str, str, str]] = {}
        for instrument_type in types:
            raw = await asyncio.to_thread(
                self._get_json,
                "/api/v5/public/instruments",
                {"instType": instrument_type},
            )
            if not isinstance(raw, dict) or raw.get("code") != "0":
                raise PublicMarketDataError(
                    "OKX returned unexpected trade instrument metadata"
                )
            rows = raw.get("data")
            if not isinstance(rows, list):
                raise PublicMarketDataError("OKX trade instrument metadata is malformed")
            for item in rows:
                if (
                    not isinstance(item, dict)
                    or item.get("instId") not in instrument_ids
                    or item.get("state") != "live"
                    or item.get("ctType") != "linear"
                    or item.get("settleCcy") != "USDT"
                ):
                    continue
                try:
                    metadata[str(item["instId"]).upper()] = (
                        float(item["ctVal"]),
                        str(item["ctValCcy"]).upper(),
                        str(item["baseCcy"]).upper(),
                        str(item["quoteCcy"]).upper(),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise PublicMarketDataError(
                        "OKX returned malformed contract metadata"
                    ) from exc
        missing = set(instrument_ids) - metadata.keys()
        if missing:
            raise PublicMarketDataError(
                "OKX contract metadata missing for: " + ", ".join(sorted(missing))
            )

        async with connect(
            "wss://ws.okx.com:8443/ws/v5/public",
            ping_interval=None,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            pong_received = asyncio.Event()

            async def keepalive() -> None:
                while True:
                    await asyncio.sleep(20)
                    pong_received.clear()
                    await websocket.send("ping")
                    try:
                        await asyncio.wait_for(pong_received.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        await websocket.close(
                            code=1011, reason="OKX heartbeat timeout"
                        )
                        return

            keepalive_task = asyncio.create_task(keepalive())
            try:
                for start in range(0, len(instrument_ids), 100):
                    args = [
                        {"channel": "trades", "instId": instrument_id}
                        for instrument_id in instrument_ids[start:start + 100]
                    ]
                    await websocket.send(json.dumps({"op": "subscribe", "args": args}))
                async for message in websocket:
                    if message == "pong":
                        pong_received.set()
                        continue
                    for trade in self.parse_trade_message(message, metadata):
                        yield trade
            finally:
                keepalive_task.cancel()
                await asyncio.gather(keepalive_task, return_exceptions=True)
