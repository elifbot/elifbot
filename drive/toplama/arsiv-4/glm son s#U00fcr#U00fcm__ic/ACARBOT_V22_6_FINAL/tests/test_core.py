from phoenix.config import Config
from phoenix.risk import RiskManager
from phoenix.models import Market,Snapshot,Position
from phoenix.strategy import Strategy
from phoenix.position_manager import PositionManager
from phoenix.engine import Engine

def test_target_notional():assert RiskManager(Config()).target_notional()==500

def test_stop_loss_budget():
 c=Config();r=RiskManager(c);s=r.stop_price(100,'LONG',5,1.0,0);assert s<100

def test_stop_loss_contract_size_changes_distance():
 c=Config(max_loss_usd=20, fee_bps_per_side=0, slippage_bps_reserve=0, liquidation_buffer_fraction=0.0); r=RiskManager(c)
 s1=r.stop_price(100,'LONG',1,1.0,0); s2=r.stop_price(100,'LONG',1,0.01,0)
 assert (100-s2) > (100-s1)

def test_position_margin_consumes_capacity():
 c=Config();r=RiskManager(c);p=Position('1','B','BTC','LONG',100,5,500,50,96,108,0,contract_size=0.01)
 assert r.can_enter(1000,[p]*19,0,500).allowed
 assert not r.can_enter(1000,[p]*20,0,500).allowed

def test_pending_margin_and_expire():
 e=Engine();s=type('S',(),{'notional':500,'margin':50})();e.pending['x']=s
 for i in range(19):e.pending[str(i)]=s
 assert not e.entry_allowed(1000,s).allowed

def test_stop_and_time():
 c=Config(max_hold_bars=2);p=Position('1','B','BTC','LONG',100,5,500,50,96,108,0,contract_size=0.01);pm=PositionManager(c)
 assert pm.check(p,95)[0]=='STOP';p=Position('2','B','BTC','LONG',100,5,500,50,96,108,0,contract_size=0.01);assert pm.check(p,100)[0] is None;assert pm.check(p,100)[0]=='TIME'

def test_strategy_signal():
 c=Config(min_score=.5);m=Market('B','BTC','BTC','USDT','USDT','swap');s=Snapshot(m,1,100,99.9,100.1,1,10_000_000,0,0,0.8,0.9,0.8,0.7,0.8,0);sig=Strategy(c).evaluate(s);assert sig and sig.notional==500 and sig.margin==50 and sig.qty>0


def test_backtest_stop_uses_risk_manager():
 from phoenix.backtest import Backtester, Bar
 from phoenix.config import Config
 c=Config(max_loss_usd=20, fee_bps_per_side=5.5, slippage_bps_reserve=3)
 b=Backtester(c); bars=[Bar(1,100,100,100,100,0.8),Bar(2,100,100,95,99,0)]
 r=b.run(bars); assert r.trades==1 and r.losses==1 and r.net_pnl < 0

def test_global_kill_switch_closes_reduce_only(tmp_path):
    class X:
        def amount_to_precision(self,s,a): return a
        def create_order(self,s,t,side,a,p,params): return {'id':'close-1','type':t,'params':params}
    from phoenix.exchange_execution import ExchangeExecutor
    from phoenix.models import Position
    e=Engine(exchange_executor=ExchangeExecutor(X(), Config()))
    p=Position('p','BINANCE','BTC/USDT:USDT','LONG',100,1,100,10,90,120,0)
    e.register_position(p)
    reason, results=e.trigger_kill_switch('test')
    assert reason=='test' and results and results[0][1]['params']['reduceOnly'] is True

def test_position_serialization_roundtrip():
    p=Position('p','B','BTC','LONG',100,1,100,10,90,120,0,contract_size=.01)
    q=Position.from_dict(p.to_dict())
    assert q.symbol=='BTC' and q.contract_size==.01 and q.reserved_margin==10
