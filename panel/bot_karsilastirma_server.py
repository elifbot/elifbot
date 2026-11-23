"""Read-only Arena view of a pinned GitHub compatibility run, never issues trades."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
RUN_ID = os.environ.get('BOT_PROBE_RUN_ID', '')
if not RUN_ID.isdigit():
    raise SystemExit('BOT_PROBE_RUN_ID must be numeric')
FREQ_RUN_ID = os.environ.get('FREQ_RUN_ID', '')
if FREQ_RUN_ID and not FREQ_RUN_ID.isdigit():
    raise SystemExit('FREQ_RUN_ID must be numeric')
PAGE = Path(__file__).with_name('bot_karsilastirma.html')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        elif self.path == '/api/status':
            try:
                r = subprocess.run(['gh', 'run', 'view', RUN_ID, '--json',
                                    'status,conclusion,url,createdAt,updatedAt,jobs'],
                                   cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
                run = json.loads(r.stdout)
                jobs = [{'name': j['name'], 'status': j['status'], 'conclusion': j['conclusion'],
                         'steps': [{'name': s['name'], 'status': s['status'], 'conclusion': s['conclusion']}
                                   for s in j.get('steps', [])]}
                        for j in run.get('jobs', []) if 'kurulum ve OKX erişimi' in j.get('name', '')]
                freq = None
                if FREQ_RUN_ID:
                    try:
                        p = subprocess.run(['gh', 'run', 'view', FREQ_RUN_ID, '--json', 'status,conclusion,url,jobs,headSha'],
                                           cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
                        f = json.loads(p.stdout)
                        active = [step['name'] for job in f.get('jobs', []) if 'freqtrade-uzun-paper' in job.get('name', '')
                                  for step in job.get('steps', []) if step['status'] == 'in_progress']
                        freq = {k: f.get(k) for k in ('status', 'conclusion', 'url')}
                        freq['active_steps'] = active
                        checks = subprocess.run(['gh', 'api', f"repos/elifbot/elifbot/commits/{f['headSha']}/check-runs?per_page=100"],
                                                cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
                        candidates = [c for c in json.loads(checks.stdout).get('check_runs', [])
                                      if c.get('name') == f'Freqtrade Paper {FREQ_RUN_ID}']
                        if candidates:
                            summary = (max(candidates, key=lambda c: c['id']).get('output') or {}).get('summary') or '{}'
                            report = json.loads(summary)
                            if report.get('kind') == 'freqtrade-live-paper':
                                freq['report'] = report
                    except Exception:
                        freq = {'status': 'unknown', 'error': 'Freqtrade koşusu sorgulanamadı'}
                body = json.dumps({'run': {k: run.get(k) for k in ('status','conclusion','url','createdAt','updatedAt')},
                                   'jobs': jobs, 'freqtrade_smoke': freq, 'checked_at': time.time()}, ensure_ascii=False).encode()
                self.send_response(200)
            except Exception as e:
                body = json.dumps({'error': 'GitHub durumuna ulaşılamadı: ' + type(e).__name__}).encode()
                self.send_response(503)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
        else:
            self.send_error(404)
            return
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    print('Bot karşılaştırma tanı paneli: 0.0.0.0:8001', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 8001), Handler).serve_forever()
