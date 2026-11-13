"""OKX swap 'trades' kanali. Abonelik/baglanti limitleri icin OKX dokumanina bakin; parcalar kucuk tutuldu."""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from ..models import Trade
from ..universe import base_of, canon
from .common import push, reconnect_forever

WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


async def run_chunk(idx: int, symbols: list[str], ctval: dict[str, float], queue: asyncio.Queue,
                    stats: Counter, stop: asyncio.Event) -> None:
    import websockets
    args = [{"channel": "trades", "instId": f"{base_of(s)}-USDT-SWAP"} for s in symbols]

    async def once() -> None:
        async with websockets.connect(WS_URL, ping_interval=None, max_queue=None, open_timeout=15) as ws:
            for i in range(0, len(args), 50):
                await ws.send(json.dumps({"op": "subscribe", "args": args[i:i + 50]}))
                await asyncio.sleep(0.5)
            awaiting_pong = False
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=20)
                except asyncio.TimeoutError:
                    if awaiting_pong:
                        raise ConnectionError("pong gelmedi")
                    await ws.send("ping")
                    awaiting_pong = True
                    continue
                awaiting_pong = False
                if raw == "pong":
                    continue
                m = json.loads(raw)
                if m.get("arg", {}).get("channel") != "trades" or "data" not in m:
                    continue
                for d in m["data"]:
                    sym = canon(d["instId"].split("-")[0])
                    px, sz = float(d["px"]), float(d["sz"])
                    usd = px * sz * ctval.get(sym, 1.0)
                    push(queue, stats, Trade("okx", sym, int(d["ts"]) / 1000.0, px, usd, d["side"] == "buy"))

    await reconnect_forever(f"okx#{idx}", once, stop, stats)
