"""Opt-in measurement decorator; frozen trading source files remain byte-identical.
Original return values are returned unchanged. Observational failures never alter
orders, positions, thresholds or the original method's exception behavior.
"""
from __future__ import annotations
from .counterfactual import CounterfactualTracker
from .v94_core import V94DecisionCore,market_context


class GateMeasurementOverlay:
    def __init__(self,engine,policy):
        self.engine=engine;self.policy=policy;self.seen=set();self.errors=[]
        self.tracker=CounterfactualTracker(max_blocked_records=5000)
        self._install()

    def _observe_quote(self,exchange,symbol,price,ts_ms):
        try:self.tracker.on_price_update(symbol,float(price),now_ts=ts_ms/1000,exchange=exchange)
        except Exception as exc:self.errors.append(type(exc).__name__+': '+str(exc))

    def _install(self):
        e=self.engine;original_universe=e.ingest_universe_price
        def universe(exchange,symbol,price,ts_ms=None):
            result=original_universe(exchange,symbol,price,ts_ms)
            if ts_ms is not None:self._observe_quote(exchange,symbol,price,ts_ms)
            return result
        e.ingest_universe_price=universe
        original_trade=e.on_trade
        async def trade(exchange,symbol,price,qty,**kwargs):
            result=await original_trade(exchange,symbol,price,qty,**kwargs)
            if kwargs.get('ts_ms') is not None:self._observe_quote(exchange,symbol,price,kwargs['ts_ms'])
            return result
        e.on_trade=trade
        original_evaluate=e.evaluate_and_route
        async def evaluate(exchange,symbol,df,**kwargs):
            had_position=symbol in e.executor.positions
            result=await original_evaluate(exchange,symbol,df,**kwargs)
            try:self.note_decision(exchange,symbol,df,kwargs,had_position)
            except Exception as exc:self.errors.append(type(exc).__name__+': '+str(exc))
            return result
        e.evaluate_and_route=evaluate

    def note_decision(self,exchange,symbol,df,kwargs,had_position):
        if had_position or not kwargs.get('allow_new_entries',True):return
        now=kwargs.get('now_ms');mark=kwargs.get('mark_price');spread=kwargs.get('spread_pct',.015)
        if now is None or mark is None:return
        tscol='open_time' if 'open_time' in df else 'ts';ts=int(df[tscol].iloc[-1])
        identity=(symbol,exchange,ts)
        if identity in self.seen or not 0<=now-(ts+300000)<=180000:return
        self.seen.add(identity)
        router=getattr(self.engine,'v94_router',None)
        if router is None:return
        f=router.cache.get((symbol,ts))
        if f is None:return
        context=market_context(getattr(self.engine,'v94_frames',{}),ts)
        base=router.core.decide(f,context,spread)
        if base['side'] in ('LONG','SHORT'):return
        for family in ('TREND','FLOW','MARKET'):
            other=V94DecisionCore(self.policy,disabled=family).decide(f,context,spread)
            if other['side'] not in ('LONG','SHORT'):continue
            distance=self.policy.risk_distance(f.close,f.atr)
            self.tracker.record_blocked_signal(gate='SINGLE_BLOCKER_'+family,symbol=symbol,side=other['side'],
                price=mark,now_ts=now/1000,decision_id=ts,exchange=exchange,
                roundtrip_cost_bps=13+spread*100,tactical_stop_bps=distance/f.close*10000,
                reason=base['reason'],cohort_type='SINGLE_GATE_ONLY_BLOCKER')

    def summary(self):
        return {'gate_cohorts':self.tracker.summary(),'observer_errors':self.errors[-30:],
                'trading_decision_return_values_modified':False,'frozen_trading_source_modified':False,
                'runtime_note':'Observation adds runtime overhead; exact live execution timing is not claimed identical.'}
