"""Opt-in bounded aggregate telemetry; observation only, never changes thresholds.

All ages use local book-insertion/evaluation time minus exchange event time. Histograms are
integer milliseconds with documented bounded ranges; quantiles use nearest-rank.
No market event time is treated as a local monotonic duration.
"""
from collections import Counter
from contextlib import contextmanager
import math,time

class AgeHistogram:
    def __init__(self,lo=-5000,hi=20000):
        self.lo=lo;self.hi=hi;self.bins=Counter();self.count=0;self.overflow=0;self.minimum=None;self.maximum=None
    def add(self,value):
        value=int(value);self.count+=1
        self.minimum=value if self.minimum is None else min(value,self.minimum)
        self.maximum=value if self.maximum is None else max(value,self.maximum)
        if self.lo<=value<=self.hi:self.bins[value]+=1
        else:self.overflow+=1
    def quantile(self,q):
        if not self.count or self.overflow:return None
        rank=max(1,math.ceil(self.count*q));seen=0
        for v,n in sorted(self.bins.items()):
            seen+=n
            if seen>=rank:return v
        return None
    def status(self):
        return {'n':self.count,'p50_ms':self.quantile(.5),'p95_ms':self.quantile(.95),
                'min_ms':self.minimum,'max_ms':self.maximum,'overflow':self.overflow,
                'quantile_method':'nearest-rank on exact integer-millisecond bins; unknown if overflow',
                'negative_age_note':'exchange timestamp ahead of local observation clock'}

class PaperMetrics:
    def __init__(self,bot,stats,stop_event):
        self.bot=bot;self.stats=stats;self.stop_event=stop_event;self.taker={x:AgeHistogram() for x in ('binance','okx')}
        self.taker_decision={x:AgeHistogram() for x in ('binance','okx')}
        self.scored=set();self.score_bins=Counter();self.score_components=Counter()
        self.candle_counts=Counter();self.candle_age_ms={};self.candle_unknown=Counter();self.candle_last=[]
        self.score_n=0;self.over_2000=0;self.older_whale_observations=0;self.coverage_sum=0.;self.whale_obs=0;self.spike_obs=0
        self.metrics_errors=0;self.calls=Counter();self.ns=Counter();self.ns_max=Counter()
    def active(self):return getattr(self.bot,'asama',None)=='tarama' and getattr(self.bot,'baslangic',None) is not None and not getattr(self.bot,'yeni_giris_kapali',False)
    @contextmanager
    def measured(self,name):
        t=time.monotonic_ns()
        try:yield
        except Exception:
            self.metrics_errors+=1
            self.stats['observation_errors']+=1
            self.stop_event.set()  # disable only the new source; V4 continues
        finally:
            elapsed=time.monotonic_ns()-t;self.calls[name]+=1;self.ns[name]+=elapsed;self.ns_max[name]=max(self.ns_max[name],elapsed)
    def on_taker(self,exchange,ts_ms):
        if not self.active():return
        with self.measured('taker'):
            if exchange in self.taker:
                hist=self.taker[exchange];hist.add(int(time.time()*1000)-int(ts_ms))
                if hist.overflow:self.stats['taker_age_histogram_overflow']+=1;self.stop_event.set()
    def on_score(self,exchange,symbol,snap,flow,events):
        if not self.active():return
        with self.measured('score'):
            self.scored.add((exchange,symbol));self.score_n+=1
            score=float(snap['score'])
            if math.isfinite(score):self.score_bins[int(round(score*10))]+=1
            for k,v in (snap.get('score_components') or {}).items():
                if math.isfinite(float(v)):self.score_components[k]+=float(v)
            self.coverage_sum+=float(snap.get('window_coverage_sec',0))
            self.over_2000+=int(len(events)>2000)
            if len(events)>2000:
                self.older_whale_observations+=int(any((e[3]+e[4])>=100_000 for e in events[:-2000]))
            self.whale_obs+=int(float(snap.get('whale_buy_usdt',0))+float(snap.get('whale_sell_usdt',0))>0)
            self.spike_obs+=int(bool(snap.get('volume_spike')))
            if flow.son_ts and exchange in self.taker_decision:self.taker_decision[exchange].add(int(time.time()*1000)-int(flow.son_ts))
    def on_candle(self,stage,exchange,symbol,closed_end_ms,reason=''):
        if not self.active():return
        with self.measured('candle'):
            key=f'{exchange}:{stage}';self.candle_counts[key]+=1
            now=int(time.time()*1000)
            age=None if closed_end_ms is None else now-int(closed_end_ms)
            if age is None:self.candle_unknown[key]+=1
            else:
                h=self.candle_age_ms.setdefault(key,AgeHistogram(lo=-1000000,hi=3000000));h.add(age)
            # Most recent bounded events; totals + unknown counts disclose truncation.
            row={'local_ms':now,'exchange':exchange,'symbol':symbol,'stage':stage,'closed_end_ms':closed_end_ms,'age_ms':age,'reason':str(reason)[:120]}
            self.candle_last.append(row)
            if len(self.candle_last)>256:self.candle_last.pop(0);self.stats['candle_detail_overflow']+=1
    def status(self):
        # Wall time spent inside hooks is NOT causal difference versus an observer-off run.
        return {'scope':'only asama=tarama; accepted trades are source-book insertions',
            'taker_book_insertion_age':{k:v.status() for k,v in self.taker.items()},
            'taker_latest_at_score_age':{k:v.status() for k,v in self.taker_decision.items()},
            'score_evaluation_count':self.score_n,'scored_unique_count':len(self.scored),
            'scored_unique_by_exchange':{k:sum(ex==k for ex,s in self.scored) for k in ('binance','okx')},
            'scored_symbols':[{'exchange':ex,'symbol':sym} for ex,sym in sorted(self.scored)],
            'score_histogram_tenths':dict(sorted(self.score_bins.items())),
            'score_component_sum':dict(self.score_components),'score_coverage_mean_sec':self.coverage_sum/self.score_n if self.score_n else None,
            'score_compact_trade_limit_exceeded_count':self.over_2000,'score_older_whale_input_observations':self.older_whale_observations,'score_whale_observations':self.whale_obs,'score_spike_observations':self.spike_obs,
            'candle_event_counts':dict(self.candle_counts),'candle_age_ms':{k:v.status() for k,v in self.candle_age_ms.items()},
            'candle_age_unknown_counts':dict(self.candle_unknown),'candle_last_events':self.candle_last,
            'hook_calls':dict(self.calls),'hook_total_ns':dict(self.ns),'hook_max_ns':dict(self.ns_max),'errors':self.metrics_errors,
            'hook_time_note':'gross local hook elapsed time, not causal overhead versus unobserved V4; audit hook tracked separately'}
