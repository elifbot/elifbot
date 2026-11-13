"""Gerçek alt süreç ile restart/yok fiyat testleri; sadece sentetik paper."""
import json,os,sqlite3,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
INIT=r'''
import asyncio,json,os,sys
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
 assert 'BTC/USDT' in e.positions
 if case=='setup':
  st.set_meta('trade_plans',{'BTC/USDT':{'tp1':105,'tp2':110,'tp1_hit':False,'initial_risk':5,'initial_stop':95}})
 if case in ('missing','stale','fresh'):
  import time
  if case=='missing':e.last_prices.pop('BTC/USDT',None)
  else:
   await e.on_price_tick('BTC/USDT',100.)
   if case=='stale':e._price_receipt_mono['BTC/USDT']=time.monotonic()-20
  n=await e.close_all_positions('FIYAT KONTROL',urgent=False)
  print('RESULT='+json.dumps({'positions':list(e.positions),'closed':n,'trades':len(st.get_trades())}),flush=True)
 await b.close()
asyncio.run(go())
'''
RESTORE=r'''
import json,sys
from pathlib import Path
from src.config import load_config
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.state_store import StateStore
root=Path(sys.argv[1]);cfg=load_config();cfg['genel']['mod']='paper';cfg['paper']['bakiye']=1000.
b=ExchangeManager(cfg);st=StateStore(root/'v78.db')
e=Executor(b,RiskManager(),Strategy(),protection_on=False,state_store=st,trade_plan_cfg={'aktif':False})
try:unreal=e.total_unrealized_usdt(); known=True
except RuntimeError:unreal=None;known=False
print('RESULT='+json.dumps({'locked':e.paper_recovery_locked,'prices':e.last_prices,
 'positions':list(e.positions),'paper_balance':b.paper.balance,'saved_balance':st.get_meta('paper_account')['balance'],
 'unreal_known':known,'unreal':unreal}),flush=True)
'''
def run(src,tmp,case=None):
 cmd=[sys.executable,'-c',src,str(tmp)]+([case] if case else [])
 p=subprocess.run(cmd,cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
 assert p.returncode==0,p.stdout+p.stderr
 return p

def output(p):return json.loads(next(x[7:] for x in p.stdout.splitlines() if x.startswith('RESULT=')))
def saved(tmp):
 with sqlite3.connect(tmp/'v78.db') as c:
  return c.execute("select key,value,updated_at from bot_meta where key in ('position_meta','trade_plans','paper_account','paper_funding_clock') order by key").fetchall()

def test_restart_kilitliyken_finansal_meta_ve_plani_degistirmez(tmp_path):
 run(INIT,tmp_path,'setup');before=saved(tmp_path)
 r=output(run(RESTORE,tmp_path));after=saved(tmp_path)
 assert r['locked'] and r['positions']==['BTC/USDT']
 assert after==before, 'kilitli restart finansal metadata veya planı degistirdi'
 assert r['paper_balance']==pytest.approx(r['saved_balance'])

def test_restart_giris_fiyatini_canli_son_fiyat_ve_pnl_yapmaz(tmp_path):
 run(INIT,tmp_path,'setup');r=output(run(RESTORE,tmp_path))
 assert 'BTC/USDT' not in r['prices'] and not r['unreal_known']

def test_kapanis_fiyat_yoksa_giris_fiyati_ile_yapay_kapamaz(tmp_path):
 r=output(run(INIT,tmp_path,'missing'))
 assert r['positions']==['BTC/USDT'] and r['closed']==0 and r['trades']==0

def test_kapanis_bayat_son_fiyatla_gerceklesmez(tmp_path):
 r=output(run(INIT,tmp_path,'stale'))
 assert r['positions']==['BTC/USDT'] and r['closed']==0 and r['trades']==0

def test_kapanis_son_alim_zamani_taze_fiyatla_test_edilir(tmp_path):
 r=output(run(INIT,tmp_path,'fresh'))
 assert r['positions']==[] and r['closed']==1 and r['trades']==1

@pytest.mark.parametrize('corruption',['missing_account','nan_balance','missing_meta','missing_funding_clock'])
def test_eksik_veya_bozuk_kayitla_restart_sessiz_baslamaz(tmp_path,corruption):
 run(INIT,tmp_path,'setup')
 with sqlite3.connect(tmp_path/'v78.db') as c:
  if corruption=='missing_account': c.execute("delete from bot_meta where key='paper_account'")
  elif corruption=='nan_balance':
   account=json.loads(c.execute("select value from bot_meta where key='paper_account'").fetchone()[0]);account['balance']=float('nan')
   c.execute("update bot_meta set value=? where key='paper_account'",(json.dumps(account),))
  elif corruption=='missing_meta': c.execute("update bot_meta set value='{}' where key='position_meta'")
  elif corruption=='missing_funding_clock': c.execute("update bot_meta set value='{}' where key='paper_funding_clock'")
 before=saved(tmp_path)
 p=subprocess.run([sys.executable,'-c',RESTORE,str(tmp_path)],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
 assert p.returncode!=0 and 'mutabakat gerekli' in p.stderr,p.stdout+p.stderr
 assert saved(tmp_path)==before
