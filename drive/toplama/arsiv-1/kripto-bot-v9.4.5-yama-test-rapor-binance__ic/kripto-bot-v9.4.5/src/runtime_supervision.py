"""Operational liveness/continuity only; does not select trades or alter risk rules."""
import json,time
from pathlib import Path


class RuntimeSupervision:
    def __init__(self, *, clock=None, wall=None, event_path=None, on_fatal=None, stopping=None,
                 progress_timeout_sec=30., heartbeat_timeout_sec=15., gap_sec=5., clock_skew_sec=2.):
        self.clock=clock or time.monotonic;self.wall=wall or time.time
        self.event_path=Path(event_path) if event_path else None;self.on_fatal=on_fatal;self.stopping=stopping or (lambda:False)
        self.progress_timeout_sec=progress_timeout_sec;self.heartbeat_timeout_sec=heartbeat_timeout_sec
        self.gap_sec=gap_sec;self.clock_skew_sec=clock_skew_sec
        self.active=False;self.shutting_down=False;self.tasks={};self.failures={}
        self.started=self.clock();self.last_cycle=self.started;self.last_progress=self.started;self.last_count=0
        self.gap_count=0;self.max_sleep_sec=0.;self.max_excess_sec=0.;self.max_wall_skew_sec=0.;self.timings={}

    def event(self,kind,**data):
        row={'event':kind,'epoch':self.wall(),'monotonic':self.clock(),**data}
        if self.event_path:
            with self.event_path.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')

    def activate(self,count=0):
        self.active=True;self.started=self.clock();self.last_cycle=self.started;self.last_progress=self.started;self.last_count=count

    def add_task(self,name,task):
        self.tasks[name]=task
        task.add_done_callback(lambda completed:self.inspect_task(name,completed))

    def inspect_task(self,name,task):
        if not self.active or self.shutting_down or self.stopping() or name in self.failures or not task.done():return
        if task.cancelled():reason='unexpected_cancellation'
        else:
            exc=task.exception();reason=type(exc).__name__ if exc else 'unexpected_return'
        self.failures[name]=reason;self.event('BACKGROUND_TASK_FAILED',task=name,reason=reason)
        if self.on_fatal:self.on_fatal()

    def check_tasks(self):
        for name,task in self.tasks.items():self.inspect_task(name,task)
        if self.failures:raise RuntimeError('BACKGROUND_TASK_FAILED:'+','.join(sorted(self.failures)))

    def progress(self,count):
        if count!=self.last_count:self.last_count=count;self.last_progress=self.clock()

    def cycle_completed(self,duration):
        self.last_cycle=self.clock();self.timing('strategy_cycle_including_awaits',duration)

    def timing(self,name,seconds):
        ms=1000*max(0.,seconds);old=self.timings.get(name,{'last_ms':0.,'max_ms':0.,'count':0})
        self.timings[name]={'last_ms':ms,'max_ms':max(old['max_ms'],ms),'count':old['count']+1}

    def sleep_observed(self,requested,before_mono,before_wall):
        dm=self.clock()-before_mono;dw=self.wall()-before_wall;excess=max(0.,dm-requested);skew=abs(dw-dm)
        self.max_sleep_sec=max(self.max_sleep_sec,dm);self.max_excess_sec=max(self.max_excess_sec,excess);self.max_wall_skew_sec=max(self.max_wall_skew_sec,skew)
        if dm>self.gap_sec or skew>self.clock_skew_sec:
            self.gap_count+=1;self.event('RUN_DISCONTINUITY',requested_sec=requested,observed_monotonic_sec=dm,observed_wall_sec=dw,wall_monotonic_skew_sec=skew)
        elif excess>1:self.event('EVENT_LOOP_DELAY',requested_sec=requested,observed_monotonic_sec=dm,excess_sec=excess)

    def snapshot(self):
        for name,task in self.tasks.items():self.inspect_task(name,task)
        now=self.clock();alarms=[]
        if self.failures:alarms.append('BACKGROUND_TASK_FAILED('+','.join(sorted(self.failures))+')')
        if self.active and not self.shutting_down:
            if now-self.last_cycle>self.heartbeat_timeout_sec:alarms.append('STRATEGY_CYCLE_HEARTBEAT_STALE')
            if now-self.last_progress>self.progress_timeout_sec:alarms.append('EVALUATION_CALLS_STALLED')
        if self.gap_count:alarms.append('RUN_DISCONTINUITY_DETECTED')
        return {'enabled':True,'active':self.active,'shutting_down':self.shutting_down,'healthy':not alarms,'alarms':alarms,
                'background_tasks':{n:('cancelled' if t.cancelled() else 'done' if t.done() else 'running') for n,t in self.tasks.items()},
                'task_failures':dict(self.failures),'strategy_cycle_age_sec':max(0,now-self.last_cycle),
                'evaluation_progress_age_sec':max(0,now-self.last_progress),'evaluation_count':self.last_count,
                'continuity_ok':self.gap_count==0,'gap_count':self.gap_count,'max_observed_sleep_sec':self.max_sleep_sec,
                'max_poll_excess_sec':self.max_excess_sec,'max_wall_monotonic_skew_sec':self.max_wall_skew_sec,
                'thresholds':{'progress_timeout_sec':self.progress_timeout_sec,'heartbeat_timeout_sec':self.heartbeat_timeout_sec,'gap_sec':self.gap_sec,'clock_skew_sec':self.clock_skew_sec},
                'timings':dict(self.timings),'scope':'Liveness is not signal profitability; monotonic time alone does not prove continuity'}
