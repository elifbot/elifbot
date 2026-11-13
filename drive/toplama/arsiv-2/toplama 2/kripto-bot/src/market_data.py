"""Gerçek zamanlı veri: Binance + OKX WebSocket akışları
+ Keep-Alive (Ping/Pong) Döngüsü + Kopma Anında SQLite Durum Kurtarmalı Yeniden Bağlanma.

Gizli Tuzak Korumaları:
  1) WEBSOCKET KEEP-ALIVE (Ping/Pong):
     - Binance ve OKX bağlantıları 24 saat içinde veya ağ geçişlerinde sessizce düşebilir.
     - Protokol seviyesi `ping_interval=15, ping_timeout=10` yanında OKX için uygulama
       seviyesi `"ping" -> "pong"` döngüsü ve `recv_timeout` bekçisi (watchdog) çalışır.
     - 23 saatte bir proaktif temiz oturum yenilemesi yapılır (24s borsa kopmasını önler).
  2) KOPMA ANINDA SQLITE DURUM KURTARMALI RECONNECT (`handle_reconnect`):
     - Bağlantı koptuğunda ve yeniden kurulduğunda `StateStore` (`bot_state.db`)
       üzerinden açık pozisyonlar, giriş fiyatları ve kâr kilidi (`locked_profit`)
       durumları anında senkronize edilir; hiçbir açık pozisyon hafızadan kaybolmaz.
"""
from __future__ import annotations

import asyncio
import json
import time

from .security import safe_exception_msg


def to_binance_stream(symbol: str) -> str:
    return symbol.replace("/", "").split(":")[0].lower()


def to_okx_inst(symbol: str) -> str:
    return symbol.replace("/", "-").split(":")[0]


class MarketData:
    def __init__(
        self,
        symbols: list[str],
        exchanges: list[str],
        on_trade=None,
        on_price=None,
        on_book=None,
        reconnect_sec: int = 5,
        on_liquidation=None,
        on_ws_heartbeat=None,
        state_store=None,
        executor=None,
        on_reconnect=None,
        ping_interval_sec: float = 15.0,
        ping_timeout_sec: float = 10.0,
        recv_timeout_sec: float = 25.0,
        max_session_sec: float = 23 * 3600,
    ):
        self.symbols = symbols
        self.exchanges = exchanges
        self.on_trade = on_trade
        self.on_price = on_price
        self.on_book = on_book
        self.on_liquidation = on_liquidation
        self.on_ws_heartbeat = on_ws_heartbeat
        self.state_store = state_store
        self.executor = executor
        self.on_reconnect = on_reconnect

        self.reconnect_sec = reconnect_sec
        self.ping_interval_sec = ping_interval_sec
        self.ping_timeout_sec = ping_timeout_sec
        self.recv_timeout_sec = recv_timeout_sec
        self.max_session_sec = max_session_sec

        self._running = False
        self.prices: dict[str, float] = {}
        self.quotes: dict[str, dict[str, tuple[float, float]]] = {}
        self._lat: list[float] = []
        self.last_message_ts: float = time.time()
        self.last_pong_ts: dict[str, float] = {}
        self.ping_pong_count: int = 0
        self.reconnect_count: int = 0
        self.recovered_positions_on_reconnect: int = 0

    def avg_latency_ms(self) -> float:
        return sum(self._lat) / len(self._lat) if self._lat else 0.0

    def _mark_lat(self, event_ts_ms: int | None):
        self.last_message_ts = time.time()
        if self.on_ws_heartbeat:
            try:
                self.on_ws_heartbeat(self.last_message_ts)
            except Exception:
                pass
        if event_ts_ms:
            try:
                dt = time.time() * 1000 - float(event_ts_ms)
                if 0 < dt < 10_000:
                    self._lat.append(dt)
                    if len(self._lat) > 500:
                        self._lat.pop(0)
            except Exception:
                pass

    def record_pong(self, exchange: str):
        """Ping/Pong yanıtını kaydeder ve Circuit Breaker WS sayacını tazeler."""
        now = time.time()
        self.last_pong_ts[exchange] = now
        self.ping_pong_count += 1
        self._mark_lat(None)

    async def handle_reconnect(self, exchange: str) -> dict:
        """WebSocket kopup yeniden bağlandığında SQLite durumunu okuyarak
        açık pozisyonları ve stop/kâr kilidi seviyelerini anında geri yükler."""
        self.reconnect_count += 1
        self.record_pong(exchange)
        recovered_syms: list[str] = []

        if self.executor is not None and hasattr(self.executor, "restore_state"):
            self.executor.restore_state()
            recovered_syms = list(self.executor.positions.keys())
        elif self.state_store is not None:
            positions = self.state_store.load_positions()
            recovered_syms = list(positions.keys())

        self.recovered_positions_on_reconnect = len(recovered_syms)

        # Yeniden bağlanma anında mevcut fiyatlarla tüm açık pozisyonların stoplarını denetle
        if self.executor is not None and self.executor.positions:
            for sym in list(self.executor.positions.keys()):
                px = self.get_price(sym) or self.executor.last_prices.get(sym)
                if px and px > 0:
                    await self.executor.on_price_tick(sym, px)

        if self.on_reconnect is not None:
            try:
                res = self.on_reconnect(exchange, recovered_syms)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

        return {
            "exchange": exchange,
            "reconnect_count": self.reconnect_count,
            "recovered_symbols": recovered_syms,
            "ping_pong_count": self.ping_pong_count,
        }

    async def _ws_keepalive_task(self, ws, exchange: str):
        """Düzenli Ping/Pong döngüsü: sessiz bağlantıları canlı tutar ve test eder."""
        try:
            while self._running:
                await asyncio.sleep(self.ping_interval_sec)
                if not self._running:
                    break
                if exchange == "okx":
                    # OKX v5 uygulama seviyesi "ping" metin çerçevesi bekler
                    await ws.send("ping")
                else:
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=self.ping_timeout_sec)
                self.record_pong(exchange)
        except asyncio.CancelledError:
            pass
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass

    # -- Binance Spot + BookTicker + 20-Level Depth (@depth20@100ms) -----------
    async def _binance_loop(self):
        import websockets

        streams = []
        for s in self.symbols:
            b = to_binance_stream(s)
            streams.append(f"{b}@aggTrade")
            streams.append(f"{b}@bookTicker")
            streams.append(f"{b}@depth20@100ms")
        url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        rev = {to_binance_stream(s): s for s in self.symbols}
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
                        await self.handle_reconnect("binance")
                    first_connect = False
                    self.record_pong("binance")
                    session_start = time.time()
                    keepalive_task = asyncio.create_task(
                        self._ws_keepalive_task(ws, "binance")
                    )

                    while self._running:
                        if time.time() - session_start >= self.max_session_sec:
                            # 24 saatlik borsa zorunlu kopmasından önce temiz yenileme
                            break
                        raw = await asyncio.wait_for(
                            ws.recv(), timeout=self.recv_timeout_sec
                        )
                        try:
                            msg = json.loads(raw)
                            stream = msg.get("stream", "")
                            d = msg.get("data", {})
                            base = stream.split("@")[0]
                            sym = rev.get(base)
                            if not sym:
                                continue
                            if stream.endswith("@aggTrade"):
                                price = float(d["p"])
                                qty = float(d["q"])
                                self.prices[f"binance:{sym}"] = price
                                self._mark_lat(d.get("T"))
                                if self.on_trade:
                                    await self.on_trade(
                                        "binance", sym, price, qty, bool(d.get("m"))
                                    )
                            elif "@depth20" in stream:
                                raw_bids = d.get("bids") or d.get("b") or []
                                raw_asks = d.get("asks") or d.get("a") or []
                                bids_20 = [
                                    (float(p), float(q)) for p, q in raw_bids[:20]
                                ]
                                asks_20 = [
                                    (float(p), float(q)) for p, q in raw_asks[:20]
                                ]
                                self._mark_lat(None)
                                if bids_20 and asks_20 and self.on_book:
                                    await self.on_book(
                                        "binance", sym, bids_20, asks_20
                                    )
                            elif stream.endswith("@bookTicker"):
                                bid_p, bid_q = float(d["b"]), float(d["q"])
                                ask_p, ask_q = float(d["a"]), float(d["Q"])
                                mid = (bid_p + ask_p) / 2
                                self.prices[f"binance:{sym}"] = mid
                                self.quotes.setdefault(sym, {})["binance"] = (
                                    bid_p,
                                    ask_p,
                                )
                                self._mark_lat(None)
                                if self.on_price:
                                    await self.on_price("binance", sym, mid)
                        except Exception:
                            continue
            except Exception as e:
                print(
                    f"⚠️ Binance WS kopma algılandı ({safe_exception_msg(e)}), "
                    f"SQLite durumu korunarak {self.reconnect_sec}sn içinde yeniden bağlanılıyor...",
                    flush=True,
                )
                await asyncio.sleep(self.reconnect_sec)
            finally:
                if keepalive_task:
                    keepalive_task.cancel()

    # -- Binance Futures Likidasyon (forceOrder) Akışı -------------------------
    async def _binance_liq_loop(self):
        import websockets

        streams = [f"{to_binance_stream(s)}@forceOrder" for s in self.symbols]
        url = f"wss://fstream.binance.com/stream?streams={'/'.join(streams)}"
        rev = {to_binance_stream(s): s for s in self.symbols}
        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=self.ping_interval_sec,
                    ping_timeout=self.ping_timeout_sec,
                    max_size=2 * 1024 * 1024,
                ) as ws:
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                            d = msg.get("data", {}).get("o", {})
                            if not d:
                                continue
                            base = str(d.get("s", "")).lower()
                            sym = rev.get(base)
                            if not sym:
                                continue
                            side = str(d.get("S", "SELL"))
                            price = float(d.get("ap") or d.get("p") or 0)
                            qty = float(d.get("q") or 0)
                            if price > 0 and qty > 0 and self.on_liquidation:
                                await self.on_liquidation(
                                    "binance", sym, side, price, qty
                                )
                        except Exception:
                            continue
            except Exception:
                await asyncio.sleep(self.reconnect_sec * 2)

    # -- OKX -------------------------------------------------------------------
    async def _okx_loop(self):
        import websockets

        url = "wss://ws.okx.com:8443/ws/v5/public"
        args = []
        for s in self.symbols:
            inst = to_okx_inst(s)
            args.append({"channel": "trades", "instId": inst})
            args.append({"channel": "tickers", "instId": inst})
        rev = {to_okx_inst(s): s for s in self.symbols}
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
                        await self.handle_reconnect("okx")
                    first_connect = False
                    self.record_pong("okx")
                    session_start = time.time()
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
                            if msg.get("event") or "data" not in msg:
                                continue
                            sym = rev.get(msg.get("arg", {}).get("instId", ""))
                            if not sym:
                                continue
                            ch = msg.get("arg", {}).get("channel", "")
                            if ch == "trades":
                                for t in msg["data"]:
                                    price = float(t["px"])
                                    qty = float(t["sz"])
                                    self.prices[f"okx:{sym}"] = price
                                    self._mark_lat(t.get("ts"))
                                    buyer_maker = t.get("side") == "sell"
                                    if self.on_trade:
                                        await self.on_trade(
                                            "okx", sym, price, qty, buyer_maker
                                        )
                            elif ch == "tickers":
                                for t in msg["data"]:
                                    price = float(t["last"])
                                    bid_p = float(t.get("bidPx") or price)
                                    ask_p = float(t.get("askPx") or price)
                                    bid_q = float(t.get("bidSz") or 1.0)
                                    ask_q = float(t.get("askSz") or 1.0)
                                    self.prices[f"okx:{sym}"] = price
                                    self.quotes.setdefault(sym, {})["okx"] = (
                                        bid_p,
                                        ask_p,
                                    )
                                    self._mark_lat(t.get("ts"))
                                    if self.on_book:
                                        await self.on_book(
                                            "okx",
                                            sym,
                                            [(bid_p, bid_q)],
                                            [(ask_p, ask_q)],
                                        )
                                    if self.on_price:
                                        await self.on_price("okx", sym, price)
                        except Exception:
                            continue
            except Exception as e:
                print(
                    f"⚠️ OKX WS kopma algılandı ({safe_exception_msg(e)}), "
                    f"SQLite durumu korunarak {self.reconnect_sec}sn içinde yeniden bağlanılıyor...",
                    flush=True,
                )
                await asyncio.sleep(self.reconnect_sec)
            finally:
                if keepalive_task:
                    keepalive_task.cancel()

    async def run_forever(self):
        self._running = True
        tasks = []
        if "binance" in self.exchanges:
            tasks.append(asyncio.create_task(self._binance_loop()))
            if self.on_liquidation:
                tasks.append(asyncio.create_task(self._binance_liq_loop()))
        if "okx" in self.exchanges:
            tasks.append(asyncio.create_task(self._okx_loop()))
        if not tasks:
            return
        await asyncio.gather(*tasks)

    def stop(self):
        self._running = False

    def get_price(self, symbol: str) -> float | None:
        for ex in self.exchanges:
            p = self.prices.get(f"{ex}:{symbol}")
            if p:
                return p
        return None
