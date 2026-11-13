"""Diagnostic instrumentation only. Inclusive wall time, NOT CPU time; adds measurable overhead."""
import asyncio,functools,json,time
from pathlib import Path

class Probe:
    def __init__(self,runner,path,period=.05,flush_sec=1.):
        self.runner=runner;self.path=Path(path);self.period=period;self.flush_sec=flush_sec
        self.agg={};self.originals=[];self.task=None;self.closing=False;self.failed=None
        self.base_mono=time.perf_counter();self.base_epoch=time.time();self.window_start=self.base_mono
        self.lag_ms=0.;self.lag_event=None;self.record_ns=0;self.record_ns_total=0;self.calls=0
        self.write_ns_total=0;self.write_ns_max=0;self.windows=0;self.fh=None
    def _record(self,key,start,end,args,kwargs):
        rec_start=time.perf_counter_ns();dt=max(0,end-start)
        x=self.agg.setdefault(key,{'n':0,'total_sec':0.,'max_sec':0.,'max_start_epoch':None,'max_end_epoch':None,'context':{}})
        x['n']+=1;x['total_sec']+=dt;self.calls+=1
        if dt>=x['max_sec']:
            x.update(max_sec=dt,max_start_epoch=self.base_epoch+start-self.base_mono,max_end_epoch=self.base_epoch+end-self.base_mono)
            context={}
            if key in ('features','market_context'):
                if key=='market_context' and len(args)>1:context['bar_open_ms']=args[1]
                elif args:
                    df=args[0];col='open_time' if 'open_time' in df else 'ts'
                    try:
                        if len(df) and col in df:context['bar_open_ms']=int(df[col].iloc[-1])
                    except Exception:context['bar_open_ms']=None
            elif args and isinstance(args[0],str):
                if key in ('on_trade','evaluate_and_route') and len(args)>1:context={'exchange':args[0],'symbol':args[1]}
                else:context={'symbol':args[0]}
            if kwargs.get('exchange'):context['exchange']=kwargs['exchange']
            x['context']=context
        cost=time.perf_counter_ns()-rec_start;self.record_ns+=cost;self.record_ns_total+=cost
    def wrap(self,obj,attr,key=None):
        fn=getattr(obj,attr);key=key or attr
        own=getattr(obj,'__dict__',{});had_own=attr in own;old_own=own.get(attr)
        if getattr(fn,'_latency_probe_owner',None) is not None:raise RuntimeError('already instrumented: '+attr)
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def w(*a,**k):
                t=time.perf_counter()
                try:return await fn(*a,**k)
                finally:self._record(key,t,time.perf_counter(),a,k)
        else:
            @functools.wraps(fn)
            def w(*a,**k):
                t=time.perf_counter()
                try:return fn(*a,**k)
                finally:self._record(key,t,time.perf_counter(),a,k)
        w._latency_probe_owner=self;setattr(obj,attr,w);self.originals.append((obj,attr,had_own,old_own,w))
    def restore(self):
        for obj,attr,had_own,old,w in reversed(self.originals):
            if getattr(obj,attr,None) is w:
                if had_own:setattr(obj,attr,old)
                else:delattr(obj,attr)
        self.originals.clear()
    def flush(self,final=False):
        end=time.perf_counter();stats={}
        for key,x in self.agg.items():
            stats[key]={'n':x['n'],'total_ms':x['total_sec']*1000,'max_ms':x['max_sec']*1000,'max_start_epoch':x['max_start_epoch'],'max_end_epoch':x['max_end_epoch'],'context':x['context']}
        row={'epoch':time.time(),'monotonic':end,'window_elapsed_ms':(end-self.window_start)*1000,'phase':getattr(self.runner,'phase',None),'final':final,'open_positions':len(self.runner.executor.positions),'loop_lag_max_ms':self.lag_ms,'loop_lag_event':self.lag_event,'recorder_ns_this_window':self.record_ns,'recorder_ns_total':self.record_ns_total,'write_ns_total_before_this_row':self.write_ns_total,'write_ns_max_before_this_row':self.write_ns_max,'stats':stats,'scope':'inclusive wall durations; nested/overlapping calls MUST NOT be summed as CPU use; probe changes timing'}
        start=time.perf_counter_ns();self.fh.write(json.dumps(row,ensure_ascii=False)+'\n');self.fh.flush();cost=time.perf_counter_ns()-start
        self.write_ns_total+=cost;self.write_ns_max=max(self.write_ns_max,cost);self.windows+=1
        self.agg.clear();self.lag_ms=0.;self.lag_event=None;self.record_ns=0;self.window_start=end
    async def _run(self):
        try:
            while not self.runner.stop_Flag:
                t=time.perf_counter();await asyncio.sleep(self.period);now=time.perf_counter();lag=max(0.,now-t-self.period)*1000
                if lag>=self.lag_ms:
                    self.lag_ms=lag;self.lag_event={'sleep_start_epoch':self.base_epoch+t-self.base_mono,'wake_epoch':self.base_epoch+now-self.base_mono,'requested_ms':self.period*1000,'observed_ms':(now-t)*1000}
                if now-self.window_start>=self.flush_sec:self.flush()
        finally:
            try:self.flush(final=True)
            finally:self.fh.close()
    def _done(self,task):
        if task.cancelled():
            if self.closing or self.runner.stop_Flag:return
            self.failed='unexpected probe cancellation'
        else:
            exc=task.exception()
            if exc is not None:self.failed=repr(exc)
            elif not self.closing and not self.runner.stop_Flag:self.failed='unexpected probe return'
        if self.failed:
            self.runner.allow_new_entries=False;self.runner.stop_Flag=True
    def launch(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.fh=self.path.open('a',encoding='utf-8');self.task=asyncio.create_task(self._run(),name='latency_probe');self.task.add_done_callback(self._done)
        return self
    async def close(self):
        self.closing=True
        if self.task is not None:
            if not self.task.done():self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        if self.fh is not None and not self.fh.closed:
            try:self.flush(final=True)
            finally:self.fh.close()
        self.restore()
        return {'failed':self.failed,'calls':self.calls,'windows':self.windows,'recorder_ns_total':self.record_ns_total,'log_write_ns_total':self.write_ns_total,'log_write_ns_max':self.write_ns_max,'scope':'Measured recorder aggregation+JSONL writes only; excludes all clock/wrapper overhead. Not total probe overhead.'}

def start(runner,path='latency_probe.jsonl'):
    old=getattr(runner,'_diagnostic_latency_probe',None)
    if old is not None:
        if not old.closing:return old
        raise RuntimeError('probe already closed on this runner')
    p=Probe(runner,path)
    try:
        p.wrap(runner.executor,'on_price_tick');p.wrap(runner.engine,'on_trade');p.wrap(runner.engine,'evaluate_and_route')
        stores={id(s):s for s in (getattr(runner.executor,'state_store',None),getattr(runner,'store',None)) if s is not None}
        for i,s in enumerate(stores.values()):
            for m in ('update_paper_risk_if_unchanged','acquire_writer_lease'):
                if hasattr(s,m):p.wrap(s,m,m if len(stores)==1 else str(i)+'.'+m)
        import src.v94_live_router as router
        p.wrap(router,'features');p.wrap(router,'market_context')
        for m in ('build_state_payload','_rows_to_df','warmup_symbol'):
            if hasattr(runner,m):p.wrap(runner,m)
        if hasattr(runner.executor,'risk'):p.wrap(runner.executor.risk,'find_pair_rescue')
        p.launch();runner._diagnostic_latency_probe=p
        monitor=getattr(runner,'runtime_supervision',None)
        if monitor is not None:monitor.add_task('latency_probe',p.task)
        return p
    except BaseException:
        p.restore()
        if p.fh is not None:p.fh.close()
        raise
