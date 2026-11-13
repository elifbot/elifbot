"""Canli calistirici: akis -> kuyruk -> motor. mode=paper iken sanal emir, testnet/live iken ccxt."""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections import Counter

from .alerts import Alerter
from .brokers.paper import PaperBroker
from .config import Config
from .engine import Engine
from .safety import SafetyMonitor
from .storage import Storage
from .streams.common import chunks
from .universe import binance_universe, okx_universe

log = logging.getLogger("app")
BINANCE_CHUNK, OKX_CHUNK = 150, 100


async def _universes(cfg: Config):
    out = {}
    for ex, ec in cfg.exchanges.items():
        if not ec.enabled:
            continue
        out[ex] = await (binance_universe(ec) if ex == "binance" else okx_universe(ec))
    return out


async def run_universe(cfg: Config) -> int:
    for ex, u in (await _universes(cfg)).items():
        syms = u if isinstance(u, list) else u[0]
        print(f"{ex}: {len(syms)} sembol  (ilk 10: {', '.join(syms[:10])})")
    return 0


def _make_broker(ex: str, cfg: Config, safety: SafetyMonitor):
    ec = cfg.exchanges[ex]
    if cfg.mode == "paper":
        return PaperBroker(ex, cfg, ec, lambda k, p: None)
    from .brokers.ccxt_broker import CcxtBroker
    return CcxtBroker(ex, cfg, ec, safety, sandbox=(cfg.mode == "testnet"))


async def run_bot(cfg: Config) -> int:
    from .streams import binance as bstream, okx as ostream
    alerter, storage, safety = Alerter(), Storage(cfg.storage.path), SafetyMonitor(cfg.safety)
    brokers = {ex: _make_broker(ex, cfg, safety) for ex, ec in cfg.exchanges.items() if ec.enabled}
    engine = Engine(cfg, brokers, alerter, storage, safety)
    for b in brokers.values():
        await b.startup()

    universes = await _universes(cfg)
    total = sum(len(u if isinstance(u, list) else u[0]) for u in universes.values())
    queue: asyncio.Queue = asyncio.Queue(maxsize=300_000)
    stats: Counter = Counter()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:   # Windows
            pass

    tasks = []
    for ex, u in universes.items():
        if ex == "binance":
            for i, part in enumerate(chunks(u, BINANCE_CHUNK)):
                tasks.append(asyncio.create_task(bstream.run_chunk(i, part, queue, stats, stop)))
        else:
            syms, ctval = u
            for i, part in enumerate(chunks(syms, OKX_CHUNK)):
                tasks.append(asyncio.create_task(ostream.run_chunk(i, part, ctval, queue, stats, stop)))

    async def consume() -> None:
        while not stop.is_set():
            try:
                engine.on_trade(await asyncio.wait_for(queue.get(), timeout=1.0))
            except asyncio.TimeoutError:
                continue
            for _ in range(5000):
                try:
                    engine.on_trade(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            await asyncio.sleep(0)

    async def evaluate() -> None:
        errors = 0
        while not stop.is_set():
            t0 = time.time()
            try:
                lag = queue.qsize()
                if lag > 100_000 and ("*", "queue_lag") not in safety.halts:
                    await alerter.send(safety.halt("*", "queue_lag", f"islem kuyrugu doldu ({lag})", manual=False))
                elif lag < 1_000 and ("*", "queue_lag") in safety.halts:
                    safety.resume("*", "queue_lag")
                await engine.evaluate(time.time())
                errors = 0
            except Exception:  # noqa: BLE001
                errors += 1
                log.exception("evaluate hatasi (%d)", errors)
                if errors >= 5:
                    await alerter.send(safety.halt("*", "engine_error", "motor art arda hata verdi", manual=True))
            await asyncio.sleep(max(0.0, cfg.scanner.eval_interval_sec - (time.time() - t0)))

    async def report() -> None:
        while not stop.is_set():
            await asyncio.sleep(cfg.alerts.summary_interval_min * 60)
            await alerter.send("OZET\n" + engine.summary() + f"\nveri: {stats['trades']} islem, "
                               f"{stats['dropped']} dusen, {stats['reconnects']} yeniden baglanma")

    tasks += [asyncio.create_task(consume()), asyncio.create_task(evaluate()), asyncio.create_task(report())]
    await alerter.send(f"Bot basladi | mod={cfg.mode} | borsalar={','.join(brokers)} | {total} coin taraniyor")
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await alerter.send("Bot durduruldu.\n" + engine.summary())
    if cfg.mode != "paper":
        await alerter.send("Not: Acik pozisyonlar borsadaki stop emirleriyle korunur; bot kapaninca kapatilmaz.")
    storage.close()
    return 0
