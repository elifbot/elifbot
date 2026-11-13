"""Bounded-field event audit for opt-in source comparison; not a decision gate."""
import json,os,time,uuid
from scanner.v78_metrics import AgeHistogram

class PaperAudit:
    def __init__(self,path,stats,stop_event,active=lambda:True):
        self.path=path;self.stats=stats;self.stop_event=stop_event
        self.session=uuid.uuid4().hex;self.seq=0;self.last_error=None;self.active=active
        self.elapsed_us=AgeHistogram(lo=0,hi=2_000_000)
    def write(self,signal,source,stage,ready):
        start=time.monotonic_ns()
        try:
            event_id=getattr(signal,'_v78_audit_id',None)
            if event_id is None:
                self.seq+=1;event_id=f'{self.session}-{self.seq}'
                setattr(signal,'_v78_audit_id',event_id)
            row={'id':event_id,'source':source,'stage':stage,'signal_ts_ms':int(signal.ts_ms),
                 'observed_ts_ms':int(time.time()*1000),'exchange':signal.exchange,
                 'symbol':signal.symbol,'side':signal.yon,'ready':bool(ready)}
            data=json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n'
            os.makedirs(os.path.dirname(self.path),exist_ok=True)
            with open(self.path,'a',encoding='utf-8') as f:f.write(data)
            self.stats['audit_records']+=1;self.stats['audit_bytes']+=len(data.encode('utf-8'))
        except Exception as exc:
            self.last_error=f'{type(exc).__name__}: {str(exc)[:160]}'
            self.stats['audit_errors']+=1
            self.stop_event.set() # stop only new source; leave V4 tasks alone
        finally:
            elapsed=time.monotonic_ns()-start
            self.stats['audit_calls']+=1;self.stats['audit_total_ns']+=elapsed
            self.stats['audit_max_ns']=max(self.stats['audit_max_ns'],elapsed)
            if self.active():self.elapsed_us.add(elapsed//1000)

    def timing_status(self):
        x=self.elapsed_us.status()
        return {'n':x['n'],'p50_us':x['p50_ms'],'p95_us':x['p95_ms'],'min_us':x['min_ms'],
                'max_us':x['max_ms'],'overflow':x['overflow'],
                'scope':'during scan only; gross time inside audit hook',
                'note':'does not measure causal end-to-end observer overhead; zero calls means unknown'}
