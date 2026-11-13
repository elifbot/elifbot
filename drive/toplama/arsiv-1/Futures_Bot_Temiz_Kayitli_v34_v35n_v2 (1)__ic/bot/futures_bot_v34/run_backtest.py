#!/usr/bin/env python3
"""
run_backtest.py — Backtest / walk-forward / ablasyon çalıştırıcı.

Kullanım:
    python run_backtest.py --csv data/fixtures/synthetic_btc_1m.csv \
        --strategy trend --out backtest_report.txt

Veri seti sentetikse sonuç hiçbir performans iddiası taşımaz.
"""
from __future__ import annotations

import argparse
import os
import sys

import config
from backtests.ablation import run_ablation
from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig
from backtests.report import render_ablation, render_backtest, render_walk_forward
from backtests.walk_forward import run_walk_forward
from main import load_replay_csv
from strategies.mean_reversion import MeanReversionStrategy
from strategies.squeeze_breakout import SqueezeBreakoutStrategy
from strategies.trend_follower import TrendFollowerStrategy

_FACTORIES = {
    "trend": TrendFollowerStrategy,
    "meanrev": MeanReversionStrategy,
    "squeeze": SqueezeBreakoutStrategy,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paper backtest çalıştırıcı")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--strategy", default="trend", choices=sorted(_FACTORIES))
    ap.add_argument("--train-bars", type=int, default=500)
    ap.add_argument("--test-bars", type=int, default=200)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    if not os.path.exists(args.csv):
        print(f"HATA: CSV bulunamadı: {args.csv}", file=sys.stderr)
        return 1

    df = load_replay_csv(args.csv)
    factory = _FACTORIES[args.strategy]
    cfg = BacktestConfig(
        fee_rate=config.TAKER_FEE_RATE,
        starting_balance=config.STARTING_BALANCE_USDT,
        leverage=config.DEFAULT_LEVERAGE,
    )
    synthetic = "synthetic" in os.path.basename(args.csv).lower()

    parts = [
        f"VERİ: {args.csv} ({len(df)} mum)"
        + ("  [SENTETİK — performans iddiası DEĞİL]" if synthetic else ""),
        f"STRATEJİ: {factory.NAME} (STATUS={factory.STATUS})",
        "",
        render_backtest(SimpleBacktestEngine(factory(), cfg).run(df).results()),
        "",
    ]

    if len(df) >= args.train_bars + args.test_bars:
        parts.append(
            render_walk_forward(
                run_walk_forward(
                    df, factory, train_bars=args.train_bars, test_bars=args.test_bars, config=cfg
                )
            )
        )
    else:
        parts.append(
            f"WALK-FORWARD: atlandı (veri {len(df)} < {args.train_bars + args.test_bars})"
        )
    parts.append("")
    parts.append(render_ablation(run_ablation(df, factory, config=cfg)))

    text = "\n".join(parts)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\nRapor yazıldı: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
