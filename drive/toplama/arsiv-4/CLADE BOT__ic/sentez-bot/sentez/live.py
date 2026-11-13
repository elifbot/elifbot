"""Canlı PAPER koşucusu: Binance KAMU klines'ı yoklar, aynı motoru kullanır. Gerçek emir YOK.

Her yoklamada yeni KAPANMIŞ mumlar sembol geçmişine eklenir ve zaman sırasıyla motora verilir.
Sinyal mum kapanışında üretilir, giriş bir sonraki kapanmış mumun AÇILIŞ fiyatından dolar;
bu, backtest ile birebir aynı semantiktir (bu yüzden gerçek giriş ~1 mum gecikmeli kaydedilir).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from .data import INTERVAL_MS, fetch_binance, parse_klines, _get_json, BINANCE
from .engine import Engine
from .models import Bar, Config
from .report import attribution, metrics, render_markdown
from .signals import RollingSource

WARMUP_BARS = 400


def closed_bars(symbol: str, interval: str, limit: int = 5) -> list[Bar]:
    ms = INTERVAL_MS[interval]
    rows = parse_klines(_get_json(f"{BINANCE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"))
    now = int(time.time() * 1000)
    return [b for b in rows if b.ts + ms <= now]


def run_live(symbols: list[str], cfg: Config, interval: str, out: Path, minutes: float,
             log: Callable[[str], None] = print,
             fetch_history: Callable[[str, str, int], list[Bar]] = fetch_binance,
             fetch_recent: Callable[[str, str, int], list[Bar]] = closed_bars,
             sleep: Callable[[float], None] = time.sleep) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    events = open(out / "events.jsonl", "a", encoding="utf-8")

    def on_event(kind: str, payload: dict) -> None:
        events.write(json.dumps({"kind": kind, **payload}, ensure_ascii=False) + "\n")
        events.flush()
        if kind in ("open", "close"):
            log(f"[{kind}] {payload}")

    history: dict[str, list[Bar]] = {}
    for s in symbols:
        history[s] = fetch_history(s, interval, WARMUP_BARS)
        log(f"{s}: {len(history[s])} mum yüklendi")
    source = RollingSource(history, cfg)
    eng = Engine(cfg, source, on_event)
    seen = {s: (h[-1].ts if h else 0) for s, h in history.items()}
    deadline = time.time() + minutes * 60
    poll = max(20.0, INTERVAL_MS[interval] / 1000 / 6)
    while time.time() < deadline:
        new: dict[int, dict[str, Bar]] = {}
        for s in symbols:
            try:
                for b in fetch_recent(s, interval, 5):
                    if b.ts > seen[s]:
                        history[s].append(b)
                        seen[s] = b.ts
                        new.setdefault(b.ts, {})[s] = b
            except RuntimeError as e:
                log(f"{s}: veri alınamadı ({e}); bu turda sinyal üretilmez")
        for ts in sorted(new):
            eng.step(ts, new[ts])
        sleep(poll)
    last = {s: h[-1] for s, h in history.items() if h}
    eng.finish(last, max(seen.values()) if seen else 0)
    events.close()
    m = metrics(eng.trades, eng.equity_curve, cfg)
    (out / "SONUC.json").write_text(json.dumps({"metrics": m, "stats": dict(eng.stats),
                                                "trades": [t.__dict__ for t in eng.trades]},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "RAPOR.md").write_text(render_markdown(
        "SENTEZ canlı PAPER", {"semboller": len(symbols), "aralık": interval, "dakika": minutes},
        m, attribution(eng.trades), dict(eng.stats), eng.breaker.trips), encoding="utf-8")
    return m
