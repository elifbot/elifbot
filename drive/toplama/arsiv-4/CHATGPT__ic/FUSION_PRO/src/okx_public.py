import asyncio, time, httpx

class OKXPublic:
    def __init__(self, base='https://www.okx.com'):
        self.base=base.rstrip('/'); self.client=httpx.AsyncClient(timeout=8, headers={'User-Agent':'FusionPro/4.0'})
    async def close(self): await self.client.aclose()
    async def get(self,path,params=None):
        r=await self.client.get(self.base+path,params=params); r.raise_for_status(); d=r.json()
        if d.get('code')!='0': raise RuntimeError(d)
        return d['data']
    async def klines(self,symbol,interval='5m',limit=260):
        bar={'1m':'1m','5m':'5m','15m':'15m','1h':'1H','4h':'4H'}.get(interval,interval)
        rows=await self.get('/api/v5/market/candles',{'instId':symbol,'bar':bar,'limit':str(min(limit,300))}); out=[]; now=int(time.time()*1000)
        ms={'1m':60000,'5m':300000,'15m':900000,'1h':3600000,'4h':14400000}.get(interval,300000)
        for x in reversed(rows):
            ts=int(x[0]);
            if ts+ms>=now: continue
            out.append({'ts':ts,'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4]),'volume':float(x[5]),'trades':0,'taker_buy_volume':0.0})
        return out
    async def ticker(self,symbol):
        d=(await self.get('/api/v5/market/ticker',{'instId':symbol}))[0]; bid=float(d['bidPx']); ask=float(d['askPx']); return bid,ask,(bid+ask)/2
    async def funding(self,symbol):
        d=(await self.get('/api/v5/public/funding-rate',{'instId':symbol}))[0]; return float(d.get('fundingRate') or 0), int(d.get('fundingTime') or 0)
    async def oi(self,symbol):
        d=(await self.get('/api/v5/public/open-interest',{'instId':symbol}))[0]; return float(d.get('oi') or 0)
    async def depth(self,symbol,limit=20): return (await self.get('/api/v5/market/books',{'instId':symbol,'sz':str(min(limit,400))}))[0]
    async def snapshot(self,symbol,interval='5m',limit=260):
        candles,ticker,fund,oi,depth=await asyncio.gather(self.klines(symbol,interval,limit),self.ticker(symbol),self.funding(symbol),self.oi(symbol),self.depth(symbol,20))
        bid,ask,price=ticker; bids=sum(float(p)*float(q) for p,q,*_ in depth.get('bids',[])); asks=sum(float(p)*float(q) for p,q,*_ in depth.get('asks',[])); di=(bids-asks)/(bids+asks) if bids+asks else 0
        funding,nextf=fund; secs=max(0,(nextf-int(time.time()*1000))/1000) if nextf else 999999
        return candles,{'price':price,'bid':bid,'ask':ask,'spread_bps':(ask-bid)/price*10000 if price else 999,'funding':funding,'next_funding_time':nextf,'funding_sec_to_settlement':secs,'funding_guard_active':abs(funding)>=0.0015 and secs<=900,'oi':oi,'depth_imbalance':di,'depth_raw':depth,'ts':int(time.time()*1000)}
