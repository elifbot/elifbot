from __future__ import annotations

import asyncio
import logging
from collections import Counter

from ..models import Trade

log = logging.getLogger("stream")


def push(queue: asyncio.Queue, stats: Counter, t: Trade) -> None:
    try:
        queue.put_nowait(t)
        stats["trades"] += 1
    except asyncio.QueueFull:
        stats["dropped"] += 1


async def reconnect_forever(name: str, once, stop: asyncio.Event, stats: Counter) -> None:
    """Baglanti kopunca ustel geri cekilme ile yeniden baglanir."""
    delay = 1.0
    while not stop.is_set():
        try:
            await once()
            delay = 1.0
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            stats["reconnects"] += 1
            log.warning("%s baglanti hatasi (%s): %.0f sn sonra yeniden", name, type(e).__name__, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)


def chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]
