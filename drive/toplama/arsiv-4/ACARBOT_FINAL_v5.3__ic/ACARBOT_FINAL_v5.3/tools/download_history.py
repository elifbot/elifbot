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


# ---------------------------------------------------------------------------
# v5.2: HEDEFLI ARALIK INDIRME (iki gecisli 1m stratejisi)
# ---------------------------------------------------------------------------
# v5.1'de 1m veri "--fine-days N" ile yalnızca SON N günden çekiliyordu.
# 90 günlük testte işlemler bu pencereye düşmediği için real_coverage_ratio
# 0.0 çıkıyor ve "1m yol" etiketi gerçek dışı kalıyordu.
#
# Ölçüm: OKX history-candles 1m barı 90+ gün geriye gidiyor. Yani sorun
# verinin yokluğu değil, yanlış yerden istenmesiydi. Çözüm: önce 5m koş,
# sonra YALNIZCA işlem açılan/kapanılan aralıkların 1m'ini indir.

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1H": 3_600_000, "4H": 14_400_000, "1D": 86_400_000,
}


def fetch_okx_range(
    inst_id: str, start_ms: int, end_ms: int, interval: str = "1m",
    max_pages: int = 60, pause: float = 0.0,
):
    """[start_ms, end_ms) aralığındaki mumları indirir (OKX).

    `after` imleci DAHA ESKİ kayıtları getirir; bu yüzden end_ms'ten
    geriye doğru sayfalanır ve start_ms'e ulaşınca durulur.
    """
    if end_ms <= start_ms:
        return []
    rows: list[tuple] = []
    after = str(int(end_ms))
    for _ in range(max_pages):
        params: dict[str, object] = {
            "instId": inst_id, "bar": interval, "limit": 100, "after": after,
        }
        payload = _get(
            "https://www.okx.com/api/v5/market/history-candles?"
            + urlencode(params)
        )
        data = payload.get("data") or []
        if not data:
            break
        for row in data:
            rows.append((int(row[0]), float(row[1]), float(row[2]),
                         float(row[3]), float(row[4]), float(row[5])))
        oldest = min(int(r[0]) for r in data)
        if oldest <= start_ms:
            break
        after = str(oldest)
        if len(data) < 100:
            break
        if pause:
            import time as _t
            _t.sleep(pause)
    unique = _dedupe_sort(rows)
    return [r for r in unique if start_ms <= r[0] < end_ms]


def merge_windows(windows, pad_ms: int = 0):
    """Üst üste binen / bitişik [start,end) aralıklarını birleştirir."""
    if not windows:
        return []
    spans = sorted((int(a) - pad_ms, int(b) + pad_ms) for a, b in windows)
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def fetch_okx_windows(
    inst_id: str, windows, interval: str = "1m", pause: float = 0.0,
    max_requests: int = 400,
):
    """Birden çok aralığın mumlarını indirir, birleştirip sıralar.

    max_requests: toplam sayfa çağrısı tavanı (rate limit koruması).
    Dönüş: (rows, kullanılan_istek_sayısı, kesildi_mi)
    """
    step = INTERVAL_MS.get(interval, 60_000)
    merged = merge_windows(windows)
    rows: list[tuple] = []
    requests = 0
    truncated = False
    for start, end in merged:
        pages = max(1, ((end - start) // step) // 100 + 1)
        if requests + pages > max_requests:
            truncated = True
            break
        chunk = fetch_okx_range(
            inst_id, start, end, interval=interval,
            max_pages=pages, pause=pause,
        )
        requests += pages
        rows.extend(chunk)
        if pause:
            import time as _t
            _t.sleep(pause)
    return _dedupe_sort(rows), requests, truncated


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
