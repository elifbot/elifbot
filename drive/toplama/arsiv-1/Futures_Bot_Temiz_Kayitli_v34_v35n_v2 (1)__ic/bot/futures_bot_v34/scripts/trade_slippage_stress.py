#!/usr/bin/env python3
"""Kapanmış işlem CSV'sine giriş/çıkış kayması uygulayan duyarlılık analizi.

Bu bir replay/backtest değildir: aynı işlem miktarını ve işlem yolunu sabit tutar,
yalnızca fill fiyatlarını aleyhte değiştirip ücretleri yeniden hesaplar. Funding
bilinmiyorsa sonuç yine funding hariçtir ve açıkça etiketlenir.

Örnek:
    python3 scripts/trade_slippage_stress.py live_trades.csv --bps 0 5 10 20
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def _funding(row: dict[str, str]) -> tuple[float, str]:
    raw = row.get("funding_fee", "bilinmiyor")
    try:
        value = float(raw)
        return (value, "funding dahil") if math.isfinite(value) else (0.0, "bilinmiyor")
    except (TypeError, ValueError):
        return 0.0, "bilinmiyor"


def stress_trade_rows(rows: list[dict[str, str]], slippage_bps: float) -> dict:
    if not math.isfinite(slippage_bps) or slippage_bps < 0:
        raise ValueError("kayma bps negatif olamaz")
    slip = slippage_bps / 10_000.0
    nets: list[float] = []
    gross_total = fee_total = funding_total = 0.0
    funding_labels: set[str] = set()

    for row in rows:
        side = row["side"].upper()
        if side not in ("LONG", "SHORT"):
            raise ValueError(f"geçersiz yön: {side}")
        qty = float(row["qty_base"])
        entry = float(row["entry_price"])
        exit_ = float(row["exit_price"])
        if qty <= 0 or entry <= 0 or exit_ <= 0:
            raise ValueError("miktar ve fiyatlar pozitif olmalı")
        direction = 1.0 if side == "LONG" else -1.0
        stressed_entry = entry * (1.0 + direction * slip)
        stressed_exit = exit_ * (1.0 - direction * slip)
        entry_rate = float(row["entry_fee"]) / (entry * qty)
        exit_rate = float(row["exit_fee"]) / (exit_ * qty)
        gross = direction * (stressed_exit - stressed_entry) * qty
        fees = stressed_entry * qty * entry_rate + stressed_exit * qty * exit_rate
        funding, label = _funding(row)
        funding_labels.add(label)
        net = gross - fees - funding
        nets.append(net)
        gross_total += gross
        fee_total += fees
        funding_total += funding

    return {
        "trades": len(rows),
        "slippage_bps_per_side": slippage_bps,
        "gross_pnl": round(gross_total, 6),
        "fees": round(fee_total, 6),
        "funding_fee": round(funding_total, 6),
        "funding": ("bilinmiyor" if "bilinmiyor" in funding_labels else "funding dahil"),
        "net_pnl": round(sum(nets), 6),
        "wins": sum(net > 0 for net in nets),
        "win_rate": round(sum(net > 0 for net in nets) / len(nets), 6) if nets else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--bps", type=float, nargs="+", default=[0, 5, 10, 20])
    parser.add_argument("--output", help="JSON çıktısını dosyaya da yaz")
    args = parser.parse_args(argv)
    with Path(args.csv_path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    result = [stress_trade_rows(rows, bps) for bps in args.bps]
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
