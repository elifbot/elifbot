"""Supervise the real Freqtrade dry-run and publish compact read-only GitHub telemetry."""
import importlib.resources
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from .freqtrade_smoke import config

ROOT = Path('runs/freqtrade_30m').resolve()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_stats(db):
    if not db.exists():
        return {'database_ready': False}
    try:
        with sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=2) as con:
            con.row_factory = sqlite3.Row
            a = con.execute('''select count(*) as total, coalesce(sum(is_open),0) as open,
                sum(case when is_open=0 then 1 else 0 end) as closed,
                sum(case when is_open=0 and close_profit_abs>0 then 1 else 0 end) as wins,
                sum(case when is_open=0 and close_profit_abs<0 then 1 else 0 end) as losses,
                sum(case when is_open=0 then close_profit_abs else 0 end) as realized_profit
                from trades''').fetchone()
            recent = con.execute('''select id,pair,is_open,is_short,open_rate,close_rate,open_date,close_date,
                stake_amount,close_profit_abs,exit_reason from trades order by id desc limit 30''').fetchall()
            return {'database_ready': True, 'trades': dict(a), 'recent': [dict(x) for x in recent]}
    except sqlite3.Error as e:
        return {'database_ready': False, 'database_error': str(e)[:300]}


class Publisher:
    def __init__(self):
        self.repo = os.environ['GITHUB_REPOSITORY']
        self.sha = os.environ['GITHUB_SHA']
        self.run_id = os.environ['GITHUB_RUN_ID']
        self.token = os.environ['GH_TOKEN']
        if self.repo != 'elifbot/elifbot' or not self.run_id.isdigit() or not self.token:
            raise ValueError('Invalid GitHub context')
        d = self._call('POST', f'/repos/{self.repo}/check-runs', {'name': f'Freqtrade Paper {self.run_id}',
             'head_sha': self.sha, 'status': 'in_progress', 'output': {'title': 'Freqtrade · başlıyor', 'summary': '{}'}})
        self.check_id = d['id']

    def _call(self, method, path, data):
        req = urllib.request.Request('https://api.github.com' + path, method=method,
             data=json.dumps(data, ensure_ascii=False).encode(), headers={
                 'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + self.token,
                 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    def publish(self, state, final=False):
        body = {'output': {'title': 'Freqtrade · gerçek dry-run', 'summary': json.dumps(state, ensure_ascii=False)}}
        if final:
            body.update(status='completed', conclusion='success' if state['status'] == 'completed' else 'failure')
        self._call('PATCH', f'/repos/{self.repo}/check-runs/{self.check_id}', body)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'strategies').mkdir(exist_ok=True)
    source = importlib.resources.files('freqtrade.templates').joinpath('sample_strategy.py').read_text()
    if 'can_short: bool = False' not in source:
        raise RuntimeError('Upstream sample changed')
    (ROOT / 'strategies/SampleStrategy.py').write_text(source.replace('can_short: bool = False', 'can_short: bool = True', 1))
    cfg = config()
    if cfg['dry_run'] is not True or any(cfg['exchange'].get(k) for k in ('key','secret','password')) or cfg['max_open_trades'] != -1:
        raise RuntimeError('Paper güvenlik kontrolü başarısız')
    (ROOT / 'config.json').write_text(json.dumps(cfg, indent=2))
    db, logfile = ROOT / 'trades.dryrun.sqlite', ROOT / 'freqtrade.log'
    pub = Publisher()
    state = {'kind': 'freqtrade-live-paper', 'run_id': pub.run_id, 'status': 'starting',
             'updated_at': now_iso(), 'starting_usdt': 1_000_000, 'requested_seconds': 1800,
             'scope': 'USDT-settled linear swaps; not dated or inverse contracts',
             'strategy': 'Freqtrade SampleStrategy (short enabled), 5m', 'no_total_trade_cap': True,
             'one_open_trade_per_pair': True, 'margin_mode': 'isolated',
             'leverage_note': 'Freqtrade sample default leverage', 'database_ready': False}
    proc = None
    started = None
    launched = time.monotonic()
    success = False
    try:
        with (ROOT / 'console.txt').open('w') as console:
            proc = subprocess.Popen(['freqtrade','trade','--userdir',str(ROOT), '--config',str(ROOT/'config.json'),
                    '--strategy','SampleStrategy','--db-url',f'sqlite:///{db}','--logfile',str(logfile)],
                    stdout=console, stderr=subprocess.STDOUT)
            next_publish = 0
            while True:
                t = time.monotonic()
                if proc.poll() is not None:
                    state['failure'] = f'Freqtrade exited prematurely ({proc.returncode})'
                    break
                text = ''
                if logfile.exists():
                    with logfile.open('rb') as f:
                        f.seek(0, 2); f.seek(max(0, f.tell()-100000)); text = f.read().decode(errors='replace')
                if started is None and "state='RUNNING'" in text:
                    started = t
                    state['started_at'] = now_iso()
                if started is None and t - launched > 600:
                    state['failure'] = 'No RUNNING heartbeat within 600 seconds'
                    break
                if started is not None and t - started >= 1800:
                    success = True
                    break
                if t >= next_publish:
                    state.update(status='running' if started else 'starting', updated_at=now_iso(),
                                 seconds=round(t-started) if started else 0, **read_stats(db))
                    try:
                        pub.publish(state)
                    except Exception as e:
                        print('Telemetry error:', type(e).__name__, flush=True)
                    next_publish = t + 12
                time.sleep(2)
    finally:
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try: proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
        state.update(status='completed' if success else 'failed', updated_at=now_iso(),
                     seconds=round(time.monotonic()-started) if started else 0, **read_stats(db))
        if not success:
            log = logfile if logfile.exists() else ROOT/'console.txt'
            if log.exists():
                lines = log.read_text(errors='replace').splitlines()
                state['errors'] = [x[:400] for x in lines if 'ERROR' in x or 'CRITICAL' in x][-5:]
        (ROOT / 'report.json').write_text(json.dumps(state, ensure_ascii=False, indent=2))
        try: pub.publish(state, final=True)
        except Exception as e: print('Final telemetry error:', type(e).__name__, flush=True)
        print('::notice title=Freqtrade Paper özeti::' + json.dumps(state, ensure_ascii=False)[:3500], flush=True)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
