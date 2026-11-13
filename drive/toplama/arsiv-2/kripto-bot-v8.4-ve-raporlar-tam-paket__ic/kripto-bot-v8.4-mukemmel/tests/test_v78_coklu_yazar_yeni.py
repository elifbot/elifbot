"""Real independent subprocesses competing to create unresolved paper intents.

No market, API or key. This narrow experiment is NOT a multi-process account
ownership protocol or evidence that concurrent fills/commits are safe.
"""
import json,os,sqlite3,subprocess,sys
from pathlib import Path
from src.state_store import StateStore

ROOT=Path(__file__).resolve().parents[1]
WORKER=r'''
import json,sys
from src.state_store import StateStore
store=StateStore(sys.argv[1]);sym=sys.argv[2]
print('READY',flush=True)
sys.stdin.readline()
try:
 store.prepare_paper_open('operation-'+sym,{'symbol':sym,'qty':1,'price_hint':100,'side':'LONG'})
 print(json.dumps({'result':'prepared'}),flush=True)
except Exception as e:
 print(json.dumps({'result':'rejected','error':type(e).__name__,'message':str(e)}),flush=True)
'''

def test_iki_surec_ayni_anda_pending_kaydi_hazirlar(tmp_path):
 db=tmp_path/'multi.db'
 StateStore(db)
 ps=[subprocess.Popen([sys.executable,'-c',WORKER,str(db),sym],cwd=ROOT,env=os.environ.copy(),
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
     for sym in ('BTC/USDT','ETH/USDT')]
 try:
  for p in ps: assert p.stdout.readline().strip()=='READY'
  for p in ps:p.stdin.write('go\n');p.stdin.flush()
  results=[]
  for p in ps:
   p.stdin.close();p.stdin=None
   out,err=p.communicate(timeout=20)
   assert p.returncode==0,err
   results.append(json.loads(out.strip().splitlines()[-1]))
  assert sorted(r['result'] for r in results)==['prepared','rejected'],results
  with sqlite3.connect(db) as conn:
   rows=conn.execute("select symbol,status from paper_intents").fetchall()
  assert len(rows)==1 and rows[0][1]=='PENDING'
  assert StateStore(db).paper_requires_recovery()
 finally:
  for p in ps:
   if p.poll() is None:p.kill();p.wait()

WORKER_EXEC=r'''
import asyncio,json,sys
from pathlib import Path
from tests._paper_fixtures import make_paper_broker
from src.state_store import StateStore
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.sizing import PositionSizer
st=StateStore(sys.argv[1]);sym=sys.argv[2]
b=make_paper_broker(1000,fee_pct=.05)
r=RiskManager(leverage=10,dynamic_leverage_enabled=False)
sz=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=Path(sys.argv[3])/(sym.replace('/','_')+'.json'))
e=Executor(b,r,Strategy(),sizer=sz,state_store=st,protection_on=False)
print('READY',flush=True)
sys.stdin.readline()
asyncio.run(e._open(sym,'LONG',100.,'MULTI WRITER TEST'))
print('RESULT='+json.dumps({'positions':list(e.positions),'locked':e.paper_recovery_locked,'balance':b.paper.balance}),flush=True)
'''

def test_iki_surec_eski_ram_ile_paper_hesabini_ezmemeli(tmp_path):
 db=tmp_path/'multi.db';StateStore(db)
 ps=[subprocess.Popen([sys.executable,'-c',WORKER_EXEC,str(db),sym,str(tmp_path)],cwd=ROOT,env=os.environ.copy(),
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
     for sym in ('BTC/USDT','ETH/USDT')]
 try:
  for p in ps:assert p.stdout.readline().strip()=='READY'
  results=[]
  for p in ps:
   p.stdin.write('go\n');p.stdin.flush();p.stdin.close();p.stdin=None
   out,err=p.communicate(timeout=20)
   assert p.returncode==0,err
   result_line=next(x for x in out.splitlines() if x.startswith('RESULT='))
   results.append(json.loads(result_line[7:]))
  st=StateStore(db);positions=st.load_positions();meta=st.get_meta('position_meta',{})
  assert set(meta)==set(positions),f'positions={list(positions)}, metadata={list(meta)}'
  assert set(positions)=={'BTC/USDT'}
  assert results[1]['positions']==[] and results[1]['locked'] is True
  assert results[1]['balance']==1000.  # reject BEFORE the second fill
  assert st.get_meta('paper_account')['balance']==results[0]['balance']
 finally:
  for p in ps:
   if p.poll() is None:p.kill();p.wait()
