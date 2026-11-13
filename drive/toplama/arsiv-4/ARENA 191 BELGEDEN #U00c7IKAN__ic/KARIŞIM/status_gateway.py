#!/usr/bin/env python3
"""Birleşik deftere yalnız loopback, bearer-korumalı salt-okunur status gateway.
Varsayılan olarak çalışmaz ve borsa/veri akışı başlatmaz. TLS/reverse proxy ayrı.
"""
import argparse,hmac,json,os,re,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from acar.unified_simulator import UnifiedSimulator
from acar.omnistudio_contract import build_omni_status

def validate_token(token):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):raise ValueError('gateway token missing or invalid')
    return token

class ReadOnlyStatusServer(ThreadingHTTPServer):
    def __init__(self,port,db,token):
        if type(port) is not int or not 0<=port<=65535:raise ValueError('invalid port')
        self.token=validate_token(token);self.sim=UnifiedSimulator(db)
        self.panel=(Path(__file__).resolve().parent/'web'/'birlesik_panel.html').read_bytes()
        super().__init__(('127.0.0.1',port),Handler)

class Handler(BaseHTTPRequestHandler):
    server_version='ACARStatus/1'
    sys_version=''
    def log_message(self,*args):pass
    def _send(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def _authenticated(self):
        headers=self.headers.get_all('Authorization',[])
        if len(headers)!=1:return False
        try:return hmac.compare_digest(headers[0].encode('utf-8'),('Bearer '+self.server.token).encode('utf-8'))
        except (UnicodeError,TypeError):return False
    def do_GET(self):
        if self.path=='/':
            body=self.server.panel;self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(body);return
        if not self._authenticated():self._send(401,{'error':'unauthorized'});return
        if self.path!='/v1/status':self._send(404,{'error':'not_found'});return
        try:self._send(200,build_omni_status(self.server.sim.snapshot(),int(time.time())))
        except Exception:self._send(503,{'error':'status_unavailable'})
    def do_POST(self):self._send(405,{'error':'read_only'})
    def do_PUT(self):self._send(405,{'error':'read_only'})
    def do_DELETE(self):self._send(405,{'error':'read_only'})

def main():
    parser=argparse.ArgumentParser(description='Salt-okunur, yalnız loopback gateway. Token ortam değişkeninden alınır.')
    parser.add_argument('--db',required=True);parser.add_argument('--port',type=int,default=8091)
    args=parser.parse_args()
    try:server=ReadOnlyStatusServer(args.port,args.db,os.environ.get('ACAR_GATEWAY_TOKEN',''))
    except (OSError,ValueError) as e:raise SystemExit('Gateway başlatılamadı: '+str(e)) from None
    print('Salt-okunur status gateway yalnız 127.0.0.1 üzerinde hazır.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
