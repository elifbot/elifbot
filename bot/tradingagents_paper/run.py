"""30 dakikalık OKX public futures verisiyle TradingAgents paper denemesi.

Sadece GET /api/v5/public/instruments ve GET /api/v5/market/tickers kullanır.
Gerçek emir gönderme kodu ve borsa kimlik bilgisi bu modülde yoktur.
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

from .paper import Instrument, PaperBook, rating_action

BASE = 'https://www.okx.com'
PATHS = {'/api/v5/public/instruments?instType=SWAP', '/api/v5/market/tickers?instType=SWAP'}


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
            if not (symbol.endswith('-USDT-SWAP') and r['state'] == 'live'
                    and r['ctType'] == 'linear' and r['settleCcy'] == 'USDT'):
                continue
            inst = Instrument(symbol, float(r['ctVal']), float(r['lotSz']), float(r['minSz']))
            if all(math.isfinite(x) and x > 0 for x in (inst.ct_val, inst.lot, inst.minimum)):
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
            vol = float(r['volCcy24h']) * px
            opening = float(r['open24h'])
            if not all(math.isfinite(x) for x in (px, ts, vol, opening)) or px <= 0 or opening <= 0 or vol < 0:
                continue
            if not -5 <= now - ts <= 20:
                continue
            out[s] = {'price': px, 'ts': ts, 'volume_usd': vol, 'open24h': opening,
                      'high24h': float(r['high24h']), 'low24h': float(r['low24h'])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


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
        symbol, snapshot, sampled = task
        try:
            rating, decision, report = decide(graph, symbol, snapshot)
            results.put({'symbol': symbol, 'sampled': sampled, 'rating': rating,
                         'decision': decision, 'market_report': report})
        except Exception as exc:
            results.put({'symbol': symbol, 'sampled': sampled,
                         'error': f'{type(exc).__name__}: {exc}'})


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--dakika', type=float, default=30)
    p.add_argument('--sembol', type=int, default=20)
    p.add_argument('--model', default='qwen2.5:1.5b')
    p.add_argument('--output', default='runs/tradingagents_okx_paper')
    args = p.parse_args(argv)
    if not 0 < args.dakika <= 30 or not 2 <= args.sembol <= 50:
        p.error('dakika 0–30 aralığında ve sembol 2–50 arasında olmalı')

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    events_path = output / 'events.jsonl'
    def log(kind, **kw):
        event = {'time': datetime.now(timezone.utc).isoformat(), 'type': kind, **kw}
        with events_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
        print(json.dumps(event, ensure_ascii=False), flush=True)

    meta = instruments(fetch('/api/v5/public/instruments?instType=SWAP'))
    initial = quotes(fetch('/api/v5/market/tickers?instType=SWAP'), time.time())
    symbols = sorted((s for s in initial if s in meta), key=lambda s: initial[s]['volume_usd'], reverse=True)[:args.sembol]
    if len(symbols) < 2:
        raise RuntimeError('OKX üzerinde en az iki taze USDT perpetual bulunamadı')
    book = PaperBook()
    prices = {}
    seen = {}
    history = {s: collections.deque(maxlen=36) for s in symbols}
    tasks, results = queue.Queue(maxsize=1), queue.Queue()
    threading.Thread(target=analyse_loop, args=(tasks, results, args.model), daemon=True).start()
    start = time.monotonic()
    end = start + args.dakika * 60
    next_log = start
    pending = False
    cursor = 0
    decisions = 0
    valid_decisions = 0
    fetch_errors = 0
    last_prices = {}
    fatal_agent_error = None
    log('start', symbols=symbols, duration_seconds=args.dakika * 60, model=args.model,
        note='Yalnızca public GET ve simülasyon; gerçek emir yok. Sadece LONG; Sell=kapama.')

    while time.monotonic() < end:
        now = time.time()
        try:
            all_quotes = quotes(fetch('/api/v5/market/tickers?instType=SWAP'), now)
            fresh = {s: all_quotes[s] for s in symbols if s in all_quotes}
            for s, q in fresh.items():
                prices[s], seen[s] = q['price'], q['ts']
                history[s].append((q['ts'], q['price']))
                closed = book.update(s, q['price'], now)
                if closed:
                    log('paper_close', **closed)
            if fresh:
                last_prices = fresh
            if all(s in prices and now - seen[s] <= 20 for s in book.positions):
                if book.liquidation(prices, now):
                    log('cross_liquidation_approx')
        except Exception as exc:
            fetch_errors += 1
            log('data_error', error=f'{type(exc).__name__}: {exc}')

        while not results.empty():
            result = results.get_nowait()
            pending = False
            if 'error' in result:
                log('agent_error', **result)
                if result['error'].startswith('agent_init:'):
                    fatal_agent_error = result['error']
                continue
            symbol = result['symbol']
            age = now - result['sampled']
            decisions += 1
            if result['rating'] in ('Buy', 'Overweight', 'Hold', 'Underweight', 'Sell'):
                valid_decisions += 1
            log('decision', **result, age_seconds=round(age, 1))
            # Do not act on analysis of stale data or on an old quote.
            if age > 300 or symbol not in seen or now - seen[symbol] > 20:
                log('skip_stale', symbol=symbol, age_seconds=round(age, 1))
                continue
            action = rating_action(result['rating'])
            if action == 'open_long':
                if any(now - seen.get(s, 0) > 20 for s in book.positions):
                    log('skip_stale_portfolio', symbol=symbol)
                elif book.open_long(meta[symbol], prices[symbol], prices, now):
                    log('paper_open', **book.events[-1])
            elif action == 'close':
                closed = book.close(symbol, prices[symbol], 'agent_sell_or_underweight', now)
                if closed:
                    log('paper_close', **closed)

        if not pending and not fatal_agent_error and last_prices:
            # Rotate symbols; choose a fresh quote only.
            for _ in symbols:
                s = symbols[cursor % len(symbols)]
                cursor += 1
                q = last_prices.get(s)
                if q is None or now - q['ts'] > 20:
                    continue
                samples = list(history[s])[-12:]
                snapshot = json.dumps({'symbol': s, **q, 'recent_sampled_prices': samples}, ensure_ascii=False)
                tasks.put_nowait((s, snapshot, q['ts']))
                pending = True
                log('analysis_started', symbol=s, quote_time=q['ts'])
                break

        if time.monotonic() >= next_log:
            log('progress', seconds=round(time.monotonic() - start), decisions=decisions,
                open_positions=len(book.positions), cash=round(book.cash, 2),
                equity=round(book.equity(prices), 2), fresh_symbols=sum(now - seen.get(s, 0) <= 20 for s in symbols))
            next_log = time.monotonic() + 30
        time.sleep(min(5, max(0, end - time.monotonic())))

    summary = book.summary(prices)
    summary.update({'symbols': symbols, 'duration_seconds': round(time.monotonic() - start, 1),
                    'completed_decisions': decisions, 'valid_decisions': valid_decisions, 'data_errors': fetch_errors,
                    'agent_error': fatal_agent_error, 'unrealized_uses_last_sample': True,
                    'freshness_seconds_at_end': {s: round(time.time() - seen[s], 1) for s in seen},
                    'pending_analysis_not_used': pending})
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    log('finish', decisions=decisions, closed=summary['closed_count'], open_positions=len(book.positions),
        equity=round(summary['equity_usd'], 2), valid_decisions=valid_decisions,
        valid=valid_decisions > 0 and not fatal_agent_error)
    return 0 if valid_decisions > 0 and not fatal_agent_error else 1


if __name__ == '__main__':
    raise SystemExit(main())
