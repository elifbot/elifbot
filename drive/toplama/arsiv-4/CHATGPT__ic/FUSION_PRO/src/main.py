import argparse, asyncio
from .config import load_config
from .exchange_factory import public_client
from .storage import Store
from .multi_engine import MultiExchangeEngine
from .engine import FusionEngine

async def run(args):
    cfg=load_config(args.config)
    clients={}
    exchanges=['binance','okx'] if args.exchange=='both' else [args.exchange or cfg['market'].get('exchange','binance')]
    for ex in exchanges:
        c=dict(cfg['market'])
        c['exchange']=ex
        cfg_ex=dict(cfg); cfg_ex['market']=c
        clients[ex]=public_client(cfg_ex)
    store=Store(cfg['paper']['persist_db']); eng=MultiExchangeEngine(clients,cfg,store)
    try:
        if args.once:
            instruments,results=await eng.cycle()
            print(f'UNIVERSE={len(instruments)} DEEP_SCANNED={len(results)}')
            for r in sorted(results,key=lambda x:float(x.get('quality_score') or 0),reverse=True): print(FusionEngine.scan_line(r))
        else:
            await eng.loop()
    finally:
        await asyncio.gather(*[c.close() for c in clients.values()])

def main():
    p=argparse.ArgumentParser(); p.add_argument('--exchange',choices=['binance','okx','both'],default='both'); p.add_argument('--mode',default='live-paper'); p.add_argument('--once',action='store_true'); p.add_argument('--config',default='config.yaml'); a=p.parse_args()
    if a.mode not in ('live-paper','live'): raise SystemExit('mode: live-paper veya live')
    cfg=load_config(a.config)
    if a.mode=='live' and not cfg['trading'].get('live_enabled',False): raise SystemExit('LIVE kapalı. config.yaml trading.live_enabled=true yapmadan gerçek emir gönderilmez.')
    asyncio.run(run(a))
if __name__=='__main__': main()
