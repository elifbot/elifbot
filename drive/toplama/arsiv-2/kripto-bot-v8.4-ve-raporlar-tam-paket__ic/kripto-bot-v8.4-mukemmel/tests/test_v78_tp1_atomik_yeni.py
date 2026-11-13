"""TP1 kısmi kapanış ve planı aynı SQLite işleminde olmalı; ağsız paper."""
import json,os,sqlite3,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=r'''
import asyncio,json,os,sys,sqlite3
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
broker=ExchangeManager(cfg)
async def ba(symbol,exchange=None):return 100.98,101.02
async def bp(symbol,side):return 'binance',100.02
broker.fetch_bid_ask=ba;broker.best_price=bp
risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=False,max_layers=1,pair_rescue_enabled=False)
strat=Strategy(runner_exit=True);store=StateStore(root/'state.db')
sizer=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=root/'kelly.json')
ex=Executor(broker,risk,strat,sizer=sizer,order_type='maker',maker_timeout=3.,protection_on=False,state_store=store)
combined=strat.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
async def go():
 await ex.on_signal('BTC/USDT',100.,combined,-20.,False)
 pos=ex.positions['BTC/USDT'];before=pos.qty
 ex._trade_plans['BTC/USDT']={'tp1':101.5,'tp2':200.,'tp1_fraction':.5,'tp1_hit':False,'source':'TEST'}
 store.set_meta('trade_plans',ex._trade_plans)
 if case=='crash_after_commit':
  real=store.commit_paper_close
  def kill(*a,**k):real(*a,**k);os._exit(84)
  store.commit_paper_close=kill
 if case=='rollback':
  with store._conn() as c:
   c.execute("CREATE TRIGGER fail_trade BEFORE INSERT ON trade_history BEGIN SELECT RAISE(ABORT,'injected'); END")
 await ex.on_price_tick('BTC/USDT',102.)
 print('RESULT_JSON='+json.dumps({'case':case,'before':before,'locked':ex.paper_recovery_locked,'qty':pos.qty}),flush=True)
 await broker.close()
asyncio.run(go())
'''
def run(tmp,case):return subprocess.run([sys.executable,'-c',SCRIPT,str(tmp),case],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
def db(tmp):
 with sqlite3.connect(tmp/'state.db') as c:
  plan=json.loads(c.execute("select value from bot_meta where key='trade_plans'").fetchone()[0])['BTC/USDT']
  return plan,c.execute('select qty from open_positions').fetchone()[0],c.execute('select status from paper_close_intents').fetchone()[0],c.execute('select count(*) from trade_history').fetchone()[0]

def test_tp1_commit_sonrasi_surec_olse_plan_ve_kismi_kapanis_beraber_kalir(tmp_path):
 p=run(tmp_path,'crash_after_commit');assert p.returncode==84,p.stdout+p.stderr
 plan,qty,status,trades=db(tmp_path)
 assert plan['tp1_hit'] is True and plan['tp1_qty']>0 and qty>0 and status=='CLOSED' and trades==1

def test_tp1_commit_basarisizsa_plan_degismez_ve_kilit_acilmaz(tmp_path):
 p=run(tmp_path,'rollback');assert p.returncode==0,p.stdout+p.stderr
 r=json.loads(next(x[12:] for x in p.stdout.splitlines() if x.startswith('RESULT_JSON=')))
 plan,qty,status,trades=db(tmp_path)
 assert plan['tp1_hit'] is False and qty==pytest.approx(r['before']) and status=='PENDING' and trades==0
 assert r['locked']

def test_tp1_normalde_plan_ve_miktar_uyumlu(tmp_path):
 p=run(tmp_path,'normal');assert p.returncode==0,p.stdout+p.stderr
 r=json.loads(next(x[12:] for x in p.stdout.splitlines() if x.startswith('RESULT_JSON=')))
 plan,qty,status,trades=db(tmp_path)
 assert plan['tp1_hit'] is True and plan['tp1_qty']==pytest.approx(r['before']-qty)
 assert status=='CLOSED' and trades==1 and not r['locked']
