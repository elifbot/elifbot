"""Offline isolated tests: invalid TP1 must never initiate a paper fill."""
import asyncio
import pytest
from test_v78_bayat_risk_yeni import open_one
from src.dashboard import ProductionBotHub

@pytest.mark.parametrize('plan',[None, {'tp1_hit':True}])
def test_gecersiz_tp1_fill_oncesi_kilitlenir(tmp_path,plan):
 async def go():
  ex,b,st=await open_one(tmp_path)
  sym='BTC/USDT'; pos=ex.positions[sym]
  if plan is None: ex._trade_plans.pop(sym,None)
  else: ex._trade_plans[sym]=plan
  before_balance=b.paper.balance; before_qty=pos.qty
  before_ledger=dict(b.paper.position_qty)
  with st._conn() as c: before_intents=c.execute('select count(*) from paper_close_intents').fetchone()[0]
  result=await ex._close(sym,101.,'TP1',1.,qty_override=pos.qty/2,tp1_transition=True)
  with st._conn() as c: after_intents=c.execute('select count(*) from paper_close_intents').fetchone()[0]
  assert result is False and ex.paper_recovery_locked
  assert b.paper.balance==before_balance and pos.qty==before_qty and b.paper.position_qty==before_ledger
  assert after_intents==before_intents
  await b.close()
 asyncio.run(go())

def test_panel_toplam_getiri_kayitli_baslangic_bakiyesini_kullanir(tmp_path):
 hub=ProductionBotHub(db_path=tmp_path/'s.db')
 hub.store.set_meta('bot_status',{'mode':'PAPER','balance_usdt':1100.,'equity_usdt':1100.,'unrealized_usdt':0.})
 hub.store.set_meta('paper_account',{'start_balance':1000.})
 # Not the beginning of the account: recent samples only.
 hub.store.record_equity(1090.,1090.,0)
 assert hub.build_state_payload()['total_return_pct']==10.0

def test_panel_baslangic_yoksa_toplam_getiri_uydurmaz(tmp_path):
 hub=ProductionBotHub(db_path=tmp_path/'s.db')
 hub.store.set_meta('bot_status',{'mode':'PAPER','balance_usdt':1100.,'equity_usdt':1100.,'unrealized_usdt':0.})
 assert hub.build_state_payload()['total_return_pct'] is None

def test_tp1_plani_fill_sirasinda_degisirse_pending_ve_kilit_korunur(tmp_path):
 async def go():
  ex,b,st=await open_one(tmp_path); sym='BTC/USDT'
  ex._trade_plans[sym]={'tp1_hit':False}
  original=b.market_order
  async def race(*a,**kw):
   fill=await original(*a,**kw)
   ex._trade_plans.pop(sym,None)  # synthetic racing mutation after fill
   return fill
  b.market_order=race
  await ex._close(sym,101.,'TP1',1.,qty_override=ex.positions[sym].qty/2,tp1_transition=True)
  with st._conn() as c: status=c.execute('select status from paper_close_intents').fetchone()[0]
  assert ex.paper_recovery_locked and status=='PENDING' and not st.get_trades()
  await b.close()
 asyncio.run(go())

@pytest.mark.parametrize('value',[None,0.,-1.,float('nan'),'bad',True])
def test_gecersiz_baslangic_degeri_bilinmiyor(tmp_path,value):
 hub=ProductionBotHub(db_path=tmp_path/'s.db')
 hub.store.set_meta('bot_status',{'mode':'PAPER','balance_usdt':1100.,'equity_usdt':1100.})
 hub.store.set_meta('paper_account',{'start_balance':value})
 assert hub.build_state_payload()['total_return_pct'] is None

def test_live_paper_baslangic_degerini_kullanmaz(tmp_path):
 hub=ProductionBotHub(db_path=tmp_path/'s.db')
 hub.store.set_meta('bot_status',{'mode':'LIVE','balance_usdt':1100.,'equity_usdt':1100.})
 hub.store.set_meta('paper_account',{'start_balance':1000.})
 assert hub.build_state_payload()['total_return_pct'] is None
