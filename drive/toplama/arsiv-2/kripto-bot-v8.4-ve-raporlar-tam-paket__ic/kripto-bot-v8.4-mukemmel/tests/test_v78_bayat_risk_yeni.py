"""Bayat/eksik fiyatın kârlılık ve fırsat takasını tetiklemesini engelle."""
import asyncio,time
from pathlib import Path
from src.config import load_config
from src.exchanges import ExchangeManager
from src.executor import Executor
from src.risk import RiskManager
from src.strategy import Strategy
from src.sizing import PositionSizer
from src.state_store import StateStore

async def open_one(tmp_path,opened=True):
 cfg=load_config();cfg['genel']['mod']='paper';cfg['paper']['bakiye']=1000.
 b=ExchangeManager(cfg)
 async def ba(symbol,exchange=None):return 99.98,100.02
 async def bp(symbol,side):return 'binance',100.02
 b.fetch_bid_ask=ba;b.best_price=bp
 risk=RiskManager(stop_model='marj',margin_stop_fraction=.8,leverage=10,unlimited_pyramiding=False,max_layers=1,pair_rescue_enabled=False)
 s=Strategy(runner_exit=True);st=StateStore(tmp_path/'s.db')
 sz=PositionSizer(mode='sabit_usdt',fixed_margin_usdt=50,leverage=10,stats_path=tmp_path/'kelly.json')
 ex=Executor(b,risk,s,sizer=sz,order_type='maker',maker_timeout=3.,protection_on=False,state_store=st,opportunity_swap_enabled=True)
 combined=s.combine(80.,75.,20.,60.,market_context={'regime_aware':False})
 if opened:
  await ex.on_signal('BTC/USDT',100.,combined,-20.,False)
  assert 'BTC/USDT' in ex.positions
 return ex,b,st

def test_bayat_kar_kesin_kar_sayilmaz(tmp_path):
 async def check():
  ex,b,st=await open_one(tmp_path)
  await ex.on_price_tick('BTC/USDT',110.)
  ex._price_receipt_mono['BTC/USDT']=time.monotonic()-20
  assert ex._all_positions_in_profit() is False
  await b.close()
 asyncio.run(check())

def test_fiyat_yokken_firsat_takasi_eski_giris_fiyati_ile_kapatmaz(tmp_path):
 async def check():
  ex,b,st=await open_one(tmp_path)
  ex.last_prices.pop('BTC/USDT',None)
  ex._position_opened_ts['BTC/USDT']=time.time()-1000
  assert await ex._try_opportunity_swap('ETH/USDT') is False
  assert 'BTC/USDT' in ex.positions and st.get_trades()==[]
  await b.close()
 asyncio.run(check())

def test_sinyal_yerel_taze_fiyat_kaydini_sessizce_degistirmez(tmp_path):
 async def check():
  ex,b,st=await open_one(tmp_path)
  await ex.on_price_tick('BTC/USDT',100.)
  original=ex.last_prices['BTC/USDT'];receipt=ex._price_receipt_mono['BTC/USDT']
  ex.strategy.exit_decision=lambda *a,**k:{'action':'hold'}
  ex.risk.can_add_to_winner=lambda *a,**k:(False,'test')
  combined=ex.strategy.combine(0.,0.,0.,0.,market_context={'regime_aware':False})
  await ex.on_signal('BTC/USDT',99.,combined,0.,False)
  assert ex.last_prices['BTC/USDT']==original and ex._price_receipt_mono['BTC/USDT']==receipt
  await b.close()
 asyncio.run(check())
