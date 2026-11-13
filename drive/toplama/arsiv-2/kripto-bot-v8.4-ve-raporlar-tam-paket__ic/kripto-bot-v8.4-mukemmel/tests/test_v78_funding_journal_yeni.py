"""Ağsız v7.8 paper funding / SQLite tutarlılık ve çökme testleri."""
import json,os,sqlite3,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=r'''
import asyncio,json,os,sys,time,sqlite3
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
async def ba(symbol,exchange=None):return 99.98,100.02
async def bp(symbol,side):return 'binance',100.02 if side=='LONG' else 99.98
broker.fetch_bid_ask=ba;broker.best_price=bp
risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=False,max_layers=1,pair_rescue_enabled=False)
strat=Strategy(runner_exit=True);store=StateStore(root/'state.db')
sizer=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=root/'kelly.json')
ex=Executor(broker,risk,strat,sizer=sizer,order_type='maker',maker_timeout=3.,protection_on=False,state_store=store)
combined=strat.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
async def go():
 await ex.on_signal('BTC/USDT',100.,combined,-20.,False)
 assert 'BTC/USDT' in ex.positions
 old_ts=time.time()-3600;ex._funding_last['BTC/USDT']=old_ts
 store.set_meta('paper_funding_clock',ex._funding_last)
 before=store.get_meta('paper_account')['balance']
 if case=='crash':
  real=broker.paper.apply_funding
  def kill(*a,**k):
   real(*a,**k);os._exit(82)
  broker.paper.apply_funding=kill
 if case=='rollback':
  with store._conn() as c:
   c.execute("CREATE TRIGGER fail_funding BEFORE UPDATE ON bot_meta WHEN NEW.key='paper_account' BEGIN SELECT RAISE(ABORT,'injected funding'); END")
 if case=='commit_lost':
  real=store.commit_paper_funding
  def unknown(*a,**k):real(*a,**k);raise sqlite3.OperationalError('sentetik commit sonrasi yanit kaybi')
  store.commit_paper_funding=unknown
 error=None
 try: delta=ex.apply_funding('BTC/USDT',0.0008,100.,enabled=True)
 except Exception as e:delta=None;error=type(e).__name__
 if case in ('rollback','commit_lost'):
  await ex.on_signal('ETH/USDT',100.,combined,-20.,False)
 funding_meta=store.get_meta('position_meta')['BTC/USDT']['funding_usdt']
 funding_clock=store.get_meta('paper_funding_clock')['BTC/USDT']
 repeated=None
 if case=='roundtrip':
  repeated=ex.apply_funding('BTC/USDT',0.0008,100.,enabled=True)
  assert await ex._close('BTC/USDT',100.,'FUNDING SONRASI',0.) is True
 print('RESULT_JSON='+json.dumps({'case':case,'before':before,'balance':broker.paper.balance,'saved':store.get_meta('paper_account')['balance'],
   'meta':funding_meta,'clock':funding_clock,'repeated':repeated,
   'old_ts':old_ts,'delta':delta,'error':error,'locked':ex.paper_recovery_locked,'positions':sorted(ex.positions)}),flush=True)
 await broker.close()
asyncio.run(go())
'''

def run(tmp,case):
    return subprocess.run([sys.executable,'-c',SCRIPT,str(tmp),case],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)

def result(p):
    assert p.returncode==0,p.stdout+p.stderr
    return json.loads(next(x[12:] for x in p.stdout.splitlines() if x.startswith('RESULT_JSON=')))

def status(tmp):
    with sqlite3.connect(tmp/'state.db') as c:
        return c.execute('select status from paper_funding_intents').fetchall()

def test_normal_funding_hesap_metadata_saat_birlikte_kaydedilir(tmp_path):
    r=result(run(tmp_path,'normal'))
    assert r['delta']<0 and r['saved']==pytest.approx(r['balance'])
    assert r['saved']==pytest.approx(r['before']+r['delta'])
    assert r['meta']==pytest.approx(r['delta']) and r['clock']>r['old_ts']
    assert status(tmp_path)==[('APPLIED',)] and not r['locked']

def test_funding_ram_guncellendikten_sonra_cokmede_pending_kalir(tmp_path):
    p=run(tmp_path,'crash');assert p.returncode==82,p.stdout+p.stderr
    assert status(tmp_path)==[('PENDING',)]
    from src.state_store import StateStore
    store=StateStore(tmp_path/'state.db');assert store.paper_requires_recovery()
    assert store.get_meta('position_meta')['BTC/USDT']['funding_usdt']==0

def test_funding_transaction_hatasi_eski_state_korur_kilitler(tmp_path):
    r=result(run(tmp_path,'rollback'))
    assert status(tmp_path)==[('PENDING',)] and r['error'] and r['locked']
    assert r['saved']==pytest.approx(r['before']) and r['meta']==0
    assert r['clock']==pytest.approx(r['old_ts']) and 'ETH/USDT' not in r['positions']

def test_funding_commit_sonrasi_yanit_kaybi_tekrar_girisi_engeller(tmp_path):
    r=result(run(tmp_path,'commit_lost'))
    assert status(tmp_path)==[('APPLIED',)] and r['error'] and r['locked']
    assert r['saved']==pytest.approx(r['balance']) and r['meta']<0
    assert r['clock']>r['old_ts'] and 'ETH/USDT' not in r['positions']
    from src.state_store import StateStore
    assert StateStore(tmp_path/'state.db').paper_requires_recovery()

def test_funding_tekrari_ve_sonraki_kapanis_net_pnl_ile_uyumludur(tmp_path):
    r=result(run(tmp_path,'roundtrip'))
    assert r['repeated']==0 and status(tmp_path)==[('APPLIED',)]
    assert r['saved']==pytest.approx(r['balance']) and not r['positions']
    with sqlite3.connect(tmp_path/'state.db') as c:
        rec=c.execute('select net_pnl_usdt,funding_usdt from trade_history').fetchone()
    assert rec[1]==pytest.approx(r['delta'])
    assert r['balance']-1000==pytest.approx(rec[0])
