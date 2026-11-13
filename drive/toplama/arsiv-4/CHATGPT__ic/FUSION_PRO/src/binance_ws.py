import asyncio, json, time
import websockets

class BinanceFuturesWS:
    """Public futures WS: BBO + aggTrade. No API key. Reconnects with backoff."""
    def __init__(self, base='wss://fstream.binance.com/stream'):
        self.base=base; self.running=False; self.latest={}; self.trade_imb={}; self.last_message=0.0
    async def run(self,symbols):
        streams=[]
        for s in symbols:
            x=s.lower(); streams += [f'{x}@bookTicker',f'{x}@aggTrade']
        url=self.base+'?streams='+'/'.join(streams); delay=1
        while self.running:
            try:
                async with websockets.connect(url,ping_interval=20,ping_timeout=10,max_size=2_000_000) as ws:
                    delay=1
                    async for raw in ws:
                        msg=json.loads(raw); d=msg.get('data',{}); st=msg.get('stream',''); sym=st.split('@')[0].upper()
                        self.last_message=time.time()
                        if st.endswith('@bookTicker'):
                            self.latest[sym]={'bid':float(d['b']),'ask':float(d['a']),'bid_qty':float(d['B']),'ask_qty':float(d['A']),'ts':time.time()}
                        elif st.endswith('@aggTrade'):
                            q=float(d['q']); self.trade_imb[sym]=0.8*self.trade_imb.get(sym,0)+0.2*( -1 if d.get('m') else 1)*min(q,10.0)
            except Exception:
                await asyncio.sleep(delay); delay=min(delay*2,30)
    def start(self,symbols): self.running=True; return asyncio.create_task(self.run(symbols))
    async def stop(self): self.running=False
