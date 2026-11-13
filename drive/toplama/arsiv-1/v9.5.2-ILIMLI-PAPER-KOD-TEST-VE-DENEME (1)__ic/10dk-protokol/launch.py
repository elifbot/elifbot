"""Fresh v952 PAPER only; verified mail required, no log truncation or old-session resume."""
import asyncio,hashlib,json,logging,signal,sys,time,os
from pathlib import Path
E=Path(__file__).resolve().parent;B=E.parent/'kripto-bot-v9.5.2-paper-rc1';sys.path.insert(0,str(B))
from src.config import load_config
from src.live_runner import DualVenueLiveRunner
from scripts.verify_release import verify

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    receipt=json.loads((E/'mail_before_run_receipt.json').read_text())
    assert receipt['gmail_sent_verified'] and receipt['attachments_match'] and receipt['to']=='omeracar56@gmail.com'
    pkg=E.parent/receipt['attachment_filename'];assert digest(pkg)==receipt['attachment_sha256'] and pkg.stat().st_size==receipt['attachment_bytes']
    assert verify()['ok']
    plan=json.loads((E/'plan.json').read_text())
    for name,h in plan['external_diagnostic_sha256'].items():assert digest(E/name)==h,name
    assert not list(E.glob('natural10m_mild_*')),'Consumed prefix; choose a NEW session directory and prefix'
    # Reserve the attempt BEFORE opening a log; neither can overwrite previous evidence.
    (E/'launch_attempt.lock').open('x').close()
    with (E/'run.console.log').open('x',buffering=1) as console:
        os.dup2(console.fileno(),1);os.dup2(console.fileno(),2)
        logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s',force=True)
        asyncio.run(run(receipt,plan))

async def run(receipt,plan):
    cfg=load_config();assert cfg['genel']['mod']=='paper'
    assert not any(v for k,v in cfg['api'].items() if k!='dashboard_token')
    runner=DualVenueLiveRunner(cfg,duration_sec=600,max_drain_sec=120,port=8080,reports_dir=E,report_prefix='natural10m_mild',keep_panel_alive=False)
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try:loop.add_signal_handler(sig,setattr,runner,'stop_Flag',True)
        except NotImplementedError:pass
    start=time.time();(E/'started.json').write_text(json.dumps({'epoch':start,'paper_only':True,'release':'9.5.2-paper-rc1','gmail_sent_message_id':receipt['message_id'],'new_db':str(runner.db_path),'active_sec':600,'drain_max_sec':120,'plan_created_utc':plan['created_utc']},indent=2))
    try:result=await runner.run()
    except BaseException as exc:
        (E/'process_result.json').write_text(json.dumps({'started_epoch':start,'ended_epoch':time.time(),'error':type(exc).__name__,'paper_only':True},indent=2));raise
    summary={'started_epoch':start,'ended_epoch':time.time(),'phase':result.get('phase'),'completion':result.get('run_completion'),'position_lifecycle':result.get('position_lifecycle'),'open_positions':len(result.get('open_positions',[])),'closed_count':result.get('closed_count'),'signal_profile':result.get('signal_profile'),'profile_comparison':result.get('profile_comparison'),'paper_only':True,'external_llm_calls':0,'sealed_files_unchanged':verify()['ok'],'diagnostics_unchanged':all(digest(E/name)==h for name,h in plan['external_diagnostic_sha256'].items())}
    (E/'process_result.json').write_text(json.dumps(summary,indent=2))

if __name__=='__main__':main()
