"""Explicit bounded repair of recorded collector gaps using public REST.
No PAPER orders. A repair is successful only when every expected closed bar exists.
Missing/too-old/partial history remains unresolved; nothing is fabricated.
"""
from __future__ import annotations
import argparse,asyncio,json,sqlite3,time
from pathlib import Path
import aiohttp
from omnistudio.market.data import VenueRateLimiter
from .futures_market import MARKETS,instruments,candles_url,candles
from .futures_stream import INTERVAL,Store,valid

def expected_gap(prev,current,max_bars=250):
    if prev%INTERVAL or current%INTERVAL or current<=prev:raise ValueError('invalid gap bounds')
    n=(current-prev)//INTERVAL-1
    if n>max_bars:raise ValueError('gap exceeds bounded backfill')
    return set(range(prev+INTERVAL,current,INTERVAL))

def normalize_rows(inst,payload):
    cs=candles(inst,payload)
    if inst.market=='binance_coinm':
      # contract count * fixed quote face is not base volume * final price
      quantities={int(r[0]):float(r[5])*float(inst.contract_value) for r in payload if len(r)>=8}
    else:quantities={}
    return [(c.open_ms,c.open,c.high,c.low,c.close,quantities.get(c.open_ms,c.quote_volume),c.closed) for c in cs]

async def repair(dbpath,out,max_gaps=100):
    dbpath=Path(dbpath);out=Path(out)
    if not dbpath.is_file():raise FileNotFoundError(dbpath)
    out.mkdir(parents=True,exist_ok=False)
    db=sqlite3.connect(dbpath);db.execute('PRAGMA busy_timeout=5000')
    gaps=db.execute("SELECT rowid,market,symbol,details FROM incidents WHERE kind='GAP' ORDER BY rowid LIMIT ?",(max_gaps,)).fetchall();db.close()
    results=[];lim={'okx':VenueRateLimiter(4),'binance':VenueRateLimiter(3)}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'Mozilla/5.0 ACARBOT research'}) as s:
      catalogs={}
      for m in {g[1] for g in gaps}:
        try:
          root,path=MARKETS[m]
          async with s.get(root+path) as res:
            if res.status!=200:raise RuntimeError('HTTP '+str(res.status))
            records=instruments(m,await res.json(content_type=None));catalogs[m]={x.symbol:x for x in records}
        except Exception:catalogs[m]={}
      store=Store(dbpath)
      store.db.execute('PRAGMA busy_timeout=5000')
      for rid,m,symbol,details in gaps:
        res={'incident_rowid':rid,'market':m,'symbol':symbol,'status':'UNRESOLVED'}
        try:
          d=json.loads(details);expected=expected_gap(int(d['previous']),int(d['current']));inst=catalogs.get(m,{}).get(symbol)
          if not inst:raise ValueError('instrument metadata unavailable')
          existing={r[0] for r in store.db.execute('SELECT open_ms FROM candles WHERE market=? AND symbol=? AND open_ms>? AND open_ms<?',(m,symbol,d['previous'],d['current']))}
          need=expected-existing
          if need:
            limiter=lim[inst.exchange];await limiter.acquire()
            async with s.get(candles_url(inst)) as response:
              if response.status==429:limiter.on_throttle();raise RuntimeError('HTTP 429')
              if response.status!=200:raise RuntimeError('HTTP '+str(response.status))
              payload=await response.json(content_type=None)
            now=int(time.time()*1000)
            for row in normalize_rows(inst,payload):
              if row[0] in need and row[6] and row[0]+INTERVAL<=now and valid(row):store.insert(inst,row,now)
            store.commit()
          final={r[0] for r in store.db.execute('SELECT open_ms FROM candles WHERE market=? AND symbol=? AND open_ms>? AND open_ms<?',(m,symbol,d['previous'],d['current']))}
          res.update(status='REPAIRED' if expected<=final else 'UNRESOLVED',missing=len(expected-final),expected=len(expected))
        except Exception as e:res['error']=type(e).__name__+': '+str(e)[:200]
        results.append(res)
      store.close()
    result={'mode':'OBSERVE_BACKFILL','gaps_reviewed':len(gaps),'repaired':sum(x['status']=='REPAIRED' for x in results),'results':results,'real_orders':0,'note':'Historical repair is never a fresh entry signal. Collector does not run this automatically.'}
    (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--out',required=True);p.add_argument('--max-gaps',type=int,default=100);a=p.parse_args();asyncio.run(repair(a.db,a.out,a.max_gaps))
if __name__=='__main__':main()
