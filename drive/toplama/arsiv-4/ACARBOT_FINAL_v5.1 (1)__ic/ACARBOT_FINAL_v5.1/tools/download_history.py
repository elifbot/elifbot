#!/usr/bin/env python3
"""ACARBOT v3.0/v4.0 — Gerçek mum + funding verisi indirme aracı (backtest).

Borsanın PUBLIC uçlarından 5m mum CSV'si indirir; backtest'in beklediği
formatta yazar:  data/<SYMBOL>_5m.csv  →  timestamp,open,high,low,close,volume

v4.0 (--funding): tarihsel FUNDING ORANI geçmişi de indirir:
  data/<SYMBOL>_funding.csv  →  timestamp,rate
Backtest motoru bu dosyayı görürse sabit varsayılan oran yerine GERÇEK
geçmiş oranları uygular (madde 23: tarihsel funding verisi).

Kullanım:
    python tools/download_history.py --exchange okx --symbol BTC-USDT-SWAP \
        --out-symbol BTCUSDT --bars 2000 --funding
    python tools/download_history.py --exchange binance --symbol BTCUSDT \
        --bars 1500 --funding

Notlar:
  - İstekler imzasızdır (API anahtarı GEREKMEZ).
  - OKX:  GET /api/v5/market/history-candles  (uzun geçmiş; limit 100/istek)
  - Binance: GET /fapi/v1/klines (limit 1500/istek)
  - Funding: OKX /api/v5/public/funding-rate-history (100/istek);
    Binance /fapi/v1/fundingRate (1000/istek)
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


def fetch_okx(inst_id: str, bars: int, interval: str = "5m"):
    """OKX history-candles: sayfalama `after` (daha eski) ile yapılır.

    v5.1: `interval` parametresi eklendi — mum içi yol modeli için 1m
    alt çözünürlük indirilebilir ("1m", "5m", "15m", "1H" ...).
    """
    rows = []
    after = ""
    while len(rows) < bars:
        params: dict[str, object] = {
            "instId": inst_id, "bar": interval, "limit": 100,
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


def fetch_binance(symbol: str, bars: int, interval: str = "5m"):
    """v5.1: interval parametresi. NOT: fapi bu bölgeden 451 dönebilir;
    o durumda OKX kaynağı kullanılmalıdır."""
    rows = []
    end_time = ""
    while len(rows) < bars:
        params: dict[str, object] = {
            "symbol": symbol, "interval": interval, "limit": 1500,
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


# ---------------------------------------------------------------------------
# v4.0: tarihsel funding geçmişi (madde 23)
# ---------------------------------------------------------------------------

def fetch_funding_okx(inst_id: str, periods: int):
    """OKX funding-rate-history: sayfalama `after` (daha eski) ile."""
    rows = []
    after = ""
    while len(rows) < periods:
        params: dict[str, object] = {"instId": inst_id, "limit": 100}
        if after:
            params["after"] = after
        payload = _get(
            "https://www.okx.com/api/v5/public/funding-rate-history?"
            + urlencode(params)
        )
        data = payload.get("data") or []
        if not data:
            break
        for row in data:
            rows.append((int(row["fundingTime"]), float(row["fundingRate"])))
        after = str(min(int(r["fundingTime"]) for r in data))
        if len(data) < 100:
            break
    return _dedupe_sort(rows)[-periods:]


def fetch_funding_binance(symbol: str, periods: int):
    """Binance /fapi/v1/fundingRate: sayfalama endTime ile geriye."""
    rows = []
    end_time = ""
    while len(rows) < periods:
        params: dict[str, object] = {"symbol": symbol, "limit": 1000}
        if end_time:
            params["endTime"] = end_time
        data = _get(
            "https://fapi.binance.com/fapi/v1/fundingRate?" + urlencode(params)
        )
        if not isinstance(data, list) or not data:
            break
        for row in data:
            rows.append((int(row["fundingTime"]), float(row["fundingRate"])))
        end_time = str(min(int(r["fundingTime"]) for r in data) - 1)
        if len(data) < 1000:
            break
    return _dedupe_sort(rows)[-periods:]


def write_funding_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("timestamp,rate\n")
        for ts, rate in rows:
            handle.write(f"{ts},{rate}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerçek 5m mum + funding CSV indirici")
    parser.add_argument("--exchange", choices=("okx", "binance"), default="okx")
    parser.add_argument("--symbol", default="BTC-USDT-SWAP",
                        help="borsa sembolü (OKX: BTC-USDT-SWAP, Binance: BTCUSDT)")
    parser.add_argument("--out-symbol", default=None,
                        help="CSV dosya adı sembolü (varsayılan: tireler/SWAP temizlenir)")
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--funding-periods", type=int, default=90,
                        help="v4.0: --funding ile indirilecek funding dönem sayısı "
                             "(8 saatlik dönem; 90 ≈ 30 gün)")
    parser.add_argument("--funding", action="store_true",
                        help="v4.0: tarihsel funding geçmişini de indir "
                             "(data/<SYM>_funding.csv; backtest gerçek oranları kullanır)")
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
    if args.funding:
        funding_fetcher = (
            fetch_funding_okx if args.exchange == "okx"
            else fetch_funding_binance
        )
        print(f"{args.exchange} {args.symbol}: {args.funding_periods} funding "
              "dönemi indiriliyor...")
        try:
            f_rows = funding_fetcher(args.symbol, args.funding_periods)
        except Exception as exc:  # noqa: BLE001
            print(f"UYARI: funding indirilemedi ({exc}) — backtest varsayılan "
                  "oranla sürer", file=sys.stderr)
            f_rows = []
        if f_rows:
            f_path = Path(args.data_dir) / f"{out_symbol}_funding.csv"
            write_funding_csv(f_path, f_rows)
            f_days = (f_rows[-1][0] - f_rows[0][0]) / 86_400_000.0
            print(f"OK: {f_path} — {len(f_rows)} dönem (~{f_days:.1f} gün, "
                  "GERÇEK oranlar)")
        else:
            print("UYARI: funding verisi boş — backtest varsayılan oranla sürer",
                  file=sys.stderr)
    print(f"Backtest: python -m app.main --mode backtest --data-dir {args.data_dir} "
          f"--symbols {out_symbol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
