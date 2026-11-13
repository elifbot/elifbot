#!/usr/bin/env python3
"""ACARBOT v3.0 — Gerçek mum verisi indirme aracı (backtest için).

Borsanın PUBLIC uçlarından 5m mum CSV'si indirir; backtest'in beklediği
formatta yazar:  data/<SYMBOL>_5m.csv  →  timestamp,open,high,low,close,volume

Kullanım:
    python tools/download_history.py --exchange okx --symbol BTC-USDT-SWAP \
        --out-symbol BTCUSDT --bars 2000
    python tools/download_history.py --exchange binance --symbol BTCUSDT \
        --bars 1500

Notlar:
  - İstekler imzasızdır (API anahtarı GEREKMEZ).
  - OKX:  GET /api/v5/market/history-candles  (uzun geçmiş; limit 100/istek)
  - Binance: GET /fapi/v1/klines (limit 1500/istek)
  - Mumlar kapanmış mumlardır (forming mum dahil edilmez).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _get(url: str) -> object:
    request = Request(url, headers={"User-Agent": "acarbot-download/3.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _dedupe_sort(rows):
    rows.sort(key=lambda r: r[0])
    unique: dict[int, tuple] = {r[0]: r for r in rows}
    return list(unique.values())


def fetch_okx(inst_id: str, bars: int):
    """OKX history-candles: sayfalama `after` (daha eski) ile yapılır."""
    rows = []
    after = ""
    while len(rows) < bars:
        params: dict[str, object] = {
            "instId": inst_id, "bar": "5m", "limit": 100,
        }
        if after:
            params["after"] = after
        payload = _get(
            "https://www.okx.com/api/v5/market/history-candles?"
            + urlencode(params)
        )
        data = payload.get("data") or []
        if not data:
            break
        for row in data:
            # OKX: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            rows.append((int(row[0]), float(row[1]), float(row[2]),
                         float(row[3]), float(row[4]), float(row[5])))
        after = str(min(int(r[0]) for r in data))
        if len(data) < 100:
            break
    return _dedupe_sort(rows)[-bars:]


def fetch_binance(symbol: str, bars: int):
    rows = []
    end_time = ""
    while len(rows) < bars:
        params: dict[str, object] = {
            "symbol": symbol, "interval": "5m", "limit": 1500,
        }
        if end_time:
            params["endTime"] = end_time
        data = _get(
            "https://fapi.binance.com/fapi/v1/klines?" + urlencode(params)
        )
        if not isinstance(data, list) or not data:
            break
        for row in data:
            rows.append((int(row[0]), float(row[1]), float(row[2]),
                         float(row[3]), float(row[4]), float(row[5])))
        end_time = str(int(row[0]) - 1)
        if len(data) < 1500:
            break
    return _dedupe_sort(rows)[-bars:]


def write_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("timestamp,open,high,low,close,volume\n")
        for ts, o, h, low, c, v in rows:
            handle.write(f"{ts},{o},{h},{low},{c},{v}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerçek 5m mum CSV indirici")
    parser.add_argument("--exchange", choices=("okx", "binance"), default="okx")
    parser.add_argument("--symbol", default="BTC-USDT-SWAP",
                        help="borsa sembolü (OKX: BTC-USDT-SWAP, Binance: BTCUSDT)")
    parser.add_argument("--out-symbol", default=None,
                        help="CSV dosya adı sembolü (varsayılan: tireler/SWAP temizlenir)")
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    out_symbol = args.out_symbol
    if not out_symbol:
        cleaned = args.symbol.upper().replace("-SWAP", "")
        out_symbol = cleaned.replace("-", "")
    fetcher = fetch_okx if args.exchange == "okx" else fetch_binance
    print(f"{args.exchange} {args.symbol}: {args.bars} 5m mum indiriliyor...")
    rows = fetcher(args.symbol, args.bars)
    if len(rows) < 100:
        print(f"HATA: yalnızca {len(rows)} mum geldi", file=sys.stderr)
        return 1
    path = Path(args.data_dir) / f"{out_symbol}_5m.csv"
    write_csv(path, rows)
    span_days = (rows[-1][0] - rows[0][0]) / 86_400_000.0
    print(f"OK: {path} — {len(rows)} mum (~{span_days:.1f} gün)")
    print(f"Backtest: python -m app.main --mode backtest --data-dir {args.data_dir} "
          f"--symbols {out_symbol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
