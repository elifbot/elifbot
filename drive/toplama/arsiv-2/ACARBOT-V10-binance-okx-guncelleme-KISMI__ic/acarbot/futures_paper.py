"""Binance + OKX PAPER: sınırsız evren keşfi; yalnız USDT lineer SWAP icrası.
Diğer sözleşmeler gözlenir; inverse/vadeli/USDC defteri doğrulanana kadar
reddedilir. Borsa erişilemezse sonuç PARTIAL. Gerçek emir kesinlikle yok.
"""
from __future__ import annotations
import argparse, asyncio, json, time
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
import aiohttp
from omnistudio.core.types import Quote
from omnistudio.market.data import VenueRateLimiter
from omnistudio.strategy.indicators import atr
from .futures_market import MARKETS, instruments, tickers, ticker_url, candles_url, candles
from .strategy import decide, closed_candles
from .ledger import Ledger

def utc():return datetime.now(timezone.utc).isoformat()
def ms():return int(time.time()*1000)

def paper_eligible(i):
    return ((i.market=='okx_swap' and i.contract_type=='linear' and i.settlement=='USDT')
            or (i.market=='binance_usdm' and i.contract_type=='PERPETUAL' and i.settlement=='USDT'))

def f_url(i):
    if i.market=='okx_swap':return 'https://www.okx.com/api/v5/public/funding-rate?'+urlencode({'instId':i.symbol})
    if i.market=='binance_usdm':return 'https://fapi.binance.com/fapi/v1/premiumIndex?'+urlencode({'symbol':i.symbol})
    raise ValueError('funding desteklenmiyor')

def f_next(i,data):
    if i.market=='okx_swap':
        if data.get('code')!='0' or not data.get('data'):raise ValueError('funding verisi yok')
        return int(data['data'][0]['fundingTime'])
    return int(data['nextFundingTime'])

async def run(out:Path,duration=600,limit_per_market=0):
    if duration<=0 or limit_per_market<0:raise ValueError('Geçersiz ayar')
    out.mkdir(parents=True,exist_ok=False); event=out/'events.jsonl'; counters=Counter(); ledger=Ledger(); quotes={}; bars={}; seen={}; funding={}; markets={}; universe=[]; errors=[]
    def log(row):
        with event.open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
    rates={'okx':VenueRateLimiter(8),'binance':VenueRateLimiter(5)};sem=asyncio.Semaphore(12); start=time.monotonic();started_utc=utc();active=0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'Mozilla/5.0 (ACARBOT market research)'}) as session:
      async def get(url,exchange):
        limiter=rates[exchange];await limiter.acquire()
        async with session.get(url) as r:
          raw=await r.text()
          if r.status==429:limiter.on_throttle();raise RuntimeError('HTTP 429')
          if r.status!=200:raise RuntimeError(f'HTTP {r.status}: {raw[:100]}')
          limiter.on_success(); return json.loads(raw)
      async def discover(market,base,path):
        exchange='okx' if market.startswith('okx') else 'binance'
        try:
          items=instruments(market,await get(base+path,exchange))
          if not items:raise RuntimeError('aktif evren boş')
          total=len(items);items=items[:limit_per_market] if limit_per_market else items
          universe.extend(items);markets[market]={'status':'AVAILABLE','discovered':total,'selected':len(items)}
        except Exception as e:markets[market]={'status':'ERROR','error':str(e)[:200]}
      await asyncio.gather(*(discover(m,*v) for m,v in MARKETS.items()))
      if not universe:
        result={'status':'FAILED','markets':markets,'reason':'NO_AVAILABLE_MARKETS','real_orders':0};(out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result
      bymarket={m:[i for i in universe if i.market==m] for m in MARKETS}
      async def refresh_quotes(market):
        ins=bymarket[market]
        if not ins:return
        try:
          rows=tickers(market,await get(ticker_url(market),ins[0].exchange)); stamp=ms()
          for i in ins:
            r=rows.get(i.symbol)
            if not r or not r['ts_ms'] or abs(stamp-r['ts_ms'])>15000:continue
            q=Quote(i.market,i.key,r['bid'],r['ask'],r['ts_ms']);quotes[i.key]=q;counters['fresh_quotes']+=1
            trade=ledger.on_quote(q,stamp)
            if trade:log({'event':'CLOSE',**asdict(trade)})
            if i.key in ledger.positions and i.key in funding and stamp>=funding[i.key]-180000:
              trade=ledger.close(q,'FUNDING_AVOIDANCE',stamp);log({'event':'CLOSE',**asdict(trade)})
          counters['ticker_fetch_ok']+=1
        except Exception as e:counters['ticker_errors']+=1;errors.append(f'{market} ticker: {e}')
      async def refresh_candle(i):
        async with sem:
          try:
            data=candles(i,await get(candles_url(i),i.exchange));bars[i.key]=data;counters['candles_ok']+=1
          except Exception as e:counters['candle_errors']+=1;log({'event':'CANDLE_ERROR','key':i.key,'error':str(e)[:120]})
      async def refresh_all_candles():await asyncio.gather(*(refresh_candle(i) for i in universe))
      await asyncio.gather(*(refresh_quotes(m) for m in MARKETS),refresh_all_candles())
      # Eski mumu başlangıçta girişe dönüştürme.
      for i in universe:
        cc=closed_candles(bars.get(i.key,[]),ms())
        if cc:seen[i.key]=cc[-1].open_ms
      ready=sum(len(closed_candles(x,ms()))>=250 for x in bars.values());t0=time.monotonic();deadline=t0+duration;last_candles=0
      log({'event':'ACTIVE_START','time':utc(),'universe':len(universe),'ready':ready,'scope':'PAPER linear USDT perpetual only'})
      print(f'ACTIVE {duration}s: {len(universe)} enstrüman, {ready} hazır',flush=True)
      async def quote_loop():
        while time.monotonic()<deadline:
          await asyncio.gather(*(refresh_quotes(m) for m in MARKETS))
          await asyncio.sleep(5)
      quote_task=asyncio.create_task(quote_loop())
      while time.monotonic()<deadline:
        t=time.monotonic()
        if t-last_candles>=20:
          await refresh_all_candles();last_candles=time.monotonic()
          for i in universe:
            if time.monotonic()>=deadline:break
            cs=closed_candles(bars.get(i.key,[]),ms())
            if not cs or seen.get(i.key)==cs[-1].open_ms:continue
            seen[i.key]=cs[-1].open_ms; counters['bars_evaluated']+=1
            dec=decide(cs,ms());counters['strategy_'+dec.reason]+=1
            if not dec.side:continue
            counters['signals']+=1
            if not paper_eligible(i):counters['reject_contract_type_not_supported']+=1;continue
            q=quotes.get(i.key);a=atr(cs)
            if not q or ms()-q.ts_ms>15000:counters['reject_stale_quote']+=1;continue
            if i.key in ledger.positions:counters['reject_already_open']+=1;continue
            if q.spread_bps>8:counters['reject_spread']+=1;continue
            if abs(q.mid/cs[-1].close-1)*10000>25:counters['reject_price_deviation']+=1;continue
            if not a or (a/q.mid)*10000*.35<(15+q.spread_bps)*1.15:counters['reject_cost']+=1;continue
            try:
              nxt=f_next(i,await get(f_url(i),i.exchange))
              if nxt-ms()<180000:raise ValueError('funding yakın veya geçmiş')
              funding[i.key]=nxt
            except Exception as e:counters['reject_funding']+=1;log({'event':'REJECT','key':i.key,'reason':'FUNDING_UNAVAILABLE','error':str(e)[:150]});continue
            if time.monotonic()>=deadline or ms()-q.ts_ms>15000:counters['reject_stale_after_checks']+=1;continue
            p=ledger.open(q,dec.side,a,ms())
            if p:counters['opened']+=1;log({'event':'OPEN',**asdict(p)})
            else:counters['reject_portfolio']+=1
        # Funding öncesi taze teklif varsa kapat; maliyet atlanmaz.
        for key in list(ledger.positions):
          if key in funding and ms()>=funding[key]-180000:
            q=quotes.get(key)
            if q and ms()-q.ts_ms<=15000:
              p=ledger.close(q,'FUNDING_AVOIDANCE',ms());log({'event':'CLOSE',**asdict(p)})
        await asyncio.sleep(min(1,max(0,deadline-time.monotonic())))
      active=time.monotonic()-t0
      quote_task.cancel()
      await asyncio.gather(quote_task,return_exceptions=True)
      # taze son quote olmadan açık pozisyon kapatıldığı varsayılmaz.
      await asyncio.gather(*(refresh_quotes(m) for m in MARKETS))
      for key in list(ledger.positions):
        q=quotes.get(key)
        if q and ms()-q.ts_ms<=15000:
          p=ledger.close(q,'RUN_END',ms());log({'event':'CLOSE',**asdict(p)})
    all_available=all(markets.get(m,{}).get('status')=='AVAILABLE' for m in MARKETS)
    complete=all_available and limit_per_market==0 and not ledger.positions and not counters['candle_errors'] and not counters['ticker_errors'] and not any(not paper_eligible(i) for i in universe)
    result={'status':'COMPLETE' if complete else 'PARTIAL','started_utc':started_utc,'finished_utc':utc(),'active_sec':round(active,3),'total_sec':round(time.monotonic()-start,3),'markets':markets,'symbols_selected':len(universe),'paper_eligible':sum(paper_eligible(i) for i in universe),'paper_unsupported':sum(not paper_eligible(i) for i in universe),'counts':dict(counters),'execution':ledger.summary(),'errors':errors[:30], 'real_orders':0,'real_money_approved':False,'limitations':['Binance 451 olursa eksik; başka kaynakla ikame yok.','Yalnız lineer USDT sürekli sözleşmeler PAPER; inverse ve vadeli yalnız izlenir.','Tüm sözleşme listesi yalnız başlangıçta alınır.','Piyasa derinliği, funding muhasebesi ve gerçek dolum garanti edilmez.','Bağımsız YZ incelemesi tasarım içindir; canlı işlem hakemi değildir.']}
    (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('SONUÇ',json.dumps({'status':result['status'],'active_sec':result['active_sec'],'counts':result['counts'],'selected':len(universe)},ensure_ascii=False),flush=True)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--duration',type=float,default=600);p.add_argument('--limit-per-market',type=int,default=0);p.add_argument('--out',required=True);a=p.parse_args()
    r=asyncio.run(run(Path(a.out),a.duration,a.limit_per_market));raise SystemExit(0 if r['status']=='COMPLETE' else 1)
if __name__=='__main__':main()
