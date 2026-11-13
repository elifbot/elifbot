"""Paper kademe finansal durum / crash, gerçek API ve ağ yok."""
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
async def bp(symbol,side):return 'binance',101.02
async def fp(symbol,exchange):return 101.02
broker.fetch_bid_ask=ba;broker.best_price=bp;broker.fetch_price=fp
risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=True,max_layers=3,pair_rescue_enabled=False)
strat=Strategy(runner_exit=True);store=StateStore(root/'state.db')
sizer=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=root/'kelly.json')
ex=Executor(broker,risk,strat,sizer=sizer,order_type='maker',maker_timeout=3.,protection_on=False,state_store=store)
combined=strat.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
async def go():
 await ex.on_signal('BTC/USDT',101.,combined,-20.,False)
 assert 'BTC/USDT' in ex.positions
 before=store.get_meta('paper_account')['balance']; before_qty=ex.positions['BTC/USDT'].qty
 if case=='crash':
  real=broker.execute_entry
  async def kill(*a,**k):
   out=await real(*a,**k);assert out['qty']>0;os._exit(83)
  broker.execute_entry=kill
 if case=='rollback':
  with store._conn() as c:
   c.execute("CREATE TRIGGER fail_layer BEFORE UPDATE ON open_positions BEGIN SELECT RAISE(ABORT,'injected layer'); END")
 if case=='commit_lost':
  real=store.commit_paper_layer
  def unknown(*a,**k):real(*a,**k);raise sqlite3.OperationalError('sentetik commit sonrasi yanit kaybi')
  store.commit_paper_layer=unknown
 await ex._add_layer('BTC/USDT',101.02,'sentetik')
 if case in ('rollback','commit_lost'):
  await ex.on_signal('ETH/USDT',101.,combined,-20.,False)
 print('RESULT_JSON='+json.dumps({'case':case,'before':before,'before_qty':before_qty,'balance':broker.paper.balance,
  'saved':store.get_meta('paper_account')['balance'],'saved_qty':store.load_positions()['BTC/USDT'].qty,
  'ram_qty':ex.positions['BTC/USDT'].qty,'meta_fee':store.get_meta('position_meta')['BTC/USDT']['entry_fee_usdt'],
  'locked':ex.paper_recovery_locked,'positions':sorted(ex.positions)}),flush=True)
 await broker.close()
asyncio.run(go())
'''
def run(tmp,case):
 p=subprocess.run([sys.executable,'-c',SCRIPT,str(tmp),case],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
 return p

def result(p):
 assert p.returncode==0,p.stdout+p.stderr
 return json.loads(next(x[12:] for x in p.stdout.splitlines() if x.startswith('RESULT_JSON=')))

def status(tmp):
 with sqlite3.connect(tmp/'state.db') as c:return c.execute('select status from paper_layer_intents').fetchall()

def test_normal_kademe_bakiye_pozisyon_ucret_tek_islemde(tmp_path):
 r=result(run(tmp_path,'normal'))
 assert status(tmp_path)==[('APPLIED',)] and not r['locked']
 assert r['saved']==pytest.approx(r['balance']) and r['saved']<r['before']
 assert r['saved_qty']==pytest.approx(r['ram_qty']) and r['ram_qty']>r['before_qty']
 assert r['meta_fee']>0

def test_kademe_fill_sonrasi_cokmede_pending_ve_eski_state(tmp_path):
 p=run(tmp_path,'crash');assert p.returncode==83,p.stdout+p.stderr
 assert status(tmp_path)==[('PENDING',)]
 from src.state_store import StateStore
 assert StateStore(tmp_path/'state.db').paper_requires_recovery()

def test_kademe_transaction_hatasi_kilitleyerek_eski_state_korur(tmp_path):
 r=result(run(tmp_path,'rollback'))
 assert status(tmp_path)==[('PENDING',)] and r['locked']
 assert r['saved']==pytest.approx(r['before']) and r['saved_qty']==pytest.approx(r['before_qty'])
 assert 'ETH/USDT' not in r['positions']

def test_kademe_commit_sonrasi_yanit_kaybinda_tekrar_engeli(tmp_path):
 r=result(run(tmp_path,'commit_lost'))
 assert status(tmp_path)==[('APPLIED',)] and r['locked']
 assert r['saved']==pytest.approx(r['balance']) and r['saved_qty']==pytest.approx(r['ram_qty'])
 assert 'ETH/USDT' not in r['positions']
 from src.state_store import StateStore
 assert StateStore(tmp_path/'state.db').paper_requires_recovery()
