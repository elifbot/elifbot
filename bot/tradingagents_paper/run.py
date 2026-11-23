"""OKX SWAP/FUTURES public veri + sinyal değerlendirmeli TradingAgents paper testi.

Yalnızca açık piyasa verisi GET çağrıları kullanılır. Özel API/emir yolu yoktur.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import queue
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .paper import Instrument, PaperBook, accepts_signal

BASE = 'https://www.okx.com'
TYPES = ('SWAP', 'FUTURES')
PATHS = {f'/api/v5/{path}?instType={kind}' for path in ('public/instruments', 'market/tickers') for kind in TYPES}


def fetch(path):
    if path not in PATHS:
        raise ValueError('Yalnızca izinli genel veri uçları kullanılabilir')
    req = urllib.request.Request(BASE + path, headers={'User-Agent': 'elifbot-paper-research/1.0'})
    with urllib.request.urlopen(req, timeout=12) as response:
        obj = json.load(response)
    if obj.get('code') != '0' or not isinstance(obj.get('data'), list):
        raise ValueError('OKX veri cevabı geçersiz')
    return obj['data']


def instruments(rows):
    found = {}
    for r in rows:
        try:
            symbol = r['instId']
            if r['state'] != 'live' or r.get('instType') not in TYPES:
                continue
            parts = symbol.split('-')
            quote = parts[1] if len(parts) > 1 else ''
            inst = Instrument(symbol, float(r['ctVal']), float(r['lotSz']), float(r['minSz']),
                              r['ctType'], quote, int(r.get('expTime') or 0),
                              float(r.get('ctMult') or 1))
            if all(math.isfinite(x) and x > 0 for x in (inst.ct_val, inst.lot, inst.minimum, inst.multiplier)):
                found[symbol] = inst
        except (KeyError, TypeError, ValueError):
            continue
    return found


def quotes(rows, now):
    out = {}
    for r in rows:
        try:
            s = r['instId']
            px, ts = float(r['last']), int(r['ts']) / 1000
            vol = float(r['volCcy24h'] or 0)
            opening = float(r['open24h'])
            if not all(math.isfinite(x) for x in (px, ts, vol, opening)) or px <= 0 or opening <= 0 or vol < 0:
                continue
            if not -5 <= now - ts <= 20:
                continue
            out[s] = {'price': px, 'ts': ts, 'volume_ccy_24h': vol, 'open24h': opening,
                      'high24h': float(r['high24h']), 'low24h': float(r['low24h'])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def signal(history):
    """Son yaklaşık dakika değişimi: yön her iki tarafa açık bir adaydır.

    Fiyat değişmemişse ya da en az 50 saniyelik veri yoksa sinyal yok. Bu basit
    aday üretici kârlılık iddiası değildir; agent her adayı değerlendirir.
    """
    if len(history) < 2:
        return None
    last_ts, last_price = history[-1]
    earlier = next(((t, p) for t, p in history if 50 <= last_ts - t <= 75), None)
    if not earlier:
        return None
    change = last_price / earlier[1] - 1
    if change == 0:
        return None
    return {'direction': 1 if change > 0 else -1, 'change_pct': 100 * change,
            'window_seconds': last_ts - earlier[0], 'source': 'sampled_1m_direction'}


def analyse_loop(tasks, results, model):
    try:
        from .agents import create_graph, decide
        graph = create_graph(model)
    except Exception as exc:
        results.put({'error': f'agent_init: {type(exc).__name__}: {exc}'})
        return
    while True:
        task = tasks.get()
        if task is None:
            return
        try:
            rating, decision, report = decide(graph, task['symbol'], task['snapshot'])
            results.put({**task, 'rating': rating, 'decision': decision, 'market_report': report})
        except Exception as exc:
            results.put({**task, 'error': f'{type(exc).__name__}: {exc}'})


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--dakika', type=float, default=30)
    p.add_argument('--model', default='qwen2.5:0.5b')
    p.add_argument('--output', default='runs/tradingagents_okx_paper')
    args = p.parse_args(argv)
    if not 0 < args.dakika <= 30:
        p.error('dakika 0–30 aralığında olmalı')

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    events_path = output / 'events.jsonl'
    def log(kind, **kw):
        event = {'time': datetime.now(timezone.utc).isoformat(), 'type': kind, **kw}
        with events_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
        print(json.dumps(event, ensure_ascii=False), flush=True)
        if kind == 'agent_error':
            print('::warning title=TradingAgents model hatası::' + str(kw.get('error', 'unknown')).replace('\n', ' ')[:500], flush=True)
        elif kind == 'decision':
            print('::notice title=TradingAgents kararı::' + str(kw.get('symbol')) + ' ' + str(kw.get('rating')), flush=True)
        elif kind == 'start':
            print(f"::notice title=OKX evreni::{kw['universe']} aktif sözleşme; {kw['supported']} paper uyumlu", flush=True)
        elif kind == 'progress':
            print(f"::notice title=Paper ilerleme::{kw['seconds']}sn; taze={kw['fresh_symbols']}/{kw['universe']}, sinyal={kw['signals']}, kuyruk={kw['queued']}, eski={kw['stale_signals']}, karar={kw['decisions']}", flush=True)

    def get_all(path):
        rows = []
        for kind in TYPES:
            rows.extend(fetch(f'/api/v5/{path}?instType={kind}'))
        return rows

    meta = instruments(get_all('public/instruments'))
    if not meta:
        raise RuntimeError('OKX SWAP/FUTURES sözleşmeleri alınamadı')
    book = PaperBook()
    prices, seen = {}, {}
    history = collections.defaultdict(lambda: collections.deque(maxlen=40))
    pending = collections.deque()
    queued_symbols = set()
    last_signal_at = {}
    tasks, results = queue.Queue(maxsize=1), queue.Queue()
    threading.Thread(target=analyse_loop, args=(tasks, results, args.model), daemon=True).start()
    start = time.monotonic()
    end = start + args.dakika * 60
    wall_end = time.time() + args.dakika * 60
    next_log, next_refresh = start, start + 60
    active = None
    decisions = valid_decisions = usable_decisions = fetch_errors = signals = stale_signals = 0
    fatal_agent_error = None
    log('start', universe=len(meta), supported=sum(x.supported for x in meta.values()),
        symbols=sorted(meta), duration_seconds=args.dakika * 60, model=args.model,
        note='Tüm canlı SWAP/FUTURES sözleşmeleri; LONG/SHORT. Yalnızca public GET ve simülasyon.')

    while time.monotonic() < end:
        now = time.time()
        if time.monotonic() >= next_refresh:
            try:
                # Keep any open position's metadata even if OKX delists it.
                meta = instruments(get_all('public/instruments')) | {s: meta[s] for s in book.positions if s in meta}
            except Exception as exc:
                fetch_errors += 1
                log('metadata_error', error=f'{type(exc).__name__}: {exc}')
            next_refresh = time.monotonic() + 60
        try:
            fresh = {s: q for s, q in quotes(get_all('market/tickers'), now).items() if s in meta}
            for s, q in fresh.items():
                prices[s], seen[s] = q['price'], q['ts']
                h = history[s]
                if not h or q['ts'] > h[-1][0]:
                    h.append((q['ts'], q['price']))
                closed = book.update(s, q['price'], now)
                if closed:
                    log('paper_close', **closed)
                candidate = signal(h)
                if candidate and s not in queued_symbols and now - last_signal_at.get(s, 0) >= 60:
                    task = {'symbol': s, 'sampled': q['ts'], 'candidate': candidate,
                            'snapshot': json.dumps({'symbol': s, **q, 'signal': candidate,
                                                    'recent_sampled_prices': list(h)[-15:]}, ensure_ascii=False)}
                    pending.append(task)
                    queued_symbols.add(s)
                    last_signal_at[s] = now
                    signals += 1
                    log('signal', symbol=s, **candidate)
            if all(s in prices and now - seen[s] <= 20 for s in book.positions):
                if book.liquidation(prices, now):
                    log('cross_liquidation_approx')
        except Exception as exc:
            fetch_errors += 1
            log('data_error', error=f'{type(exc).__name__}: {exc}')

        while not results.empty():
            result = results.get_nowait()
            active = None
            s = result.get('symbol')
            if s:
                queued_symbols.discard(s)
            if 'error' in result:
                log('agent_error', **result)
                if result['error'].startswith('agent_init:'):
                    fatal_agent_error = result['error']
                continue
            age = now - result['sampled']
            decisions += 1
            if result['rating'] in ('Buy', 'Overweight', 'Hold', 'Underweight', 'Sell'):
                valid_decisions += 1
            log('decision', **result, age_seconds=round(age, 1))
            if age > 300 or s not in seen or now - seen[s] > 20:
                log('skip_stale', symbol=s, age_seconds=round(age, 1))
                continue
            if result['rating'] not in ('Buy', 'Overweight', 'Hold', 'Underweight', 'Sell'):
                continue
            usable_decisions += 1
            direction = result['candidate']['direction']
            if not accepts_signal(result['rating'], direction):
                log('signal_rejected_by_agent', symbol=s, rating=result['rating'])
                continue
            if any(now - seen.get(sym, 0) > 20 for sym in book.positions):
                log('skip_stale_portfolio', symbol=s)
                continue
            if s not in meta:
                log('skip_instrument_no_longer_live', symbol=s)
                continue
            if meta[s].expiry_ms and meta[s].expiry_ms / 1000 <= wall_end:
                log('skip_contract_expiry_during_run', symbol=s)
                continue
            existing = book.positions.get(s)
            if existing and existing['direction'] != direction:
                closed = book.close(s, prices[s], 'opposite_approved_signal', now)
                if closed:
                    log('paper_close', **closed)
            if s not in book.positions:
                if book.open(meta[s], prices[s], prices, direction, now):
                    log('paper_open', **book.events[-1])
                else:
                    log('paper_rejected', **book.events[-1])

        if active is None and not fatal_agent_error:
            while pending:
                candidate = pending.popleft()
                if now - candidate['sampled'] > 300:
                    queued_symbols.discard(candidate['symbol'])
                    stale_signals += 1
                    log('signal_expired_in_queue', symbol=candidate['symbol'])
                    continue
                active = candidate
                tasks.put_nowait(candidate)
                log('analysis_started', symbol=candidate['symbol'], direction=candidate['candidate']['direction'],
                    queue_remaining=len(pending))
                break

        if time.monotonic() >= next_log:
            log('progress', seconds=round(time.monotonic() - start), universe=len(meta),
                fresh_symbols=sum(now - seen.get(s, 0) <= 20 for s in meta), signals=signals,
                queued=len(pending), stale_signals=stale_signals, decisions=decisions,
                open_positions=len(book.positions), cash=round(book.cash, 2), equity=round(book.equity(prices), 2))
            next_log = time.monotonic() + 30
        time.sleep(min(5, max(0, end - time.monotonic())))

    summary = book.summary(prices)
    summary.update({'symbols': sorted(meta), 'universe_count': len(meta), 'signals': signals,
                    'queue_remaining': len(pending), 'stale_signals': stale_signals,
                    'duration_seconds': round(time.monotonic() - start, 1), 'completed_decisions': decisions,
                    'valid_decisions': valid_decisions, 'usable_decisions': usable_decisions,
                    'data_errors': fetch_errors, 'agent_error': fatal_agent_error,
                    'unrealized_uses_last_sample': True, 'pending_analysis_not_used': active is not None})
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    log('finish', signals=signals, decisions=decisions, closed=summary['closed_count'], open_positions=len(book.positions),
        equity=round(summary['equity_usd'], 2), valid_decisions=valid_decisions, usable_decisions=usable_decisions,
        valid=usable_decisions > 0 and not fatal_agent_error)
    return 0 if usable_decisions > 0 and not fatal_agent_error else 1


if __name__ == '__main__':
    raise SystemExit(main())
