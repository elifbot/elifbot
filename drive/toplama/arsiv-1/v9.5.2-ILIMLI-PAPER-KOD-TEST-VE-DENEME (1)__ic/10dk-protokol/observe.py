"""Independent timing/HTTP and read-only SQLite sampler. No trading-source hooks."""
import json,sqlite3,time,urllib.request,urllib.error
from pathlib import Path
E=Path(__file__).resolve().parent;start=time.monotonic();seen=False;next_state=0;next_db=0
plan=json.loads((E/'plan.json').read_text());db=E/'natural10m_mild_state.db'

def request(path,timeout):
    global seen
    row={'epoch':time.time(),'path':path,'seen_response_before':seen};begin=time.monotonic()
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080'+path,timeout=timeout) as r:
            row.update(status=r.status,body=json.loads(r.read()));seen=True
    except urllib.error.HTTPError as exc:
        row.update(status=exc.code,body=json.loads(exc.read()));seen=True
    except Exception as exc:
        row.update(error=type(exc).__name__,detail=str(exc),bootstrap_before_first_response=not seen)
    row['duration_ms']=(time.monotonic()-begin)*1000
    return row

with (E/'http_observations.jsonl').open('x') as out,(E/'db_observations.jsonl').open('x') as dout:
    while time.monotonic()-start<1000:
        if (E/'process_result.json').exists():break
        row=request('/health',2);out.write(json.dumps(row)+'\n');out.flush()
        now=time.monotonic()
        if seen and now>=next_state:
            out.write(json.dumps(request('/api/state',3))+'\n');out.flush();next_state=now+10
        if db.exists() and now>=next_db:
            row={'epoch':time.time()}
            try:
                with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=1) as conn:
                    row['intent_status_counts']={t:dict(conn.execute('SELECT status,COUNT(*) FROM '+t+' GROUP BY status')) for t in ['paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents']}
                    row['open_positions']=conn.execute('SELECT COUNT(*) FROM open_positions').fetchone()[0]
                    row['closed_trades']=conn.execute('SELECT COUNT(*) FROM trade_history').fetchone()[0]
            except Exception as exc:row.update(error=type(exc).__name__,detail=str(exc))
            dout.write(json.dumps(row)+'\n');dout.flush();next_db=now+2
        time.sleep(.5)
(E/'observer_result.json').write_text(json.dumps({'ended_epoch':time.time(),'elapsed_sec':time.monotonic()-start,'runner_result_exists':(E/'process_result.json').exists()},indent=2))
