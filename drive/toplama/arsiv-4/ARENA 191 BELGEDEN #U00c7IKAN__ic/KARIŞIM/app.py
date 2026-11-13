#!/usr/bin/env python3
"""Acar Paper — salt okunur dashboard + tek işçi PAPER bot."""
import argparse,copy,fcntl,json,logging,os,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from acar import market
from acar.engine import process,unrealized
from acar.store import Store
from acar.indicators import technical_snapshot

ROOT=Path(__file__).resolve().parent
class Worker:
 def __init__(self,store):
  self.store=store;self.lock=threading.RLock();self.view={'status':'BASLATILIYOR','message':'Veri bağlantısı bekleniyor.','state':store.load(),'quote':None,'funding':None,'candles':[],'updated_at':None,'errors':[]};self.hard_error=False
 def snapshot(self):
  with self.lock:return copy.deepcopy(self.view)
 def run(self):
  bars=[]
  while True:
   start=time.time();errors=[];q=None;f=None;fresh_bars=False
   try:bars=market.candles();fresh_bars=True
   except Exception as e:errors.append('Mum verisi alınamadı ('+type(e).__name__+').')
   try:q=market.quote()
   except Exception as e:errors.append('Kotasyon alınamadı ('+type(e).__name__+').')
   try:f=market.funding()
   except Exception as e:errors.append('Funding verisi alınamadı ('+type(e).__name__+').')
   now=time.time()
   if q is not None and (now-q['time']>20 or q['time']-now>5):
    q=None;errors.append('Kotasyon işlenirken bayatladı.')
   try:
    state=self.store.load();ledger=self.store.audit()
    if not ledger['ok']:self.hard_error=True
    if not self.hard_error:
     new,events,trades=process(state,bars,q,f,now)
     self.store.commit(new,events,trades,expected_state=state,candles=bars if fresh_bars else None,captured_at=now);state=new
     ledger=self.store.audit()
    events,trades=self.store.latest(); candle_archive=self.store.candle_summary()
    eq=state['cash']+unrealized(state['position'],q) if q else None
    stale=not bars or now-(bars[-1].timestamp+60)>90
    if not ledger['ok']:status='DEFTER HATASI';message='Muhasebe tutarsız; kayıt değiştirilmedi, yeni işlem durduruldu.'
    elif self.hard_error:status='HATA';message='Kayıt hatası; worker durduruldu.'
    elif state['halt']:status='KILITLI';message='Yeni girişler kilitli: '+state['halt_reason']
    elif state['daily_halt']:status='RISK DURDURDU';message='Günlük zarar sınırı yeni girişleri durdurdu.'
    elif q is None or stale:status='VERI YOK';message='Taze mum/kotasyon yok; pozisyon izleme aksayabilir.'
    elif f is None:status='KORUMALI';message='Funding yok; yeni sanal giriş engellenir.'
    else:status='IZLIYOR';message='Kapalı mumlar ve halka açık kotasyonlar izleniyor.'
    view={'status':status,'message':message,'state':state,'quote':q,'funding':f,'candles':[{'time':b.timestamp,'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in bars[-120:]],'equity':eq,'events':events,'trades':trades,'ledger':ledger,'candle_archive':candle_archive,'indicators':technical_snapshot(bars),'updated_at':now,'errors':errors,'fresh_candles':fresh_bars,'mode':'PAPER','market':'BTC-USDT-SWAP','venue':'OKX PUBLIC'}
    with self.lock:self.view=view
   except Exception:
    logging.exception('Paper durumu kaydedilemedi; yeni işlem durduruldu.')
    self.hard_error=True
    with self.lock:self.view.update({'status':'HATA','message':'Defter / hesaplama hatası; işlem durduruldu.','updated_at':now})
   time.sleep(max(1,12-(time.time()-start)))

class Handler(BaseHTTPRequestHandler):
 worker=None
 def do_GET(self):
  if self.path in ('/','/index.html'):
   body=(ROOT/'web'/'index.html').read_bytes();typ='text/html; charset=utf-8'
  elif self.path=='/api/state':
   body=json.dumps(self.worker.snapshot(),ensure_ascii=False,allow_nan=False).encode();typ='application/json; charset=utf-8'
  elif self.path=='/health':
   body=b'{"service":"paper-dashboard","note":"not a trading readiness guarantee"}';typ='application/json'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=8000);ap.add_argument('--db',default='data/paper.sqlite');a=ap.parse_args()
 db=Path(a.db).resolve();db.parent.mkdir(parents=True,exist_ok=True)
 lock=open(str(db)+'.lock','a+')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('Bu PAPER defteri başka bir süreç tarafından kullanılıyor.')
 store=Store(db,time.time());worker=Worker(store);Handler.worker=worker
 threading.Thread(target=worker.run,daemon=True).start()
 server=ThreadingHTTPServer(('0.0.0.0',a.port),Handler)
 print(f'ACAR PAPER: http://0.0.0.0:{a.port} | BTC-USDT-SWAP | gerçek emir YOK',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close();lock.close()
if __name__=='__main__':main()
