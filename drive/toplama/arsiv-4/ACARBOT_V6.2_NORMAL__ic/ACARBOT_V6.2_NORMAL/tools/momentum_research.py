"""v6.1 research-only 15m pullback / 1h + 4h trend experiment.

No exchange orders or production pipeline changes. CSVs contain timestamp(ms),
open,high,low,close,volume in 5m UTC. Stop/target tests use 15m candles with
stop-first if both touched; no tick, liquidity or funding simulation. Gross and
estimated fee+slippage values are shown separately. Results are NOT proof.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

MS5 = 300_000
DAY = 86_400_000


@dataclass(frozen=True)
class Bar:
    ts: int
    op: float
    high: float
    low: float
    close: float
    volume: float


def load_csv(path: Path) -> list[Bar]:
    out = []
    with path.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            b = Bar(int(float(r['timestamp'])), float(r['open']), float(r['high']),
                    float(r['low']), float(r['close']), float(r['volume']))
            vals = (b.op, b.high, b.low, b.close, b.volume)
            if (b.ts <= 0 or b.ts % MS5 or not all(math.isfinite(x) for x in vals)
                    or min(b.op, b.high, b.low, b.close) <= 0 or b.volume < 0
                    or b.low > min(b.op, b.close) or b.high < max(b.op, b.close)
                    or b.low > b.high):
                raise ValueError(f'{path}: invalid OHLCV at {b.ts}')
            if out and b.ts <= out[-1].ts:
                raise ValueError(f'{path}: timestamps must be strictly increasing')
            out.append(b)
    return out


def aggregate(rows: list[Bar], period: int) -> tuple[list[Bar], int]:
    """Only full, contiguous, epoch-aligned 5m buckets; never invent bars."""
    if period < MS5 or period % MS5:
        raise ValueError('period must be a 5m multiple')
    groups: dict[int, list[Bar]] = defaultdict(list)
    for b in rows:
        groups[b.ts - b.ts % period].append(b)
    result, dropped = [], 0
    for start, bars in sorted(groups.items()):
        expected = range(start, start + period, MS5)
        if [b.ts for b in bars] != list(expected):
            dropped += 1
            continue
        result.append(Bar(start, bars[0].op, max(x.high for x in bars),
                          min(x.low for x in bars), bars[-1].close,
                          sum(x.volume for x in bars)))
    return result, dropped


def ema(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    if len(xs) < n:
        return out
    value = sum(xs[:n]) / n
    out[n - 1] = value
    alpha = 2 / (n + 1)
    for i in range(n, len(xs)):
        value = alpha * xs[i] + (1 - alpha) * value
        out[i] = value
    return out


def rsi(xs: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    if len(xs) <= n:
        return out
    changes = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    gain = sum(max(x, 0) for x in changes[:n]) / n
    loss = sum(max(-x, 0) for x in changes[:n]) / n
    def val(gain_value, loss_value):
        return (50.0 if gain_value == 0 and loss_value == 0 else
                100.0 if loss_value == 0 else 100 - 100 / (1 + gain_value / loss_value))
    out[n] = val(gain, loss)
    for i in range(n + 1, len(xs)):
        delta = xs[i] - xs[i - 1]
        gain = (gain * (n - 1) + max(delta, 0)) / n
        loss = (loss * (n - 1) + max(-delta, 0)) / n
        out[i] = val(gain, loss)
    return out


def atr(rows: list[Bar], n: int = 14) -> list[float | None]:
    tr = [max(b.high - b.low, abs(b.high - rows[i - 1].close),
              abs(b.low - rows[i - 1].close)) if i else b.high - b.low
          for i, b in enumerate(rows)]
    out: list[float | None] = [None] * len(rows)
    if len(rows) < n:
        return out
    value = sum(tr[:n]) / n
    out[n - 1] = value
    for i in range(n, len(rows)):
        value = (value * (n - 1) + tr[i]) / n
        out[i] = value
    return out


def trend_at(rows: list[Bar], period: int, query_ms: int, fast, slow) -> int:
    """Uses only higher-TF candles that closed at or before the decision time."""
    idx = bisect.bisect_right([b.ts + period for b in rows], query_ms) - 1
    if idx < 0 or fast[idx] is None or slow[idx] is None:
        return 0
    return 1 if fast[idx] > slow[idx] else -1 if fast[idx] < slow[idx] else 0


def simulate(rows: list[Bar], i: int, side: int, risk: float,
             per_side_cost: float, max_bars: int = 16):
    """Next open entry, 1R symmetric exits, stop first on same candle.

    If the next candle gaps beyond stop, exit at worse open; target gaps use
    target (no optimistic price improvement). Reject missing exit windows.
    """
    if i + max_bars >= len(rows) or risk <= 0:
        return None
    entry = rows[i + 1].op
    stop, target = entry - side * risk, entry + side * risk
    if min(stop, target) <= 0:
        return None
    exit_price = None
    why = 'time'
    end_i = i + max_bars
    for j in range(i + 1, i + max_bars + 1):
        b = rows[j]
        if j > i + 1 and b.ts != rows[j - 1].ts + 900_000:
            return None
        if (side == 1 and b.op <= stop) or (side == -1 and b.op >= stop):
            exit_price, why, end_i = b.op, 'gap_stop', j
            break
        stop_hit = b.low <= stop if side == 1 else b.high >= stop
        target_hit = b.high >= target if side == 1 else b.low <= target
        if stop_hit or target_hit:
            exit_price, why, end_i = (stop, 'stop', j) if stop_hit else (target, 'target', j)
            break
    if exit_price is None:
        exit_price = rows[end_i].close
    gross = side * (exit_price - entry) / risk
    cost = (entry + exit_price) * per_side_cost / risk
    return {'entry_ts': rows[i + 1].ts, 'exit_ts': rows[end_i].ts + 900_000,
            'side': 'LONG' if side == 1 else 'SHORT', 'gross_r': gross,
            'cost_r': cost, 'net_r': gross - cost, 'exit_reason': why}


def trades_for_symbol(rows5: list[Bar], symbol: str, per_side_cost: float):
    p15, drop15 = aggregate(rows5, 900_000)
    h1, drop1 = aggregate(rows5, 3_600_000)
    h4, drop4 = aggregate(rows5, 14_400_000)
    c15 = [x.close for x in p15]
    e15, rs, ar = ema(c15, 20), rsi(c15), atr(p15)
    a1, b1 = ema([x.close for x in h1], 20), ema([x.close for x in h1], 50)
    a4, b4 = ema([x.close for x in h4], 20), ema([x.close for x in h4], 50)
    # Precompute closed-TF timelines for O(log n) access.
    t1 = [x.ts + 3_600_000 for x in h1]
    t4 = [x.ts + 14_400_000 for x in h4]
    trades, next_free = [], 0
    for i in range(20, len(p15) - 16):
        if i < next_free or p15[i].ts != p15[i - 1].ts + 900_000:
            continue
        if p15[i + 1].ts != p15[i].ts + 900_000:
            continue
        now = p15[i].ts + 900_000
        j, k = bisect.bisect_right(t1, now) - 1, bisect.bisect_right(t4, now) - 1
        if j < 0 or k < 0 or None in (a1[j], b1[j], a4[k], b4[k], e15[i], e15[i-1], rs[i], ar[i]):
            continue
        # Reject stale higher-TF data after gaps.
        if now - t1[j] >= 3_600_000 or now - t4[k] >= 14_400_000:
            continue
        side = 0
        if (a1[j] > b1[j] and a4[k] > b4[k] and c15[i-1] <= e15[i-1]
                and c15[i] > e15[i] and 45 <= rs[i] <= 65):
            side = 1
        elif (a1[j] < b1[j] and a4[k] < b4[k] and c15[i-1] >= e15[i-1]
              and c15[i] < e15[i] and 35 <= rs[i] <= 55):
            side = -1
        if not side:
            continue
        trade = simulate(p15, i, side, 1.5 * ar[i], per_side_cost)
        if trade is not None:
            trade['symbol'] = symbol
            trades.append(trade)
            next_free = bisect.bisect_left([x.ts for x in p15], trade['exit_ts'])
    return trades, {'5m_bars': len(rows5), '15m_bars': len(p15),
                    'dropped_15m': drop15, 'dropped_1h': drop1, 'dropped_4h': drop4}


def summary(trades, bootstrap=2000, seed=610):
    if not trades:
        return {'n': 0, 'mean_gross_r': None, 'mean_net_r': None, 'day_bootstrap_95': None}
    days = defaultdict(list)
    for t in trades:
        days[t['entry_ts'] // DAY].append(t['net_r'])
    groups = list(days.values())
    rng = random.Random(seed)
    draws = []
    if len(groups) >= 2:
        for _ in range(bootstrap):
            sample = [rng.choice(groups) for _ in groups]
            flat = [v for group in sample for v in group]
            draws.append(sum(flat) / len(flat))
        draws.sort()
    return {'n': len(trades), 'days': len(groups),
            'mean_gross_r': sum(t['gross_r'] for t in trades) / len(trades),
            'mean_net_r': sum(t['net_r'] for t in trades) / len(trades),
            'day_bootstrap_95': [draws[int(.025 * (len(draws)-1))],
                                 draws[int(.975 * (len(draws)-1))]] if draws else None,
            'mean_net_r_2x_cost': sum(t['gross_r']-2*t['cost_r'] for t in trades)/len(trades),
            'win_rate': sum(t['net_r'] > 0 for t in trades)/len(trades)}


def run(paths, cost, min_oos=30, bootstrap=2000):
    all_trades, diagnostics, starts, ends = [], {}, [], []
    for path in paths:
        rows = load_csv(path)
        if not rows:
            continue
        trades, info = trades_for_symbol(rows, path.stem, cost)
        all_trades.extend(trades)
        diagnostics[path.name] = info
        starts.append(rows[0].ts)
        ends.append(rows[-1].ts + MS5)
    if not starts:
        raise ValueError('No candle data')
    start, end = max(starts), min(ends)  # shared time range, no survivorship claims
    if end <= start:
        raise ValueError('No shared data period')
    cut = start + int((end-start)*.75)
    # Trades overlapping the split are excluded from both sets.
    usable = [t for t in all_trades if t['entry_ts'] >= start and t['exit_ts'] <= end]
    train = [t for t in usable if t['exit_ts'] <= cut]
    test = [t for t in usable if t['entry_ts'] >= cut]
    discarded = len(usable)-len(train)-len(test)
    return {'method': '15m pullback; 1h/4h EMA20/50; fixed 1R; conservative OHLC',
            'research_only': True, 'live_allowed': False, 'start_ms': start, 'end_ms': end,
            'oos_start_ms': cut, 'split_overlap_excluded': discarded,
            'per_side_cost_assumption': cost, 'funding': 'UYGULANMADI',
            'funding_note': 'No funding data applied: net estimates EXCLUDE funding.',
            'execution_note': '15m OHLC, stop-first; 1m/tick, order book, maker fill and portfolio constraints not modelled.',
            'sample_note': 'Shared time range; cross-symbol dependence handled only by day clustering; no point-in-time universe.',
            'train': summary(train, bootstrap), 'oos': summary(test, bootstrap),
            'all': summary(train+test, bootstrap), 'diagnostics': diagnostics,
            'min_oos': min_oos, 'verdict': 'EDGE_KANITLANMADI',
            'reason': 'Araştırma taraması; funding/gerçek maliyet/yürütme ve bağımsız üretim doğrulaması eksik.'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', nargs='+', required=True, type=Path)
    p.add_argument('--fee-bps', type=float, default=5.0, help='Her bacak; varsayım')
    p.add_argument('--slippage-bps', type=float, default=2.0, help='Her bacak; varsayım')
    p.add_argument('--bootstrap', type=int, default=2000)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    if (not math.isfinite(args.fee_bps) or not math.isfinite(args.slippage_bps)
            or args.fee_bps < 0 or args.slippage_bps < 0 or args.bootstrap < 100):
        p.error('Maliyetler sonlu ve negatif olmayan; bootstrap >= 100 olmalı')
    result = run(args.csv, (args.fee_bps + args.slippage_bps)/10_000, bootstrap=args.bootstrap)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
