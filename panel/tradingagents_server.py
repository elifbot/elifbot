#!/usr/bin/env python3
"""Arena panel: GitHub koşu anotasyonları + açıkça işaretlenmiş ağsız teknik prova.

Gerçek emir, özel borsa API'si ve kullanıcıdan alınan komut çalıştırma yoktur.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).with_name('tradingagents.html')
RUN_ID = 45185083638
CHECK_ID = 137728484631
RUN_URL = f'https://github.com/elifbot/elifbot/actions/runs/{RUN_ID}'


def parse_annotations(annotations):
    metrics = {'universe': None, 'supported': None, 'signals_at_least': None,
               'fresh': None, 'fresh_total': None, 'queue_observed': None,
               'decisions': None, 'valid': None, 'usable': None,
               'closed': None, 'open': None, 'equity_usd': None}
    errors, progress = [], []
    for a in annotations:
        title, msg = a.get('title', ''), a.get('message', '')
        if title == 'OKX evreni':
            match = re.search(r'(\d+) aktif sözleşme; (\d+) paper uyumlu', msg)
            if match:
                metrics['universe'], metrics['supported'] = map(int, match.groups())
        elif title == 'Paper ilerleme':
            match = re.search(r'(\d+)sn; taze=(\d+)/(\d+), sinyal=(\d+), kuyruk=(\d+), eski=(\d+), karar=(\d+)', msg)
            if match:
                seconds, fresh, total, signals, queued, stale, decisions = map(int, match.groups())
                progress.append({'seconds': seconds, 'fresh': fresh, 'total': total, 'signals': signals,
                                 'queue': queued, 'stale': stale, 'decisions': decisions})
        elif title == 'Paper sonuç':
            match = re.search(r'Karar=(\d+), geçerli=(\d+), kullanılabilir=(\d+), kapanan=(\d+), açık=(\d+), özkaynak=([\d.]+)', msg)
            if match:
                vals = match.groups()
                for key, value in zip(('decisions', 'valid', 'usable', 'closed', 'open'), vals[:5]):
                    metrics[key] = int(value)
                metrics['equity_usd'] = float(vals[5])
        elif title == 'TradingAgents model hatası':
            errors.append(msg)
    progress.sort(key=lambda x: x['seconds'])
    if progress:
        last = progress[-1]
        metrics.update({'signals_at_least': max(p['signals'] for p in progress),
                        'fresh': last['fresh'], 'fresh_total': last['total'],
                        'queue_observed': last['queue']})
    return metrics, errors, progress


def gh_json(*args):
    result = subprocess.run(['gh', *args], cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)
    return json.loads(result.stdout)


def github_state():
    run = gh_json('run', 'view', str(RUN_ID), '--json', 'status,conclusion,url,createdAt,updatedAt')
    annotations = gh_json('api', f'repos/elifbot/elifbot/check-runs/{CHECK_ID}/annotations', '--paginate')
    metrics, errors, progress = parse_annotations(annotations)
    return {'run': run, 'metrics': metrics, 'model_errors': errors, 'progress': progress,
            'source': 'GitHub Actions anotasyonları', 'source_url': RUN_URL,
            'checked_at': datetime.now(timezone.utc).isoformat()}


_lock = threading.Lock()
_cache = {'at': 0.0, 'value': None}
_live_cache = {'at': 0.0, 'value': None}
_rehearsal = {'status': 'not_started', 'result': None, 'error': None}


def cached_github():
    with _lock:
        if _cache['value'] and time.monotonic() - _cache['at'] < 30:
            return _cache['value']
    state = github_state()
    with _lock:
        _cache.update(at=time.monotonic(), value=state)
    return state


def live_github_state():
    """Mevcut dal commit'indeki en son paper check durumunu oku."""
    pinned_run = os.environ.get('PAPER_RUN_ID', '')
    if pinned_run:
        if not pinned_run.isdigit():
            raise ValueError('Geçersiz koşu kimliği')
        run_meta = gh_json('run', 'view', pinned_run, '--json', 'headSha')
        sha = run_meta['headSha']
    else:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                             text=True, timeout=10, check=True).stdout.strip()
    checks = gh_json('api', f'repos/elifbot/elifbot/commits/{sha}/check-runs?per_page=100')
    candidates = [c for c in checks.get('check_runs', [])
                  if re.fullmatch(r'TradingAgents Paper \d+', c.get('name', ''))
                  and (not pinned_run or c.get('name') == f'TradingAgents Paper {pinned_run}')]
    if not candidates:
        return {'status': 'waiting', 'message': 'Canlı testin başlatılması bekleniyor.'}
    check = max(candidates, key=lambda c: c['id'])
    state = json.loads((check.get('output') or {}).get('summary') or '{}')
    if state.get('kind') != 'okx-live-paper' or not str(state.get('run_id', '')).isdigit():
        raise ValueError('Geçersiz canlı test verisi')
    run_id = str(state['run_id'])
    run = gh_json('run', 'view', run_id, '--json', 'status,conclusion,url')
    return {'status': state.get('status', 'unknown'), 'data': state, 'run': run,
            'checked_at': datetime.now(timezone.utc).isoformat()}


def cached_live():
    with _lock:
        if _live_cache['value'] and time.monotonic() - _live_cache['at'] < 10:
            return _live_cache['value']
    value = live_github_state()
    with _lock:
        _live_cache.update(at=time.monotonic(), value=value)
    return value


def technical_rehearsal():
    """Gerçek TradingAgents grafiği + sahte, deterministik model ve sentetik fiyatlar.

    Prova yalnızca bağlantı/işleyiş denetimidir. Sonuç gerçek bot performansı
    veya gerçek piyasa verisi olarak kullanılmamalıdır.
    """
    from langchain_core.messages import AIMessage
    from bot.tradingagents_paper.agents import create_graph, decide
    from bot.tradingagents_paper.paper import Instrument, PaperBook, accepts_signal
    from bot.tradingagents_paper.run import signal

    class FakeLLM:
        def __init__(self, rating):
            self.rating = rating
            self.calls = 0

        def with_structured_output(self, *args, **kwargs):
            raise NotImplementedError('teknik prova için sahte model')

        def invoke(self, *args, **kwargs):
            self.calls += 1
            return AIMessage(content=f'Rating: {self.rating}\nSentetik teknik prova kararı.')

    cases = [('DEMO-LONG', 1, 101.0, 'Buy'), ('DEMO-SHORT', -1, 99.0, 'Sell')]
    book, events = PaperBook(), []
    prices = {}
    total_calls = 0
    for name, expected_direction, last_price, rating in cases:
        ticks = [(0, 100.0), (60, last_price)]
        candidate = signal(ticks)
        if candidate is None or candidate['direction'] != expected_direction:
            raise RuntimeError('Sentetik sinyal testi beklenmedik sonuç verdi')
        events.append({'step': 'Sinyal', 'symbol': name,
                       'detail': f"{'LONG' if expected_direction == 1 else 'SHORT'} · sentetik fiyat {last_price}"})
        fake = FakeLLM(rating)
        graph = create_graph('mock', fake)
        final_rating, _, _ = decide(graph, name, json.dumps({'signal': candidate, 'synthetic': True}))
        total_calls += fake.calls
        if not accepts_signal(final_rating, candidate['direction']):
            raise RuntimeError('Prova model kararı sinyalle uyuşmadı')
        events.append({'step': 'Değerlendirme', 'symbol': name,
                       'detail': f'{final_rating} · sahte model, {fake.calls} ajan çağrısı'})
        inst = Instrument(name, .1, .01, .01)
        prices[name] = last_price
        if not book.open(inst, last_price, prices, candidate['direction'], now=60):
            raise RuntimeError('Sanal defter provasında pozisyon açılamadı')
        events.append({'step': 'Sanal açılış', 'symbol': name,
                       'detail': f"{'LONG' if expected_direction == 1 else 'SHORT'} · yalnızca prova"})
        # Prices fixed in advance. This is an implementation check, not a return measurement.
        exit_price = last_price * (1 + expected_direction * .001)
        prices[name] = exit_price
        close = book.close(book.events[-1]['position_id'], exit_price, 'prova_sonu', now=65)
        events.append({'step': 'Sanal kapanış', 'symbol': name,
                       'detail': f"{close['net']:+.4f} $ · sentetik; performans değil"})
    return {'kind': 'synthetic_rehearsal', 'model': 'Sahte / deterministik', 'market': 'Sentetik',
            'agent_calls': total_calls, 'events': events, 'closed': len(book.closed),
            'finished_at': datetime.now(timezone.utc).isoformat()}


def start_rehearsal():
    with _lock:
        if _rehearsal['status'] == 'running':
            return False
        _rehearsal.update(status='running', result=None, error=None)
    def work():
        try:
            result = technical_rehearsal()
            with _lock:
                _rehearsal.update(status='completed', result=result, error=None)
        except Exception as exc:
            with _lock:
                _rehearsal.update(status='failed', result=None, error=f'{type(exc).__name__}: {exc}')
    threading.Thread(target=work, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/index.html'):
            data = PAGE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/api/github':
            try:
                self.send_json(cached_github())
            except (OSError, subprocess.SubprocessError, ValueError):
                self.send_json({'error': 'GitHub koşu verisi alınamadı.', 'source_url': RUN_URL}, 503)
        elif path == '/api/live':
            try:
                self.send_json(cached_live())
            except (OSError, subprocess.SubprocessError, ValueError):
                self.send_json({'status': 'unavailable', 'error': 'Canlı koşu verisi alınamadı.'}, 503)
        elif path == '/api/rehearsal':
            with _lock:
                value = dict(_rehearsal)
            self.send_json(value)
        else:
            self.send_json({'error': 'Bulunamadı'}, 404)

    def do_POST(self):
        if urlsplit(self.path).path != '/api/rehearsal':
            return self.send_json({'error': 'Bulunamadı'}, 404)
        # No cross-site form submission to the state-changing endpoint.
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        if not origin or urlsplit(origin).netloc != host:
            return self.send_json({'error': 'Geçersiz kaynak'}, 403)
        started = start_rehearsal()
        self.send_json({'started': started}, 202 if started else 409)

    def log_message(self, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', default=8000, type=int)
    args = parser.parse_args()
    start_rehearsal()
    print(f'TradingAgents panel başlatıldı; port {args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
