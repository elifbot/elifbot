"""Supervisor for ONE approved paper run. No order APIs or credentials.

The source watchdog disables only the opt-in source; it never kills V4. The
supervisor terminates the *experiment* only for independent global clock,
heartbeat or overall-timeout faults, with graceful SIGTERM and a final result.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'gozlem'))
from saat_kontrolu import sample
from saat_guard import ClockDiscontinuityGuard

ROOT=Path(os.environ.get('V78_RUN_DIR', str(Path(__file__).resolve().parent/'aday'))).resolve()
LOG=ROOT/'logs';LOG.mkdir(exist_ok=True)
status=LOG/'ws_durum.json';logfile=LOG/'supervisor.jsonl'


def append(record):
    with logfile.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')

def run():
    clock=sample();append({'event':'clock_preflight','sample':clock})
    if not clock.get('ok'):
        print('CLOCK_PREFLIGHT_FAILED',flush=True);return 1
    if status.exists():raise RuntimeError('status file already exists: run must start in a fresh directory')
    cmd=[sys.executable,'-u','ws_bot.py','--eski-v78-paper','--v78-v4-akis-onsecim','--supertrend-paper','--sure-dk','5','--sembol-limit','0',
         '--strateji','momentum','--binance-hacim-kaynagi','aggtrade',
         '--sinyal-zenginlestirme','--giris-teyit','--kar-kilidi',
         '--indikator-hazirlik-zamanasimi-dk','5']
    # Retain only basic OS environment. No account/API variables are passed.
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL','TZ','SSL_CERT_FILE','SSL_CERT_DIR')}
    env['PYTHONUNBUFFERED']='1'
    (ROOT/'PAPER_KOMUT.json').write_text(json.dumps({'argv':cmd,'duration_min_after_ready':5,
        'readiness_timeout_min':5,'whole_run_cap_sec':900,'symbol_limit_per_exchange':0,
        'env_allowlist':sorted(env),'note':'real public data; paper portfolio only; no keys/orders'},indent=2,ensure_ascii=False))
    started=time.monotonic();guard=ClockDiscontinuityGuard();last_hb=started;last_stamp=None
    next_sample=started+60;last_emit=started;source_stop=None;trend_stop=None;reason=None;view={}
    with (LOG/'paper_stdout.log').open('w',buffering=1,encoding='utf8') as stdout:
        proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=subprocess.STDOUT)
        append({'event':'start','pid':proc.pid,'at_wall':time.time(),'at_mono':started})
        print(f'PAPER_STARTED pid={proc.pid}',flush=True)
        try:
            while True:
                now=time.monotonic()
                if not guard.check():reason='clock_discontinuity';break
                if proc.poll() is not None:reason='bot_exited';break
                if now-started>900:reason='overall_timeout_900s';break
                if status.exists():
                    try:
                        view=json.loads(status.read_text(encoding='utf8'))
                        if view.get('pid')!=proc.pid:reason='status_pid_mismatch';break
                        stamp=view.get('son_heartbeat_utc')
                        if stamp and stamp!=last_stamp:last_stamp=stamp;last_hb=now
                        if now-last_hb>30:reason='heartbeat_stale_30s';break
                        source=view.get('eski_v78_paper') or {}
                        if source.get('watchdog_stopped') and source_stop is None:
                            source_stop={'detected_mono':now,'stop_reason':source.get('stop_reason'),
                                         'stage':source.get('watchdog_stage'),'last_error':source.get('last_error')}
                            append({'event':'new_source_stopped_v4_continues',**source_stop})
                            print('NEW_SOURCE_STOPPED V4_CONTINUES '+json.dumps(source_stop,ensure_ascii=False),flush=True)
                        trend=view.get('supertrend_paper') or {}
                        if trend.get('watchdog_stopped') and trend_stop is None:
                            trend_stop={'detected_mono':now,'stage':trend.get('watchdog_stage'),
                                        'counts':trend.get('counts'),'stop_reason':trend.get('stop_reason'),'last_error':trend.get('last_error')}
                            append({'event':'supertrend_source_stopped_v4_continues',**trend_stop})
                            print('SUPERTREND_SOURCE_STOPPED V4_CONTINUES '+json.dumps(trend_stop,ensure_ascii=False),flush=True)
                    except (OSError,ValueError,TypeError):pass
                elif now-started>30:reason='heartbeat_missing_30s';break
                if now>=next_sample:
                    c=sample();append({'event':'clock_sample','sample':c})
                    if not c.get('ok'):reason='clock_health_failed';break
                    next_sample=now+60
                if now-last_emit>=30:
                    source=view.get('eski_v78_paper') or {};counts=source.get('counts') or {}
                    row={'event':'status','phase':view.get('asama'),'elapsed_scan_sec':view.get('sure_sn'),
                         'candidate_count_v4':counts.get('source_v4_candidate_dispatch_attempt',0),
                         'candidate_count_v78':counts.get('source_v78_candidate_dispatch_attempt',0),
                         'candidate_count_supertrend':counts.get('source_supertrend_candidate_dispatch_attempt',0),
                         'supertrend_evaluated':(view.get('supertrend_paper',{}).get('counts') or {}).get('evaluated',0),
                         'new_source_active':source.get('active'),'clock_elapsed_s':round(now-started,2)}
                    append(row);print('PAPER_STATUS '+json.dumps(row,ensure_ascii=False),flush=True);last_emit=now
                time.sleep(.5)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=5)
                    append({'event':'forced_kill','note':'portfolio closure may be uncertain'})
            exitcode=proc.returncode
            try:view=json.loads(status.read_text(encoding='utf8'))
            except (OSError,ValueError):pass
            result={'reason':reason,'bot_exit_code':exitcode,'elapsed_monotonic_s':time.monotonic()-started,
                    'clock_guard':guard.status(),'new_source_stop':source_stop,'supertrend_source_stop':trend_stop,
                    'last_phase':view.get('asama'),'last_scan_elapsed_sec':view.get('sure_sn'),
                    'scan_started_utc':view.get('tarama_baslangic_utc'),
                    'note':'watchdog stops source only; global safety faults may stop the whole experiment'}
            (LOG/'supervisor_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            append({'event':'supervisor_finished',**result})
            print('SUPERVISOR_FINISHED '+json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if reason=='bot_exited' and exitcode==0 else 1

def main(argv=None):
    parser=argparse.ArgumentParser(description='Five-minute paper supervisor')
    parser.add_argument('--preflight-only', action='store_true',
                        help='Only sample the clock; never launch the bot')
    args=parser.parse_args(argv)
    if args.preflight_only:
        clock=sample()
        print(json.dumps(clock,ensure_ascii=False),flush=True)
        return 0 if clock.get('ok') else 1
    return run()

if __name__=='__main__':sys.exit(main())
