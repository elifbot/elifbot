import sqlite3,time,tempfile,json,resource,statistics
from pathlib import Path
from src.state_store import StateStore
out=[]
with tempfile.TemporaryDirectory() as td:
 for mb,draws in [(0,10),(1,10),(10,10),(100,5)]:
  p=Path(td)/('bench'+str(mb)+'.db');st=StateStore(p)
  if mb:
   with st._conn() as c:
    c.execute('CREATE TABLE benchmark_padding (payload BLOB)')
    for _ in range(mb):c.execute('INSERT INTO benchmark_padding VALUES (zeroblob(1048576))')
  times=[];cpu=[]
  for _ in range(draws):
   a=time.perf_counter();b=time.process_time();v=st.paper_ledger_health_snapshot()
   assert v['ok'];times.append((time.perf_counter()-a)*1000);cpu.append((time.process_time()-b)*1000)
  times.sort();out.append({'padding_mib':mb,'db_bytes':p.stat().st_size,'draws':draws,'wall_p50_ms':statistics.median(times),'wall_p95_ms':times[min(len(times)-1,int(.95*len(times)))],'wall_max_ms':max(times),'cpu_mean_ms':statistics.mean(cpu),'process_peak_rss_kib_so_far':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
result={'synthetic_padding_not_real_trade_population':True,'scope':'isolated ledger health snapshot, not full API or thread race benchmark','results':out}
Path('/evidence/health_copy_benchmark.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
