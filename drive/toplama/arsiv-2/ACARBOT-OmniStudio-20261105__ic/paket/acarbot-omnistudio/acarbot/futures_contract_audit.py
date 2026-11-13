"""Public metadata + synthetic price arithmetic audit. No trade or market signal."""
from __future__ import annotations
import argparse,asyncio,json,time
from collections import Counter,defaultdict
from decimal import Decimal as D
from pathlib import Path
import aiohttp
from .futures_market import MARKETS
from .contract_math import from_exchange_record,CurrencyLedger

async def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);summary={};examples=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'Mozilla/5.0 ACARBOT research'}) as session:
      async def one(market,base,path):
        info={'source':'public exchange metadata','mapped':0,'failed':0,'total':0,'errors':[],'kinds':{},'settlements':{},'synthetic_roundtrips':0,'status':'ERROR'}
        try:
          async with session.get(base+path) as resp:
            if resp.status!=200:raise RuntimeError('HTTP '+str(resp.status))
            payload=await resp.json(content_type=None)
          rows=payload.get('symbols') if market.startswith('binance') else payload.get('data')
          if not isinstance(rows,list):raise ValueError('invalid catalog')
          state='contractStatus' if market=='binance_coinm' else 'status' if market=='binance_usdm' else 'state'; live='live' if market.startswith('okx') else 'TRADING'
          rows=[r for r in rows if r.get(state)==live];info['total']=len(rows);kind=Counter();settle=Counter();now=int(time.time()*1000)
          for r in rows:
            try:
              s=from_exchange_record(market,r);qty=s.qty(max(s.min_qty,s.lot_step));kind[s.kind]+=1;settle[s.settlement]+=1
              for side,expect in [('LONG',1),('SHORT',-1)]:
                ledger=CurrencyLedger({s.settlement:'1000000000'});ledger.open(s,side,qty,'100',0,now);result=ledger.close(market,s.symbol,'110',0,now+1)
                if result['gross']*expect<=0:raise ValueError('unexpected sign')
              info['synthetic_roundtrips']+=2;info['mapped']+=1
              if len(examples)<12 and (s.kind=='inverse' or s.settlement!='USDT'):
                examples.append({'market':market,'symbol':s.symbol,'kind':s.kind,'settlement':s.settlement,'face':str(s.face),'lot_step':str(s.lot_step),'entry':'100','exit':'110','long_pnl_native':str(s.pnl('LONG',qty,100,110)),'prices_are_synthetic':True})
            except Exception as e:
              info['failed']+=1
              if len(info['errors'])<20:info['errors'].append({'symbol':r.get('symbol') or r.get('instId'),'reason':f'{type(e).__name__}: {str(e)[:120]}'})
          info['kinds']=dict(kind);info['settlements']=dict(settle);info['status']='OK' if info['failed']==0 and info['total'] else 'PARTIAL'
        except Exception as e:info['errors'].append({'reason':f'{type(e).__name__}: {str(e)[:160]}'})
        summary[market]=info
      await asyncio.gather(*(one(m,*p) for m,p in MARKETS.items()))
    result={'status':'METADATA_AND_SYNTHETIC_MATH_ONLY','markets':summary,'examples':examples,'real_orders':0,'paper_strategy_orders':0,'limits':['not wired to live strategy','synthetic prices, not live executions or profitability','fee schedule, FX, margin risk, X-perp funding and expiry not validated','no 1:1 currency conversion']}
    (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();asyncio.run(run(a.out))
if __name__=='__main__':main()
