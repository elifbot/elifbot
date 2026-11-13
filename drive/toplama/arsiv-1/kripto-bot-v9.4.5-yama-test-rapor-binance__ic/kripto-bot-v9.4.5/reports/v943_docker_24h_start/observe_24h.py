"""External read-only PENDING-focused observer. Never creates orders or DB rows."""
import json,time,sqlite3,urllib.request,urllib.error,subprocess,os
from pathlib import Path
E=Path('/home/user/v943-long-paper-evidence');DB=E/'paper24h_state.db'
NAME='kripto-v943-paper24h-20261103';BASE='http://127.0.0.1:8080'
TABLES=('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents')
plan=json.loads((E/'preregistered_24h_plan.json').read_text())
known={};last_health=0;last_state=0;last_docker=0;last_progress=0;last_pending={};docker_logs=set()
count={'health_samples':0,'http_200':0,'http_503':0,'http_errors':0,'owned_young_pending_http200':0,'real_closed_trades':0,'natural_entry_fills':0,'pending_events':0,'db_read_errors':0}
first_pending_matches=set();latest={};start=time.time();stopped_at=None

def record(name,row):
 row={'observed_at_epoch':time.time(),**row}
 with (E/name).open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')

def fetch(path):
 try:
  with urllib.request.urlopen(BASE+path,timeout=2) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read().decode())

def scan():
 if not DB.exists():return {}
 c=sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1);c.row_factory=sqlite3.Row
 try:
  c.execute('BEGIN');current={}
  for table in TABLES:
   for r in c.execute('SELECT operation_id,symbol,status,created_at FROM '+table+" WHERE status='PENDING'"):
    key=table+':'+r['operation_id'];current[key]=dict(r)|{'table':table}
   for key,item in list(known.items()):
    if item['table']!=table:continue
    row=c.execute('SELECT status FROM '+table+' WHERE operation_id=?',(item['operation_id'],)).fetchone()
    terminal=row['status'] if row else 'ABSENT_AFTER_PENDING'
    if terminal!='PENDING':
     record('pending_events.jsonl',{'event':'pending_terminal','key':key,'status':terminal,'note':'absence alone does not prove cancellation'});known.pop(key,None)
  return current
 finally:c.close()

while time.time()-start<plan['duration_sec']+plan['max_drain_sec']+600:
 now=time.time()
 try:
  current=scan()
  for key,item in current.items():
   if key not in known:
    known[key]=item;count['pending_events']+=1;record('pending_events.jsonl',{'event':'pending_seen','key':key,**item})
 except Exception as exc:
  current={};count['db_read_errors']+=1;record('observer_errors.jsonl',{'type':'db_read','error':repr(exc)})
 interval=.5 if current else 5.
 if now-last_health>=interval:
  try:
   request_start=time.perf_counter();code,h=fetch('/health');response_ms=(time.perf_counter()-request_start)*1000;last_health=time.time();count['health_samples']+=1
   if code==200:count['http_200']+=1
   elif code==503:count['http_503']+=1
   matches=[]
   for p in h.get('pending_operations',[]):
    key=p['table']+':'+p['operation_id']
    if key in current and code==200 and h.get('ledger_status')=='IN_FLIGHT' and not h.get('ledger_reconciled') and p.get('owned_by_this_process') and p.get('age_sec',100)>=0 and p.get('age_sec',100)<15:
     matches.append(key);first_pending_matches.add(key);count['owned_young_pending_http200']+=1
   record('health_events.jsonl',{'http_status':code,'response_ms':response_ms,'db_pending_keys':list(current),'matched_pending_keys':matches,'body':h})
  except Exception as exc:
   last_health=time.time();count['http_errors']+=1;record('observer_errors.jsonl',{'type':'http_health','error':repr(exc)})
 if now-last_state>=15:
  try:
   _,s=fetch('/api/state');latest=s
   count['real_closed_trades']=s['closed_count'];count['natural_entry_fills']=s['analytics']['maker_queue']['filled']
   record('state_samples.jsonl',{'state':s})
   tmp=E/'latest_state.tmp';tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2));tmp.replace(E/'latest_state.json')
  except Exception as exc:record('observer_errors.jsonl',{'type':'http_state','error':repr(exc)})
  last_state=time.time()
 if now-last_docker>=20:
  try:
   obj=json.loads(subprocess.check_output(['sudo','-n','docker','inspect',NAME],text=True,timeout=5))[0]
   state=obj['State'];record('docker_health_history.jsonl',{'running':state['Running'],'status':state['Status'],'health':state.get('Health'),'restart_count':obj['RestartCount'],'exit_code':state['ExitCode'],'oom_killed':state.get('OOMKilled')})
   if not state['Running']:
    stopped_at=stopped_at or time.time()
    (E/'container_final_inspect.json').write_text(json.dumps(obj,indent=2))
  except Exception as exc:record('observer_errors.jsonl',{'type':'docker_inspect','error':repr(exc)})
  last_docker=time.time()
 if now-last_progress>=5:
  summary_path=E/'paper24h_summary.json';finished=json.loads(summary_path.read_text()) if summary_path.exists() else None
  completed=bool(finished and finished.get('phase')=='COMPLETED' and finished['elapsed_sec']-finished.get('drain_elapsed_sec',0)>=plan['duration_sec'])
  progress={'status':'COMPLETED' if completed else ('INTERRUPTED' if stopped_at else 'RUNNING'),'observed_at_epoch':time.time(),'plan_sha256':plan['plan_identity'],'counts':count,'matched_pending_operation_ids':sorted(first_pending_matches),
   'live_pending_http_observed':bool(first_pending_matches),'live_open_close_cycle_observed':count['natural_entry_fills']>0 and count['real_closed_trades']>0,
   'long_run_complete':completed,'real_money_approved':False,'elapsed_sec':(latest or {}).get('elapsed_sec'),'event_sufficiency_not_profitability':True}
  if completed:progress['minimum_event_evidence_met']=bool(first_pending_matches) and count['natural_entry_fills']>0 and count['real_closed_trades']>0
  tmp=E/'progress.tmp';tmp.write_text(json.dumps(progress,ensure_ascii=False,indent=2));tmp.replace(E/'progress.json')
  last_progress=time.time()
  if completed or (stopped_at and now-stopped_at>20):break
 time.sleep(.25)
print('OBSERVER_FINISHED; see progress.json')
