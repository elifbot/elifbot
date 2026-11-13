"""Komut satırı: demo | backtest | walkforward | fetch | live."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Optional

from . import __version__
from .backtest import run_backtest, walk_forward
from .data import INTERVAL_MS, fetch_binance, load_csv, load_csv_dir, save_csv, synthetic, top_symbols, validate_bars
from .models import Bar, Config
from .report import attribution, metrics, render_markdown


def _add_cfg_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="JSON ayar dosyası (Config alanları)")
    p.add_argument("--set", action="append", default=[], metavar="ANAHTAR=DEĞER",
                   help="tek tek ayar, örn --set conf_th=5 --set risk_pct=0.3 (tekrarlanabilir)")


def _build_cfg(args: argparse.Namespace) -> Config:
    d: dict = {}
    if getattr(args, "config", None):
        d.update(json.loads(Path(args.config).read_text(encoding="utf-8")))
    types = {f.name: f.type for f in fields(Config)}
    for kv in getattr(args, "set", []):
        k, _, v = kv.partition("=")
        if k not in types:
            raise SystemExit(f"bilinmeyen ayar: {k}")
        t = types[k]
        d[k] = (v.lower() in ("1", "true", "evet")) if "bool" in str(t) else \
               int(v) if "int" in str(t) else float(v)
    if getattr(args, "interval", None):
        d.setdefault("bar_ms", INTERVAL_MS[args.interval])
    return Config.from_dict(d)


def _load_data(args: argparse.Namespace, cfg: Config) -> dict[str, list[Bar]]:
    if args.csv_dir:
        raw = load_csv_dir(args.csv_dir)
    elif args.csv:
        raw = {Path(args.csv).stem.upper(): load_csv(args.csv)}
    else:
        raw = synthetic(n_bars=args.bars, n_symbols=args.symbols, seed=args.seed, bar_ms=cfg.bar_ms)
        print("UYARI: sentetik veri kullanılıyor; sonuçlar gerçek piyasa hakkında bir şey söylemez.",
              file=sys.stderr)
    out = {}
    for s, bars in raw.items():
        clean, issues = validate_bars(bars, cfg.bar_ms)
        if any(issues.values()):
            print(f"{s}: veri sorunları {issues}", file=sys.stderr)
        if clean:
            out[s] = clean
    if not out:
        raise SystemExit("veri yok")
    return out


def _write(out: Path, title: str, meta: dict, res, cfg: Config, wf: Optional[dict] = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    m = metrics(res.trades, res.equity_curve, cfg) if res else wf["oos"]
    attr = attribution(res.trades) if res else {}
    stats = res.stats if res else {}
    trips = res.breaker_trips if res else {}
    (out / "RAPOR.md").write_text(render_markdown(title, meta, m, attr, stats, trips, wf), encoding="utf-8")
    payload = {"meta": meta, "config": cfg.to_dict(), "metrics": m, "stats": stats, "breaker": trips}
    if wf:
        payload["walk_forward"] = wf
    (out / "SONUC.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if res:
        with open(out / "trades.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sym", "side", "open_ts", "close_ts", "entry", "exit", "qty", "pnl", "r", "reason", "bars"])
            for t in res.trades:
                w.writerow([t.sym, t.side, t.open_ts, t.close_ts, round(t.entry, 6), round(t.exit, 6),
                            round(t.qty, 6), round(t.pnl, 4), round(t.r_mult, 3), t.reason, t.bars])
    return m


def _data_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", help="tek sembol CSV (timestamp,open,high,low,close,volume)")
    p.add_argument("--csv-dir", help="klasördeki her SEMBOL.csv bir sembol")
    p.add_argument("--bars", type=int, default=3000, help="sentetik mum sayısı")
    p.add_argument("--symbols", type=int, default=8, help="sentetik sembol sayısı")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--interval", default="15m", choices=list(INTERVAL_MS))
    p.add_argument("--out", default="runs/son")
    _add_cfg_flags(p)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="sentez", description=f"SENTEZ {__version__} — PAPER işlem botu")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backtest", help="geçmiş mumlarda koş"); _data_flags(p)
    p = sub.add_parser("demo", help="sentetik veride hızlı deneme"); _data_flags(p)
    p = sub.add_parser("walkforward", help="örneklem-dışı doğrulama"); _data_flags(p)
    p.add_argument("--train", type=int, default=1200); p.add_argument("--test", type=int, default=400)
    p = sub.add_parser("fetch", help="Binance kamu klines → CSV (ağ gerekir)")
    p.add_argument("--symbols", default="top", help="'top' veya BTCUSDT,ETHUSDT,...")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--interval", default="15m", choices=list(INTERVAL_MS))
    p.add_argument("--bars", type=int, default=3000); p.add_argument("--dir", default="data")
    p = sub.add_parser("live", help="canlı PAPER (kamu veri, gerçek emir yok; ağ gerekir)")
    p.add_argument("--symbols", default="top"); p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--minutes", type=float, default=60); p.add_argument("--interval", default="15m", choices=list(INTERVAL_MS))
    p.add_argument("--out", default="runs/live"); _add_cfg_flags(p)
    args = ap.parse_args(argv)

    if args.cmd == "fetch":
        syms = top_symbols(args.top_n) if args.symbols == "top" else args.symbols.split(",")
        for s in syms:
            bars = fetch_binance(s, args.interval, args.bars)
            save_csv(Path(args.dir) / f"{s}.csv", bars)
            print(f"{s}: {len(bars)} mum → {args.dir}/{s}.csv")
        return 0

    cfg = _build_cfg(args)
    if args.cmd == "live":
        from .live import run_live
        syms = top_symbols(args.top_n) if args.symbols == "top" else args.symbols.split(",")
        m = run_live(syms, cfg, args.interval, Path(args.out), args.minutes)
        print(json.dumps(m, ensure_ascii=False, indent=1))
        return 0

    data = _load_data(args, cfg)
    meta = {"sürüm": __version__, "semboller": len(data), "mum/sembol": max(len(b) for b in data.values()),
            "aralık": args.interval, "kaynak": "csv" if (args.csv or args.csv_dir) else "SENTETİK"}
    if args.cmd == "walkforward":
        wf = walk_forward(data, cfg, args.train, args.test, progress=print)
        m = _write(Path(args.out), "SENTEZ walk-forward", meta, None, cfg, wf)
    else:
        res = run_backtest(data, cfg)
        m = _write(Path(args.out), "SENTEZ backtest", meta, res, cfg)
    print(json.dumps(m, ensure_ascii=False, indent=1))
    print(f"\nRapor: {Path(args.out) / 'RAPOR.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
