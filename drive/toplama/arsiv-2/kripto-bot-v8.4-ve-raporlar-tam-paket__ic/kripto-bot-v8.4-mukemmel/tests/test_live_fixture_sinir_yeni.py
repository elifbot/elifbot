"""Do not turn a legacy live-mode test double into a live trading protocol."""
import asyncio
from src.executor import Executor
from src.risk import Position,RiskManager
from src.state_store import StateStore
from src.strategy import Strategy
from tests._paper_fixtures import seed_paper_state
from tests.test_regressions import FakeCloseBroker,SYMBOL

def test_live_fixture_metasi_tam_olsa_dahi_live_kilitlidir(tmp_path):
 store=StateStore(tmp_path/'live.db')
 seed_paper_state(store,{SYMBOL:Position(SYMBOL,'LONG',100,1,95,exchange='binance',margin_usdt=5)})
 broker=FakeCloseBroker()
 executor=Executor(broker,RiskManager(),Strategy(),state_store=store)
 assert executor.paper_recovery_locked is True
 assert asyncio.run(executor._close(SYMBOL,101,'TEST',1)) is False
 assert broker.market_calls==[]
 assert SYMBOL in store.load_positions()
