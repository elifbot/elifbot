"""Faz 1 veri bütçesi: indirme hacmi, süre ve disk tahmini (ÇEVRİMDIŞI).

12 ay x 30-50 sembol veri indirmeden önce ne kadar mum / disk / istek
gerektiğini hesaplar. Ağa çıkmaz, dosya yazmaz.

Kullanım:
    python -m tools.data_budget --symbols 50 --months 12 --intervals 5m,1m
    python -m tools.data_budget --symbols 40 --months 12 --intervals 5m --json

Varsayımlar (ölçülmeden önce TAHMİNDİR; --bytes-per-row ile değiştirilir):
  * CSV satırı ~58 bayt (ts,open,high,low,close,volume)
  * gzip sıkıştırma oranı ~0.28
  * Sayfalama: istek başına 100 mum (OKX history-candles üst sınırı) ve
    istek başına ~0.25 sn bekleme (rate limit payı)
"""

from __future__ import annotations

import argparse
import json
import sys

INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440,
}
DAYS_PER_MONTH = 365.0 / 12.0


def estimate(
    symbols: int,
    months: float,
    intervals: tuple[str, ...],
    bytes_per_row: int = 58,
    gzip_ratio: float = 0.28,
    page_size: int = 100,
    seconds_per_request: float = 0.25,
) -> dict:
    if symbols <= 0 or months <= 0:
        raise ValueError("symbols ve months pozitif olmalı")
    if page_size <= 0 or seconds_per_request < 0:
        raise ValueError("page_size pozitif, seconds_per_request >= 0 olmalı")
    days = months * DAYS_PER_MONTH
    rows: list[dict] = []
    total_candles = 0
    for interval in intervals:
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"bilinmeyen aralık: {interval}")
        per_symbol = int(days * 1440 / INTERVAL_MINUTES[interval])
        candles = per_symbol * symbols
        requests = -(-candles // page_size)  # tavan bölme
        raw_bytes = candles * bytes_per_row
        rows.append({
            "interval": interval,
            "candles_per_symbol": per_symbol,
            "candles": candles,
            "requests": requests,
            "download_minutes": round(requests * seconds_per_request / 60, 1),
            "csv_mb": round(raw_bytes / 1e6, 1),
            "gzip_mb": round(raw_bytes * gzip_ratio / 1e6, 1),
        })
        total_candles += candles
    return {
        "symbols": symbols,
        "months": months,
        "intervals": rows,
        "total_candles": total_candles,
        "total_requests": sum(r["requests"] for r in rows),
        "total_download_hours": round(
            sum(r["download_minutes"] for r in rows) / 60, 2),
        "total_csv_mb": round(sum(r["csv_mb"] for r in rows), 1),
        "total_gzip_mb": round(sum(r["gzip_mb"] for r in rows), 1),
        "assumptions": {
            "bytes_per_row": bytes_per_row,
            "gzip_ratio": gzip_ratio,
            "page_size": page_size,
            "seconds_per_request": seconds_per_request,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Faz 1 veri bütçesi tahmini")
    parser.add_argument("--symbols", type=int, default=50)
    parser.add_argument("--months", type=float, default=12.0)
    parser.add_argument("--intervals", default="5m",
                        help="virgülle ayrılmış: 1m,5m,15m,1h ...")
    parser.add_argument("--bytes-per-row", type=int, default=58)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--seconds-per-request", type=float, default=0.25)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    intervals = tuple(x.strip() for x in args.intervals.split(",") if x.strip())
    try:
        result = estimate(
            args.symbols, args.months, intervals,
            bytes_per_row=args.bytes_per_row,
            page_size=args.page_size,
            seconds_per_request=args.seconds_per_request,
        )
    except ValueError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"{result['symbols']} sembol x {result['months']:g} ay")
    for row in result["intervals"]:
        print(
            f"  {row['interval']:>4}: {row['candles']:>12,} mum | "
            f"{row['requests']:>9,} istek | ~{row['download_minutes']:g} dk | "
            f"CSV {row['csv_mb']:g} MB | gzip {row['gzip_mb']:g} MB"
        )
    print(
        f"TOPLAM: {result['total_candles']:,} mum, {result['total_requests']:,} "
        f"istek, ~{result['total_download_hours']:g} saat, "
        f"CSV {result['total_csv_mb']:g} MB, gzip {result['total_gzip_mb']:g} MB"
    )
    print("Not: tahmindir (varsayımlar --json çıktısında); gerçek süre rate limit'e bağlıdır.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
