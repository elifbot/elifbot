"""Gerçek Gate USDT perpetual REST verisiyle 10dk PAPER çalışması."""
import asyncio, json, time, uuid
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import aiohttp
from omnistudio.market.data import MarketData
from omnistudio.strategy.indicators import atr, choppiness
from omnistudio.ai.council import AICouncil
from omnistudio.core.types import Signal
from .strategy import decide, closed_candles
from .ledger import Ledger

# Sabit, açıkça belgelenmiş kripto örneklemi; emtia/hisse tokenları evrene girmez.
CRYPTO_UNIVERSE = ('BTC_USDT','ETH_USDT','SOL_USDT','XRP_USDT','DOGE_USDT','BNB_USDT','ADA_USDT','AVAX_USDT','LINK_USDT','LTC_USDT','TRX_USDT','SUI_USDT','BCH_USDT','DOT_USDT','NEAR_USDT','UNI_USDT','AAVE_USDT','ATOM_USDT','ETC_USDT','FIL_USDT')

def ms(): return int(time.time()*1000)

def write(path, obj):
    with path.open('a',encoding='utf8') as f: f.write(json.dumps(obj,ensure_ascii=False,default=str)+'\n')

async def run(out: Path, duration=600, symbols=20, strategy='trend'):
    if duration<=0 or symbols<1: raise ValueError('Geçersiz süre/sembol sayısı')
    out.mkdir(parents=True,exist_ok=False)
    log=out/'events.jsonl'; counts=Counter(); ledger=Ledger(); council=AICouncil(); quotes={}; candles={}; lastbar={}; funding={}; start=time.monotonic()
    settings={'duration_sec':duration,'venue':'gateio','market':'USDT perpetual','interval':'5m','symbols':symbols,'strategy':strategy,'source':'acarbot-system (1).html','real_orders':0,'council_mode':council.mode,'fees_bps_per_side':5.5,'slippage_bps_per_side':2,'real_money_approved':False}
    (out/'config.json').write_text(json.dumps(settings,indent=2,ensure_ascii=False))
    status='FAILED'; error=''; active=0; max_gap=0; lastbeat=time.monotonic(); active_start=None
    timeout=aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
      market=MarketData(session,['gateio'],rest_rps=5)
      try:
        await market.probe_all()
        if 'gateio' not in market.reachable_venues: raise RuntimeError('Gate.io erişilemedi')
        available=set(await market.universe('gateio',2000))
        syms=[s for s in CRYPTO_UNIVERSE[:symbols] if s in available]
        if not syms: raise RuntimeError('Sembol evreni boş')
        sem=asyncio.Semaphore(5)
        async def get_c(s):
          async with sem:
            try:
              data=await market.candles('gateio',s,'5m',260)
              if data: candles[s]=data; counts['candle_fetch_ok']+=1
            except Exception as e: counts['candle_fetch_error']+=1; write(log,{'event':'CANDLE_ERROR','symbol':s,'error':str(e)[:200]})
        async def get_q(s):
          async with sem:
            q=await market.quote('gateio',s)
            if q:
              quotes[s]=q; counts['quotes']+=1
              p=ledger.on_quote(q,ms())
              if p: write(log,{'event':'CLOSE',**asdict(p)})
            else: counts['quote_error']+=1
        async def get_f(s):
          # funding() başarısızlığı sıfır diye gösterebilir; ham veriyi doğrula.
          async with sem:
            try:
              d=await market._get(f'https://api.gateio.ws/api/v4/futures/usdt/contracts/{s}','gateio',8)
              nxt=float(d['funding_next_apply']); rate=float(d['funding_rate'])
              if nxt<=0: raise ValueError('funding zamanı yok')
              funding[s]={'next_ms':int(nxt*1000),'rate':rate}
            except Exception as e: counts['funding_error']+=1; write(log,{'event':'FUNDING_ERROR','symbol':s,'error':str(e)[:200]})
        await asyncio.gather(*(get_c(s) for s in syms),*(get_f(s) for s in syms),*(get_q(s) for s in syms))
        ready=sum(len(closed_candles(c,ms()))>=250 for c in candles.values())
        if ready==0 or not quotes: raise RuntimeError(f'Yetersiz veri: {ready} hazır mum seti, {len(quotes)} quote')
        # İlk tarama ısınmadır; bot açıldığında eski mumdan geriye dönük işlem yok.
        for s,c in candles.items():
          cc=closed_candles(c,ms())
          if cc: lastbar[s]=cc[-1].open_ms
        active_start=time.monotonic(); deadline=active_start+duration; next_c=active_start; next_f=active_start+120
        write(log,{'event':'ACTIVE_START','time_ms':ms(),'symbols':syms,'ready':ready})
        lastbeat=active_start
        print(f'ACTIVE: {len(syms)} sembol, {ready} hazır, {duration} saniye',flush=True)
        while time.monotonic()<deadline:
          now=time.monotonic(); gap=now-lastbeat; max_gap=max(max_gap,gap); lastbeat=now
          # Gözlenen büyük duraklama süreklilik hatasıdır, başarı gibi sunulmaz.
          if gap>45: raise RuntimeError(f'Gözlem boşluğu {gap:.1f} sn')
          await asyncio.gather(*(get_q(s) for s in syms))
          # Açık pozisyon funding öncesinde taze quote ile kapatılır; funding tahmini yazılmaz.
          for s,p in list(ledger.positions.items()):
            q=quotes.get(s); f=funding.get(s)
            if f and q and ms()-q.ts_ms<15000 and ms()>=f['next_ms']-180000:
              trade=ledger.close(q,'FUNDING_AVOIDANCE',ms()); write(log,{'event':'CLOSE',**asdict(trade)})
          if time.monotonic()>=next_f:
            await asyncio.gather(*(get_f(s) for s in syms)); next_f=time.monotonic()+120
          if time.monotonic()>=next_c:
            await asyncio.gather(*(get_c(s) for s in syms)); next_c=time.monotonic()+15
            for s in syms:
              if time.monotonic() >= deadline: break
              cc=closed_candles(candles.get(s,[]),ms())
              if not cc or cc[-1].open_ms==lastbar.get(s): continue
              lastbar[s]=cc[-1].open_ms; counts['bars_evaluated']+=1
              result=decide(cc,ms(),strategy); counts['strategy_'+result.reason]+=1
              if not result.side: continue
              counts['signals']+=1; q=quotes.get(s); f=funding.get(s); a=atr(cc)
              reason=''
              if not q or ms()-q.ts_ms>15000: reason='STALE_QUOTE'
              elif not f or f['next_ms']-ms()<180000: reason='FUNDING_UNAVAILABLE_OR_NEAR'
              elif s in ledger.positions: reason='ALREADY_OPEN'
              elif q.spread_bps>8: reason='SPREAD_TOO_WIDE'
              elif abs(q.mid/cc[-1].close-1)*10000>25: reason='PRICE_MOVED_AWAY'
              elif not a or a<=0: reason='ATR_MISSING'
              if reason:
                counts['reject_'+reason]+=1; write(log,{'event':'REJECT','symbol':s,'reason':reason,'bar':result.bar_open_ms}); continue
              cost=11+4+q.spread_bps; move=(a/q.mid)*10000*.35
              if move < cost*1.15:
                counts['reject_EDGE_BELOW_COST']+=1; write(log,{'event':'REJECT','symbol':s,'reason':'EDGE_BELOW_COST','cost_bps':cost,'atr_proxy_bps':move}); continue
              ret=(cc[-1].close/cc[-2].close-1)*100
              sig=Signal('gateio',s,result.side,q.mid,ms(),ret,result.volume_ratio,cc[-1].quote_volume,300000,ctx_ret=ret,ctx_vratio3=result.volume_ratio,signal_id=uuid.uuid4().hex,tag='html_'+strategy)
              # Akış ve piyasa genişliği bilinmiyor; varsayılan sıfır nötr değer,
              # 15dk yön teyidi ölçülmedi; bunlar gözlemlenmiş veri değildir.
              metrics={'entry_side':result.side.value,'spread_bps':q.spread_bps,'roundtrip_cost_bps':cost,'expected_move_bps':move,'atr_pct':a/q.mid*100,'choppiness':choppiness(cc) or 50,'mtf_aligned':False,'funding_rate':f['rate'],'minutes_to_funding':(f['next_ms']-ms())/60000}
              verdict=await council.evaluate(sig,metrics,session)
              write(log,{'event':'COUNCIL','symbol':s,'signal':sig.to_dict(),'verdict':verdict.to_dict(),'unknown':['flow','breadth','15m_alignment']})
              if not verdict.approved: counts['reject_COUNCIL']+=1; continue
              # değerlendirme uzarsa tazeliği tekrar kontrol et.
              if time.monotonic()>=deadline: counts['reject_AFTER_DEADLINE']+=1; continue
              if ms()-q.ts_ms>15000: counts['reject_STALE_AFTER_COUNCIL']+=1; continue
              p=ledger.open(q,result.side,a,ms())
              if p: counts['opened']+=1; write(log,{'event':'OPEN',**asdict(p)})
              else: counts['reject_RISK']+=1
          await asyncio.sleep(min(1,max(0,deadline-time.monotonic())))
        active=time.monotonic()-active_start
        # Kullanılamayan quote varsa kapanış uydurulmaz.
        for s,p in list(ledger.positions.items()):
          await get_q(s); q=quotes.get(s)
          if s in ledger.positions and q and ms()-q.ts_ms<15000:
            p=ledger.close(q,'RUN_END',ms()); write(log,{'event':'CLOSE',**asdict(p)})
        fresh_coverage=sum(1 for s in syms if s in quotes and ms()-quotes[s].ts_ms<30000)
        status='COMPLETED' if active>=duration and not ledger.positions and fresh_coverage else 'INCOMPLETE'
        counts['fresh_quotes_at_end']=fresh_coverage
      except Exception as e:
        error=f'{type(e).__name__}: {e}'; write(log,{'event':'ERROR','error':error})
      finally:
        if active_start and not active: active=time.monotonic()-active_start
        result={'status':status,'error':error,'active_sec':round(active,3),'requested_active_sec':duration,'total_sec':round(time.monotonic()-start,3),'max_observed_cycle_gap_sec':round(max_gap,3),'settings':settings,'counts':dict(counts),'execution':ledger.summary(),'council':council.status(),'market':market.health_report(),'limitations':['PAPER, gerçek emir yok','Sadece Gate.io USDT perpetual; Binance/OKX/Bybit test edilmedi','Taker quote + varsayımsal slipaj, emir defteri derinliği ve gerçek dolum garantisi yok','Funding öncesi kapanış hedeflenir; funding muhasebesi yok, veri kaybında açık pozisyon belirsiz kalabilir','10 dakika kârlılık kanıtı değil','20 gerçek YZ tartışması anahtarsız yapılmadı','Sabit kripto örneklemi, 800 sembol taraması değil','HTML grafik, optimizasyon laboratuvarı ve gerçek likidasyon/marjin modeli taşınmadı'],'real_money_approved':False}
        (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'status':status,'active_sec':round(active,2),'counts':dict(counts),'closed':len(ledger.closed),'error':error},ensure_ascii=False),flush=True)
    return result
