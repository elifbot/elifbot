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
import threading
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
from scanner.signal_intel import FLOW_MAX_AGE_MS, FLOW_IMBALANCE_RATIO
from scanner.v78_audit import PaperAudit
from scanner.v78_metrics import PaperMetrics

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

def observation_last_closed_end(exchange, rows, now_ms):
    """Best latest individually valid closed row; observation only, not acceptance."""
    if not isinstance(rows,list):return None
    found=[]
    for r in rows:
        try:
            ts=int(r[0]);o,h,l,c=map(float,r[1:5]);volume=float(r[5])
            if exchange=='okx' and (len(r)<9 or str(r[8])!='1'):continue
            if ts%FIVE_MIN_MS or ts+FIVE_MIN_MS>now_ms-2000:continue
            if not all(math.isfinite(x) for x in (o,h,l,c,volume)) or min(o,h,l,c)<=0 or volume<0 or h<max(o,c,l) or l>min(o,c,h):continue
            found.append(ts+FIVE_MIN_MS)
        except (TypeError,ValueError,IndexError,OverflowError):continue
    return max(found) if found else None


class LegacyScoreCancelled(Exception):
    """Only the optional legacy source exceeded its cooperative deadline."""


def legacy_flow_snapshot(events, now_ms, cancel_check=None):
    """Rebuild from all accepted events in this connection's 300-second window.

    MoneyFlow keeps its original compact internal limits, including a separate
    200-entry whale deque. Do not pre-truncate to 2,000 input trades: that can
    discard an in-window whale still retained by the authentic implementation.
    This is trade-only: book/OI/liquidations and older-than-window history are
    not supplied, so it is not the complete live v7.8 application.
    """
    m=MoneyFlow('paper',window_sec=300,compact_history=True)
    for i,(ts,ab,sb,au,su) in enumerate(events):
        if i%1024==0 and cancel_check is not None and cancel_check():
            raise LegacyScoreCancelled('source deadline or stop')
        if ts>now_ms or ts<now_ms-300_000: continue
        base=ab+sb; usd=au+su
        if base<=0 or usd<=0: continue
        m.add_trade(usd/base,base,is_buyer_maker=bool(sb),ts=ts/1000)
    if cancel_check is not None and cancel_check():raise LegacyScoreCancelled('source deadline or stop')
    return m.snapshot(include_vpvr=False)

class LegacyFlowAdapter:
    def __init__(self, bot):
        self.bot=bot
        self.stats=Counter()
        self.last_attempt={}
        self.cache={}
        self.strategy=Strategy(w_ind=.4,w_flow=.3,w_news=.15,w_ml=0, flow_trigger=True,flow_th=50,flow_ind_min=10,flow_min_total=15)
        self.last_error=None
        self.watchdog_seconds=5.0
        self.watchdog_stopped=threading.Event()
        self.watchdog_fired=threading.Event()
        self.watchdog_stage=None
        self.current_stage='idle'
        self._cycle_deadline=None
        self._epochs={}
        self._ever_connected=set()
        self.okx_connected=set()
        self.okx_epochs={}
        self._okx_ever_connected=set()
        self._okx_last_ts={}
        # Directional paper mode examines up to four eligible symbols each
        # second, but HTTP starts remain paced at <=4 per five seconds.
        self.candle_lock=asyncio.Lock()
        self.candle_next_request=0.0
        self.directional_only=bool(getattr(bot, 'yonlu_akis', False))
        self.v4_aligned_preselection=bool(getattr(bot, 'v78_v4_akis_onsecim', False))
        if not math.isfinite(FLOW_IMBALANCE_RATIO) or FLOW_IMBALANCE_RATIO<1:
            raise ValueError('V4 akış oranı geçersiz')
        # A/B paper option only: align candidate preselection to the existing
        # V4 flow confirmation ratio, without touching that confirmation itself.
        self.min_abs_imbalance=((FLOW_IMBALANCE_RATIO-1)/(FLOW_IMBALANCE_RATIO+1)
                                if self.v4_aligned_preselection else .5)
        self.path=bot.profit_protection_csv.rsplit('/',1)[0]+'/v78_flow_adaylari.jsonl'
        self.metrics=PaperMetrics(bot,self.stats,self.watchdog_stopped)
        self.audit=PaperAudit(bot.profit_protection_csv.rsplit('/',1)[0]+'/v78_kaynak_olaylari.jsonl',self.stats,self.watchdog_stopped,active=self.metrics.active)
    def status(self):
        return {'active':not self.watchdog_stopped.is_set(), 'watchdog_stopped':self.watchdog_stopped.is_set(), 'watchdog_seconds':self.watchdog_seconds, 'watchdog_stage':self.watchdog_stage, 'stop_reason':('audit_failure' if self.audit.last_error else 'metrics_error' if self.metrics.metrics_errors else 'histogram_overflow' if self.stats['taker_age_histogram_overflow'] else 'deadline' if self.watchdog_fired.is_set() else None), 'audit_last_error':self.audit.last_error, 'model':'v7.8 adaptation; no book/OI/liquidation, neutral news, no ML', 'directional_only':self.directional_only, 'candidate_preselection_mode':('v4_flow_ratio_aligned' if self.v4_aligned_preselection else 'original_0_5'), 'candidate_preselection_min_abs_imbalance':self.min_abs_imbalance, 'candidate_cycle_sleep_sec':1 if self.directional_only else 5, 'max_per_cycle':4, 'candle_request_spacing_sec':1.25 if self.directional_only else None, 'counts':dict(self.stats),'metrics':self.metrics.status(),'audit_timing':self.audit.timing_status(),'last_error':self.last_error}
    def connection_change(self, symbol, up, gap=False):
        """New-source epoch and shared book reset on Binance transport/ID gaps.

        Exchange timestamps are compared against a local wall-clock cutoff.
        No claim is made that exchange and local clocks are perfectly aligned.
        """
        key=('binance',symbol)
        self._epochs[symbol]=self._epochs.get(symbol,0)+1
        d=self.bot.detektor.durum(*key)
        d._flow_start_ms=int(time.time()*1000) if up else 0
        flow=self.bot.akis._kayitlar.get(key) if self.bot.akis is not None else None
        if flow is not None:
            self.stats['book_events_cleared']+=len(flow.olaylar)
            flow.olaylar.clear()
            flow.son_ts=0
        if gap:
            self.stats['binance_gap_reset_symbols']+=1
        elif up:
            if symbol in self._ever_connected:
                self.stats['binance_reconnect_symbols']+=1
            else:
                self.stats['binance_initial_connect_symbols']+=1
                self._ever_connected.add(symbol)
        else:
            self.stats['binance_disconnect_symbols']+=1

    def okx_connection_change(self,symbol,up):
        key=('okx',symbol)
        was_up=symbol in self.okx_connected
        if was_up==up: return
        self.okx_epochs[symbol]=self.okx_epochs.get(symbol,0)+1
        if up: self.okx_connected.add(symbol)
        else: self.okx_connected.discard(symbol)
        d=self.bot.detektor.durum(*key)
        d._flow_start_ms=int(time.time()*1000) if up else 0
        self._okx_last_ts.pop(symbol,None)
        flow=self.bot.akis._kayitlar.get(key) if self.bot.akis is not None else None
        if flow is not None:
            self.stats['okx_book_events_cleared']+=len(flow.olaylar)
            flow.olaylar.clear(); flow.son_ts=0
        if up and symbol in self._okx_ever_connected: self.stats['okx_reconnect_symbols']+=1
        elif up:
            self._okx_ever_connected.add(symbol);self.stats['okx_initial_connect_symbols']+=1
        else:self.stats['okx_disconnect_symbols']+=1

    def accept_okx_trade(self,symbol,ts,price,contract,side,multiplier):
        now=int(time.time()*1000)
        try:
            ts=int(ts);price=float(price);contract=float(contract);multiplier=float(multiplier)
            if (side not in ('buy','sell') or not all(math.isfinite(v) and v>0 for v in (price,contract,multiplier,price*contract*multiplier))):
                raise ValueError('invalid trade')
        except (TypeError,ValueError,OverflowError):
            self.stats['okx_invalid_trade']+=1;return False
        d=self.bot.detektor.durumlar.get(('okx',symbol))
        start=getattr(d,'_flow_start_ms',0) if d else 0
        if symbol not in self.okx_connected or not start or ts<start:
            self.stats['okx_not_connected_or_before_generation']+=1;return False
        if ts>now or now-ts>FLOW_MAX_AGE_MS or ts<self._okx_last_ts.get(symbol,0):
            self.stats['okx_stale_future_or_out_of_order']+=1;return False
        self._okx_last_ts[symbol]=ts
        return True

    def accepted_in_generation(self, symbol, ts):
        d=self.bot.detektor.durumlar.get(('binance',symbol))
        start=getattr(d,'_flow_start_ms',0) if d is not None else 0
        try: ts=int(ts)
        except (TypeError,ValueError,OverflowError): return False
        if not start or ts < start:
            self.stats['before_generation_rejected']+=1
            return False
        return True

    def _expired(self):
        return (self.watchdog_stopped.is_set() or
                (self._cycle_deadline is not None and time.monotonic() >= self._cycle_deadline))

    @staticmethod
    def _continuous(flow, now):
        # Existing legacy-source thresholds, not claimed to be V4's general gate.
        valid=[e[0] for e in flow.olaylar if now-40_000<=e[0]<=now]
        return (len(valid)>=3 and now-valid[0]>=35_000 and now-valid[-1]<=FLOW_MAX_AGE_MS
                and not any(b-a>15_000 or b<a for a,b in zip(valid,valid[1:])))

    def _v4_volume_ready(self,d,now):
        # Reuse V4's per-exchange volume freshness and computed warm-up state.
        volume_age=max(self.bot.detektor.tazelik_ms,15_000) if d.exchange=='binance' else self.bot.detektor.tazelik_ms
        return bool(d.hiz_uzun and d.son_hacim_ts and now-d.son_hacim_ts<=volume_age)

    def record(self,row):
        import json
        with open(self.path,'a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    async def candles(self,exchange,symbol,now):
        key=(exchange,symbol)
        if key in self.cache and now-self.cache[key][0]<120_000 and now//FIVE_MIN_MS==self.cache[key][0]//FIVE_MIN_MS:
            cached=self.cache[key][1]
            closed_end=cached.get('_closed_5m_end_ms')
            if isinstance(closed_end,int) and 2_000<=now-closed_end<=FIVE_MIN_MS+20_000:
                self.metrics.on_candle('cache_served',exchange,symbol,closed_end)
                self.stats['candle_cache_hit']+=1; return cached
        if exchange=='binance':
            base=getattr(self.bot._bnc,'BASE',PUBLIC_BINANCE_FAPI_BASE)
            url=base+'/klines'; params={'symbol':symbol,'interval':'5m','limit':'201'}
        else:
            url='https://www.okx.com/api/v5/market/history-candles';params={'instId':symbol,'bar':'5m','limit':'201'}
        ensure_url_allowed(url)
        if self.directional_only:
            async with self.candle_lock:
                delay=max(0.0,self.candle_next_request-time.monotonic())
                if delay:
                    self.stats['candle_rate_waits']+=1
                    await asyncio.sleep(delay)
                self.candle_next_request=time.monotonic()+1.25
        self.stats['candle_request_starts']+=1
        try:
            async with self.bot._oturum.get(url,params=params,timeout=aiohttp.ClientTimeout(total=8)) as r:
                r.raise_for_status(); data=await r.json()
        except asyncio.CancelledError:
            self.metrics.on_candle('fetch_cancelled',exchange,symbol,None,'cancelled')
            raise
        except Exception as exc:
            self.metrics.on_candle('fetch_failed',exchange,symbol,None,type(exc).__name__)
            raise
        if exchange=='okx':
            if not isinstance(data,dict) or data.get('code')!='0':
                self.metrics.on_candle('response_rejected',exchange,symbol,None,'okx_candle_error')
                raise ValueError('okx_candle_error')
            data=data.get('data')
        received_ms=int(time.time()*1000)
        try: observed_end=observation_last_closed_end(exchange,data,received_ms)
        except Exception:
            observed_end=None
            self.metrics.metrics_errors+=1
            self.stats['observation_errors']+=1
            self.watchdog_stopped.set()
        self.metrics.on_candle('response_received',exchange,symbol,observed_end)
        try:
            df=closed_5m(exchange,data,received_ms)
        except Exception as exc:
            self.metrics.on_candle('closed_rejected',exchange,symbol,observed_end,type(exc).__name__+':'+str(exc))
            raise
        self.metrics.on_candle('closed_accepted',exchange,symbol,int(df.iloc[-1]['timestamp'])+FIVE_MIN_MS)
        result=await asyncio.to_thread(indicator_score,df, None, True, 1.5)
        score=float(result['score'])
        if not math.isfinite(score): raise ValueError('invalid_technical_score')
        result=dict(result)
        result['_closed_5m_end_ms']=int(df.iloc[-1]['timestamp'])+FIVE_MIN_MS
        self.cache[key]=(int(time.time()*1000),result)
        self.stats['candle_fetch_ok']+=1
        return result
    async def cycle(self):
        bot=self.bot; now=int(time.time()*1000)
        if self._expired(): return
        if not bot.indikator_hazir or bot.yeni_giris_kapali or bot.akis is None: return
        self.current_stage='shortlist'
        shortlist=[]
        for key,flow in list(bot.akis._kayitlar.items()):
            ex,sym=key; d=bot.detektor.durumlar.get(key)
            if d is None or d.son_fiyat<=0 or now-d.son_fiyat_ts<0 or now-d.son_fiyat_ts>bot.detektor.tazelik_ms: continue
            if not self._v4_volume_ready(d,now):
                self.stats['v4_volume_not_ready']+=1;continue
            if ex=='binance' and (bot._real_volume is None or sym not in bot._real_volume.connected or d.hiz_uzun<=0 or not getattr(d,'_flow_start_ms',0)): continue
            if ex=='okx' and (sym not in self.okx_connected or not getattr(d,'_flow_start_ms',0)): continue
            if self.directional_only and flow.son_ts > now:
                self.stats['future_flow_reject']+=1;continue
            f=flow.anlik(now,15)
            if not f.hazir or f.islem_adedi<3 or f.toplam_usd<1000 or f.son_islem_yas_ms is None or f.son_islem_yas_ms>FLOW_MAX_AGE_MS: continue
            imbalance=abs(f.cvd_usd/f.toplam_usd)
            # Preselection only: not claimed to be v7.8's complete score.
            if imbalance<self.min_abs_imbalance or now-self.last_attempt.get(key,0)<30_000: continue
            if not self._continuous(flow,now): continue
            if self.v4_aligned_preselection and imbalance<.5:
                self.stats['expanded_only_preselection_observations']+=1  # repeated observations, not unique events
            shortlist.append((imbalance,f.toplam_usd,key))
        self.stats['preselected']+=len(shortlist)
        if self.directional_only:
            # Least-recently-attempted first prevents the same high-imbalance
            # symbols from repeatedly starving the rest. Still rate-limited;
            # deferred events can expire and are explicitly counted.
            ordered=sorted(shortlist, key=lambda x:(self.last_attempt.get(x[2],0),-x[0],-x[1],x[2]))
            self.stats['deferred_evaluations']+=max(0,len(ordered)-4)
        else:
            ordered=sorted(shortlist,reverse=True)
        for selected_imbalance,_,key in ordered[:4]:
            expanded_only=self.v4_aligned_preselection and selected_imbalance<.5
            if expanded_only:self.stats['expanded_only_flow_evaluated']+=1
            now=int(time.time()*1000);ex,sym=key
            self.last_attempt[key]=now
            self.stats['flow_evaluated']+=1
            try:
                flow=bot.akis._kayitlar[key]
                d=bot.detektor.durumlar[key]  # her adayın kendi bağlantı/ısınma durumu
                start=getattr(d, '_flow_start_ms', 0)
                events=[e for e in flow.olaylar if e[0]>=start]
                self.current_stage='legacy_flow_score'
                score_started=time.monotonic_ns()
                try: snap=legacy_flow_snapshot(events,now,self._expired)
                finally:
                    score_elapsed=time.monotonic_ns()-score_started
                    self.stats['score_calls']+=1
                    self.stats['score_total_ns']+=score_elapsed
                    self.stats['score_max_ns']=max(self.stats['score_max_ns'],score_elapsed)
                if self._expired(): self.stats['deadline_reject']+=1; return
                now=int(time.time()*1000)
                self.metrics.on_score(ex,sym,snap,flow,events)
                flow_score=float(snap['score'])
                if not math.isfinite(flow_score):
                    self.stats['invalid_flow_score']+=1;continue
                if abs(flow_score)<50:
                    self.stats['legacy_flow_below_50']+=1;continue
                if expanded_only:self.stats['expanded_only_score_ge_50']+=1
                side='LONG' if flow_score>0 else 'SHORT'
                if self.directional_only:
                    if flow.son_ts > now:
                        self.stats['future_flow_reject']+=1;continue
                    recent=flow.anlik(now,15)
                    if (not recent.hazir or recent.son_islem_yas_ms is None or recent.son_islem_yas_ms>FLOW_MAX_AGE_MS
                            or (recent.cvd_usd if side=='LONG' else -recent.cvd_usd)<=0):
                        self.stats['short_flow_direction_mismatch']+=1;continue
                d=bot.detektor.durumlar[key]
                if now-d.son_fiyat_ts>bot.detektor.tazelik_ms: self.stats['price_stale']+=1;continue
                self.current_stage='indicator_gate'
                ok,reason,_=giris_karari(d,now,d.son_fiyat,side)
                if not ok: self.stats['indicator_'+reason]+=1;continue
                generation=(self._epochs if ex=='binance' else self.okx_epochs).get(sym,0)
                self.current_stage='candles'
                candle_begin=time.monotonic_ns()
                try: ind=await self.candles(ex,sym,now)
                finally:
                    candle_elapsed=time.monotonic_ns()-candle_begin
                    self.stats['candle_stage_total_ns']+=candle_elapsed
                    self.stats['candle_stage_max_ns']=max(self.stats['candle_stage_max_ns'],candle_elapsed)
                now=int(time.time()*1000); d=bot.detektor.durumlar[key]
                if self._expired():
                    self.stats['deadline_reject']+=1; return
                closed_end=ind.get('_closed_5m_end_ms')
                if not isinstance(closed_end,int) or not (2_000<=now-closed_end<=FIVE_MIN_MS+20_000):
                    self.metrics.on_candle('post_await_rejected',ex,sym,closed_end,'not_closed_or_stale')
                    self.stats['closed_candle_stale_after_await']+=1;continue
                self.metrics.on_candle('post_await_accepted',ex,sym,closed_end)
                if not bot.indikator_hazir or bot.yeni_giris_kapali or not (0<=now-d.son_fiyat_ts<=bot.detektor.tazelik_ms): self.stats['late_or_stale']+=1;continue
                if not self._v4_volume_ready(d,now):
                    self.stats['v4_volume_changed']+=1;continue
                if ex=='binance' and (bot._real_volume is None or sym not in bot._real_volume.connected
                        or d.hiz_uzun<=0 or not getattr(d,'_flow_start_ms',0)
                        or generation!=self._epochs.get(sym,0)):
                    self.stats['connection_or_warmup_changed']+=1;continue
                if ex=='okx' and (sym not in self.okx_connected or not getattr(d,'_flow_start_ms',0)
                        or generation!=self.okx_epochs.get(sym,0)):
                    self.stats['okx_connection_changed']+=1;continue
                if not self._continuous(bot.akis._kayitlar[key],now):
                    self.stats['continuity_changed']+=1;continue
                # Re-read flow after I/O; no stale flow decision.
                start=getattr(d, '_flow_start_ms', 0)
                score_started=time.monotonic_ns()
                try: snap=legacy_flow_snapshot([e for e in bot.akis._kayitlar[key].olaylar if e[0]>=start],now,self._expired)
                finally:
                    score_elapsed=time.monotonic_ns()-score_started
                    self.stats['score_calls']+=1
                    self.stats['score_total_ns']+=score_elapsed
                    self.stats['score_max_ns']=max(self.stats['score_max_ns'],score_elapsed)
                if self._expired(): self.stats['deadline_reject']+=1; return
                now=int(time.time()*1000)
                # A full-window rebuild can take time; refresh time-based gates
                # after scoring so that CPU work cannot dispatch stale data.
                if (not bot.indikator_hazir or bot.yeni_giris_kapali
                        or not (0<=now-d.son_fiyat_ts<=bot.detektor.tazelik_ms)
                        or not (2_000<=now-closed_end<=FIVE_MIN_MS+20_000)
                        or not self._v4_volume_ready(d,now)):
                    self.stats['post_score_stale_reject']+=1;continue
                if not self._continuous(bot.akis._kayitlar[key],now):
                    self.stats['post_score_continuity_reject']+=1;continue
                if not math.isfinite(float(snap['score'])) or (side=='LONG' and snap['score']<50) or (side=='SHORT' and snap['score']>-50): self.stats['flow_changed']+=1;continue
                if self.directional_only:
                    if flow.son_ts > now:
                        self.stats['future_flow_reject']+=1;continue
                    recent=flow.anlik(now,15)
                    if (not recent.hazir or recent.son_islem_yas_ms is None or recent.son_islem_yas_ms>FLOW_MAX_AGE_MS
                            or recent.islem_adedi<3 or recent.toplam_usd<1000
                            or abs(recent.cvd_usd/recent.toplam_usd)<self.min_abs_imbalance
                            or (recent.cvd_usd if side=='LONG' else -recent.cvd_usd)<=0):
                        self.stats['short_flow_changed']+=1;continue
                # v7.8 breakout ve flow kontrolleri snapshot alanlarını bekler.
                context={**ind.get('snapshot', {}), **ind,
                         'cvd_slope':snap.get('cvd_slope',0.0),
                         'cvd_divergence':snap.get('cvd_divergence','YOK'),
                         'absorption':snap.get('absorption','YOK'),
                         'oi_signal':snap.get('oi_signal','NOTR')}
                self.current_stage='strategy_combine'
                result=self.strategy.combine(float(ind['score']),float(snap['score']),0.0,None,market_context=context)
                if self.directional_only:
                    # combine() does not set a flow trigger when the same side
                    # already cleared its stronger raw score threshold. Such
                    # a result is valid only if flow and all directional minima
                    # also pass, and the strategy has not vetoed the entry.
                    direction=1 if side=='LONG' else -1
                    raw_ok=(result.get('raw_signal')==side and result.get('trigger') is None
                            and float(ind['score'])*direction>=10
                            and float(result['total'])*direction>=15)
                    trigger_ok=(result.get('trigger') == ('PARA_GIRISI' if side=='LONG' else 'PARA_CIKISI'))
                    acceptable=(result.get('signal')==side and (trigger_ok or raw_ok))
                else:
                    acceptable=(result.get('trigger') in ('PARA_GIRISI','PARA_CIKISI') and result.get('signal')==side)
                if not acceptable:
                    self.metrics.on_candle('combination_rejected',ex,sym,closed_end,'legacy_combined_reject')
                    self.stats['legacy_combined_reject']+=1;continue
                if self.directional_only and len(getattr(bot, '_akis_gorevler', ()))>=128:
                    self.stats['dispatch_task_limit']+=1;continue
                if self._expired():
                    self.stats['deadline_reject']+=1; return
                self.current_stage='candidate_record'
                self.record({'ts_ms':now,'exchange':ex,'symbol':sym,'side':side,'flow_score':snap['score'],'technical_score':ind['score'],'combined':result['total'],'trigger':result['trigger'], 'raw_signal':result.get('raw_signal'), 'recent_cvd_usd': flow.anlik(now,15).cvd_usd, 'taker_event_ts_ms':flow.son_ts, 'taker_age_ms':now-flow.son_ts if flow.son_ts else None, 'price_ts_ms':d.son_fiyat_ts, 'price_age_ms':now-d.son_fiyat_ts, 'closed_candle_end_ms':closed_end, 'closed_candle_age_ms':now-closed_end, 'local_observation_ms':now, 'connection_generation':generation, 'candidate_preselection_mode':('v4_flow_ratio_aligned' if self.v4_aligned_preselection else 'original_0_5'), 'selected_imbalance':selected_imbalance, 'expanded_only_preselection':expanded_only, 'note':'adapted; no book/OI/liquidations, neutral news, no ML'})
                if self._expired():
                    self.stats['deadline_reject']+=1; return
                # Synchronous candidate recording can itself stall. Check time
                # again after it, before sending anything to V4.
                now=int(time.time()*1000)
                if (not bot.indikator_hazir or bot.yeni_giris_kapali
                        or not (0<=now-d.son_fiyat_ts<=bot.detektor.tazelik_ms)
                        or not (2_000<=now-closed_end<=FIVE_MIN_MS+20_000)
                        or not self._v4_volume_ready(d,now)
                        or not (0<=now-flow.son_ts<=FLOW_MAX_AGE_MS)):
                    self.stats['post_record_stale_reject']+=1;continue
                signal=Sinyal(ts_ms=now,exchange=ex,symbol=sym,yon=side,etiket='V78_AKIS_ADAY',fiyat=d.son_fiyat,ret_pct=d.ret_2s,rvol=d.rvol,hacim_usd=float(snap['buy_usdt'])+float(snap['sell_usdt']),gecen_ms=300_000)
                self.current_stage='candidate_dispatch'
                self.stats['dispatched']+=1
                if expanded_only:self.stats['expanded_only_dispatched']+=1
                await bot._sinyal_dispatch(signal)
            except asyncio.CancelledError: raise
            except LegacyScoreCancelled:
                self.stats['score_cancelled']+=1;return
            except Exception as exc:
                self.stats['error']+=1;self.last_error=f'{ex}:{sym} {type(exc).__name__}: {str(exc)[:160]}'
    async def run(self):
        """Stop only this source on 5s deadline; never cancel V4 tasks.

        Thread timer can notice a blocked event loop when Python threads can run.
        It cannot defeat a process suspension, interpreter/GIL freeze or VM pause.
        """
        while not self.bot.durdu and not self.watchdog_stopped.is_set():
            loop=asyncio.get_running_loop()
            start=time.monotonic()
            self._cycle_deadline=start+self.watchdog_seconds
            task=asyncio.create_task(self.cycle(),name='v78-cycle')
            def on_deadline():
                self.watchdog_stage=self.current_stage
                self.watchdog_fired.set()
                self.watchdog_stopped.set()
                try: loop.call_soon_threadsafe(task.cancel)
                except RuntimeError: pass
            timer=threading.Timer(self.watchdog_seconds,on_deadline)
            timer.daemon=True
            timer.start()
            try:
                await task
            except asyncio.CancelledError:
                if not self.watchdog_stopped.is_set(): raise
            except Exception as exc:
                self.stats['cycle_error']+=1;self.last_error=f'{type(exc).__name__}: {str(exc)[:160]}'
            finally:
                timer.cancel()
                elapsed=time.monotonic()-start
                self._cycle_deadline=None
                self.stats['cycle_count']+=1
                self.stats['cycle_total_ms']+=round(elapsed*1000)
                self.stats['cycle_max_ms']=max(self.stats['cycle_max_ms'],round(elapsed*1000))
                if elapsed>=self.watchdog_seconds or self.watchdog_fired.is_set():
                    self.watchdog_stopped.set();self.watchdog_fired.set()
                    if self.watchdog_stage is None:self.watchdog_stage=self.current_stage
                    self.stats['watchdog_stops']+=1
                    self.last_error=f'v78 cycle deadline exceeded: {elapsed:.3f}s; stage={self.watchdog_stage}'
                elif self.audit.last_error:
                    self.stats['audit_stops']+=1
                    self.last_error='audit failure: '+self.audit.last_error
            if self.watchdog_stopped.is_set(): break
            await asyncio.sleep(1 if self.directional_only else 5)
        # V4 treats any completed background task as a fatal bot failure.
        # Keep this task alive but inert after watchdog/audit stop, until V4
        # cancels it during normal bot shutdown. No new cycles are started.
        while not self.bot.durdu and self.watchdog_stopped.is_set():
            await asyncio.sleep(1)
