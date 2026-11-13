"""35-second synthetic HTTP/HEALTHCHECK fixture, NOT a natural PAPER run."""
import asyncio,time,json
from pathlib import Path
from src.live_runner import DualVenueLiveRunner
from src.config import load_config


async def main():
    r=DualVenueLiveRunner(load_config(),port=8080,report_prefix='/evidence/healthcheck_fixture')
    r.phase='TEST_FIXTURE';r.start_ts=time.time()-120
    def fresh():
        now=time.time();r.engine._last_feed_ts=now
        for z in r.venue_stats.values():z.update(last_ts=now,last_bbo_ts=now,last_trade_ts=now,ticks=1,bbo_updates=1)
    fresh();web=await r.start_web_server()
    try:
        for _ in range(35):fresh();await asyncio.sleep(1)
        Path('/evidence/health_fixture_result.json').write_text(json.dumps({'synthetic':True,'natural_paper_run':False,'market_subscriptions':False,'duration_sec':35,'real_exchange_orders':False,'state':r.build_state_payload()},indent=2))
    finally:
        await web.cleanup();await r.broker.close()
        if hasattr(r.store,'close'):r.store.close()

asyncio.run(main())
