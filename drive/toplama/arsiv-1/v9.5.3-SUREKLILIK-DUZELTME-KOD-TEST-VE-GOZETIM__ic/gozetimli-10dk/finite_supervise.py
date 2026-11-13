"""ONE finite experiment, waited to completion. No service or trading child is orphaned by this command."""
from pathlib import Path
import json,sys,subprocess,threading,time,datetime,urllib.request,urllib.error,sqlite3,os
E=Path(__file__).resolve().parent
stop=threading.Event();observer_errors=[]

def sample():
    seen=False;next_state=0.;next_db=0.
    with (E/'http_observations.jsonl').open('x') as http,(E/'db_observations.jsonl').open('x') as dbout:
        def get(path,timeout):
            nonlocal seen
            begin=time.monotonic();row={'epoch':time.time(),'path':path,'seen_response_before':seen}
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080'+path,timeout=timeout) as r:row.update(status=r.status,body=json.loads(r.read()));seen=True
            except urllib.error.HTTPError as e:row.update(status=e.code,body=json.loads(e.read()));seen=True
            except Exception as e:row.update(error=type(e).__name__,detail=str(e),bootstrap_before_first_response=not seen)
            row['duration_ms']=(time.monotonic()-begin)*1000
            http.write(json.dumps(row)+'\n');http.flush()
        while not stop.is_set():
            get('/health',2);now=time.monotonic()
            if seen and now>=next_state:get('/api/state',3);next_state=now+10
            db=E/'natural10m_continuity_state.db'
            if db.exists() and now>=next_db:
                row={'epoch':time.time()}
                try:
                    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=1) as c:
                        row['intent_status_counts']={t:dict(c.execute('SELECT status,COUNT(*) FROM '+t+' GROUP BY status')) for t in ['paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents']}
                        row['open_positions']=c.execute('SELECT COUNT(*) FROM open_positions').fetchone()[0]
                        row['closed_trades']=c.execute('SELECT COUNT(*) FROM trade_history').fetchone()[0]
                except Exception as e:row.update(error=type(e).__name__,detail=str(e))
                dbout.write(json.dumps(row)+'\n');dbout.flush();next_db=now+2
            stop.wait(.5)

def safe_sample():
    try:sample()
    except BaseException as e:observer_errors.append(type(e).__name__+': '+str(e))

def main():
    # Exclusive supervisor attempt; reopening cannot truncate data or restart a consumed run.
    (E/'supervisor_attempt.lock').open('x').close()
    start=time.time();mono=time.monotonic();watchdog=False;error=None;proc=None;thread=None
    try:
        env=dict(os.environ,BINANCE_PUBLIC_WWW='1',PYTHONUNBUFFERED='1')
        proc=subprocess.Popen([sys.executable,str(E/'launch.py')],cwd=E,env=env)
        thread=threading.Thread(target=safe_sample,name='read-only-observer');thread.start()
        print('Finite supervised PAPER started; awaiting child exit, at most 850 sec.',flush=True)
        try:code=proc.wait(timeout=850)
        except subprocess.TimeoutExpired:
            watchdog=True;proc.terminate()
            try:code=proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();code=proc.wait(timeout=5)
    except BaseException as e:
        error=type(e).__name__
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        code=proc.returncode if proc is not None else None
    finally:
        stop.set()
        if thread is not None:thread.join(timeout=10)
    receipt={'start_epoch':start,'end_epoch':time.time(),'elapsed_monotonic_sec':time.monotonic()-mono,'child_exit_code':code,'watchdog_fired':watchdog,'supervisor_error':error,'observer_errors':observer_errors,'final_result_exists':(E/'process_result.json').exists(),'trading_child_alive':bool(proc and proc.poll() is None),'scope':'bounded foreground experiment; no claim host suspension/kill can be prevented'}
    (E/'supervisor_result.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2),flush=True)
    if receipt['final_result_exists']:print((E/'process_result.json').read_text(),flush=True)
    return 0 if code==0 and not watchdog and error is None and not observer_errors else 1

if __name__=='__main__':sys.exit(main())
