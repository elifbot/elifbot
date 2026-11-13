"""Binance USDT-M futures aggTrade akisi.
DOGRULAYIN: websocket adresi/limitleri Binance dokumanlarindan guncel kontrol edilmelidir."""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from ..models import Trade
from ..universe import base_of, canon
from .common import push, reconnect_forever

WS_BASE = "wss://fstream.binance.com/stream?streams="


async def run_chunk(idx: int, symbols: list[str], queue: asyncio.Queue, stats: Counter, stop: asyncio.Event) -> None:
    import websockets
    names = "/".join(f"{base_of(s).lower()}usdt@aggTrade" for s in symbols)

    async def once() -> None:
        async with websockets.connect(WS_BASE + names, ping_interval=20, ping_timeout=30,
                                      max_queue=None, open_timeout=15) as ws:
            async for raw in ws:
                m = json.loads(raw)
                d = m.get("data", m)
                if d.get("e") != "aggTrade":
                    continue
                p, q = float(d["p"]), float(d["q"])
                push(queue, stats, Trade("binance", canon(d["s"][:-4]), d["T"] / 1000.0, p, p * q, not d["m"]))

    await reconnect_forever(f"binance#{idx}", once, stop, stats)
