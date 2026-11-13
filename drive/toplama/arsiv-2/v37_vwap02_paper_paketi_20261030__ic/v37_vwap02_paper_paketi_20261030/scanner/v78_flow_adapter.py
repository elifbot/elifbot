"""Opt-in paper-only v7.8 flow trigger adaptation, NOT the complete v7.8 strategy.

Uses actual v7.8 MoneyFlow, indicator_score, Strategy.combine; venue-specific
public trade/candle feeds. Book/OI/liq features aren't provided to MoneyFlow;
news neutral and ML absent. Downstream v37 ATR/VWAP + MTF/funding/OI/CVD,
confirmation, limit and risk filters remain active. Not calibrated for live.
"""
from __future__ import annotations
import asyncio
import math
import time
from collections import Counter
import aiohttp
import pandas as pd
from data.feed_utils import ensure_url_allowed
from config import PUBLIC_BINANCE_FAPI_BASE
from scanner.v78_indicators import indicator_score
from scanner.v78_moneyflow import MoneyFlow
from scanner.v78_strategy import Strategy
from scanner.ws_scanner import Sinyal
from scanner.ind_aktif import giris_karari

FIVE_MIN_MS=300_000

def closed_5m(exchange, rows, now_ms):
    """Only contiguous valid closed 5m candles, with freshness and no lookahead."""
    if not isinstance(rows, list): raise ValueError('candle_payload')
    parsed={}
    for r in rows:
        try:
            ts=int(r[0]); o,h,l,c=map(float,r[1:5]); volume=float(r[5])
            if exchange=='okx' and (len(r)<9 or str(r[8])!='1'): continue
            if ts%FIVE_MIN_MS or ts+FIVE_MIN_MS>now_ms-2000: continue
            if not all(math.isfinite(x) for x in (o,h,l,c,volume)) or min(o,h,l,c)<=0 or volume<0 or h<max(o,c,l) or l>min(o,c,h): continue
            item=(ts,o,h,l,c,volume)
            if ts in parsed and parsed[ts]!=item: raise ValueError('conflicting_candle')
            parsed[ts]=item
        except (TypeError, IndexError, OverflowError): continue
    ordered=sorted(parsed.values())
    if len(ordered)<200: raise ValueError('not_enough_5m_candles')
    ordered=ordered[-200:]
    if any(b[0]-a[0]!=FIVE_MIN_MS for a,b in zip(ordered,ordered[1:])): raise ValueError('5m_gap')
    if now_ms-(ordered[-1][0]+FIVE_MIN_MS)>FIVE_MIN_MS+20_000: raise ValueError('5m_stale')
    return pd.DataFrame(ordered, columns=['timestamp','open','high','low','close','volume'])

def legacy_flow_snapshot(events, now_ms):
    """v7.8 actual implementation; recent trade data only, no book/OI inputs."""
    m=MoneyFlow('paper',window_sec=300,compact_history=True)
    for ts,ab,sb,au,su in list(events)[-2000:]:
        if ts>now_ms or ts<now_ms-300_000: continue
        base=ab+sb; usd=au+su
        if base<=0 or usd<=0: continue
        m.add_trade(usd/base,base,is_buyer_maker=bool(sb),ts=ts/1000)
    return m.snapshot(include_vpvr=False)

class LegacyFlowAdapter:
    def __init__(self, bot):
        self.bot=bot
        self.stats=Counter()
        self.last_attempt={}
        self.cache={}
        self.strategy=Strategy(w_ind=.4,w_flow=.3,w_news=.15,w_ml=0, flow_trigger=True,flow_th=50,flow_ind_min=10,flow_min_total=15)
        self.last_error=None
        self.path=bot.profit_protection_csv.rsplit('/',1)[0]+'/v78_flow_adaylari.jsonl'
    def status(self):
        return {'active':True,'model':'v7.8 adaptation; no depth/liquidation, neutral news, no ML', 'counts':dict(self.stats),'last_error':self.last_error}
    def record(self,row):
        import json
        with open(self.path,'a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    async def candles(self,exchange,symbol,now):
        key=(exchange,symbol)
        if key in self.cache and now-self.cache[key][0]<120_000 and now//FIVE_MIN_MS==self.cache[key][0]//FIVE_MIN_MS:
            self.stats['candle_cache_hit']+=1; return self.cache[key][1]
        if exchange=='binance':
            base=getattr(self.bot._bnc,'BASE',PUBLIC_BINANCE_FAPI_BASE)
            url=base+'/klines'; params={'symbol':symbol,'interval':'5m','limit':'201'}
        else:
            url='https://www.okx.com/api/v5/market/history-candles';params={'instId':symbol,'bar':'5m','limit':'201'}
        ensure_url_allowed(url)
        async with self.bot._oturum.get(url,params=params,timeout=aiohttp.ClientTimeout(total=8)) as r:
            r.raise_for_status(); data=await r.json()
        if exchange=='okx':
            if data.get('code')!='0': raise ValueError('okx_candle_error')
            data=data.get('data')
        df=closed_5m(exchange,data,int(time.time()*1000))
        result=await asyncio.to_thread(indicator_score,df, None, True, 1.5)
        score=float(result['score'])
        if not math.isfinite(score): raise ValueError('invalid_technical_score')
        self.cache[key]=(int(time.time()*1000),result)
        self.stats['candle_fetch_ok']+=1
        return result
    async def cycle(self):
        bot=self.bot; now=int(time.time()*1000)
        if not bot.indikator_hazir or bot.yeni_giris_kapali or bot.akis is None: return
        shortlist=[]
        for key,flow in list(bot.akis._kayitlar.items()):
            ex,sym=key; d=bot.detektor.durumlar.get(key)
            if d is None or d.son_fiyat<=0 or now-d.son_fiyat_ts<0 or now-d.son_fiyat_ts>bot.detektor.tazelik_ms: continue
            if ex=='binance' and (bot._real_volume is None or sym not in bot._real_volume.connected or d.hiz_uzun<=0): continue
            f=flow.anlik(now,15)
            if not f.hazir or f.islem_adedi<3 or f.toplam_usd<1000 or f.son_islem_yas_ms is None or f.son_islem_yas_ms>5000: continue
            imbalance=abs(f.cvd_usd/f.toplam_usd)
            # Preselection only: not claimed to be v7.8's complete score.
            if imbalance<.5 or now-self.last_attempt.get(key,0)<30_000: continue
            valid=[e[0] for e in flow.olaylar if now-40_000<=e[0]<=now]
            if len(valid)<3 or now-valid[0]<35_000 or now-valid[-1]>5_000 or any(b-a>15_000 or b<a for a,b in zip(valid,valid[1:])): continue
            shortlist.append((imbalance,f.toplam_usd,key))
        self.stats['preselected']+=len(shortlist)
        for _,_,key in sorted(shortlist,reverse=True)[:4]:
            now=int(time.time()*1000);ex,sym=key
            self.last_attempt[key]=now
            try:
                flow=bot.akis._kayitlar[key]
                d=bot.detektor.durumlar[key]  # her adayın kendi bağlantı/ısınma durumu
                start=getattr(d, '_flow_start_ms', 0) if ex=='binance' else 0
                events=[e for e in flow.olaylar if e[0]>=start]
                snap=legacy_flow_snapshot(events,now)
                flow_score=float(snap['score'])
                if abs(flow_score)<50:
                    self.stats['legacy_flow_below_50']+=1;continue
                side='LONG' if flow_score>0 else 'SHORT'
                d=bot.detektor.durumlar[key]
                if now-d.son_fiyat_ts>bot.detektor.tazelik_ms: self.stats['price_stale']+=1;continue
                ok,reason,_=giris_karari(d,now,d.son_fiyat,side)
                if not ok: self.stats['indicator_'+reason]+=1;continue
                ind=await self.candles(ex,sym,now)
                now=int(time.time()*1000); d=bot.detektor.durumlar[key]
                if not bot.indikator_hazir or bot.yeni_giris_kapali or now-d.son_fiyat_ts>bot.detektor.tazelik_ms: self.stats['late_or_stale']+=1;continue
                # Re-read flow after I/O; no stale flow decision.
                start=getattr(d, '_flow_start_ms', 0) if ex=='binance' else 0
                snap=legacy_flow_snapshot([e for e in bot.akis._kayitlar[key].olaylar if e[0]>=start],now)
                if (side=='LONG' and snap['score']<50) or (side=='SHORT' and snap['score']>-50): self.stats['flow_changed']+=1;continue
                # v7.8 breakout ve flow kontrolleri snapshot alanlarını bekler.
                context={**ind.get('snapshot', {}), **ind,
                         'cvd_slope':snap.get('cvd_slope',0.0),
                         'cvd_divergence':snap.get('cvd_divergence','YOK'),
                         'absorption':snap.get('absorption','YOK'),
                         'oi_signal':snap.get('oi_signal','NOTR')}
                result=self.strategy.combine(float(ind['score']),float(snap['score']),0.0,None,market_context=context)
                if result.get('trigger') not in ('PARA_GIRISI','PARA_CIKISI') or result.get('signal')!=side:
                    self.stats['legacy_combined_reject']+=1;continue
                signal=Sinyal(ts_ms=now,exchange=ex,symbol=sym,yon=side,etiket='V78_AKIS_ADAY',fiyat=d.son_fiyat,ret_pct=d.ret_2s,rvol=d.rvol,hacim_usd=float(snap['buy_usdt'])+float(snap['sell_usdt']),gecen_ms=300_000)
                self.record({'ts_ms':now,'exchange':ex,'symbol':sym,'side':side,'flow_score':snap['score'],'technical_score':ind['score'],'combined':result['total'],'trigger':result['trigger'],'note':'adapted; no depth/liquidations, neutral news, no ML'})
                self.stats['dispatched']+=1
                await bot._sinyal_dispatch(signal)
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.stats['error']+=1;self.last_error=f'{ex}:{sym} {type(exc).__name__}: {str(exc)[:160]}'
    async def run(self):
        while not self.bot.durdu:
            try: await self.cycle()
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.stats['cycle_error']+=1;self.last_error=f'{type(exc).__name__}: {str(exc)[:160]}'
            await asyncio.sleep(5)
