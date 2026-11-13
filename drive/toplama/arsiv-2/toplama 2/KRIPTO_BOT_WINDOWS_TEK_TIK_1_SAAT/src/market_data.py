"""Çift Borsa Gerçek Zamanlı WebSocket Akış Motoru (Binance USDⓈ-M + OKX USDT-M Swap).

Özellikler:
  - Binance Futures ayrı `public` (`@bookTicker`, `@depth20`) ve `market` (`@aggTrade`, `@forceOrder`) kanalları
  - OKX V5 `trades`, `tickers` ve sequence-doğrulamalı artımlı `books` (20 kademe) akışı
  - OKX Swap `contractSize` normalizasyonu (kontrat adedi → coin miktarı)
  - Bağlantı kopmasında (reconnect) açık pozisyonların SQLite senkronizasyonu ve stop kontrolü
  - Ping/Pong keep-alive, gecikme (latency) ve borsa bazlı mesaj sayaçları
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any, Callable


def to_binance_stream(symbol: str) -> str:
    return symbol.replace("/", "").split(":")[0].lower()


def to_okx_inst(symbol: str, market_type: str = "spot") -> str:
    base = symbol.replace("/", "-").split(":")[0]
    return f"{base}-SWAP" if market_type == "swap" else base


def binance_ws_base(market_type: str = "spot", channel: str = "public") -> str:
    if market_type != "swap":
        return "wss://stream.binance.com:9443"
    if channel not in {"public", "market"}:
        raise ValueError("Binance Futures WS kanalı public veya market olmalı")
    return f"wss://fstream.binance.com/{channel}"


class OrderBookSyncError(RuntimeError):
    """OKX artımlı defter zinciri koptu; yeni snapshot gerekli."""


class IncrementalOrderBook:
    """OKX ``books`` snapshot + sıralı artımlı güncelleme durumu.

    Miktarlar burada ham kontrat biriminde tutulur. Coin dönüşümü yalnız
    analize gönderilen ilk kademelerde yapılır; böylece miktarı sıfır olan
    kademeler kontrat boyutu bilinmese bile doğru şekilde silinir.
    """

    def __init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.seq_id: int | None = None

    @staticmethod
    def _apply_levels(target: dict[float, float], rows: list):
        for raw_price, raw_qty, *_ in rows:
            price, qty = float(raw_price), float(raw_qty)
            if qty <= 0:
                target.pop(price, None)
            else:
                target[price] = qty

    def apply(self, action: str, data: dict):
        action = str(action or "").lower()
        if action == "snapshot":
            self.bids.clear()
            self.asks.clear()
            self._apply_levels(self.bids, data.get("bids", []))
            self._apply_levels(self.asks, data.get("asks", []))
            self.seq_id = int(data["seqId"])
            return
        if action != "update" or self.seq_id is None:
            raise OrderBookSyncError("Snapshot olmadan artımlı defter güncellemesi")
        previous = int(data["prevSeqId"])
        if previous != self.seq_id:
            raise OrderBookSyncError(
                f"Defter sıra boşluğu: beklenen {self.seq_id}, gelen {previous}"
            )
        self._apply_levels(self.bids, data.get("bids", []))
        self._apply_levels(self.asks, data.get("asks", []))
        self.seq_id = int(data["seqId"])

    def top(self, levels: int = 20) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        bids = sorted(self.bids.items(), key=lambda row: row[0], reverse=True)[:levels]
        asks = sorted(self.asks.items(), key=lambda row: row[0])[:levels]
        return bids, asks


class MarketData:
    def __init__(
        self,
        symbols: list[str],
        exchanges: list[str],
        on_trade: Callable | None = None,
        on_price: Callable | None = None,
        on_book: Callable | None = None,
        reconnect_sec: float = 5.0,
        *,
        on_liquidation: Callable | None = None,
        on_ws_heartbeat: Callable | None = None,
        state_store: Any | None = None,
        executor: Any | None = None,
        ping_interval_sec: float = 15.0,
        ping_timeout_sec: float = 10.0,
        recv_timeout_sec: float = 25.0,
        max_session_sec: float = 23 * 3600,
        market_type: str = "spot",
        contract_sizes: dict | None = None,
        symbol_exchanges: dict[str, list[str]] | None = None,
        stream_batch_size: int = 50,
        depth_update_ms: int = 100,
    ):
        self.symbols = list(symbols)
        self.exchanges = list(exchanges)
        self.symbol_exchanges = symbol_exchanges or {}
        self.stream_batch_size = max(1, int(stream_batch_size))
        depth_ms = int(depth_update_ms)
        self.depth_update_ms = depth_ms if depth_ms in {100, 250, 500} else 100
        self.on_trade = on_trade
        self.on_price = on_price
        self.on_book = on_book
        self.reconnect_sec = float(reconnect_sec)
        self.on_liquidation = on_liquidation
        self.on_ws_heartbeat = on_ws_heartbeat
        self.state_store = state_store
        self.executor = executor
        self.ping_interval_sec = float(ping_interval_sec)
        self.ping_timeout_sec = float(ping_timeout_sec)
        self.recv_timeout_sec = float(recv_timeout_sec)
        self.max_session_sec = float(max_session_sec)
        if market_type not in {"spot", "swap"}:
            raise ValueError("market_type yalnızca spot veya swap olabilir")
        self.market_type = market_type
        self.contract_sizes = contract_sizes or {}

        self._running = False
        self.prices: dict[str, float] = {}
        self.quotes: dict[str, dict[str, tuple[float, float]]] = {}
        self._lat: deque[float] = deque(maxlen=500)
        self.last_message_ts: float = 0.0
        self.last_pong_ts: dict[str, float] = {}
        self.ping_pong_count: int = 0
        self.reconnect_count: int = 0
        self.recovered_positions_on_reconnect: int = 0
        self.exchange_data_stats: dict[str, dict] = {
            name: {
                "trade_messages": 0,
                "price_messages": 0,
                "book_messages": 0,
                "liquidation_messages": 0,
                "last_data_ts": 0.0,
            }
            for name in exchanges
        }

    def _mark_exchange_data(self, exchange: str, kind: str):
        row = self.exchange_data_stats.setdefault(
            exchange,
            {
                "trade_messages": 0,
                "price_messages": 0,
                "book_messages": 0,
                "liquidation_messages": 0,
                "last_data_ts": 0.0,
            },
        )
        key = f"{kind}_messages"
        row[key] = int(row.get(key, 0)) + 1
        row["last_data_ts"] = time.time()

    def data_stats_snapshot(self) -> dict:
        return {name: dict(row) for name, row in self.exchange_data_stats.items()}

    def normalize_quantity(self, exchange: str, symbol: str, qty: float) -> float | None:
        """OKX Swap kontratlarını coin miktarına çevirir.

        ``contractSize`` bilinmiyorsa ``None`` döner; böylece kontrat adedi
        yanlışlıkla coin gibi kullanılıp para akışı şişirilmez.
        """
        if exchange != "okx" or self.market_type != "swap":
            return float(qty)
        contract_size = self.contract_sizes.get((exchange, symbol))
        if contract_size is None or float(contract_size) <= 0:
            return None
        return float(qty) * float(contract_size)

    def avg_latency_ms(self) -> float:
        return sum(self._lat) / len(self._lat) if self._lat else 0.0

    def _mark_lat(self, event_ts_ms: float | int | str | None) -> None:
        now = time.time()
        self.last_message_ts = now
        if self.on_ws_heartbeat:
            try:
                self.on_ws_heartbeat()
            except Exception:
                pass
        if event_ts_ms is not None:
            try:
                lat = max(0.0, now * 1000.0 - float(event_ts_ms))
                if lat < 60_000:
                    self._lat.append(lat)
            except (TypeError, ValueError):
                pass

    def record_pong(self, exchange: str) -> None:
        self.last_pong_ts[exchange] = time.time()
        self.ping_pong_count += 1
        if self.on_ws_heartbeat:
            try:
                self.on_ws_heartbeat()
            except Exception:
                pass

    async def _handle_reconnect_state_sync(self, exchange: str) -> None:
        self.reconnect_count += 1
        if self.state_store is not None and self.executor is not None:
            try:
                saved = self.state_store.load_positions()
                for sym, pos in saved.items():
                    if sym not in self.executor.positions:
                        self.executor.positions[sym] = pos
                        self.recovered_positions_on_reconnect += 1
            except Exception:
                pass
        # Yeniden bağlanma anında mevcut fiyatlarla tüm açık pozisyonların stoplarını denetle
        if self.executor is not None and self.executor.positions:
            for sym in list(self.executor.positions.keys()):
                pos = self.executor.positions[sym]
                px = self.get_price(sym, getattr(pos, "exchange", None)) or self.executor.last_prices.get(sym)
                if px and px > 0:
                    await self.executor.on_price_tick(sym, px)

    async def _ws_keepalive_task(self, ws, exchange: str) -> None:
        while self._running:
            await asyncio.sleep(self.ping_interval_sec)
            try:
                if exchange == "okx":
                    await ws.send("ping")
                    self.record_pong(exchange)
                else:
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=self.ping_timeout_sec)
                    self.record_pong(exchange)
            except Exception:
                try:
                    await ws.close()
                except Exception:
                    pass
                return

    def symbols_for_exchange(self, exchange: str) -> list[str]:
        if not self.symbol_exchanges:
            return list(self.symbols)
        return [s for s in self.symbols if exchange in self.symbol_exchanges.get(s, [])]

    def stream_batches(self, exchange: str) -> list[list[str]]:
        symbols = self.symbols_for_exchange(exchange)
        return [
            symbols[i : i + self.stream_batch_size]
            for i in range(0, len(symbols), self.stream_batch_size)
        ]

    # -- Binance Futures Public / Market akışları ------------------------------
    async def _binance_loop(
        self, symbols: list[str] | None = None, channel: str = "public"
    ):
        import websockets

        symbols = symbols if symbols is not None else self.symbols
        if not symbols:
            return
        streams = []
        for s in symbols:
            b = to_binance_stream(s)
            if self.market_type == "swap" and channel == "market":
                streams.append(f"{b}@aggTrade")
                if self.on_liquidation:
                    streams.append(f"{b}@forceOrder")
            else:
                if self.market_type != "swap":
                    streams.append(f"{b}@aggTrade")
                streams.append(f"{b}@bookTicker")
                streams.append(f"{b}@depth20@{self.depth_update_ms}ms")
        url = (
            f"{binance_ws_base(self.market_type, channel)}"
            f"/stream?streams={'/'.join(streams)}"
        )
        rev = {to_binance_stream(s): s for s in symbols}
        first_connect = True

        while self._running:
            keepalive_task = None
            try:
                async with websockets.connect(
                    url,
                    ping_interval=self.ping_interval_sec,
                    ping_timeout=self.ping_timeout_sec,
                    max_size=4 * 1024 * 1024,
                ) as ws:
                    if not first_connect:
                        await self._handle_reconnect_state_sync("binance")
                    first_connect = False
                    self.record_pong("binance")
                    session_start = time.time()
                    keepalive_task = asyncio.create_task(
                        self._ws_keepalive_task(ws, "binance")
                    )

                    while self._running:
                        if time.time() - session_start >= self.max_session_sec:
                            break
                        raw = await asyncio.wait_for(
                            ws.recv(), timeout=self.recv_timeout_sec
                        )
                        try:
                            msg = json.loads(raw)
                            stream = str(msg.get("stream", ""))
                            d = msg.get("data") or {}
                            if not stream or not d:
                                continue
                            base = stream.split("@", 1)[0].lower()
                            sym = rev.get(base)
                            if not sym:
                                continue
                            if stream.endswith("@forceOrder"):
                                order = d.get("o", {})
                                side = str(order.get("S", "SELL"))
                                price = float(order.get("ap") or order.get("p") or 0)
                                qty = float(order.get("q") or 0)
                                if price > 0 and qty > 0:
                                    self._mark_exchange_data("binance", "liquidation")
                                    if self.on_liquidation:
                                        await self.on_liquidation(
                                            "binance", sym, side, price, qty
                                        )
                            elif stream.endswith("@aggTrade"):
                                price = float(d["p"])
                                qty = float(d["q"])
                                self.prices[f"binance:{sym}"] = price
                                self._mark_lat(d.get("T"))
                                self._mark_exchange_data("binance", "trade")
                                if self.on_trade:
                                    await self.on_trade(
                                        "binance", sym, price, qty, bool(d.get("m"))
                                    )
                            elif "@depth" in stream:
                                raw_bids = d.get("b") or d.get("bids") or []
                                raw_asks = d.get("a") or d.get("asks") or []
                                bids_20 = [
                                    (float(p), float(q)) for p, q in raw_bids[:20]
                                ]
                                asks_20 = [
                                    (float(p), float(q)) for p, q in raw_asks[:20]
                                ]
                                self._mark_lat(d.get("T"))
                                self._mark_exchange_data("binance", "book")
                                if bids_20 and asks_20 and self.on_book:
                                    await self.on_book(
                                        "binance", sym, bids_20, asks_20
                                    )
                            elif stream.endswith("@bookTicker"):
                                bid_p = float(d["b"])
                                ask_p = float(d["a"])
                                mid = (bid_p + ask_p) / 2
                                self.prices[f"binance:{sym}"] = mid
                                self.quotes.setdefault(sym, {})["binance"] = (
                                    bid_p,
                                    ask_p,
                                )
                                self._mark_lat(d.get("T"))
                                self._mark_exchange_data("binance", "price")
                                if self.on_price:
                                    await self.on_price("binance", sym, mid)
                        except Exception:
                            continue
            except Exception:
                if self._running:
                    await asyncio.sleep(self.reconnect_sec)
            finally:
                if keepalive_task:
                    keepalive_task.cancel()

    # -- OKX -------------------------------------------------------------------
    async def _okx_loop(self, symbols: list[str] | None = None):
        import websockets

        symbols = symbols if symbols is not None else self.symbols
        if not symbols:
            return
        url = "wss://ws.okx.com:8443/ws/v5/public"
        args = []
        for s in symbols:
            inst = to_okx_inst(s, self.market_type)
            args.append({"channel": "trades", "instId": inst})
            args.append({"channel": "tickers", "instId": inst})
            args.append({"channel": "books", "instId": inst})
        rev = {to_okx_inst(s, self.market_type): s for s in symbols}
        first_connect = True

        while self._running:
            keepalive_task = None
            try:
                async with websockets.connect(
                    url,
                    ping_interval=None,
                    max_size=4 * 1024 * 1024,
                ) as ws:
                    if not first_connect:
                        await self._handle_reconnect_state_sync("okx")
                    first_connect = False
                    self.record_pong("okx")
                    session_start = time.time()
                    # Her bağlantı yeni snapshot ile başlar; önceki bağlantının
                    # sequence/defter durumu asla taşınmaz.
                    order_books: dict[str, IncrementalOrderBook] = {}
                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
                    keepalive_task = asyncio.create_task(
                        self._ws_keepalive_task(ws, "okx")
                    )

                    while self._running:
                        if time.time() - session_start >= self.max_session_sec:
                            break
                        raw = await asyncio.wait_for(
                            ws.recv(), timeout=self.recv_timeout_sec
                        )
                        if raw == "pong":
                            self.record_pong("okx")
                            continue
                        try:
                            msg = json.loads(raw)
                            arg = msg.get("arg") or {}
                            ch = arg.get("channel")
                            inst = arg.get("instId")
                            sym = rev.get(inst)
                            if not sym or "data" not in msg:
                                continue
                            if ch == "trades":
                                for t in msg["data"]:
                                    price = float(t["px"])
                                    raw_qty = float(t["sz"])
                                    qty = self.normalize_quantity("okx", sym, raw_qty)
                                    self.prices[f"okx:{sym}"] = price
                                    self._mark_lat(t.get("ts"))
                                    self._mark_exchange_data("okx", "trade")
                                    buyer_maker = t.get("side") == "sell"
                                    if self.on_trade and qty is not None and qty > 0:
                                        await self.on_trade(
                                            "okx", sym, price, qty, buyer_maker
                                        )
                            elif ch == "tickers":
                                for t in msg["data"]:
                                    price = float(t["last"])
                                    bid_p = float(t.get("bidPx") or price)
                                    ask_p = float(t.get("askPx") or price)
                                    self.prices[f"okx:{sym}"] = price
                                    self.quotes.setdefault(sym, {})["okx"] = (bid_p, ask_p)
                                    self._mark_lat(t.get("ts"))
                                    self._mark_exchange_data("okx", "price")
                                    if self.on_price:
                                        await self.on_price("okx", sym, price)
                            elif ch == "books":
                                action = str(msg.get("action", ""))
                                for book in msg["data"]:
                                    state = order_books.setdefault(
                                        sym, IncrementalOrderBook()
                                    )
                                    # Sequence boşluğu dış katmana kadar gider;
                                    # bağlantı ve snapshot yenilenir. Diğer veri
                                    # hatalarında olduğu gibi sessizce devam etmeyiz.
                                    state.apply(action, book)
                                    raw_bids, raw_asks = state.top(20)
                                    bids, asks = [], []
                                    for raw_price, raw_qty in raw_bids:
                                        qty = self.normalize_quantity("okx", sym, raw_qty)
                                        if qty is not None and qty > 0:
                                            bids.append((raw_price, qty))
                                    for raw_price, raw_qty in raw_asks:
                                        qty = self.normalize_quantity("okx", sym, raw_qty)
                                        if qty is not None and qty > 0:
                                            asks.append((raw_price, qty))
                                    self._mark_lat(book.get("ts"))
                                    self._mark_exchange_data("okx", "book")
                                    if bids and asks:
                                        self.quotes.setdefault(sym, {})["okx"] = (
                                            bids[0][0],
                                            asks[0][0],
                                        )
                                        if self.on_book:
                                            await self.on_book("okx", sym, bids, asks)
                        except OrderBookSyncError:
                            raise
                        except Exception:
                            continue
            except Exception:
                if self._running:
                    await asyncio.sleep(self.reconnect_sec)
            finally:
                if keepalive_task:
                    keepalive_task.cancel()

    async def run_forever(self):
        self._running = True
        tasks = []
        if "binance" in self.exchanges:
            for batch in self.stream_batches("binance"):
                tasks.append(asyncio.create_task(self._binance_loop(batch, "public")))
                if self.market_type == "swap":
                    tasks.append(asyncio.create_task(self._binance_loop(batch, "market")))
        if "okx" in self.exchanges:
            for batch in self.stream_batches("okx"):
                tasks.append(asyncio.create_task(self._okx_loop(batch)))
        if not tasks:
            return
        await asyncio.gather(*tasks)

    def stop(self):
        self._running = False

    def get_price(self, symbol: str, exchange: str | None = None) -> float | None:
        if exchange:
            return self.prices.get(f"{exchange}:{symbol}")
        allowed = self.symbol_exchanges.get(symbol)
        exchanges = [e for e in self.exchanges if not allowed or e in allowed]
        for ex in exchanges:
            p = self.prices.get(f"{ex}:{symbol}")
            if p:
                return p
        return None

    def get(self, symbol: str, exchange: str | None = None) -> float | None:
        return self.get_price(symbol, exchange)
