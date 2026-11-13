"""Paper kapanışlar tek finansal akışta sıralanır; gerçek borsa yok."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=r'''
import asyncio,json,sys
from pathlib import Path
from src.config import load_config
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.sizing import PositionSizer
from src.state_store import StateStore
root=Path(sys.argv[1]);case=sys.argv[2]
cfg=load_config();cfg['genel']['mod']='paper';cfg['paper']['bakiye']=1000.
b=ExchangeManager(cfg)
async def ba(symbol,exchange=None):return 99.98,100.02
async def bp(symbol,side):return 'binance',100.02 if side=='LONG' else 99.98
b.fetch_bid_ask=ba;b.best_price=bp
risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=False,max_layers=1,pair_rescue_enabled=False)
s=Strategy(runner_exit=True);st=StateStore(root/'v78.db')
sizer=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=root/'kelly.json')
e=Executor(b,risk,s,sizer=sizer,order_type='maker',maker_timeout=3.,protection_on=False,state_store=st)
combined=s.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
async def go():
 await e.on_signal('BTC/USDT',100.,combined,-20.,False)
 if case=='different':await e.on_signal('ETH/USDT',100.,combined,-20.,False)
 real=b.market_order;calls=[]
 async def slow(*a,**kw):
  calls.append(a[0]);await asyncio.sleep(.03);return await real(*a,**kw)
 b.market_order=slow
 targets=['BTC/USDT','ETH/USDT'] if case=='different' else ['BTC/USDT']*100
 results=await asyncio.wait_for(asyncio.gather(*(e._close(sym,100.,'SENTETIK',0.) for sym in targets)),10)
 print('RESULT='+json.dumps({'positions':sorted(e.positions),'calls':calls,'trades':len(st.get_trades()),
  'balance':b.paper.balance,'saved':st.get_meta('paper_account')['balance'], 'success':sum(results),'locked':e.paper_recovery_locked}),flush=True)
 await b.close()
asyncio.run(go())
'''
def go(tmp,case):
 p=subprocess.run([sys.executable,'-c',SCRIPT,str(tmp),case],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
 assert p.returncode==0,p.stdout+p.stderr
 return json.loads(next(x[7:] for x in p.stdout.splitlines() if x.startswith('RESULT=')))

def test_farkli_sembol_es_zamanli_kapanislar_kaybolmadan_serilesir(tmp_path):
 r=go(tmp_path,'different')
 assert r['positions']==[] and sorted(r['calls'])==['BTC/USDT','ETH/USDT']
 assert r['success']==2 and r['trades']==2 and not r['locked']
 assert r['saved']==pytest.approx(r['balance'])

def test_ayni_pozisyona_yuz_es_zamanli_istek_tek_dolum_uretmelidir(tmp_path):
 r=go(tmp_path,'same')
 assert r['positions']==[] and r['calls']==['BTC/USDT']
 assert r['success']==1 and r['trades']==1 and not r['locked']
 assert r['saved']==pytest.approx(r['balance'])

def test_sirada_bekleyen_toplu_kapanis_fiyati_bayatlayinca_kapatmaz(tmp_path):
 import time,asyncio
 from test_v78_bayat_risk_yeni import open_one
 async def check():
  e,b,st=await open_one(tmp_path)
  combined=e.strategy.combine(80.,75.,20.,60.,market_context={"regime_aware":False})
  await e.on_signal("ETH/USDT",100.,combined,-20.,False)
  assert "ETH/USDT" in e.positions
  await e.on_price_tick('BTC/USDT',100.)
  entered=asyncio.Event();release=asyncio.Event();real=b.market_order
  async def slow(*args,**kwargs):
   if args[0]=='ETH/USDT':entered.set();await release.wait()
   return await real(*args,**kwargs)
  b.market_order=slow
  first=asyncio.create_task(e._close('ETH/USDT',100.,'TEST',0.))
  await entered.wait()
  bulk=asyncio.create_task(e.close_all_positions('TEST',urgent=False))
  await asyncio.sleep(.02)
  e._price_receipt_mono['BTC/USDT']=time.monotonic()-20
  release.set();await first;await bulk
  assert 'BTC/USDT' in e.positions
  await b.close()
 asyncio.run(check())
