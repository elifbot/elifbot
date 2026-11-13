import json,time,sqlite3,urllib.request,urllib.error,subprocess
from pathlib import Path
E=Path(__file__).resolve().parent;DB=E/'paper10m_state.db';BASE='http://127.0.0.1:8080';NAME='kripto-v945-paper10m-tekrar-20261103'
started=time.monotonic();last_health=last_state=0.;previous_poll=None;latest={};known={};counts={'http_200':0,'http_503':0,'http_errors':0,'pending_http_matches':0,'db_errors':0};max_gap=0.;status='RUNNING'
def record(name,body):
 with (E/name).open('a') as f:f.write(json.dumps({'observed_at_epoch':time.time(),'observer_monotonic':time.monotonic(),**body},ensure_ascii=False)+'\n')
def fetch(path):
 try:
  with urllib.request.urlopen(BASE+path,timeout=2) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
while time.monotonic()-started<900:
 if (E/'paper10m_summary.json').exists():
  status='FINISHED_SUMMARY_FOUND';break
 mono=time.monotonic()
 if previous_poll is not None:
  gap=mono-previous_poll;max_gap=max(max_gap,gap)
  if gap>5:record('gaps.jsonl',{'gap_sec':gap})
 previous_poll=mono;pending={}
 if DB.exists():
  try:
   c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=.1);c.row_factory=sqlite3.Row
   try:
    for table in ('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents'):
     for row in c.execute('SELECT * FROM '+table+" WHERE status='PENDING'"):
      p=dict(row)|{'table':table};key=table+':'+p['operation_id'];pending[key]=p
      if key not in known:record('pending.jsonl',{'event':'seen','key':key,**p});known[key]=p
    for key,p in list(known.items()):
     if key not in pending:
      row=c.execute('SELECT status FROM '+p['table']+' WHERE operation_id=?',(p['operation_id'],)).fetchone()
      record('pending.jsonl',{'event':'terminal','key':key,'status':row['status'] if row else 'ABSENT_NOT_PROOF_OF_CANCEL'});known.pop(key)
   finally:c.close()
  except Exception as exc:counts['db_errors']+=1;record('errors.jsonl',{'type':'db','error':repr(exc)})
 if mono-last_health>=(.25 if pending else 1):
  begin=time.monotonic();request_start_epoch=time.time()
  try:
   code,body=fetch('/health');counts['http_200' if code==200 else 'http_503' if code==503 else 'http_errors']+=1
   matches=[p for p in body.get('pending_operations',[]) if code==200 and body.get('ledger_status')=='IN_FLIGHT' and body.get('ledger_reconciled') is False and p.get('owned_by_this_process') and 0<=p.get('age_sec',100)<15]
   counts['pending_http_matches']+=bool(matches)
   record('health.jsonl',{'http_status':code,'response_ms':1000*(time.monotonic()-begin),'phase_at_last_state':latest.get('phase'),'elapsed_at_last_state':latest.get('elapsed_sec'),'body':body,'pending_matches':matches})
  except Exception as exc:counts['http_errors']+=1;record('errors.jsonl',{'type':'http','error':repr(exc),'request_start_epoch':request_start_epoch,'request_elapsed_ms':1000*(time.monotonic()-begin)})
  last_health=time.monotonic()
 if mono-last_state>=5:
  try:
   code,latest=fetch('/api/state');record('state.jsonl',{'http_status':code,'state':latest});(E/'latest_state.json').write_text(json.dumps(latest,ensure_ascii=False,indent=2))
  except Exception as exc:record('errors.jsonl',{'type':'state','error':repr(exc)})
  last_state=time.monotonic()
 (E/'progress.json').write_text(json.dumps({'status':status,'counts':counts,'elapsed_sec':latest.get('elapsed_sec'),'phase':latest.get('phase'),'max_observer_poll_gap_sec':max_gap,'observed_at_epoch':time.time()},indent=2))
 if (E/'paper10m_summary.json').exists():
  s=json.loads((E/'paper10m_summary.json').read_text());status='FINISHED_SUMMARY_FOUND';break
 if (E/'launcher_receipt.json').exists() and not (E/'paper10m_summary.json').exists():
  status='RUNNER_STOPPED_WITHOUT_SUMMARY';break
 time.sleep(.25)
else:status='OBSERVER_WATCHDOG_TIMEOUT'
(E/'observer_final.json').write_text(json.dumps({'status':status,'counts':counts,'max_observer_poll_gap_sec':max_gap,'observer_elapsed_monotonic_sec':time.monotonic()-started},indent=2))
print('OBSERVER_DONE',status,counts,flush=True)
