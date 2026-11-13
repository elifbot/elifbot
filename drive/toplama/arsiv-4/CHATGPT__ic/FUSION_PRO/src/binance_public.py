import asyncio, time
import httpx

class BinancePublic:
    def __init__(self, rest_base='https://fapi.binance.com', ws_base='wss://fstream.binance.com/stream'):
        self.rest_base=rest_base.rstrip('/'); self.ws_base=ws_base
        self.client=httpx.AsyncClient(timeout=8, headers={'User-Agent':'FusionPro/4.0'})
    async def close(self): await self.client.aclose()
    async def get(self,path,params=None):
        r=await self.client.get(self.rest_base+path,params=params); r.raise_for_status(); return r.json()
    async def klines(self,symbol,interval='5m',limit=260):
        rows=await self.get('/fapi/v1/klines',{'symbol':symbol,'interval':interval,'limit':limit}); out=[]; now=int(time.time()*1000)
        for x in rows:
            if int(x[6])>=now: continue
            out.append({'ts':int(x[0]),'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4]),'volume':float(x[5]),'trades':int(x[8]),'taker_buy_volume':float(x[9])})
        return out
    async def ticker(self,symbol):
        d=await self.get('/fapi/v1/ticker/bookTicker',{'symbol':symbol}); bid=float(d['bidPrice']); ask=float(d['askPrice']); return bid,ask,(bid+ask)/2
    async def premium(self,symbol): return await self.get('/fapi/v1/premiumIndex',{'symbol':symbol})
    async def oi(self,symbol): return await self.get('/fapi/v1/openInterest',{'symbol':symbol})
    async def depth(self,symbol,limit=20): return await self.get('/fapi/v1/depth',{'symbol':symbol,'limit':limit})
    async def snapshot(self,symbol,interval='5m',limit=260):
        candles,ticker,prem,oi,depth=await asyncio.gather(self.klines(symbol,interval,limit),self.ticker(symbol),self.premium(symbol),self.oi(symbol),self.depth(symbol,20))
        bid,ask,price=ticker; bids=sum(float(p)*float(q) for p,q in depth.get('bids',[])); asks=sum(float(p)*float(q) for p,q in depth.get('asks',[])); di=(bids-asks)/(bids+asks) if bids+asks else 0
        funding=float(prem.get('lastFundingRate') or 0); next_funding=int(prem.get('nextFundingTime') or 0); secs=max(0,(next_funding-int(time.time()*1000))/1000) if next_funding else 999999
        return candles,{'price':price,'bid':bid,'ask':ask,'spread_bps':(ask-bid)/price*10000 if price else 999,'funding':funding,'next_funding_time':next_funding,'funding_sec_to_settlement':secs,'funding_guard_active':abs(funding)>=0.0015 and secs<=900,'oi':float(oi.get('openInterest') or 0),'depth_imbalance':di,'depth_raw':depth,'ts':int(time.time()*1000)}
