"""Shared-core live PAPER routing; operational execution guards remain in Executor."""
from __future__ import annotations
from datetime import datetime,timezone
import math
from .v94_core import features,market_context,V94DecisionCore
from .adaptive_policy import AdaptivePolicy


class V94LiveRouter:
    def __init__(self,engine,policy):
        self.engine=engine;self.executor=engine.executor;self.policy=policy
        self.core=V94DecisionCore(policy);self.seen={};self.cache={};self.rejections={}

    async def evaluate(self,exchange,symbol,df,*,mark_price=None,spread_pct=.015,now_ms,allow_new_entries=True,**kwargs):
        base={'symbol':symbol,'signal':'BEKLE','routed':False,'regime':{'macro_regime':'V94_SHARED_CORE'}}
        def reject(reason):
            self.rejections[reason]=self.rejections.get(reason,0)+1
            return {**base,'reason':reason}
        if mark_price is None or not math.isfinite(mark_price) or mark_price<=0:return reject('LIVE_MARK_UNAVAILABLE')
        if len(df)<120:return reject('INSUFFICIENT_CLOSED_HISTORY')
        tscol='open_time' if 'open_time' in df else 'ts'
        ts=int(df[tscol].iloc[-1]);key=(symbol,ts)
        if ts+300000>now_ms:return reject('FORMING_CANDLE_REJECTED')
        if key not in self.cache:
            try:self.cache[key]=features(df)
            except (ValueError,KeyError):return reject('INVALID_CANDLE_FEATURES')
        if len(self.cache)>4096:self.cache={key:self.cache[key]}
        f=self.cache[key]
        self.executor.set_atr(symbol,f.atr)
        pos=self.executor.positions.get(symbol)
        # Price risk runs independently on every venue-specific quote; candle thesis only once per close.
        if pos is not None:
            if self.seen.get(symbol)==ts:return reject('POSITION_WAIT_NEXT_CLOSED_BAR')
            self.seen[symbol]=ts
            age=max(0,now_ms/1000-self.executor._position_opened_ts.get(symbol,now_ms/1000))
            atr=pos.entry*float(pos.atr_pct)/100
            try:risk=self.policy.risk_distance(pos.entry,atr)*pos.qty
            except ValueError:risk=abs(pos.entry-pos.stop)*pos.qty
            dec=self.core.exit_decision(f,pos.side,age,self.executor.risk.pnl_usdt(pos,mark_price),risk)
            if dec['should_exit']:
                closed=await self.executor.close_position(symbol,mark_price,dec['exit_kind'])
                return {**base,'reason':dec['exit_kind'],'routed':bool(closed)}
            return reject('HOLD_CONFIRMED_THESIS')
        if not allow_new_entries:return reject('DRAIN_NO_NEW_ENTRY')
        if self.seen.get(symbol)==ts:return reject('ONE_ATTEMPT_PER_CLOSED_BAR')
        if now_ms-(ts+300000)>180000:return reject('STALE_SIGNAL_BAR')
        self.seen[symbol]=ts
        frames=getattr(self.engine,'v94_frames',{})
        ctx=market_context(frames,ts)
        dec=self.core.decide(f,ctx,spread_pct)
        if dec['side']=='HOLD':return reject(dec['reason'])
        if abs(mark_price-f.close)>self.policy.max_entry_drift_atr*f.atr:return reject('LIVE_ENTRY_DRIFT')
        # Executor still checks cooldown, circuit breaker, deduplication, financial CAS and margin.
        self.executor.set_atr(symbol,f.atr)
        self.executor.cooldown_sec=self.policy.cooldown_bars*300
        combined={'signal':dec['side'],'total':40. if dec['side']=='LONG' else -40.,'entry_allowed':True}
        await self.executor.on_price_tick(symbol,mark_price,exchange=exchange)
        before=symbol in self.executor.positions
        await self.executor.on_signal(symbol,mark_price,combined,f.flow_score,False,
            entry_context={'engine':'V94_SHARED_CLOSED_CORE','preferred_exchange':exchange,
                           'signal_close':f.close,'signal_ts':ts+300000,'atr':f.atr,
                           'playbook':dec['reason'],'features':dec['features']})
        routed=not before and symbol in self.executor.positions
        if routed:self.engine.metrics['entries_routed']+=1
        else:self.engine.metrics['maker_unfilled_skips']+=1
        return {**base,'signal':dec['side'],'routed':routed,'reason':dec['reason'] if routed else 'EXECUTION_GUARD_OR_UNFILLED',
                'features':dec['features'],'market_context':ctx}
