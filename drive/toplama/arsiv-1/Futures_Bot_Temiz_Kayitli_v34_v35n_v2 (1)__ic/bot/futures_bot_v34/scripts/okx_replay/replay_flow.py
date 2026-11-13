#!/usr/bin/env python3
"""Gerçek OKX trades üzerinde nedensel akış/giriş/çıkış replay araştırması.

Sinyal anından sonraki veri giriş/çıkış için kullanılır; ATR/Supertrend yalnızca
tamamlanmış mumlardan gelir. Paper-only, portföy başına 25 USDT × 10x ve iki
taraflı taker ücreti. Küçük örneklemde parametre optimizasyonu yapmaz.
"""
from __future__ import annotations
import bisect, csv, json, math, statistics, sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT
sys.path.insert(0, str(BOT))
from scanner.money_flow import YuvarlananAkis  # noqa: E402

MARGIN = 25.0
LEVERAGE = 10.0
FEE = 0.0005
SESSION_END = max(int(r["closed_at"]) for r in csv.DictReader(
    open(BOT / "logs/ws_akis_kapanis.csv", newline="", encoding="utf-8")))


def ms(text):
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
               .replace(tzinfo=timezone.utc).timestamp() * 1000)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@dataclass
class BarInd:
    close_ms: int
    atr: float
    supertrend: float | None


class Indicators:
    def __init__(self, candles):
        bars = sorted(candles, key=lambda x: int(x[0]))
        self.items = []
        trs = []
        for i, b in enumerate(bars):
            h, l, c = float(b[2]), float(b[3]), float(b[4])
            prev_c = float(bars[i - 1][4]) if i else c
            trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
        atr = None
        prev_up = prev_lo = prev_st = prev_close = None
        for i, b in enumerate(bars):
            h, l, c = float(b[2]), float(b[3]), float(b[4])
            if i == 14:
                atr = sum(trs[1:15]) / 14.0
            elif i > 14 and atr is not None:
                atr = (atr * 13 + trs[i]) / 14.0
            st = None
            if atr is not None and i >= 14:
                mid = (h + l) / 2.0
                up, lo = mid + 3 * atr, mid - 3 * atr
                if prev_up is None:
                    final_up, final_lo = up, lo
                    st = final_up if c <= final_up else final_lo
                else:
                    final_up = up if up < prev_up or prev_close > prev_up else prev_up
                    final_lo = lo if lo > prev_lo or prev_close < prev_lo else prev_lo
                    if prev_st == prev_up:
                        st = final_up if c <= final_up else final_lo
                    else:
                        st = final_lo if c >= final_lo else final_up
                prev_up, prev_lo, prev_st = final_up, final_lo, st
                prev_close = c
            if atr is not None and str(b[8]) == "1":
                self.items.append(BarInd(int(b[0]) + 60_000, atr, st))
        self.times = [x.close_ms for x in self.items]

    def at(self, ts):
        i = bisect.bisect_right(self.times, ts) - 1
        return self.items[i] if i >= 0 else None


@dataclass
class Candidate:
    side: str
    signal_ts: int
    signal_price: float
    since: int | None = None


@dataclass
class Position:
    side: str
    entry_ts: int
    entry: float
    qty: float
    entry_fee: float
    initial_stop: float
    stop: float
    highest: float
    lowest: float
    mfe: float = 0.0
    mae: float = 0.0
    condition_since: int | None = None


def pnl(pos, price):
    gross = (price - pos.entry) * pos.qty * (1 if pos.side == "LONG" else -1)
    exit_fee = abs(price * pos.qty) * FEE
    return gross - pos.entry_fee - exit_fee, gross, pos.entry_fee + exit_fee


def simulate(symbol, signals, payload, entry_mode, exit_mode):
    ct = float(payload["contract_multiplier"])
    flow = YuvarlananAkis()
    ind = Indicators(payload["candles"])
    trades = sorted(payload["trades"], key=lambda x: (int(x["ts"]), int(x["tradeId"])))
    events = [(int(x["ts"]), 0, "trade", x) for x in trades]
    events += [(ms(s["ts_utc"]), 1, "signal", s) for s in signals]
    events.sort(key=lambda x: (x[0], x[1]))
    pos = cand = None
    last_price = None
    closed = []
    skipped = 0
    expired = 0

    def open_pos(side, ts, price):
        nonlocal pos
        mark = ind.at(ts)
        if mark is None or not (mark.atr > 0) or not (price > 0):
            return False
        qty = MARGIN * LEVERAGE / price
        entry_fee = MARGIN * LEVERAGE * FEE
        stop = price - 2 * mark.atr if side == "LONG" else price + 2 * mark.atr
        if exit_mode == "fixed":
            stop = price * (0.98 if side == "LONG" else 1.02)
        pos = Position(side, ts, price, qty, entry_fee, stop, stop, price, price)
        return True

    def close_pos(ts, price, reason):
        nonlocal pos
        net, gross, fees = pnl(pos, price)
        closed.append({"symbol": symbol, "side": pos.side, "entry_ts": pos.entry_ts,
                       "exit_ts": ts, "entry": pos.entry, "exit": price,
                       "reason": reason, "net": net, "gross": gross, "fees": fees,
                       "mfe": pos.mfe, "mae": pos.mae,
                       "hold_s": (ts - pos.entry_ts) / 1000})
        pos = None

    for ts, _, kind, obj in events:
        if ts > SESSION_END:
            break
        if kind == "signal":
            if pos is not None or cand is not None:
                skipped += 1
                continue
            side = obj["side"]
            if entry_mode == "immediate":
                if not open_pos(side, ts, float(obj["entry_price"])):
                    skipped += 1
            else:
                cand = Candidate(side, ts, float(obj["entry_price"]))
            continue

        px = float(obj["px"])
        base = float(obj["sz"]) * ct
        flow.ekle(ts, px, base, obj["side"])
        last_price = px

        if pos is not None:
            direction = 1 if pos.side == "LONG" else -1
            ret = direction * (px / pos.entry - 1) * 100
            pos.mfe = max(pos.mfe, ret)
            pos.mae = max(pos.mae, -ret)
            pos.highest = max(pos.highest, px)
            pos.lowest = min(pos.lowest, px)
            initial_hit = ((pos.side == "LONG" and px <= pos.initial_stop)
                           or (pos.side == "SHORT" and px >= pos.initial_stop))
            if initial_hit:
                close_pos(ts, px, "fixed_sl" if exit_mode == "fixed" else "disaster_2atr")
                continue
            if exit_mode == "fixed":
                tp = pos.entry * (1.0125 if pos.side == "LONG" else 0.9875)
                if (pos.side == "LONG" and px >= tp) or (pos.side == "SHORT" and px <= tp):
                    close_pos(ts, px, "fixed_tp")
                continue

            mark = ind.at(ts)
            condition = False
            reason = None
            if mark is not None and mark.atr > 0:
                if exit_mode == "atr":
                    if pos.side == "LONG":
                        pos.stop = max(pos.stop, pos.highest - 3 * mark.atr)
                        condition = px <= pos.stop
                    else:
                        pos.stop = min(pos.stop, pos.lowest + 3 * mark.atr)
                        condition = px >= pos.stop
                    reason = "chandelier_3atr"
                elif exit_mode == "st_flow" and mark.supertrend is not None:
                    cross = ((pos.side == "LONG" and px < mark.supertrend)
                             or (pos.side == "SHORT" and px > mark.supertrend))
                    cvd = flow.anlik(ts, 15).cvd_usd
                    condition = cross and direction * cvd < 0
                    reason = "supertrend_flow15"
                elif exit_mode == "flow_runner":
                    cvd = flow.anlik(ts, 5).cvd_usd
                    peak_ret = direction * ((pos.highest if pos.side == "LONG" else pos.lowest)
                                            / pos.entry - 1) * 100
                    retrace = ((pos.highest - px) if pos.side == "LONG" else (px - pos.lowest))
                    required = max(mark.atr, 0.25 * pos.entry * max(pos.mfe, 0) / 100)
                    condition = pos.mfe >= 0.5 and direction * cvd < 0 and retrace >= required
                    reason = "flow5_atr_giveback"
            if condition:
                if pos.condition_since is None:
                    pos.condition_since = ts
                elif ts - pos.condition_since >= 1000:
                    close_pos(ts, px, reason)
                    continue
            else:
                pos.condition_since = None

        if cand is not None:
            if ts - cand.signal_ts > 60_000:
                cand = None
                expired += 1
                continue
            direction = 1 if cand.side == "LONG" else -1
            c15 = flow.anlik(ts, 15)
            c5 = flow.anlik(ts, 5)
            c60 = flow.anlik(ts, 60)
            ok = c15.hazir and direction * c15.cvd_usd > 0
            if entry_mode == "cvd5_15_vwap60":
                ok = ok and c5.hazir and direction * c5.cvd_usd > 0
            if entry_mode in ("cvd15_vwap60", "cvd5_15_vwap60"):
                ok = ok and c60.vwap is not None and direction * (px - c60.vwap) > 0
            if ok:
                if cand.since is None:
                    cand.since = ts
                elif ts - cand.since >= 1000:
                    side = cand.side
                    if open_pos(side, ts, px):
                        cand = None
                        continue
            else:
                cand.since = None

    if pos is not None:
        close_pos(SESSION_END, last_price or pos.entry, "session_end")
    return {"trades": closed, "skipped": skipped, "expired": expired}


def summarize(name, results):
    trades = [t for r in results for t in r["trades"]]
    nets = [t["net"] for t in trades]
    return {"name": name, "trades": len(trades), "net": sum(nets),
            "wins": sum(x > 0 for x in nets),
            "gross": sum(t["gross"] for t in trades),
            "fees": sum(t["fees"] for t in trades),
            "median": statistics.median(nets) if nets else 0,
            "mfe": statistics.mean(t["mfe"] for t in trades) if trades else 0,
            "mae": statistics.mean(t["mae"] for t in trades) if trades else 0,
            "hold_s": statistics.mean(t["hold_s"] for t in trades) if trades else 0,
            "skipped": sum(r["skipped"] for r in results),
            "expired": sum(r["expired"] for r in results)}


def main():
    signals = [r for r in read_csv(BOT / "logs/ws_akis_sinyal.csv")
               if r["exchange"] == "okx" and r["durum"] == "acildi"]
    by_symbol = {}
    for s in signals:
        by_symbol.setdefault(s["symbol"], []).append(s)
    payloads = {}
    for symbol in by_symbol:
        with open(ROOT / "reports" / "okx_replay_raw" / f"{symbol}.json", encoding="utf-8") as f:
            payloads[symbol] = json.load(f)
    actual = [r for r in read_csv(BOT / "logs/ws_akis_kapanis.csv") if r["exchange"] == "okx"]
    print("ACTUAL_OKX", len(actual), f"net={sum(float(r['realized_pnl']) for r in actual):+.4f}",
          "signals", len(signals), "session_end", SESSION_END)
    summaries = []
    all_trades = {}
    for entry in ("immediate", "cvd15_vwap60", "cvd5_15_vwap60"):
        for exit_mode in ("fixed", "atr", "st_flow", "flow_runner"):
            name = f"{entry}__{exit_mode}"
            results = [simulate(sym, rows, payloads[sym], entry, exit_mode)
                       for sym, rows in by_symbol.items()]
            summaries.append(summarize(name, results))
            all_trades[name] = [t for r in results for t in r["trades"]]
    for s in summaries:
        print(f"{s['name']:<38} n={s['trades']:2} net={s['net']:+8.4f} "
              f"win={s['wins']:2}/{s['trades']:<2} gross={s['gross']:+8.3f} "
              f"fee={s['fees']:6.3f} med={s['median']:+7.3f} "
              f"MFE={s['mfe']:5.2f} MAE={s['mae']:5.2f} hold={s['hold_s']:6.1f}s "
              f"skip={s['skipped']} exp={s['expired']}")
    with open(ROOT / "reports" / "v16_yeni_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)
    with open(ROOT / "reports" / "v16_yeni_replay_trades.json", "w", encoding="utf-8") as f:
        json.dump(all_trades, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
