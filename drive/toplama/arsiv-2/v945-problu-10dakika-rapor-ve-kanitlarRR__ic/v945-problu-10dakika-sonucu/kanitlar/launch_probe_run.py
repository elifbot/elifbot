"""External diagnostic launcher: frozen production source is NOT edited."""
import asyncio,json,signal,time
from pathlib import Path
from src.live_runner import DualVenueLiveRunner
from src.config import load_config
import latency_probe_fixed
E=Path(__file__).resolve().parent
P=Path('/home/user/kripto-bot-v9.4.5')
class DiagnosticRunner(DualVenueLiveRunner):
    async def warmup_all(self,session):
        await super().warmup_all(session)
        self.diag_probe=latency_probe_fixed.start(self,E/'latency_probe.jsonl')
async def main():
    cfg=load_config(P/'configs/v9-canonical-production.json')
    assert cfg['genel']['mod']=='paper'
    assert not (E/'paper10m_state.db').exists(),'Fresh database required; do not restart over an existing run'
    runner=DiagnosticRunner(cfg,duration_sec=600,max_drain_sec=120,port=8080,report_prefix=str(E/'paper10m'),keep_panel_alive=False)
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,setattr,runner,'stop_Flag',True)
    receipt={'runner_exit_ok':False,'started_epoch':time.time()}
    try:
        summary=await runner.run();receipt.update(runner_exit_ok=True,phase=summary['phase'])
    except BaseException as exc:
        receipt['runner_exception']=repr(exc);raise
    finally:
        if hasattr(runner,'diag_probe'):receipt['probe']=await runner.diag_probe.close()
        else:receipt['probe']={'not_started':True}
        receipt['finished_epoch']=time.time();(E/'launcher_receipt.json').write_text(json.dumps(receipt,indent=2))
if __name__=='__main__':asyncio.run(main())
