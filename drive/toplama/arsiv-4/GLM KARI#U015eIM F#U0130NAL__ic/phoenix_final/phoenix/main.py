"""PHOENIX FINAL CLI: backtest · walkforward · canlı (dry/testnet/canlı) · anlık tarama.

Kullanım:
  python -m phoenix.main backtest --all --bars 3000
  python -m phoenix.main walkforward --symbol BTC/USDT:USDT --bars 4000
  python -m phoenix.main scan                       # anlık sinyal taraması (anahtar gerekmez)
  python -m phoenix.main live --engine dry          # sanal para, gerçek kamu verisi
  python -m phoenix.main live --engine testnet --confirm-live   # gerçek testnet emirleri
  python -m phoenix.main live --engine live --confirm-live      # GERÇEK emirler — dikkat!
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Callable

import pandas as pd

from . import __version__
from .config import Config
from .datafeed import TIMEFRAME_MS, fetch_ohlcv
from .engine import Engine
from .models import Bar
from .report import attribution, metrics, render_markdown
from .sources import RollingSource
from .strategy import evaluate_last, funding_guard, htf_bias


def setup_logging(cfg: Config) -> None:
    log_file = Path(cfg.exec.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers, force=True)


def load_symbols(args, cfg) -> list[str]:
    if getattr(args, "all", False) or args.symbol is None:
        return list(cfg.market.symbols)
    return [args.symbol]


def _prefer(args, cfg) -> list[str]:
    raw = getattr(args, "prefer", None)
    return [x.strip() for x in raw.split(",")] if raw else cfg.market.data_failover


def cmd_backtest(args) -> None:
    cfg = Config.load(args.config)
    syms = load_symbols(args, cfg)
    tf = cfg.market.timeframe
    prefer = _prefer(args, cfg)
    data: dict[str, pd.DataFrame] = {}
    for s in syms:
        print(f"[veri] {s} {tf} {args.bars} mum …", flush=True)
        data[s] = fetch_ohlcv(s, tf, args.bars, prefer, cache_dir="data/cache")
        print(f"       {len(data[s])} mum ({data[s].ts.iloc[0]} → {data[s].ts.iloc[-1]})", flush=True)
    from .backtest import run_backtest

    r = run_backtest(data, cfg)
    m = metrics(r.trades, r.equity_curve, cfg)
    ctx = {"semboller": ", ".join(syms), "tf": tf, "aralık": f"{r.start_ts} → {r.end_ts}",
           "risk_işlem": f"%{cfg.risk.risk_per_trade_pct}",
           "motor": "kötümser (stop-once, ücret+kayma+funding)"}
    Path("data").mkdir(exist_ok=True)
    Path("data/BACKTEST.md").write_text(
        render_markdown("PHOENIX FINAL — Backtest", ctx, m, attribution(r.trades), r.stats,
                        r.breaker_trips,
                        note="Backtest geçmiş performanstır; gelecek getirinin garantisi DEĞİLDİR."),
        encoding="utf-8")
    print(json.dumps(m, indent=1, ensure_ascii=False))
    print("motor istatistikleri:", json.dumps(r.stats, ensure_ascii=False))
    print("kesici tetikleri:", json.dumps(r.breaker_trips, ensure_ascii=False))
    for t in r.trades[-15:]:
        print(f"  {t.close_ts[:16]} {t.sym:16s} {'LONG ' if t.side > 0 else 'SHORT'} "
              f"R={t.r_mult:+.2f} pnl={t.pnl:+.1f} {t.reason} (skor {t.score:+.1f})")
    print("rapor → data/BACKTEST.md")


def cmd_walkforward(args) -> None:
    cfg = Config.load(args.config)
    syms = load_symbols(args, cfg)
    tf = cfg.market.timeframe
    prefer = _prefer(args, cfg)
    data: dict[str, pd.DataFrame] = {}
    for s in syms:
        print(f"[veri] {s} {args.bars} mum …", flush=True)
        data[s] = fetch_ohlcv(s, tf, args.bars, prefer, cache_dir="data/cache")
    from .backtest import walk_forward

    res = walk_forward(data, cfg, train_bars=args.train, test_bars=args.test,
                       progress=lambda m: print("  " + m, flush=True))
    Path("data").mkdir(exist_ok=True)
    Path("data/WALKFORWARD.json").write_text(json.dumps(res, indent=1, ensure_ascii=False),
                                             encoding="utf-8")
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print("\nSONUÇ: OOS ort. R =", res["oos_ort_R"], "| sabit-ayar OOS ort. R =", res["baz_oos_ort_R"])
    print("Eğer OOS ≤ baz ise optimizasyon kazandırmıyor demektir → varsayılan ayarlarla kalın.")


def cmd_scan(args) -> None:
    """Anlık sinyal taraması — API anahtarı gerekmez, yalnız kapanmış mumlar."""
    cfg = Config.load(args.config)
    tf = cfg.market.timeframe
    for s in cfg.market.symbols:
        try:
            df = fetch_ohlcv(s, tf, cfg.market.warmup + 50, _prefer(args, cfg),
                             cache_dir="data/cache")
            htf = "NEUTRAL"
            try:
                hdf = fetch_ohlcv(s, cfg.market.htf_timeframes[0], 260,
                                  _prefer(args, cfg), cache_dir="data/cache")
                htf = htf_bias(hdf)
            except Exception:  # noqa: BLE001
                pass
            sig = evaluate_last(df.iloc[:-1], cfg, htf=htf)
            status = "SİNYAL" if (sig.side and not sig.vetoes) else "bekle"
            arrow = "LONG" if sig.side > 0 else "SHORT" if sig.side < 0 else "-"
            print(f"{s:18s} tf={tf:3s} HTF={htf:7s} skor={sig.score:+5.2f} {arrow:5s} "
                  f"rejim={sig.regime:8s} veto={','.join(sig.vetoes) or '-'} → {status}")
        except Exception as e:  # noqa: BLE001
            print(f"{s:18s} HATA: {e}")


def cmd_live(args) -> None:
    cfg = Config.load(args.config)
    setup_logging(cfg)
    log = logging.getLogger("phoenix.live")
    if args.engine:
        cfg.exec.engine = args.engine
        if args.engine == "live":
            cfg.exec.testnet = False
    log.info("PHOENIX FINAL v%s başlıyor | engine=%s | semboller=%s", __version__,
             cfg.exec.engine, ",".join(cfg.market.symbols))
    if cfg.exec.engine in ("testnet", "live") and not args.confirm_live:
        raise SystemExit(
            "GÜVENLİK KİLİDİ: testnet/canlı mod --confirm-live olmadan açılmaz.\n"
            "Önce paper (dry) testlerini bitirin; sonra: "
            "python -m phoenix.main live --engine testnet --confirm-live"
        )

    dry = cfg.exec.engine == "dry"
    bar_ms = TIMEFRAME_MS[cfg.market.timeframe]
    poll = max(20.0, bar_ms / 1000.0 / 6.0)

    eng: Engine | None = None
    live_state: dict = {}
    history: dict[str, list[tuple]] = {}
    seen: dict[str, int] = {}
    htf_data: dict[str, dict[str, pd.DataFrame]] = {}
    last_htf = 0.0
    ex = None
    if dry:
        for s in cfg.market.symbols:
            df = fetch_ohlcv(s, cfg.market.timeframe, cfg.market.warmup,
                             cfg.market.data_failover, cache_dir="data/cache")
            history[s] = list(df.tail(cfg.market.warmup).itertuples(index=False, name=None))
            htf_data[s] = _fetch_htf(s, cfg)
        eng = Engine(cfg, RollingSource(history, cfg, htf_data=htf_data), bar_ms)
        eng.load_state(cfg.exec.state_file)
        seen = {s: (history[s][-1][0] if history[s] else 0) for s in history}
        last_htf = time.time()
    else:
        from .exchange import Exchange

        ex = Exchange(cfg)
        log.info("ccxt bağlandı: binanceusdm testnet=%s", cfg.exec.testnet)
        live_state = {"balance0": ex.balance_usdt(), "positions": {}, "htf": {}}
        log.info("bakiye: %.2f USDT", live_state["balance0"])

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    events_path = Path(cfg.exec.journal_file)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events = open(events_path, "a", encoding="utf-8")

    def on_event(kind: str, payload: dict) -> None:
        events.write(json.dumps({"kind": kind, **payload}, ensure_ascii=False) + "\n")
        events.flush()
        if kind in ("open", "close", "tp1"):
            log.info("[%s] %s", kind, payload)

    try:
        while deadline is None or time.time() < deadline:
            cycle_started = time.time()
            if dry:
                if time.time() - last_htf > 3300:  # HTF oybirliği saatlik tazelenir
                    for s in cfg.market.symbols:
                        try:
                            htf_data[s] = _fetch_htf(s, cfg)
                        except Exception:  # noqa: BLE001
                            log.warning("%s HTF tazelemedi", s)
                    last_htf = time.time()
                _dry_step(cfg, eng, history, seen, log)
                eng.save_state(cfg.exec.state_file)
            else:
                _live_step(cfg, ex, live_state, on_event, log)
            wait = max(1.0, poll - (time.time() - cycle_started))
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - time.time()))
            time.sleep(wait)
    except KeyboardInterrupt:
        log.info("kullanıcı durdurdu (Ctrl+C)")
    finally:
        events.close()
        if eng is not None:
            eng.save_state(cfg.exec.state_file)
            print(json.dumps(metrics(eng.trades, eng.equity_curve, cfg), indent=1,
                             ensure_ascii=False))


def _fetch_htf(sym: str, cfg) -> dict[str, pd.DataFrame]:
    out = {}
    for rule in cfg.market.htf_timeframes:
        try:
            df = fetch_ohlcv(sym, rule, 260, cfg.market.data_failover, cache_dir="data/cache")
            out[rule] = df
        except Exception:  # noqa: BLE001
            pass
    return out


def _dry_step(cfg, eng: Engine, history, seen, log) -> None:
    """Canlı PAPER: kamu verisi → yeni KAPANMIŞ mumlar → backtest ile AYNI motor."""
    new: dict[pd.Timestamp, dict] = {}
    for s in cfg.market.symbols:
        try:
            df = fetch_ohlcv(s, cfg.market.timeframe, 5, cfg.market.data_failover,
                             min_bars=1)  # artımlı yoklama: son kapanmış mum yeter
            for row in df.itertuples(index=False):
                if row.ts > seen[s]:
                    tup = (row.ts, row.open, row.high, row.low, row.close, row.volume)
                    history[s].append(tup)
                    seen[s] = row.ts
                    t = pd.to_datetime(row.ts, unit="ms", utc=True)
                    new.setdefault(t, {})[s] = tup
        except Exception as e:  # noqa: BLE001
            log.warning("%s veri alınamadı: %s — bu turda sinyal yok", s, e)
    for t in sorted(new):
        eng.step(t, {s: Bar(*tup) for s, tup in new[t].items()})


def _live_step(cfg, ex, state: dict, on_event: Callable, log) -> None:
    """Testnet/canlı adımı: sinyal → emir; pozisyon yönetimi (BE/trail/tp1/time)."""
    from .risk import adaptive_leverage, size_position
    from .strategy import funding_guard

    if Path(cfg.exec.kill_file).exists():
        log.warning("KILL dosyası var — yeni giriş yok (mevcut pozisyonlar korunur)")
        return
    tf_ms = TIMEFRAME_MS[cfg.market.timeframe]
    for s in cfg.market.symbols:
        try:
            df = fetch_ohlcv(s, cfg.market.timeframe, cfg.market.warmup,
                             cfg.market.data_failover, cache_dir="data/cache")
        except Exception as e:  # noqa: BLE001
            log.warning("%s veri yok: %s", s, e)
            continue
        closed = df.iloc[:-1]
        price = float(closed.close.iloc[-1])
        pos = state["positions"].get(s)

        # --- pozisyon yönetimi (SL/TP gerçek borsa emirleri; BE/trail/tp1/time burada) ---
        if pos is not None:
            side, entry, r_unit = pos["side"], pos["entry"], pos["r_unit"]
            best = max(pos.get("best", entry), price) if side > 0 else min(pos.get("best", entry), price)
            r_best = side * (best - entry) / r_unit
            held_min = (time.time() - pos["opened"]) / 60.0
            if held_min >= cfg.exit.max_hold_bars * (tf_ms / 60000.0):
                ex.cancel_stops(s)
                ex.market_order(s, "sell" if side > 0 else "buy", pos["qty"], reduce_only=True)
                on_event("close", sym=s, reason="TIME", price=price)
                state["positions"].pop(s, None)
                continue
            if not pos.get("tp1_done") and r_best >= cfg.exit.tp1_r:
                part = ex.normalize_qty(s, pos["qty"] * cfg.exit.tp1_fraction)
                if part > 0:
                    ex.market_order(s, "sell" if side > 0 else "buy", part, reduce_only=True)
                    pos["qty"] = round(pos["qty"] - part, 8)
                    pos["tp1_done"] = True
                    on_event("tp1", sym=s, part=part, price=price)
            cost = (cfg.risk.taker_bps * 2 + cfg.risk.slip_bps * 2 + cfg.risk.spread_bps) / 10_000.0
            be = entry + side * entry * cost
            new_stop = pos["stop"]
            if r_best >= cfg.exit.breakeven_r:
                new_stop = max(new_stop, be) if side > 0 else min(new_stop, be)
            if pos.get("tp1_done"):
                tr = best - side * cfg.exit.trail_atr * pos["atr"]
                new_stop = max(new_stop, tr) if side > 0 else min(new_stop, tr)
            if abs(new_stop - pos["stop"]) > price * 1e-6:
                ex.cancel_stops(s)
                ex.stop_orders(s, "long" if side > 0 else "short", pos["qty"], new_stop, pos["tp"])
                pos["stop"] = new_stop
                on_event("move_stop", sym=s, stop=new_stop)
            state["positions"][s] = pos
            continue

        # --- yeni giriş ---
        if funding_guard(pd.Timestamp.utcnow(), cfg):
            log.info("%s: funding penceresi — giriş atlandı", s)
            continue
        htf = state["htf"].get(s, "NEUTRAL")
        sig = evaluate_last(closed, cfg, htf=htf)
        if sig.side == 0 or sig.vetoes:
            continue
        stop_dist = cfg.exit.stop_atr * sig.atr
        atrp = sig.atr / price * 100.0
        qty, risk_usd, lev, why = size_position(ex.balance_usdt(), price, stop_dist, atrp, cfg)
        if qty <= 0:
            log.info("%s boyutlandırma reddi: %s", s, why)
            continue
        qty = ex.normalize_qty(s, qty)
        if qty <= 0:
            continue
        ex.ensure_leverage(s, adaptive_leverage(atrp, cfg))
        entry_fill = price
        stop = entry_fill - sig.side * stop_dist
        tp = entry_fill + sig.side * cfg.exit.tp_r * stop_dist
        ex.market_order(s, "buy" if sig.side > 0 else "sell", qty)
        ex.stop_orders(s, "long" if sig.side > 0 else "short", qty, stop, tp)
        state["positions"][s] = {"side": sig.side, "entry": entry_fill, "qty": qty, "stop": stop,
                                 "tp": tp, "atr": sig.atr, "r_unit": stop_dist, "best": entry_fill,
                                 "risk_usd": risk_usd, "opened": time.time(), "lev": lev}
        on_event("open", sym=s, side=sig.side, entry=entry_fill, qty=qty, stop=stop, tp=tp, lev=lev)


def main() -> None:
    p = argparse.ArgumentParser(prog="phoenix", description="PHOENIX FINAL futures confluence bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("backtest", "walkforward"):
        sp = sub.add_parser(name)
        sp.add_argument("--config", default="config.yaml")
        sp.add_argument("--symbol", default=None)
        sp.add_argument("--all", action="store_true")
        sp.add_argument("--bars", type=int, default=3000)
        sp.add_argument("--prefer", default=None, help="veri kaynağı sırası, ör: bybit,okx")
    sub.choices["walkforward"].add_argument("--train", type=int, default=1200)
    sub.choices["walkforward"].add_argument("--test", type=int, default=400)
    sp = sub.add_parser("scan")
    sp.add_argument("--config", default="config.yaml")
    sp.add_argument("--prefer", default=None, help="veri kaynağı sırası, ör: bybit,okx")
    sp = sub.add_parser("live")
    sp.add_argument("--config", default="config.yaml")
    sp.add_argument("--engine", choices=["dry", "testnet", "live"], default=None)
    sp.add_argument("--minutes", type=float, default=None, help="süre sonu otomatik rapor (boş=sonsuz)")
    sp.add_argument("--confirm-live", action="store_true",
                    help="testnet/canlı kilidini açar (yalnız paper testleri bittikten sonra)")
    args = p.parse_args()
    {"backtest": cmd_backtest, "walkforward": cmd_walkforward,
     "scan": cmd_scan, "live": cmd_live}[args.cmd](args)


if __name__ == "__main__":
    main()
