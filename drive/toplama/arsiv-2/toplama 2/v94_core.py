"""One closed-candle decision core shared by live and historical replay.
No ticker is written into a historical candle. No LLM/agent voting claims.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
from .adaptive_policy import AdaptivePolicy


def ema(x,span):
    y=np.empty(len(x));y[0]=x[0];a=2/(span+1)
    for i in range(1,len(x)):y[i]=a*x[i]+(1-a)*y[i-1]
    return y


def wilder(x,period=14):
    y=np.empty(len(x));y[0]=x[0];a=1/period
    for i in range(1,len(x)):y[i]=a*x[i]+(1-a)*y[i-1]
    return y


def closed_htf_direction(df,decision_close_ms,minutes):
    """Only exact, complete HTF buckets; no partial first/last buckets or future rows."""
    times=df['open_time'].to_numpy(dtype=np.int64)
    expected=minutes//5;bucket=minutes*60000
    valid=times+300000<=decision_close_ms
    d=df.loc[valid];times=times[valid]
    if len(d)<expected*10:return 0
    groups=times//bucket
    starts=np.r_[0,np.flatnonzero(np.diff(groups))+1];ends=np.r_[starts[1:],len(times)]
    closes=d['close'].to_numpy(dtype=float)
    values=[]
    for a,b in zip(starts,ends):
        t=times[a:b]
        if len(t)==expected and t[0]%bucket==0 and t[-1]+300000==(groups[a]+1)*bucket and np.all(np.diff(t)==300000):
            values.append(closes[b-1])
    if len(values)<10:return 0
    v=np.asarray(values);fast=ema(v,8);slow=ema(v,21)
    return 1 if fast[-1]>slow[-1] and fast[-1]>fast[-3] else -1 if fast[-1]<slow[-1] and fast[-1]<fast[-3] else 0


@dataclass(frozen=True)
class Features:
    ts: int
    close: float
    atr: float
    ema9: float
    ema21: float
    ema50: float
    slope: float
    rsi: float
    efficiency: float
    flow_score: float
    last_delta: float
    rvol: float
    vwap_z: float
    dir15: int
    dir60: int
    breakout_up: bool
    breakout_down: bool
    reclaim_up: bool
    reclaim_down: bool
    real_taker: bool
    valid: bool


def features(df):
    df=df.tail(600)
    if 'open_time' not in df:df=df.rename(columns={'ts':'open_time'})
    if len(df)<120:raise ValueError('120 closed bars required')
    t=df.open_time.to_numpy(dtype=np.int64)
    c=df.close.to_numpy(dtype=float);h=df.high.to_numpy(dtype=float);l=df.low.to_numpy(dtype=float)
    o=df.open.to_numpy(dtype=float);v=df.volume.to_numpy(dtype=float)
    valid=bool(np.all(np.isfinite(np.r_[c,h,l,o,v])) and np.all(c>0) and np.all(h>=np.maximum(o,c)) and np.all(l<=np.minimum(o,c)) and np.all(np.diff(t)==300000) and np.all(v>=0))
    prev=np.r_[c[0],c[:-1]];tr=np.maximum(h-l,np.maximum(np.abs(h-prev),np.abs(l-prev)))
    atr=float(wilder(tr)[-1]);e9=ema(c,9);e21=ema(c,21);e50=ema(c,50)
    delta=np.diff(c);ag=wilder(np.maximum(delta,0))[-1];al=wilder(np.maximum(-delta,0))[-1]
    rsi=float(100-100/(1+ag/al)) if al>1e-12 else 100. if ag>0 else 50.
    real='taker_buy_quote' in df and bool(np.isfinite(df.taker_buy_quote.iloc[-6:]).all())
    buy=df.taker_buy_quote.to_numpy(dtype=float) if real else v*.5
    if real and (np.any(buy[-6:]<0) or np.any(buy[-6:]>v[-6:]*1.000001)):valid=False
    dv=2*buy-v
    flow=float(np.sum(dv[-2:])/max(np.sum(v[-2:]),1e-9)*100)
    rvol=float(v[-1]/max(np.median(v[-21:-1]),1e-9))
    typical=(h[-20:]+l[-20:]+c[-20:])/3
    vw=float(np.dot(typical,v[-20:])/max(v[-20:].sum(),1e-9))
    er=float(abs(c[-1]-c[-21])/max(np.abs(np.diff(c[-21:])).sum(),1e-12))
    return Features(int(t[-1]),float(c[-1]),atr,float(e9[-1]),float(e21[-1]),float(e50[-1]),
        float(e21[-1]-e21[-4]),rsi,er,flow,float(dv[-1]/max(v[-1],1e-9)),rvol,
        (float(c[-1])-vw)/max(atr,1e-12),closed_htf_direction(df,int(t[-1])+300000,15),
        closed_htf_direction(df,int(t[-1])+300000,60),
        bool(c[-1]>np.max(h[-13:-1])),bool(c[-1]<np.min(l[-13:-1])),
        bool(c[-1]>h[-2] and np.min(l[-4:-1])<=e21[-1]+.4*atr),
        bool(c[-1]<l[-2] and np.max(h[-4:-1])>=e21[-1]-.4*atr),real,valid)


def market_context(symbol_frames, decision_ts):
    """Timestamp-joined leader + breadth, excluding stale/misaligned symbol histories."""
    returns=[];leader=[];leader_names=[]
    for sym,df in symbol_frames.items():
        tc='open_time' if 'open_time' in df else 'ts'
        sub=df.loc[df[tc]<=decision_ts]
        if len(sub)<13 or int(sub[tc].iloc[-1])!=decision_ts:continue
        c=sub.close.to_numpy(dtype=float)
        if not np.isfinite(c[-13:]).all() or np.any(c[-13:]<=0):continue
        returns.append((c[-1]/c[-4]-1)*100)
        if sym.upper().replace('/','') in ('BTCUSDT','ETHUSDT'):
            leader.append((c[-1]/c[-13]-1)*100);leader_names.append(sym)
    breadth=(sum(x>.25 for x in returns)-sum(x<-.25 for x in returns))/max(1,len(returns))
    return {'leader_ret_1h_pct':float(np.mean(leader)) if leader else 0.,
            'breadth':breadth,'breadth_sample':len(returns),'leader_count':len(leader)}


class V94DecisionCore:
    def __init__(self,policy=None,disabled=None):
        self.policy=policy or AdaptivePolicy();self.disabled=disabled

    def decide(self,f:Features,ctx:dict,spread_pct=.015):
        def reject(reason):return {'side':'HOLD','reason':reason,'features':asdict(f)}
        if not f.valid:return reject('INVALID_OR_GAPPED_CANDLES')
        if not f.real_taker:return reject('REAL_TAKER_UNAVAILABLE')
        if ctx.get('leader_count',0)<2:return reject('LEADERS_UNAVAILABLE_OR_STALE')
        if not np.isfinite(spread_pct) or spread_pct<0 or spread_pct>self.policy.max_spread_pct:return reject('SPREAD_TOO_WIDE')
        if f.atr<=0:return reject('INVALID_ATR')
        sign=1 if f.close>f.ema21>f.ema50 and f.slope>0 else -1 if f.close<f.ema21<f.ema50 and f.slope<0 else 0
        if sign==0:return reject('NO_LOCAL_TREND')
        side='LONG' if sign==1 else 'SHORT'
        if self.disabled!='TREND':
            if f.dir15!=sign or f.dir60==-sign:return reject('CLOSED_HTF_DISAGREEMENT')
            if f.efficiency<.20:return reject('LOW_TREND_EFFICIENCY')
            if not (48<=f.rsi<=72 if sign==1 else 28<=f.rsi<=52):return reject('RSI_EXHAUSTION')
            if abs(f.close-f.ema21)>2*f.atr or abs(f.vwap_z)>2.5:return reject('DO_NOT_CHASE')
        if self.disabled!='FLOW':
            if f.flow_score*sign<8 or f.last_delta*sign<=0 or f.rvol<.9:return reject('INSUFFICIENT_REAL_FLOW')
        trigger=(f.reclaim_up or (f.breakout_up and f.rvol>=1.1)) if sign==1 else (f.reclaim_down or (f.breakout_down and f.rvol>=1.1))
        if not trigger:return reject('WAIT_FOR_RECLAIM_OR_BREAKOUT')
        if self.disabled!='MARKET':
            # Soft consistency rather than a broad BTC-score veto. Only joint strong opposition blocks.
            if ctx.get('leader_ret_1h_pct',0)*sign<-.6 and ctx.get('breadth',0)*sign<-.35:return reject('JOINT_MARKET_OPPOSITION')
        try:risk=self.policy.risk_distance(f.close,f.atr)
        except ValueError:return reject('ATR_EXCEEDS_RISK_CAP')
        transaction_cost=f.close*(.0007+.0006+spread_pct/100)
        if 2*risk < 4*transaction_cost:return reject('INSUFFICIENT_COST_HEADROOM')
        return {'side':side,'reason':'FLOW_CONFIRMED_RECLAIM' if (f.reclaim_up if sign==1 else f.reclaim_down) else 'FLOW_CONFIRMED_BREAKOUT',
                'risk_distance':risk,'features':asdict(f)}

    def exit_decision(self,f,side,age_sec,gross_pnl,risk_usdt):
        sign=1 if side=='LONG' else -1
        local_flip=f.slope*sign<0 and (f.close-f.ema21)*sign<0
        flow_flip=f.flow_score*sign<=-8 and f.last_delta*sign<0
        # A confirmed closed-candle thesis failure, not a gross-profit threshold that delays losing exits.
        if age_sec>=600 and local_flip and flow_flip:
            return {'should_exit':True,'exit_kind':'CONFIRMED_THESIS_FAILURE'}
        return {'should_exit':False}
