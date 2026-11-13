"""The test adapter must update the real synthetic paper ledger, not fake fills."""
import asyncio
import pytest
from src.executor import Executor
from src.risk import Position, RiskManager
from src.state_store import StateStore
from src.strategy import Strategy
from tests._paper_fixtures import make_paper_broker, seed_paper_state


def test_fixture_entry_and_reduce_only_share_paper_account():
 async def run():
  b=make_paper_broker(1000.,fee_pct=.05)
  f=await b.execute_entry('BTC/USDT','buy',2,price_hint=100.)
  assert f['fee']==pytest.approx(.1)
  assert b.paper.balance==pytest.approx(999.9)
  assert b.paper.position_qty['BTC/USDT']==2
  close=await b.market_order('BTC/USDT','sell',2,price_hint=101.,reduce_only=True)
  assert close['qty']==2 and not b.paper.position_qty
  assert b.paper.balance==pytest.approx(999.799)
  with pytest.raises(ValueError):
   await b.market_order('BTC/USDT','sell',1,price_hint=101.,reduce_only=True)
 asyncio.run(run())


def test_fixture_seed_restore_and_prevents_overwriting_existing_state(tmp_path):
 store=StateStore(tmp_path/'state.db')
 p=Position('BTC/USDT','LONG',100,2,90)
 seed_paper_state(store,{'BTC/USDT':p},balance=999.,start_balance=1000.,entry_fees={'BTC/USDT':1.})
 e=Executor(make_paper_broker(),RiskManager(),Strategy(),state_store=store)
 assert e.positions['BTC/USDT'].qty==2
 assert e.broker.paper.position_qty['BTC/USDT']==2
 assert e.broker.paper.balance==999.
 assert e._position_meta['BTC/USDT']['entry_fee_usdt']==1.
 assert e.paper_recovery_locked  # historical positions still require recovery
 with pytest.raises(ValueError):seed_paper_state(store,{'BTC/USDT':p})
