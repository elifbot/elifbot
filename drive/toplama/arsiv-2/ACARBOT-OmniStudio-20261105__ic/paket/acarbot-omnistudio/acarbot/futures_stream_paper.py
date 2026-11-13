"""Kapanmış WebSocket mumlarıyla USDT-lineer PAPER araştırma koşusu.

`futures_stream` ayrı süreçte aynı SQLite dosyasını beslemelidir. İlk 260 mum
REST ile ısıtılır. Sanal alım-satım yalnız önceki USDT lineer perpetual scope;
çok-para birimli deneysel contract_math otomatik yürütmeye BAĞLI DEĞİLDİR.
"""
from __future__ import annotations
import argparse,asyncio,json,sqlite3,time
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import aiohttp
from omnistudio.core.types import Candle,Quote
from omnistudio.market.data import VenueRateLimiter
from omnistudio.strategy.indicators import atr
from .futures_market import MARKETS,instruments,tickers,ticker_url,candles_url,candles
from .futures_paper import paper_eligible,f_url,f_next
from .strategy import decide,closed_candles
from .ledger import Ledger

def ms():return int(time.time()*1000)
def utc():return datetime.now(timezone.utc).isoformat()

def merge_bar(history,bar):
    """Kapanış sırasını koru; yenisini ekle veya yineleni düzelt; gap kontrolü stratejide."""
    if not bar.closed:raise ValueError('open candle is not strategy input')
    d={c.open_ms:c for c in history};d[bar.open_ms]=bar
    return [d[k] for k in sorted(d)][-260:]

async def run(out:Path,dbpath:Path,duration=600,limit=0):
    if duration<=0 or limit<0:raise ValueError('geçersiz ayar')
    if not dbpath.is_file():raise FileNotFoundError('Önce futures_stream başlatın')
    out.mkdir(parents=True,exist_ok=False); event=out/'events.jsonl'; counts=Counter();history={};quotes={};funding={};markets={};ledger=Ledger(); errors=[]; universe=[]
    began=utc();begin=time.monotonic(); rates={'binance':VenueRateLimiter(5),'okx':VenueRateLimiter(8)};sem=asyncio.Semaphore(12)
    def log(d):
        with event.open('a',encoding='utf8') as f:f.write(json.dumps(d,ensure_ascii=False,default=str)+'\n')
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'Mozilla/5.0 ACARBOT research'}) as s:
      async def get(url,exchange):
        rate=rates[exchange];await rate.acquire()
        async with s.get(url) as r:
          body=await r.text()
          if r.status==429:rate.on_throttle();raise RuntimeError('HTTP 429')
          if r.status!=200:raise RuntimeError('HTTP '+str(r.status))
          rate.on_success();return json.loads(body)
      async def discover(m,base,path):
        x='okx' if m.startswith('okx') else 'binance'
        try:
          rows=instruments(m,await get(base+path,x));total=len(rows)
          if not total:raise ValueError('empty')
          if limit:rows=rows[:limit]
          markets[m]={'status':'AVAILABLE','total':total,'selected':len(rows)};universe.extend(rows)
        except Exception as e:markets[m]={'status':'ERROR','error':str(e)[:150]}
      await asyncio.gather(*(discover(m,*p) for m,p in MARKETS.items()))
      bymarket={m:[i for i in universe if i.market==m] for m in MARKETS};bykey={(i.market,i.symbol):i for i in universe}
      if not universe:raise RuntimeError('no accessible markets')
      async def load(i):
        async with sem:
          try:history[i.key]=candles(i,await get(candles_url(i),i.exchange));counts['warmup_ok']+=1
          except Exception as e:counts['warmup_errors']+=1;log({'event':'WARMUP_ERROR','key':i.key,'error':str(e)[:150]})
      await asyncio.gather(*(load(i) for i in universe))
      # DB geçmişte eklenen kayıtları başlangıçta signal sayma; sonraki yeni
      # sıra numaralarını dinle. Stream sonrası REST ile kapanmış mum uyuşmazlığı
      # CANDLE_GAP/tazelik kontrollerinden geçmek zorundadır.
      db=sqlite3.connect('file:'+str(dbpath.resolve())+'?mode=ro',uri=True,isolation_level=None)
      watermark=db.execute('SELECT COALESCE(MAX(rowid),0) FROM candles').fetchone()[0]
      # Uzak REST snapshot'ı yaşlı olabilir: gözlemdeki son kapanışları
      # history'ye kat; başlangıç öncesi mumları giriş sinyali yapma.
      rows=db.execute('SELECT market,symbol,open_ms,o,h,l,c,quote_volume FROM candles WHERE rowid<=? ORDER BY rowid',(watermark,)).fetchall()
      for m,symbol,t,o,h,l,c,v in rows:
        i=bykey.get((m,symbol))
        if i:history[i.key]=merge_bar(history.get(i.key,[]),Candle(symbol,m,t,o,h,l,c,v,True))
      seen={i.key:closed_candles(history.get(i.key,[]),ms())[-1].open_ms for i in universe if closed_candles(history.get(i.key,[]),ms())}
      ready=sum(len(closed_candles(x,ms()))>=250 for x in history.values())
      t0=time.monotonic();deadline=t0+duration
      log({'event':'ACTIVE_START','time':utc(),'symbols':len(universe),'ready':ready,'feed_watermark':watermark,'mode':'USDT linear perpetual PAPER only'})
      print(f'ACTIVE {duration}s {len(universe)} instruments {ready} histories',flush=True)
      async def refresh(m):
        ins=bymarket[m]
        if not ins:return
        try:
          q=tickers(m,await get(ticker_url(m),ins[0].exchange)); now=ms()
          for i in ins:
            z=q.get(i.symbol)
            if not z or not z['ts_ms'] or abs(now-z['ts_ms'])>15000:continue
            qq=Quote(i.market,i.key,z['bid'],z['ask'],z['ts_ms']);quotes[i.key]=qq;counts['fresh_quotes']+=1
            trade=ledger.on_quote(qq,now)
            if trade:log({'event':'CLOSE',**asdict(trade)})
            if i.key in ledger.positions and i.key in funding and now>=funding[i.key]-180000:
              trade=ledger.close(qq,'FUNDING_AVOIDANCE',now);log({'event':'CLOSE',**asdict(trade)})
          counts['ticker_fetch_ok']+=1
        except Exception as e:counts['ticker_errors']+=1;errors.append(m+': '+str(e)[:150])
      await asyncio.gather(*(refresh(m) for m in MARKETS))
      async def quotes_loop():
        while time.monotonic()<deadline:
          await asyncio.gather(*(refresh(m) for m in MARKETS));await asyncio.sleep(5)
      qt=asyncio.create_task(quotes_loop())
      try:
        while time.monotonic()<deadline:
          rows=db.execute('SELECT rowid,market,symbol,open_ms,o,h,l,c,quote_volume,observed_ms FROM candles WHERE rowid>? ORDER BY rowid LIMIT 5000',(watermark,)).fetchall()
          for rowid,m,symbol,t,o,h,l,c,v,observed in rows:
            if time.monotonic()>=deadline:break
            watermark=rowid;i=bykey.get((m,symbol))
            if not i:continue
            bar=Candle(symbol,m,t,o,h,l,c,v,True); history[i.key]=merge_bar(history.get(i.key,[]),bar)
            if t<=seen.get(i.key,0):continue
            seen[i.key]=t;counts['bars_evaluated']+=1;counts['bars_'+m]+=1
            decision=decide(history[i.key],ms());counts['strategy_'+decision.reason]+=1
            if not decision.side:continue
            counts['signals']+=1
            if not paper_eligible(i):counts['reject_unsupported_type']+=1;continue
            q=quotes.get(i.key);a=atr(closed_candles(history[i.key],ms()))
            if not q or ms()-q.ts_ms>15000:counts['reject_stale_quote']+=1;continue
            if i.key in ledger.positions:counts['reject_already_open']+=1;continue
            if q.spread_bps>8:counts['reject_spread']+=1;continue
            if abs(q.mid/c-1)*10000>25:counts['reject_price_deviation']+=1;continue
            if not a or (a/q.mid)*10000*.35<(15+q.spread_bps)*1.15:counts['reject_cost']+=1;continue
            try:
              remaining=deadline-time.monotonic()
              if remaining<=0:break
              nxt=f_next(i,await asyncio.wait_for(get(f_url(i),i.exchange),remaining))
              if nxt-ms()<180000:raise ValueError('funding near')
              funding[i.key]=nxt
            except Exception as e:counts['reject_funding']+=1;continue
            if time.monotonic()>=deadline or ms()-q.ts_ms>15000:counts['reject_stale_after_checks']+=1;continue
            p=ledger.open(q,decision.side,a,ms())
            if p:counts['opened']+=1;log({'event':'OPEN',**asdict(p)})
            else:counts['reject_portfolio']+=1
          await asyncio.sleep(.2 if rows else 1)
      finally:
        qt.cancel();await asyncio.gather(qt,return_exceptions=True)
        active=time.monotonic()-t0
        await asyncio.gather(*(refresh(m) for m in MARKETS))
        for key in list(ledger.positions):
          q=quotes.get(key)
          if q and ms()-q.ts_ms<=15000:
            p=ledger.close(q,'RUN_END',ms());log({'event':'CLOSE',**asdict(p)})
        db.close()
    result={'status':'PARTIAL','started_utc':began,'finished_utc':utc(),'active_sec':round(active,3),'total_sec':round(time.monotonic()-begin,3),'markets':markets,'symbols_selected':len(universe),'paper_eligible':sum(paper_eligible(i) for i in universe),'paper_unsupported':sum(not paper_eligible(i) for i in universe),'counts':dict(counts),'execution':ledger.summary(),'errors':errors[:30],'real_orders':0,'limits':['USDT-linear perpetual only; multi-currency core not wired','stream and initial REST must be running and reachable','feed gap backfill is not automatic','no slippage/depth/real fill guarantee','funding avoidance; funding accounting absent','symbols list refresh requires restart']}
    (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('SONUÇ',json.dumps(result,ensure_ascii=False),flush=True);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--db',required=True);p.add_argument('--duration',type=float,default=600);p.add_argument('--limit-per-market',type=int,default=0);a=p.parse_args();asyncio.run(run(Path(a.out),Path(a.db),a.duration,a.limit_per_market))
if __name__=='__main__':main()
