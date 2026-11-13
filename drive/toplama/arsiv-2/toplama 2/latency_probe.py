"""Davranışı değiştirmeyen gecikme probu.

Metotları zamanlayıcıyla sarar (dönüş değeri/istisna aynen geçer) ve her saniye
tek satır JSONL yazar: çağrı sayısı, toplam ms, maks ms, event-loop gecikmesi,
açık pozisyon sayısı. Karar/filtre/stop mantığına dokunmaz.

Kullanım (live_runner.py -> run() içinde, görevler başlamadan hemen önce):
    import latency_probe
    probe_task = latency_probe.start(self)

Not: async metotların süresi await noktalarındaki bekleme dahil duvar süresidir.
Senkron metotlar (SQLite, features, market_context) için süre = loop'u bloke eden süre.
"""
import asyncio
import functools
import json
import time

_AGG: dict[str, list[float]] = {}


def _rec(name: str, dt: float) -> None:
    a = _AGG.get(name)
    if a is None:
        _AGG[name] = [1, dt, dt]
    else:
        a[0] += 1
        a[1] += dt
        if dt > a[2]:
            a[2] = dt


def _wrap(obj, attr: str, name: str | None = None) -> None:
    fn = getattr(obj, attr)
    key = name or attr
    if asyncio.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def w(*a, **k):
            t = time.perf_counter()
            try:
                return await fn(*a, **k)
            finally:
                _rec(key, time.perf_counter() - t)
    else:
        @functools.wraps(fn)
        def w(*a, **k):
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                _rec(key, time.perf_counter() - t)
    setattr(obj, attr, w)


async def _flush(runner, path: str, period: float = 0.05) -> None:
    worst = 0.0
    next_flush = time.monotonic() + 1.0
    with open(path, "a", buffering=1, encoding="utf-8") as fh:
        while not runner.stop_Flag:
            t = time.monotonic()
            await asyncio.sleep(period)
            worst = max(worst, time.monotonic() - t - period)
            if time.monotonic() >= next_flush:
                row = {
                    "epoch": round(time.time(), 3),
                    "loop_lag_max_ms": round(worst * 1000, 1),
                    "open_positions": len(runner.executor.positions),
                }
                for k, (n, tot, mx) in _AGG.items():
                    row[k] = {"n": int(n), "total_ms": round(tot * 1000, 1), "max_ms": round(mx * 1000, 1)}
                _AGG.clear()
                worst = 0.0
                fh.write(json.dumps(row) + "\n")
                next_flush = time.monotonic() + 1.0


def start(runner, path: str = "latency_probe.jsonl") -> asyncio.Task:
    ex, en = runner.executor, runner.engine
    _wrap(ex, "on_price_tick")
    _wrap(en, "on_trade")
    stores = {id(s): s for s in (getattr(ex, "state_store", None), getattr(runner, "store", None)) if s is not None}
    for s in stores.values():
        for m in ("update_paper_risk_if_unchanged", "acquire_writer_lease"):
            if hasattr(s, m):
                _wrap(s, m)
    import src.v94_live_router as router  # features/market_context burada isimle aranıyor
    _wrap(router, "features")
    _wrap(router, "market_context")
    return asyncio.create_task(_flush(runner, path))
