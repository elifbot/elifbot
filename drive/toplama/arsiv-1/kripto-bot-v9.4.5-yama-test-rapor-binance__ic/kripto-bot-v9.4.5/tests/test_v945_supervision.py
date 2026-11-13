import asyncio,time
from types import SimpleNamespace
import aiohttp,pytest
from src.runtime_supervision import RuntimeSupervision
from src.live_runner import DualVenueLiveRunner
from src.config import load_config


@pytest.mark.parametrize('kind',['exception','return','cancel'])
def test_every_unexpected_task_exit_is_fatal(kind):
    async def run():
        actions=[];m=RuntimeSupervision(on_fatal=lambda:actions.append('stop_new_entries'));m.activate()
        async def job():
            if kind=='exception':raise ValueError('synthetic')
            if kind=='cancel':raise asyncio.CancelledError()
        task=asyncio.create_task(job());m.add_task('strategy_eval',task);await asyncio.sleep(0);await asyncio.sleep(0)
        assert 'strategy_eval' in m.snapshot()['task_failures']
        with pytest.raises(RuntimeError,match='BACKGROUND_TASK_FAILED'):m.check_tasks()
        assert actions==['stop_new_entries']
    asyncio.run(run())


def test_planned_shutdown_is_not_a_task_failure():
    async def run():
        m=RuntimeSupervision();m.activate()
        task=asyncio.create_task(asyncio.sleep(100));m.add_task('strategy_eval',task);m.shutting_down=True;task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert not m.snapshot()['task_failures']
    asyncio.run(run())


def test_stalls_are_not_confused_with_no_trade_signals():
    clock=[0.];m=RuntimeSupervision(clock=lambda:clock[0]);m.activate()
    clock[0]=31;m.last_cycle=31
    assert m.snapshot()['alarms']==['EVALUATION_CALLS_STALLED']
    m.progress(10);assert m.snapshot()['healthy'] # ten HOLD/retry evaluations are still progress
    clock[0]=47;m.progress(11)
    assert m.snapshot()['alarms']==['STRATEGY_CYCLE_HEARTBEAT_STALE']


@pytest.mark.parametrize('mono,wall,expected',[(1.,1.,0),(6.,6.,1),(1.,601.,1),(1.,-100.,1)])
def test_suspend_and_wall_clock_jump_are_recorded(mono,wall,expected):
    a=[0.];b=[0.];m=RuntimeSupervision(clock=lambda:a[0],wall=lambda:b[0]);m.activate();a[0]=mono;b[0]=wall
    m.sleep_observed(1,0,0)
    assert m.snapshot()['gap_count']==expected
    assert m.snapshot()['continuity_ok']==(expected==0)


@pytest.mark.parametrize('case',['dead_task','counter_stall','heartbeat_stall','gap'])
def test_real_health_http_fails_despite_fresh_feeds(tmp_path,case):
    async def run():
        r=DualVenueLiveRunner(load_config(),port=0,report_prefix=str(tmp_path/case));r.start_ts=time.time()-900;r.phase='ACTIVE'
        clock=[0.];m=RuntimeSupervision(clock=lambda:clock[0]);r.runtime_supervision=m;m.activate()
        if case=='dead_task':
            async def fail():raise RuntimeError('leader preamble failure')
            task=asyncio.create_task(fail());m.add_task('strategy_eval',task);await asyncio.sleep(0)
        elif case=='counter_stall':clock[0]=31;m.last_cycle=31
        elif case=='heartbeat_stall':clock[0]=16;m.progress(1)
        else:clock[0]=6;m.sleep_observed(1,0,0)
        now=time.time();r.engine._last_feed_ts=now
        for z in r.venue_stats.values():z.update(last_ts=now,last_bbo_ts=now,last_trade_ts=now,ticks=1,bbo_updates=1)
        web=await r.start_web_server();port=web.addresses[0][1]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f'http://127.0.0.1:{port}/health') as response:
                    body=await response.json();assert response.status==503
                    assert body['binance_healthy'] and body['okx_healthy'] and body['ledger_reconciled']
                    assert body['runtime_supervision']['alarms']
        finally:m.shutting_down=True;await web.cleanup();await r.broker.close()
    asyncio.run(run())


def test_lease_error_is_not_swallowed():
    r=DualVenueLiveRunner.__new__(DualVenueLiveRunner);r.stop_Flag=False
    def broken(*a,**k):raise OSError('synthetic lease failure')
    r.store=SimpleNamespace(acquire_writer_lease=broken)
    with pytest.raises(RuntimeError,match='WRITER_LEASE_RENEWAL_FAILED'):asyncio.run(r.strategy_eval_loop())
