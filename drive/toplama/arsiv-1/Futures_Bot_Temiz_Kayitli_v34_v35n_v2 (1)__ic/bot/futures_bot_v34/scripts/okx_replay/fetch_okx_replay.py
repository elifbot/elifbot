#!/usr/bin/env python3
"""OKX sinyal sembollerinin ham trades + 1m mum geçmişini nedensel replay için indir."""
from __future__ import annotations
import csv, json, os, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT
OUT = ROOT / "reports" / "okx_replay_raw"
OUT.mkdir(exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "flow-research/1.0"})
OKX_INSTRUMENTS = "https://www.okx.com/api/v5/public/instruments"
OKX_HISTORY_TRADES = "https://www.okx.com/api/v5/market/history-trades"
OKX_HISTORY_CANDLES = "https://www.okx.com/api/v5/market/history-candles"


def get(url, **params):
    for attempt in range(6):
        try:
            r = S.get(url, params=params, timeout=25)
            j = r.json()
            if r.status_code == 200 and j.get("code") == "0":
                return j.get("data", [])
            print("API_RETRY", url, r.status_code, j.get("code"), j.get("msg"))
        except Exception as exc:
            print("API_RETRY", url, type(exc).__name__, str(exc)[:120])
        time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"OKX verisi alınamadı: {url} {params}")


with open(BOT / "logs/ws_akis_sinyal.csv", newline="", encoding="utf-8") as f:
    signals = [r for r in csv.DictReader(f)
               if r["exchange"] == "okx" and r["durum"] == "acildi"]
by_symbol = {}
for r in signals:
    by_symbol.setdefault(r["symbol"], []).append(r)

instruments = get(OKX_INSTRUMENTS, instType="SWAP")
ct = {i["instId"]: float(i["ctVal"]) * float(i.get("ctMult") or 1)
      for i in instruments if i.get("settleCcy") == "USDT"}
manifest = []
for n, (symbol, rows) in enumerate(sorted(by_symbol.items()), 1):
    # ISO zamanı datetime ile UTC'ye çevir (yerel saat kullanma).
    from datetime import datetime, timezone
    ts_values = [int(datetime.strptime(r["ts_utc"], "%Y-%m-%d %H:%M:%S.%f")
                     .replace(tzinfo=timezone.utc).timestamp() * 1000) for r in rows]
    hedef = min(ts_values) - 90_000
    trades = {}
    after = None
    oldest = None
    pages = 0
    while True:
        params = {"instId": symbol, "limit": 100}
        if after is not None:
            params["after"] = after
        data = get(OKX_HISTORY_TRADES, **params)
        pages += 1
        if not data:
            break
        for x in data:
            trades[x["tradeId"]] = x
        oldest = min(int(x["ts"]) for x in data)
        if oldest <= hedef or len(data) < 100 or pages >= 100:
            break
        after = data[-1]["tradeId"]
        time.sleep(0.11)  # resmi 20 istek / 2 sn limitinin altında
    ordered = sorted(trades.values(), key=lambda x: (int(x["ts"]), int(x["tradeId"])))
    # 1m mumlar: son 100 bar test penceresinden çok daha geniş; yine de kapsama yazılır.
    candles = get(OKX_HISTORY_CANDLES, instId=symbol, bar="1m", limit=100)
    payload = {"symbol": symbol, "contract_multiplier": ct.get(symbol),
               "target_oldest_ms": hedef, "pages": pages,
               "trades": ordered, "candles": candles}
    with open(OUT / f"{symbol.replace('/', '_')}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    coverage = bool(ordered and int(ordered[0]["ts"]) <= hedef and ct.get(symbol))
    rec = {"symbol": symbol, "signals": len(rows), "trades": len(ordered),
           "pages": pages, "oldest_ms": int(ordered[0]["ts"]) if ordered else None,
           "newest_ms": int(ordered[-1]["ts"]) if ordered else None,
           "target_oldest_ms": hedef, "coverage_ok": coverage,
           "candles": len(candles), "contract_multiplier": ct.get(symbol)}
    manifest.append(rec)
    print(f"{n:02d}/{len(by_symbol)} {symbol:<22} trades={len(ordered):5} pages={pages:2} "
          f"coverage={coverage} oldest={rec['oldest_ms']} target={hedef}")
    time.sleep(0.11)

with open(OUT / "manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("TAMAM", len(manifest), "sembol", sum(x["trades"] for x in manifest), "işlem",
      "kapsama", sum(x["coverage_ok"] for x in manifest), "/", len(manifest))
