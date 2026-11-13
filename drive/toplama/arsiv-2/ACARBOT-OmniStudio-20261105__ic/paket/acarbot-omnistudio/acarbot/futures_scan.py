"""İki borsanın bütün mevcut vadeli evrenini kamu verisiyle gözlemler.
Gözlem modu: PAPER dahil emir üretmez. Eksik borsa/seri açıkça raporlanır.
"""
from __future__ import annotations
import argparse, asyncio, json, time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import aiohttp
from omnistudio.market.data import VenueRateLimiter
from .futures_market import MARKETS,instruments,ticker_url,tickers,candles_url,candles
from .strategy import decide

async def scan(out:Path, do_candles=True, limit_rate=8):
    out.mkdir(parents=True,exist_ok=False)
    report={'started_utc':datetime.now(timezone.utc).isoformat(),'mode':'OBSERVE_NO_ORDERS','markets':{},'instruments':0,'quotes':0,'candles_requested':0,'candles_ok':0,'signals':0,'errors':[],'real_orders':0,'real_money_approved':False}
    limiter=VenueRateLimiter(limit_rate); sem=asyncio.Semaphore(12); series=[]; results=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'Mozilla/5.0 (ACARBOT market research)'}) as session:
      async def get(url,limited=True):
        if limited:await limiter.acquire()
        async with session.get(url) as r:
          body=await r.text()
          if r.status==429:limiter.on_throttle(); raise RuntimeError('HTTP 429')
          if r.status!=200:raise RuntimeError(f'HTTP {r.status}: {body[:120]}')
          limiter.on_success()
          return json.loads(body)
      async def load(market,base,path):
        info={'discovered':0,'quoted':0,'status':'ERROR','error':''}
        try:
          ins=instruments(market,await get(base+path));
          if not ins:raise RuntimeError('aktif enstrüman bulunamadı')
          series.extend(ins); info['discovered']=len(ins); info['status']='AVAILABLE'
          try:
            q=tickers(market,await get(ticker_url(market))); info['quoted']=sum(i.symbol in q for i in ins)
          except Exception as e:info['ticker_error']=f'{type(e).__name__}: {e}'
        except Exception as e:info['error']=f'{type(e).__name__}: {e}'
        report['markets'][market]=info
      await asyncio.gather(*(load(m,*v) for m,v in MARKETS.items()))
      report['instruments']=len(series);report['quotes']=sum(x['quoted'] for x in report['markets'].values())
      print('EVREN',json.dumps(report['markets'],ensure_ascii=False),flush=True)
      if do_candles:
        async def one(inst):
          async with sem:
            report['candles_requested']+=1
            try:
              cs=candles(inst,await get(candles_url(inst)));report['candles_ok']+=1
              res=decide(cs,int(time.time()*1000),'trend')
              return {'instrument':asdict(inst),'key':inst.key,'candles_returned':len(cs),'reason':res.reason,'side':res.side.value if res.side else None,'bar_open_ms':res.bar_open_ms,'volume_ratio':res.volume_ratio}
            except Exception as e:
              return {'instrument':asdict(inst),'key':inst.key,'reason':'DATA_ERROR','error':f'{type(e).__name__}: {str(e)[:220]}'}
        tasks=[asyncio.create_task(one(x)) for x in series]
        for fut in asyncio.as_completed(tasks):
          row=await fut;results.append(row)
          if len(results)%100==0:print('MUM',len(results),'/',len(series),flush=True)
    reasons=Counter(r['reason'] for r in results)
    report['strategy_reasons']=dict(reasons);report['signals']=sum(bool(r.get('side')) for r in results)
    report['rate_limit']=limiter.to_dict();report['finished_utc']=datetime.now(timezone.utc).isoformat()
    report['status']='COMPLETE' if len(report['markets'])==4 and all(r['status']=='AVAILABLE' and r.get('quoted')==r.get('discovered') for r in report['markets'].values()) and (not do_candles or report['candles_ok']==len(series)) else 'PARTIAL'
    report['limitations']=['Bu mod gözlemdir; PAPER dahi emir açmaz.','Binance erişimi yoksa sonuç PARTIAL; hiçbir alternatif borsa Binance yerine gösterilmez.','Tüm aktif sözleşmeler keşfedilir; inverse/teslimatlı sözleşmeler için PAPER hesaplama henüz uygulanmadı.','Tek tarama sürekli izleme veya kârlılık kanıtı değildir.','COIN-M quote hacmi fiyatla yaklaşık dönüştürülür.']
    (out/'SONUC.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (out/'ENSTRUMANLAR.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in results))
    print('SONUÇ',json.dumps({'status':report['status'],'instruments':report['instruments'],'quotes':report['quotes'],'candles_ok':report['candles_ok'],'signals':report['signals'],'reasons':report['strategy_reasons']},ensure_ascii=False),flush=True)
    return report

def main():
    p=argparse.ArgumentParser(description='Binance ve OKX vadeli evren gözlem taraması, emir yok')
    p.add_argument('--out',required=True);p.add_argument('--no-candles',action='store_true');p.add_argument('--rate',type=float,default=8)
    a=p.parse_args(); r=asyncio.run(scan(Path(a.out),not a.no_candles,a.rate));raise SystemExit(0 if r['status']=='COMPLETE' else 1)
if __name__=='__main__':main()
