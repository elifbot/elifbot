"""Readonly UI resume AFTER the run. Imports no bot code, touches no exchange/SQLite, never starts trading."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import ast,json
E=Path(__file__).resolve().parent;B=E.parent/'kripto-bot-v9.5.3-paper-rc1'
tree=ast.parse((B/'src/live_runner.py').read_text())
page=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DASHBOARD_HTML' for t in n.targets)))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=urlsplit(self.path).path;code=200;kind='application/json; charset=utf-8'
        done=(E/'process_result.json').exists();snapshot=E/'natural10m_continuity_summary.json'
        if path=='/health':body=json.dumps({'status':'ok','scope':'Preview readiness ONLY, NOT bot/feed health','trading_running':False,'read_only':True,'run_result_exists':done}).encode()
        elif not done or not snapshot.exists():code=503;body=b'{"status":"No final snapshot yet; this server NEVER starts or resumes trading"}'
        elif path in ('/','/index.html'):body=page.encode();kind='text/html; charset=utf-8'
        elif path=='/api/state':
            s=json.loads(snapshot.read_text());s['position_lifecycle']['monitoring_active']=False
            s['entry_admission']['allowed']=False;s['preview']={'read_only':True,'trading_running':False,'prices_are_live':False}
            body=json.dumps(s,ensure_ascii=False).encode()
        else:code=404;body=b'{}'
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)

if __name__=='__main__':
    print('Readonly final-snapshot viewer at 0.0.0.0:8080; NO bot restart',flush=True)
    ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()
