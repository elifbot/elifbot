#!/usr/bin/env python3
"""
scripts/make_synthetic_fixture.py

DİKKAT: Bu betik SENTETİK (uydurma) fiyat serisi üretir. Amaç yalnızca
kodun uçtan uca çalıştığını görmektir. Üretilen veri GERÇEK PİYASA VERİSİ
DEĞİLDİR ve hiçbir performans iddiası için kullanılamaz.

Kullanım:
    python scripts/make_synthetic_fixture.py --bars 600 --out data/fixtures/synthetic_btc_1m.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path


def generate(bars: int, seed: int = 42, start_price: float = 60_000.0) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    price = start_price
    ts0 = 1_700_000_000_000
    for i in range(bars):
        # Yavaş trend + sinüzoidal rejim + gürültü (tamamen sentetik).
        drift = 12.0 * math.sin(i / 45.0) + 4.0 * math.sin(i / 7.0)
        shock = rng.gauss(0, 18.0)
        open_p = price
        close_p = max(1.0, open_p + drift + shock)
        high_p = max(open_p, close_p) + abs(rng.gauss(0, 9.0))
        low_p = min(open_p, close_p) - abs(rng.gauss(0, 9.0))
        low_p = max(0.01, low_p)
        volume = max(0.0001, abs(rng.gauss(120, 45)))
        rows.append(
            {
                "open_time": ts0 + i * 60_000,
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": round(volume, 4),
            }
        )
        price = close_p
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=600)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/fixtures/synthetic_btc_1m.csv")
    args = ap.parse_args()

    rows = generate(args.bars, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["open_time", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"SENTETİK veri yazıldı: {out} ({len(rows)} mum) — gerçek piyasa verisi DEĞİLDİR.")


if __name__ == "__main__":
    main()
