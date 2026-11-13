from phoenix.config import Config
from phoenix.models import Signal
from phoenix.trading import TradingService
class A:
 def amount_to_precision(self,s,a):return a
 def price_to_precision(self,s,p):return p
 def order_book(self,s,limit=5):return {'bids': [[99.9, 10]], 'asks': [[100.1, 10]]}
 def price_tick(self,s):return 0.1
 def create_order(self,s,t,side,a,p,params):return {'id':'ex-1','status':'open'}
 def fetch_order(self,oid,s):return {'id':oid,'status':'closed','filled':5,'average':100}
def test_api_execution_path(tmp_path):
 c=Config();svc=TradingService(A(),c,str(tmp_path/'state.json'));sig=Signal('BINANCE','BTC/USDT:USDT','LONG',.9,100,96,108,500,50,1,5);r=svc.submit(sig,1000);assert r['status']=='SUBMITTED';assert svc.reconcile_order(r['id'])['exchange_status']=='closed'

def test_account_sync_uses_exchange_state(tmp_path):
    class B(A):
        exchange_id = 'BINANCE'
        def fetch_balance(self):
            return {'info': {'totalMarginBalance': '1200'}, 'total': {'USDT': 1200}, 'free': {'USDT': 1100}}
        def fetch_positions(self):
            return [{'symbol': 'BTC/USDT:USDT', 'contracts': 1, 'side': 'long', 'initialMargin': 50, 'notional': 500}]
        def fetch_open_orders(self):
            return [{'remaining': 1, 'price': 100}]
        def fetch_my_trades(self, symbol=None, since=None, limit=None):
            return [{'info': {'realizedPnl': '-10'}}, {'info': {'realizedPnl': '3'}}]
        def market(self, s): return {'limits': {'amount': {'min': 0.001}, 'cost': {'min': 5}}}
    svc=TradingService(B(),Config(),str(tmp_path/'state.json'))
    snap=svc.refresh_risk_state()
    assert snap['equity']==1200 and len(snap['positions'])==1 and snap['daily_loss']==-7


def test_protective_orders_are_reduce_only(tmp_path):
    class B(A):
        exchange_id='BINANCE'
        def market(self,s): return {'limits': {'amount': {'min': 0}, 'cost': {'min': 0}}}
        def create_order(self,s,t,side,a,p,params):
            if t == 'limit': return {'id':'entry-1','status':'open'}
            return {'id':t,'status':'open','params':params}
    svc=TradingService(B(),Config(),str(tmp_path/'state.json'))
    sig=Signal('BINANCE','BTC/USDT:USDT','LONG',.9,100,96,108,500,50,1,5)
    rec=svc.submit(sig,1000,[],0)
    assert rec['status']=='SUBMITTED'
    rec2=svc.reconcile_order(rec['id'])
    assert rec2['status']=='FILLED' and rec2['protective_ok'] and len(rec2['protective_orders'])==2

def test_kill_switch_closes_exchange_positions(tmp_path):
    class B(A):
        exchange_id='BINANCE'
        def fetch_balance(self): return {'info': {'totalMarginBalance':'100'}, 'total': {'USDT':100}, 'free': {'USDT':50}}
        def fetch_positions(self): return [{'symbol':'BTC/USDT:USDT','contracts':1,'side':'long','initialMargin':50,'notional':500,'entryPrice':100,'markPrice':90}]
        def fetch_open_orders(self): return []
        def fetch_my_trades(self, symbol=None, since=None, limit=None): return [{'info': {'realizedPnl':'-100'}}]
        def market(self,s): return {'limits': {'amount': {'min':0}, 'cost': {'min':0}}}
        def create_order(self,s,t,side,a,p,params): return {'id':'close-1','status':'open','params':params}
    c=Config(daily_loss_limit_usd=50)
    svc=TradingService(B(),c,str(tmp_path/'state.json'))
    out=svc.reconcile_all()
    assert any(x.get('status')=='CLOSE_SUBMITTED' for x in out if isinstance(x,dict))


def test_missing_exchange_initial_margin_is_conservatively_estimated(tmp_path):
    class C(A):
        exchange_id = 'BINANCE'
        def fetch_balance(self):
            return {'info': {'totalMarginBalance': '1000'}, 'total': {'USDT': 1000}, 'free': {'USDT': 900}}
        def fetch_positions(self):
            return [{'symbol': 'BTC/USDT:USDT', 'contracts': 1, 'side': 'long', 'notional': 500, 'entryPrice': 100}]
        def fetch_open_orders(self): return []
        def fetch_my_trades(self, symbol=None, since=None, limit=None): return []
        def market(self, symbol): return {'contractSize': 1}
    svc = TradingService(C(), Config(leverage=10), str(tmp_path / 'state.json'))
    snap = svc.account_snapshot()
    assert snap['positions'][0].margin == 50
