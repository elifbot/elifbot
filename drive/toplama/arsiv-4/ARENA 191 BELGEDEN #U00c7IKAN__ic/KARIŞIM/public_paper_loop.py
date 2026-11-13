"""Optional supervised public-data PAPER worker; disabled until explicitly confirmed."""
import argparse,json,signal,sys,time,uuid,sqlite3
from decimal import Decimal,InvalidOperation
from pathlib import Path
from acar.okx_public_adapter import PublicClient,symbol_ok
from acar.public_paper_once import public_paper_once
from acar.unified_simulator import UnifiedSimulator
from acar.worker_lock import WorkerLock

def load_config(path):
 data=json.loads(Path(path).read_text(encoding='utf-8'))
 if not isinstance(data,dict) or set(data)!={'poll_seconds','instruments'}:raise ValueError('config keys: poll_seconds, instruments')
 interval=data['poll_seconds'];entries=data['instruments']
 if type(interval) is not int or not 5<=interval<=30:raise ValueError('poll_seconds must be 5..30')
 if not isinstance(entries,list) or not 1<=len(entries)<=4:raise ValueError('one to four instruments required')
 seen=set()
 for x in entries:
  if not isinstance(x,dict) or set(x)!={'symbol','quantity','leverage','min_notional'}:raise ValueError('invalid instrument fields')
  symbol_ok(x['symbol'])
  if x['symbol'] in seen:raise ValueError('duplicate symbol')
  seen.add(x['symbol'])
  for field in ('quantity','leverage','min_notional'):
   value=x[field]
   if not isinstance(value,str) or len(value)>40:raise ValueError('amounts must be short decimal strings')
   try:d=Decimal(value)
   except InvalidOperation:raise ValueError('invalid amount') from None
   if not d.is_finite() or d<0 or (field!='min_notional' and d==0):raise ValueError('invalid amount')
 return data

def run_cycle(sim,config,client,clock_ms=None,emit=print):
 """Monitor every open position first; no expensive entry scans while exposed."""
 entries={x['symbol']:x for x in config['instruments']}
 def position_set():return set(sim.snapshot()['state']['positions'])
 current=position_set();missing=current-set(entries)
 if missing:
  # main() attempts a persistent account lock and stops. Never silently leave
  # an old position unmonitored when configuration changes.
  raise ValueError('open position not covered by worker configuration')
 ordered=sorted(current)+[x['symbol'] for x in config['instruments'] if x['symbol'] not in current]
 results=[]
 for symbol in ordered:
  positions=position_set()
  if positions-set(entries):raise ValueError('open position not covered by worker configuration')
  # While exposed, complete_history may require many sequential network calls;
  # do not put open positions at risk by scanning unoccupied markets.
  if symbol not in positions and positions:
   result={'action':'SKIP','reason':'OPEN_POSITION_MONITOR_PRIORITY'}
  else:
   kw=dict(entries[symbol]);kw['client']=client
   if clock_ms is not None:kw['clock_ms']=clock_ms
   result=public_paper_once(sim,**kw)
  results.append(result)
  emit(json.dumps({'symbol':symbol,'action':result.get('action'),'reason':result.get('reason')},ensure_ascii=False),flush=True)
 return results

def main(argv=None):
 ap=argparse.ArgumentParser(description='AÇIK onay olmadan başlamayan, yalnız public veri ve sanal işlemler kullanan worker')
 ap.add_argument('--db',required=True);ap.add_argument('--config',required=True);ap.add_argument('--confirm-public-paper',action='store_true');a=ap.parse_args(argv)
 if not a.confirm_public_paper:
  print('Ağ veya PAPER başlatılmadı. --confirm-public-paper gereklidir.',file=sys.stderr);return 2
 try:config=load_config(a.config)
 except (OSError,ValueError,TypeError) as e:print('Geçersiz yapılandırma: '+str(e),file=sys.stderr);return 2
 try:
  with WorkerLock(a.db):
   sim=UnifiedSimulator(a.db);client=PublicClient();stop=[False]
   def handler(*_):stop[0]=True
   old_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
   signal.signal(signal.SIGINT,handler);signal.signal(signal.SIGTERM,handler)
   try:
    while not stop[0]:
     started=time.monotonic()
     try:run_cycle(sim,config,client)
     except Exception as e:
      # Never fabricate closure. Even the emergency lock can fail (e.g. DB I/O error).
      locked=False
      try:
       if sim.snapshot()['state']['positions']:
        sim.lock_entries('worker-error:'+uuid.uuid4().hex,'WORKER_ERROR',int(time.time()));locked=True
      except Exception:pass
      print(json.dumps({'action':'WORKER_STOPPED','reason':type(e).__name__,'lock_written':locked}),file=sys.stderr,flush=True);return 1
     if not stop[0]:time.sleep(max(1,config['poll_seconds']-(time.monotonic()-started)))
    return 0
   finally:
    for sig,previous in old_handlers.items():signal.signal(sig,previous)
 except (BlockingIOError,ValueError,OSError,sqlite3.Error) as e:print('Worker başlatılamadı: '+type(e).__name__,file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
