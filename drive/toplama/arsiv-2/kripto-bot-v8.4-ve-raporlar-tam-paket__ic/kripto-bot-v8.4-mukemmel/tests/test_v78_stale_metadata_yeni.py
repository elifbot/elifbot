"""Exercise SQLite prepare against stale same-symbol/account snapshots."""
import pytest
from src.risk import Position
from src.state_store import StateStore
from tests._paper_fixtures import seed_paper_state


def setup_state(tmp_path):
 st=StateStore(tmp_path/'s.db')
 pos=Position('BTC/USDT','LONG',100.,1.,90.,exchange='binance',margin_usdt=10.)
 seed_paper_state(st,{'BTC/USDT':pos})
 plan={'BTC/USDT':{'initial_risk':10.,'initial_stop':90.,'tp1':110.,'tp2':120.,'tp1_hit':False}}
 st.set_meta('trade_plans',plan)
 expected={
  'symbols':['BTC/USDT'], 'account':st.get_meta('paper_account'),
  'positions':{'BTC/USDT':{'symbol':pos.symbol,'side':pos.side,'entry':float(pos.entry),'qty':float(pos.qty),
    'stop':float(pos.stop),'peak':float(pos.peak),'locked_profit':bool(pos.locked_profit),'opened_at':str(pos.opened_at or ''),
    'leverage':int(pos.leverage),'margin_usdt':float(pos.margin_usdt),'layers':int(pos.layers),
    'last_add_price':float(pos.last_add_price),'exchange':str(pos.exchange or 'binance')}},
  'position_meta':st.get_meta('position_meta'), 'trade_plans':plan,
  'paper_funding_clock':st.get_meta('paper_funding_clock')}
 return st,pos,expected

@pytest.mark.parametrize('field',['stop','plan','metadata','funding_clock'])
def test_baska_yazarin_ayni_hesapta_yaptigi_degisim_acilisi_engeller(tmp_path,field):
 st,pos,expected=setup_state(tmp_path)
 if field=='stop':
  pos.stop=95.;st.save_position(pos)
 elif field=='plan':
  plan=st.get_meta('trade_plans');plan['BTC/USDT']['tp1']=111.;st.set_meta('trade_plans',plan)
 elif field=='metadata':
  meta=st.get_meta('position_meta');meta['BTC/USDT']['position_id']='changed';st.set_meta('position_meta',meta)
 else:
  clock=st.get_meta('paper_funding_clock');clock['BTC/USDT']+=1.;st.set_meta('paper_funding_clock',clock)
 req={'symbol':'ETH/USDT','side':'LONG','_expected_paper_state':expected}
 with pytest.raises(RuntimeError,match='paper state changed'):
  st.prepare_paper_open('stale-'+field,req)
 assert st.get_meta('paper_account')==expected['account']
