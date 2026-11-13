"""A report's REST quote must not inherit a WebSocket quote timestamp."""
import asyncio,time
from types import SimpleNamespace
from src.telegram import InteractiveTelegramBot
from src.risk import Position,RiskManager


def test_rapor_fiyat_istegi_islem_fiyatini_ve_zamanini_degistirmez():
 pos=Position('BTC/USDT','LONG',100,1,90,exchange='binance')
 receipt=time.monotonic()
 ex=SimpleNamespace(positions={'BTC/USDT':pos},last_prices={'BTC/USDT':101.},
                    _price_receipt_mono={'BTC/USDT':receipt},risk=RiskManager())
 class Broker:
  async def fetch_price(self,*args,**kwargs): return 110.
  async def fetch_balance_usdt(self):return 1000.
 bot=InteractiveTelegramBot(executor=ex,broker=Broker())
 quotes,balance,unreal=asyncio.run(bot._financial_snapshot())
 assert quotes['BTC/USDT']==(110.,True)
 assert balance==1000. and unreal==10.
 assert ex.last_prices['BTC/USDT']==101.
 assert ex._price_receipt_mono['BTC/USDT']==receipt
