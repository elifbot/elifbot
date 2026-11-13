from phoenix.live import LiveSignalRunner
from phoenix.config import Config
from phoenix.models import Market
import time
class FakeAdapter:
 def __init__(self,liquidation=True,exchange='BINANCE'):self.exchange=exchange;self.client=type('C',(),{'has':{'fetchTickers':True}})();self.liquidation=liquidation
 def load_markets(self):
  meta = {"instType":"SWAP", "ctVal":"1", "ctMult":"1", "ctValCcy":"BTC"} if self.exchange == "OKX" else {}
  return [Market(self.exchange,'BTC/USDT:USDT','BTC','USDT','USDT','swap', info=meta),Market(self.exchange,'ETH/USDT:USDT','ETH','USDT','USDT','swap', info=meta)]
 def tickers(self,symbols):
  out = {}
  for s in symbols:
   if self.exchange == "OKX":
    out[s] = {'bid':99.9,'ask':100.1,'last':100,'info':{'instType':'SWAP','vol24h':'100000'}}
   else:
    out[s] = {'bid':99.9,'ask':100.1,'last':100,'quoteVolume':10_000_000 if 'BTC' in s else 5_000_000}
  return out
 def ticker(self,s):return self.tickers([s])[s]
 def order_book(self,s,limit=20):return {'timestamp':time.time()*1000,'bids':[['99.9','100','0']], 'asks':[['100.1','10','0']]}
 def ohlcv(self,s,tf,limit=100):return [[i,100,100.5,99.5,100+(i%2)*.1,1000] for i in range(limit)]
 def funding(self,s):return 0.0
 def oi(self,s):return 1000.0
 def liquidations(self,s,limit=50):return [{'side':'long','amount':1,'price':100}] if self.liquidation else []
 def amount_to_precision(self,s,a):return a
 def price_to_precision(self,s,p):return p

def test_snapshot():
 r=LiveSignalRunner(Config(min_score=.5),adapters={'BINANCE':FakeAdapter()});r.refresh_universe();s=r.snapshot(r.markets[0]);assert s and s.quote_volume_24h==10_000_000

def test_missing_oi():
 class A(FakeAdapter):
  def oi(self,s):return None
 r=LiveSignalRunner(adapters={'BINANCE':A()});r.refresh_universe();assert r.snapshot(r.markets[0]) is None

def test_volume_rank_all():
 r=LiveSignalRunner(Config(max_spread_bps=30),adapters={'BINANCE':FakeAdapter()});r.refresh_universe();rank=r._rank_tickers();b=r._detail_batch(rank);assert [x[1].symbol for x in b]==['BTC/USDT:USDT','ETH/USDT:USDT']


def test_missing_book_timestamp_rejected():
 class A(FakeAdapter):
  def order_book(self,s,limit=20): return {'bids':[['99.9','100','0']], 'asks':[['100.1','10','0']]}
 r=LiveSignalRunner(adapters={'BINANCE':A()});r.refresh_universe();assert r.snapshot(r.markets[0]) is None

def test_okx_contract_book_shape():
 r=LiveSignalRunner(Config(max_spread_bps=30),adapters={'OKX':FakeAdapter(exchange='OKX')});r.refresh_universe();rank=r._rank_tickers();assert len(rank['OKX'])==2
