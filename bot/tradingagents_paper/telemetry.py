"""Koşu telemetrisini GitHub Checks üzerinden panele taşır.

Yalnızca GitHub'ın verdiği kısa ömürlü job token kullanılır. Piyasa veya emir
anahtarı yoktur. Yayınlanan veriler herkese açık depo içinde görünürdür.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


class CheckPublisher:
    def __init__(self, token, repository, sha, run_id, interval=12):
        if repository != 'elifbot/elifbot' or not token or not sha or not str(run_id).isdigit():
            raise ValueError('Geçersiz GitHub koşu kimliği')
        self.token = token
        self.repository = repository
        self.run_id = str(run_id)
        self.interval = interval
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.closed = False
        self.state = {'kind': 'okx-live-paper', 'run_id': self.run_id, 'status': 'starting',
                      'source': 'GitHub Actions / OKX public REST', 'recent': [], 'model_errors': 0}
        created = self._request('POST', f'/repos/{repository}/check-runs', {
            'name': f'TradingAgents Paper {run_id}', 'head_sha': sha, 'status': 'in_progress',
            'output': {'title': 'OKX paper · başlatılıyor', 'summary': json.dumps(self.state)}})
        self.check_id = created['id']
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('GH_TOKEN', ''), os.environ.get('GITHUB_REPOSITORY', ''),
                   os.environ.get('GITHUB_SHA', ''), os.environ.get('GITHUB_RUN_ID', ''))

    def _request(self, method, path, payload):
        req = urllib.request.Request('https://api.github.com' + path,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.load(res)

    def record(self, event):
        event = dict(event)
        kind = event.get('type')
        with self.lock:
            state = self.state
            state['updated_at'] = datetime.now(timezone.utc).isoformat()
            if kind == 'start':
                state.update(status='running', universe=event.get('universe'),
                             supported=event.get('supported'), duration_seconds=event.get('duration_seconds'),
                             model=event.get('model'), started_at=event.get('time'))
            elif kind == 'progress':
                state.update({k: event.get(k) for k in ('seconds', 'universe', 'fresh_symbols', 'signals',
                              'queued', 'stale_signals', 'decisions', 'open_positions', 'cash', 'equity')})
            elif kind == 'agent_error':
                state['model_errors'] += 1
                state['last_error'] = str(event.get('error', 'model hatası'))[:300]
            elif kind == 'finish':
                state.update(status='completed' if event.get('valid') else 'failed',
                             decisions=event.get('decisions'), signals=event.get('signals'),
                             open_positions=event.get('open_positions'), closed=event.get('closed'),
                             equity=event.get('equity'), usable_decisions=event.get('usable_decisions'))
            if kind in ('analysis_started', 'decision', 'agent_error', 'paper_open', 'paper_close',
                        'paper_rejected', 'skip_stale', 'signal_rejected_by_agent', 'data_error'):
                # Reports/prompts can be very long; telemetry only needs a compact audit trail.
                state['recent'].append({k: event.get(k) for k in ('time', 'type', 'symbol', 'direction',
                                       'rating', 'error', 'reason', 'net', 'age_seconds') if k in event})
                state['recent'] = state['recent'][-25:]

    def _publish(self, completed=False):
        with self.lock:
            snapshot = json.loads(json.dumps(self.state))
        payload = {'output': {'title': 'OKX paper test · canlı durum',
                              'summary': json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))}}
        if completed:
            payload.update(status='completed', conclusion='success' if snapshot['status'] == 'completed' else 'failure')
        self._request('PATCH', f'/repos/{self.repository}/check-runs/{self.check_id}', payload)

    def _loop(self):
        while not self.done.wait(self.interval):
            try:
                self._publish()
            except (OSError, ValueError) as e:
                print(f'Telemetri güncellenemedi: {type(e).__name__}', flush=True)

    def finish(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.state['status'] in ('starting', 'running'):
                self.state['status'] = 'failed'
                self.state['last_error'] = 'Koşu sonuç üretmeden durdu.'
        self.done.set()
        self.thread.join(timeout=12)
        try:
            self._publish(completed=True)
        except (OSError, ValueError) as e:
            print(f'Telemetri son durumu yayınlanamadı: {type(e).__name__}', flush=True)
