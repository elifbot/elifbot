import asyncio, time
from .engine import FusionEngine
from .universe import UniverseScanner

class MultiExchangeEngine:
    """Tracks the complete eligible linear futures universe on Binance and OKX.
    All contracts are monitored via lightweight market stats; deep signal analysis is
    automatically concentrated on event-driven candidates, so the universe is not
    artificially limited to 100 coins."""
    def __init__(self, clients, cfg, store=None):
        self.clients=clients; self.cfg=cfg; self.store=store
        self.scanner=UniverseScanner(clients.get('binance'),clients.get('okx'),cfg)
        self.engines={}

    async def discover(self):
        instruments=await self.scanner.discover()
        for ex in ('binance','okx'):
            subset=[i for i in instruments if i.exchange==ex]
            mapping={i.symbol:i for i in subset}
            self.engines[ex]=FusionEngine(self.clients[ex],self.cfg,self.store,ex,mapping)
        return instruments

    async def cycle(self):
        instruments=await self.discover()
        ranked=self.scanner.rank_event_candidates(instruments,int(self.cfg['market'].get('deep_scan_candidates',40)))
        # Never hard-code a coin list. The full universe is refreshed; only abnormal symbols
        # consume expensive candles/HTF/orderbook requests.
        results=[]
        for _,inst in ranked:
            eng=self.engines[inst.exchange]
            results.append(await eng.scan(inst.symbol))
        return instruments,results

    async def loop(self):
        while True:
            started=time.time()
            try:
                instruments,results=await self.cycle()
                print(f"UNIVERSE={len(instruments)} DEEP_SCANNED={len(results)}",flush=True)
                for r in sorted(results,key=lambda x:float(x.get('quality_score') or 0),reverse=True)[:10]:
                    print(FusionEngine.scan_line(r),flush=True)
            except Exception as e:
                print('MULTI-EXCHANGE ERROR:',e,flush=True)
            await asyncio.sleep(max(1,float(self.cfg['ops']['loop_sec'])-(time.time()-started)))
