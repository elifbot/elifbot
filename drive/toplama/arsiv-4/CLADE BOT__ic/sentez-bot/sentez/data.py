"""Veri: CSV okuma/yazma, doğrulama, sentetik üretici ve Binance KAMU klines (anahtar gerekmez)."""
from __future__ import annotations

import csv
import json
import math
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Bar

INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
               "1h": 3_600_000, "4h": 14_400_000}


def _parse_ts(x: str) -> int:
    x = x.strip()
    if x.replace(".", "", 1).isdigit():
        v = float(x)
        return int(v if v > 1e11 else v * 1000)           # saniye veya ms
    dt = datetime.fromisoformat(x.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def validate_bars(bars: list[Bar], bar_ms: int) -> tuple[list[Bar], dict[str, int]]:
    """Bozuk mumları atar, sıralar, tekrarları kaldırır. Boşlukları SAYAR ama doldurmaz (uydurma yok)."""
    issues = {"bad": 0, "dup": 0, "gaps": 0}
    good: list[Bar] = []
    for b in sorted(bars, key=lambda b: b.ts):
        vals = (b.open, b.high, b.low, b.close, b.volume)
        if (not all(math.isfinite(x) for x in vals) or b.low > b.high or b.volume < 0
                or b.low > min(b.open, b.close) or b.high < max(b.open, b.close) or b.close <= 0):
            issues["bad"] += 1
            continue
        if good and b.ts == good[-1].ts:
            issues["dup"] += 1
            continue
        if good and b.ts - good[-1].ts > bar_ms * 1.5:
            issues["gaps"] += 1
        good.append(b)
    return good, issues


def load_csv(path: str | Path) -> list[Bar]:
    """Başlıklı CSV: timestamp,open,high,low,close,volume (ts: ms/sn/ISO)."""
    out: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            r = {k.strip().lower(): v for k, v in row.items()}
            try:
                out.append(Bar(_parse_ts(r.get("timestamp") or r.get("ts") or r["time"]),
                               float(r["open"]), float(r["high"]), float(r["low"]),
                               float(r["close"]), float(r.get("volume", 0) or 0)))
            except (KeyError, ValueError):
                continue                                     # bozuk satır atlanır, uydurulmaz
    return out


def save_csv(path: str | Path, bars: list[Bar]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.ts, b.open, b.high, b.low, b.close, b.volume])


def load_csv_dir(directory: str | Path) -> dict[str, list[Bar]]:
    return {p.stem.upper(): load_csv(p) for p in sorted(Path(directory).glob("*.csv"))}


# ----------------------------------------------------------------------------- sentetik
def synthetic(n_bars: int = 3000, n_symbols: int = 8, seed: int = 7, bar_ms: int = 900_000,
              start_ms: int = 1_700_000_000_000, sigma: float = 0.0025
              ) -> dict[str, list[Bar]]:
    """Rejim değiştiren (yükseliş/düşüş/yatay) sentetik piyasa.

    YALNIZ boru hattını denemek içindir. Sonuçları gerçek piyasa hakkında hiçbir şey söylemez.
    Aynı seed her zaman aynı veriyi üretir.
    """
    rng = random.Random(seed)
    regimes = [(+0.0004, 1.0), (-0.0004, 1.0), (0.0, 0.7)]    # (drift/mum, vol çarpanı)
    state = 2
    market: list[tuple[float, float]] = []
    for _ in range(n_bars):
        if rng.random() > 0.985:
            state = rng.randrange(3)
        d, vm = regimes[state]
        market.append((d + rng.gauss(0, sigma * vm * 0.6), vm))
    out: dict[str, list[Bar]] = {}
    for si in range(n_symbols):
        beta = 0.6 + 0.8 * rng.random()
        px = 10 ** rng.uniform(0.5, 3.5)
        base_vol = 10 ** rng.uniform(3, 5)
        bars: list[Bar] = []
        for i in range(n_bars):
            m, vm = market[i]
            r = beta * m + rng.gauss(0, sigma * vm * 0.8)
            o, c = px, px * math.exp(r)
            h = max(o, c) * (1 + abs(rng.gauss(0, sigma * 0.4)))
            l = min(o, c) * (1 - abs(rng.gauss(0, sigma * 0.4)))
            v = base_vol * (1 + 25 * abs(r) / sigma * 0.1) * math.exp(rng.gauss(0, 0.3))
            bars.append(Bar(start_ms + i * bar_ms, o, h, l, c, v))
            px = c
        out[f"SYN{si + 1}USDT"] = bars
    return out


# ----------------------------------------------------------------------------- Binance (kamu)
BINANCE = "https://fapi.binance.com"


def _get_json(url: str, timeout: float = 15.0, retries: int = 4):
    last: Optional[Exception] = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sentez-bot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            time.sleep(min(8.0, 0.5 * 2 ** k))
    raise RuntimeError(f"istek başarısız: {url} ({last})")


def parse_klines(payload) -> list[Bar]:
    """Binance klines → Bar. Bozuk satır atlanır."""
    out: list[Bar] = []
    for row in payload or []:
        try:
            out.append(Bar(int(row[0]), float(row[1]), float(row[2]), float(row[3]),
                           float(row[4]), float(row[5])))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def fetch_binance(symbol: str, interval: str = "15m", bars: int = 3000) -> list[Bar]:
    """Geçmiş mumları sayfalayarak çeker (1500'lük istekler). Yalnız kamu ucu."""
    ms = INTERVAL_MS[interval]
    end = int(time.time() * 1000)
    out: list[Bar] = []
    while len(out) < bars:
        lim = min(1500, bars - len(out))
        url = f"{BINANCE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={lim}&endTime={end}"
        chunk = parse_klines(_get_json(url))
        if not chunk:
            break
        out = chunk + out
        end = chunk[0].ts - 1
        time.sleep(0.15)
    # son (oluşmakta olan) mumu at
    now = int(time.time() * 1000)
    if out and out[-1].ts + ms > now:
        out = out[:-1]
    return out[-bars:]


def top_symbols(n: int = 12, min_quote_vol: float = 20_000_000) -> list[str]:
    """24s quote hacmine göre en likit USDT perpetual sembolleri (kamu ucu)."""
    rows = _get_json(f"{BINANCE}/fapi/v1/ticker/24hr")
    cand = [(float(r["quoteVolume"]), r["symbol"]) for r in rows
            if r.get("symbol", "").endswith("USDT") and "_" not in r["symbol"]
            and float(r.get("quoteVolume", 0)) >= min_quote_vol]
    return [s for _, s in sorted(cand, reverse=True)[:n]]
