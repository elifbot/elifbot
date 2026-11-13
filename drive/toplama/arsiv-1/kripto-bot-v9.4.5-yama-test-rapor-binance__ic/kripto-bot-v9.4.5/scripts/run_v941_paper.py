"""Measured PAPER runner, composing the byte-identical v9.4 trading runtime."""
import asyncio,signal
from src.live_runner import DualVenueLiveRunner,parse_args
from src.config import load_config
from src.measurement_overlay import GateMeasurementOverlay


class MeasuredPaperRunner(DualVenueLiveRunner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.measurement=GateMeasurementOverlay(self.engine,self.risk.policy)

    def build_state_payload(self):
        state=super().build_state_payload()
        state['measurement_v941']=self.measurement.summary() if hasattr(self,'measurement') else {'status':'INITIALIZING'}
        state['trading_code_basis']='9.4.0 frozen rule files; 9.4.1 reporting overlay'
        return state


async def main():
    args=parse_args();cfg=load_config(args.config)
    if cfg['genel']['mod']!='paper':raise RuntimeError('Research measurement runner is PAPER ONLY')
    runner=MeasuredPaperRunner(cfg,duration_sec=args.duration_sec,max_drain_sec=args.max_drain_sec,
                              port=args.port,report_prefix=args.report_prefix,keep_panel_alive=args.keep_panel_alive)
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,setattr,runner,'stop_Flag',True)
    await runner.run()

if __name__=='__main__':asyncio.run(main())
