"""v7.8 temelli adayda sentetik paper kapanışı; ağ/anahtar/gerçek emir yok."""
import json,os,sqlite3,subprocess,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
CHILD=r'''
import asyncio,os,sys,sqlite3,json
from pathlib import Path
from src.config import load_config
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.circuit_breaker import CircuitBreaker
root=Path(sys.argv[1]);case=sys.argv[2]
cfg=load_config();cfg['genel']['mod']='paper';cfg['paper']['bakiye']=1000.
broker=ExchangeManager(cfg)
async def ba(symbol,exchange=None):return 99.98,100.02
async def bp(symbol,side):return 'binance',100.02 if side=='LONG' else 99.98
broker.fetch_bid_ask=ba;broker.best_price=bp
risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=False,max_layers=1,pair_rescue_enabled=False)
strat=Strategy(runner_exit=True)
sizer=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=root/'kelly.json')
store=StateStore(root/'v78.db');breaker=CircuitBreaker(state_store=store)
ex=Executor(broker,risk,strat,sizer=sizer,order_type='maker',maker_timeout=3.,protection_on=True,state_store=store,circuit_breaker=breaker,runner_exit_cfg=cfg['cikis'])
combined=strat.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
async def go():
 await ex.on_signal('BTC/USDT',100.,combined,-20.,False)
 assert 'BTC/USDT' in ex.positions
 if case=='concurrent':
  await ex.on_signal('ETH/USDT',100.,combined,-20.,False)
  assert 'ETH/USDT' in ex.positions
 before=store.get_meta('paper_account')['balance']
 if case=='crash':
  real=broker.market_order
  async def crash(*args,**kw):
   out=await real(*args,**kw);assert out['qty']>0;os._exit(81)
  broker.market_order=crash
 if case=='commit_lost':
  real=store.commit_paper_close
  def lost(*args,**kw):
   real(*args,**kw);raise sqlite3.OperationalError('sentetik COMMIT sonrasi yanit kaybi')
  store.commit_paper_close=lost
 if case=='rollback':
  with store._conn() as c:
   c.execute("CREATE TRIGGER fail_trade BEFORE INSERT ON trade_history BEGIN SELECT RAISE(ABORT,'injected'); END")
 pos=ex.positions['BTC/USDT'];qty=pos.qty/2 if case=='partial' else None
 if case=='concurrent':
  entered=asyncio.Event();release=asyncio.Event();real=broker.market_order
  async def delayed(*args,**kwargs):
   entered.set();await release.wait();return await real(*args,**kwargs)
  broker.market_order=delayed
  first=asyncio.create_task(ex._close('BTC/USDT',100.,'SENTETIK',0.))
  await asyncio.wait_for(entered.wait(),5)
  second=asyncio.create_task(ex._close('ETH/USDT',100.,'SENTETIK',0.))
  await asyncio.sleep(.01)
  await ex.on_signal('XRP/USDT',100.,combined,-20.,False)
  assert not second.done() and 'XRP/USDT' not in ex.positions
  release.set();assert await first is True
  result=await second
 else:
  result=await ex._close('BTC/USDT',100.,'SENTETIK',0.,qty_override=qty)
 if case in ('commit_lost','rollback'):
  await ex.on_signal('ETH/USDT',100.,combined,-20.,False)
 account=store.get_meta('paper_account')
 print('RESULT_JSON='+json.dumps({'case':case,'before':before,'balance':broker.paper.balance,'saved':account['balance'],
  'locked':ex.paper_recovery_locked,'result':result,'positions':sorted(ex.positions),
  'qty':ex.positions['BTC/USDT'].qty if 'BTC/USDT' in ex.positions else 0}),flush=True)
 await broker.close()
asyncio.run(go())
'''

def child(tmp_path,case):
    return subprocess.run([sys.executable,'-c',CHILD,str(tmp_path),case],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)

def rows(tmp_path):
    with sqlite3.connect(tmp_path/'v78.db') as c:
        return (c.execute('select status from paper_close_intents').fetchall(),
                c.execute('select symbol,qty from open_positions').fetchall(),
                c.execute('select qty,net_pnl_usdt from trade_history').fetchall(),
                json.loads(c.execute("select value from bot_meta where key='paper_account'").fetchone()[0]))

def result(out):
    return json.loads(next(x[12:] for x in out.stdout.splitlines() if x.startswith('RESULT_JSON=')))

@pytest.mark.parametrize('case',['full','partial'])
def test_paper_kapanis_bakiye_pozisyon_ve_gecmis_tutarlidir(tmp_path,case):
    p=child(tmp_path,case);assert p.returncode==0,p.stdout+p.stderr
    r=result(p);intents,positions,trades,acct=rows(tmp_path)
    assert intents==[('CLOSED',)] and len(trades)==1
    assert acct['balance']==pytest.approx(r['balance']) and not r['locked']
    if case=='full': assert not positions and r['result'] is True
    else:
        assert positions[0][1]==pytest.approx(r['qty']) and r['qty']>0
        assert r['result'] is False  # v7.8 returns False for partial close

def test_fill_sonrasi_surec_olurse_pending_ve_eski_finansal_state_korunur(tmp_path):
    p=child(tmp_path,'crash');assert p.returncode==81,p.stdout+p.stderr
    intents,positions,trades,acct=rows(tmp_path)
    assert intents==[('PENDING',)] and len(positions)==1 and not trades
    from src.state_store import StateStore
    assert StateStore(tmp_path/'v78.db').paper_requires_recovery()

def test_kapanis_transaction_hatasi_hepsini_geri_alir_ve_kilitler(tmp_path):
    p=child(tmp_path,'rollback');assert p.returncode==0,p.stdout+p.stderr
    r=result(p);intents,positions,trades,acct=rows(tmp_path)
    assert intents==[('PENDING',)] and len(positions)==1 and not trades
    assert acct['balance']==pytest.approx(r['before'])
    assert r['locked'] and r['result'] is False and 'ETH/USDT' not in r['positions']

def test_commit_olup_yanit_kaybolursa_tekrar_acilis_yok_ve_restart_kilitli(tmp_path):
    p=child(tmp_path,'commit_lost');assert p.returncode==0,p.stdout+p.stderr
    r=result(p);intents,positions,trades,acct=rows(tmp_path)
    assert intents==[('CLOSED',)] and not positions and len(trades)==1
    assert acct['balance']==pytest.approx(r['balance'])
    assert r['locked'] and r['result'] is False and 'ETH/USDT' not in r['positions']
    from src.state_store import StateStore
    assert StateStore(tmp_path/'v78.db').paper_requires_recovery()
