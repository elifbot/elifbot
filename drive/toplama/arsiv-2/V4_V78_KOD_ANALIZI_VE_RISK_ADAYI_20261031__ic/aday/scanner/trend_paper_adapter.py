"""Experimental opt-in corrected Supertrend source; paper-only via V4 gates.

No authenticated API or order endpoint. Fresh closed 1m candles, distinct
venue keys, generation and volume re-check after I/O. The five-second
watchdog stops this source, not V4 or the separate v7.8 source.
"""
from __future__ import annotations
import asyncio, json, math, threading, time
from collections import Counter
import aiohttp
import pandas as pd
from data.feed_utils import ensure_url_allowed
from scanner.ws_scanner import Sinyal
from scanner.ind_aktif import giris_karari
from strategies.trend_follower import TrendFollowerStrategy
from config import PUBLIC_BINANCE_FAPI_BASE

# Conservative, explicit cryptocurrency allow-list. Exchange discovery must
# also confirm an active USDT perpetual/swap; no synthetic-stock/index product.
CRYPTO_BASES=frozenset({'BTC','ETH','SOL','XRP','ADA','DOGE','BNB','AVAX','LINK','LTC',
 'DOT','NEAR','UNI','AAVE','TRX','SUI','ATOM','APT','ARB','OP','INJ','SAND','ETC','ALGO','BCH'})

def filtered_universe(binance_symbols,okx_symbols):
    bn={s for s in binance_symbols if s.endswith('USDT') and s[:-4] in CRYPTO_BASES}
    ok={s for s in okx_symbols if s.endswith('-USDT-SWAP') and s[:-10] in CRYPTO_BASES}
    return bn,ok

def closed_1m(exchange, rows, now):
    if exchange not in ('binance','okx') or not isinstance(rows,list):raise ValueError('payload')
    selected={};cutoff=now-2000
    for r in rows:
        try:
            ts=int(r[0]);o,h,l,c,v=map(float,r[1:6])
            if exchange=='okx' and (len(r)<9 or str(r[8])!='1'):continue
            if exchange=='binance' and int(r[6])>=cutoff:continue
            if ts%60000 or ts+60000>cutoff or ts<0:continue
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0:continue
            if h<max(o,l,c) or l>min(o,h,c):continue
            row=(ts,o,h,l,c,v)
            if ts in selected and selected[ts]!=row:raise ValueError('conflicting candle')
            selected[ts]=row
        except (IndexError,TypeError,OverflowError):continue
    ordered=sorted(selected.values()); suffix=[]
    for item in reversed(ordered):
        if suffix and suffix[-1][0]-item[0]!=60000:break
        suffix.append(item)
    suffix.reverse()
    if len(suffix)<210:raise ValueError('insufficient contiguous candles')
    if not (2000<=now-(suffix[-1][0]+60000)<=122000):raise ValueError('stale last closed candle')
    return pd.DataFrame(suffix,columns=['open_time','open','high','low','close','volume'])

class TrendPaperAdapter:
    def __init__(self,bot):
        self.bot=bot;self.stop=threading.Event();self.fired=threading.Event()
        self.stats=Counter();self.last_error=None;self.last_bar={};self.pointer=0
        self.watchdog_stage=None;self.path=bot.profit_protection_csv.rsplit('/',1)[0]+'/supertrend_paper_adaylari.jsonl'
    def status(self):
        return {'active':not self.stop.is_set(),'watchdog_stopped':self.stop.is_set(),
          'watchdog_seconds':5,'watchdog_stage':self.watchdog_stage,
          'stop_reason':('watchdog' if self.fired.is_set() else 'audit_failure_or_external_stop' if self.stop.is_set() else None), 'counts':dict(self.stats),
          'last_error':self.last_error,'strategy':'corrected TrendFollower 1m; paper-only',
          'allowlist_crypto_bases':sorted(CRYPTO_BASES)}
    def ready(self,ex,sym,now):
        b=self.bot; m=b.eski_v78_motor
        if b.asama!='tarama' or not b.indikator_hazir or b.yeni_giris_kapali or m is None or b.akis is None:return False
        d=b.detektor.durumlar.get((ex,sym));flow=b.akis._kayitlar.get((ex,sym))
        if d is None or flow is None or d.son_fiyat<=0 or not (0<=now-d.son_fiyat_ts<=b.detektor.tazelik_ms):return False
        if not m._v4_volume_ready(d,now) or not m._continuous(flow,now):return False
        if ex=='binance':return bool(b._real_volume and sym in b._real_volume.connected and d._flow_start_ms)
        return bool(ex=='okx' and sym in m.okx_connected and d._flow_start_ms)
    async def evaluate_one(self,ex,sym):
        b=self.bot;m=b.eski_v78_motor;now=int(time.time()*1000)
        if not self.ready(ex,sym,now):self.stats['not_ready']+=1;return
        generation=(m._epochs if ex=='binance' else m.okx_epochs).get(sym,0)
        if ex=='binance':
            url=getattr(b._bnc,'BASE',PUBLIC_BINANCE_FAPI_BASE)+'/klines';params={'symbol':sym,'interval':'1m','limit':300}
        else:
            url='https://www.okx.com/api/v5/market/candles';params={'instId':sym,'bar':'1m','limit':300}
        ensure_url_allowed(url);self.watchdog_stage='candles'
        async with b._oturum.get(url,params=params,timeout=aiohttp.ClientTimeout(total=3.5)) as r:
            r.raise_for_status(); payload=await r.json()
        now=int(time.time()*1000)
        rows=payload if ex=='binance' else payload.get('data',[])
        frame=closed_1m(ex,rows,now);bar=int(frame.iloc[-1]['open_time']);key=(ex,sym)
        if self.last_bar.get(key)==bar:self.stats['same_closed_bar']+=1;return
        self.watchdog_stage='strategy_evaluation'
        result=await asyncio.to_thread(TrendFollowerStrategy().evaluate,frame)
        now=int(time.time()*1000)
        if self.stop.is_set() or not self.ready(ex,sym,now):self.stats['post_await_not_ready']+=1;return
        if generation!=(m._epochs if ex=='binance' else m.okx_epochs).get(sym,0):self.stats['generation_changed']+=1;return
        if not 2000<=now-(bar+60000)<=122000:self.stats['post_await_candle_stale']+=1;return
        self.last_bar[key]=bar;self.stats['evaluated']+=1;self.stats['result_'+result.signal]+=1
        data={'ts_ms':now,'exchange':ex,'symbol':sym,'side':result.signal,'bar_open_ms':bar,
              'bar_end_ms':bar+60000,'bar_age_ms':now-(bar+60000),'candles':len(frame),
              'status':'corrected_supertrend','regime':result.regime,'contributors':result.contributor_log}
        if result.signal not in ('LONG','SHORT'):
            self.record(data);return
        d=b.detektor.durumlar[(ex,sym)]
        allowed,reason,_=giris_karari(d,now,d.son_fiyat,result.signal)
        if not allowed:
            self.stats['indicator_'+str(reason)]+=1;data['stage']='indicator_reject';data['reason']=reason;self.record(data);return
        if len(b._akis_gorevler)>=128:self.stats['dispatch_task_limit']+=1;return
        if self.stop.is_set() or not self.ready(ex,sym,int(time.time()*1000)):self.stats['pre_dispatch_not_ready']+=1;return
        data['stage']='candidate_dispatch';self.record(data)
        now=int(time.time()*1000)
        if self.stop.is_set() or not self.ready(ex,sym,now):self.stats['post_record_not_ready']+=1;return
        if generation!=(m._epochs if ex=='binance' else m.okx_epochs).get(sym,0):self.stats['generation_changed']+=1;return
        flow=b.akis.anlik(ex,sym,now,15)
        signal=Sinyal(ts_ms=now,exchange=ex,symbol=sym,yon=result.signal,etiket='SUPERTREND_PAPER_ADAY',
          fiyat=d.son_fiyat,ret_pct=d.ret_2s,rvol=d.rvol,hacim_usd=flow.toplam_usd,gecen_ms=60000)
        self.stats['dispatched']+=1;await b._sinyal_dispatch(signal)
    def record(self,data):
        try:
            with open(self.path,'a',encoding='utf-8') as f:f.write(json.dumps(data,ensure_ascii=False,allow_nan=False)+'\n')
        except Exception:
            self.stop.set()  # fail closed for this source if audit cannot persist
            raise
    async def run(self):
        # Source failure disables only this source; V4 lifecycle remains active.
        while not self.bot.durdu:
            if self.stop.is_set():await asyncio.sleep(1);continue
            pairs=sorted((ex,sym) for ex,items in self.bot.indikator_evrenleri.items() for sym in items)
            if not self.bot.indikator_hazir or not pairs:await asyncio.sleep(1);continue
            ex,sym=pairs[self.pointer%len(pairs)];self.pointer+=1
            loop=asyncio.get_running_loop();task=asyncio.create_task(self.evaluate_one(ex,sym))
            def expired():
                self.fired.set();self.stop.set()
                try:loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:pass
            timer=threading.Timer(5,expired);timer.daemon=True;timer.start()
            try:await task
            except asyncio.CancelledError:
                if not self.fired.is_set():raise
                self.stats['watchdog_stops']+=1
            except Exception as exc:
                self.stats['errors']+=1;self.last_error=f'{ex}:{sym} {type(exc).__name__}: {str(exc)[:140]}'
            finally:timer.cancel();await asyncio.gather(task,return_exceptions=True)
            await asyncio.sleep(1)
