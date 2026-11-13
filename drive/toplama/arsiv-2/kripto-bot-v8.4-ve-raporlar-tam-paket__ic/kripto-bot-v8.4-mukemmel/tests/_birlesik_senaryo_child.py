"""v7.8'e uyarlanmış iki eski xfail senaryosu; ağsız, paper, sahte fiyat."""
import asyncio, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import load_config
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.circuit_breaker import CircuitBreaker

root=Path(sys.argv[1]); root.mkdir(exist_ok=True,parents=True); case=sys.argv[2]
cfg=load_config(); cfg['genel']['mod']='paper'; cfg['paper']['bakiye']=1000.
broker=ExchangeManager(cfg)
async def ba(symbol,exchange=None):return 99.98,100.02
async def bp(symbol,side):return 'binance',100.02 if side=='LONG' else 99.98
broker.fetch_bid_ask=ba; broker.best_price=bp
risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=False,max_layers=1,pair_rescue_enabled=False)
strat=Strategy(runner_exit=True)
sizer=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=root/'kelly.json')
store=StateStore(root/'v78.db');breaker=CircuitBreaker(state_store=store)
ex=Executor(broker,risk,strat,sizer=sizer,order_type='maker',maker_timeout=3.,protection_on=True,state_store=store,circuit_breaker=breaker,runner_exit_cfg=cfg['cikis'])
combined=strat.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
if case=='crash':
    real=broker.execute_entry
    async def crash(*args,**kwargs):
        result=await real(*args,**kwargs)
        assert result['qty']>0
        os._exit(73)
    broker.execute_entry=crash
elif case=='pending_lost_ack':
    real=store.prepare_paper_open
    def pending_unknown(*args,**kwargs):
        real(*args,**kwargs)
        raise sqlite3.OperationalError('SENTETIK PENDING sonrasi kayip yanit')
    store.prepare_paper_open=pending_unknown
elif case=='lost_ack':
    name='commit_paper_open' if hasattr(store,'commit_paper_open') else 'save_position'
    real=getattr(store,name)
    def unknown(*args,**kwargs):
        real(*args,**kwargs)
        raise sqlite3.OperationalError('SENTETIK COMMIT sonrasi kayip yanit')
    setattr(store,name,unknown)

async def go():
    try:
        await ex.on_signal('BTC/USDT',100.,combined,-20.,False)
        await ex.on_signal('ETH/USDT',100.,combined,-20.,False)
        if case=='close_check':
            await ex.close_all_positions('SENTETIK TEST')
            account=store.get_meta('paper_account',{})
            print('CLOSE_CHECK broker_balance=',broker.paper.balance,'recorded_balance=',account.get('balance'),flush=True)
        print('RESULT positions=',sorted(ex.positions),'breaker=',breaker.tripped,'guard=',getattr(ex,'paper_recovery_locked',False),flush=True)
    finally: await broker.close()
asyncio.run(go())
