"""Exercise the real run() loop with deterministic clock and isolated dummy IO."""
import asyncio
import json
import os, signal
from types import SimpleNamespace
import pytest
from src.live_runner import DualVenueLiveRunner


async def exercise(monkeypatch, tmp_path, mode):
    import src.live_runner as module
    r=DualVenueLiveRunner.__new__(DualVenueLiveRunner)
    r.duration_sec=0 if mode=='indefinite' else 4
    r.max_drain_sec=3;r.stop_Flag=False;r.keep_panel_alive=mode=='panel_stop'
    r.allow_new_entries=True;r.drain_elapsed_sec=0;r.phase='WARMUP'
    r.executor=SimpleNamespace(positions={'BTC':object()} if mode in ('drain_stop','drain_limit') else {})
    r.engine=SimpleNamespace(sync_closed_trade_feedback=lambda:None)
    r.summary_path=tmp_path/'summary.json'
    cleaned=[];r.store=SimpleNamespace(close=lambda:cleaned.append('store'))
    async def close():cleaned.append('broker')
    r.broker=SimpleNamespace(close=close)
    async def cleanup():cleaned.append('web')
    async def web():return SimpleNamespace(cleanup=cleanup)
    async def discover(session):return []
    async def warmup(session):pass
    async def block(*args):await asyncio.Event().wait()
    r.start_web_server=web;r.discover_full_pure_crypto_universe=discover;r.warmup_all=warmup
    for name in ['full_universe_bbo_and_scanner_loop','open_positions_fast_quote_loop','binance_ws_loop','okx_ws_loop','candle_refresh_loop']:
        setattr(r,name,block)
    async def strategy():
        if mode=='background_fail':raise ValueError('synthetic failure before per-symbol try')
        if mode=='background_return':return
        await block()
    r.strategy_eval_loop=strategy
    clock=[1000.];mono=[1000.];real_sleep=asyncio.sleep
    monkeypatch.setattr(module.time,'time',lambda:clock[0])
    monkeypatch.setattr(module,'monotonic',lambda:mono[0],raising=False)
    async def sleep(sec):
        clock[0]+=sec;mono[0]+=sec
        if r.phase=='ACTIVE' and mode=='mono_gap' and mono[0]-getattr(r,'start_monotonic',1005)<2:clock[0]+=10;mono[0]+=10
        if r.phase=='ACTIVE' and mode=='wall_jump' and mono[0]-getattr(r,'start_monotonic',1005)<2:clock[0]+=600
        if r.phase=='ACTIVE' and mode in ('early_stop','indefinite') and clock[0]-r.start_ts>=2:r.stop_Flag=True
        if r.phase=='DRAIN' and mode=='drain_stop':r.stop_Flag=True
        if r.phase=='COMPLETED' and mode=='panel_stop':r.stop_Flag=True
        if r.phase=='ACTIVE' and mode=='cancel':raise asyncio.CancelledError()
        if r.phase=='ACTIVE' and mode=='loop_exception':raise RuntimeError('synthetic foreground failure')
        if r.phase=='ACTIVE' and mode in ('sigterm','sigint') and clock[0]-r.start_ts>=2:
            os.kill(os.getpid(),signal.SIGTERM if mode=='sigterm' else signal.SIGINT)
            await real_sleep(.01)
        await real_sleep(0)
    monkeypatch.setattr(module.asyncio,'sleep',sleep)
    r.build_state_payload=lambda:{'phase':r.phase,'elapsed_sec':clock[0]-r.start_ts,'drain_elapsed_sec':r.drain_elapsed_sec,'closed_count':0,'open_positions':list(r.executor.positions),'gross_pnl':0,'net_pnl':0,'universe_counts':{'union_pure':0},'evaluation_telemetry':{'evaluation_calls_total':0,'retry_suppressed_total':0,'non_retry_evaluation_calls':0}}
    raised=None
    try:
        if mode in ('sigterm','sigint'):
            monkeypatch.setattr(module,'DualVenueLiveRunner',lambda *args,**kwargs:r)
            result=await module.async_main([])
        else:result=await r.run()
    except (asyncio.CancelledError,RuntimeError) as exc:raised=exc;result=json.loads(r.summary_path.read_text())
    assert sorted(cleaned)==['broker','store','web']
    assert result==json.loads(r.summary_path.read_text())
    return result,r,raised


@pytest.mark.parametrize('mode,expected',[('early_stop','INTERRUPTED'),('sigterm','INTERRUPTED'),('sigint','INTERRUPTED'),('indefinite','INTERRUPTED'),('normal','COMPLETED'),('drain_stop','INTERRUPTED'),('drain_limit','COMPLETED'),('panel_stop','COMPLETED'),('cancel','INTERRUPTED'),('loop_exception','FAILED'),('background_fail','FAILED'),('background_return','FAILED'),('mono_gap','DISCONTINUOUS'),('wall_jump','DISCONTINUOUS')])
def test_real_run_status(monkeypatch,tmp_path,caplog,mode,expected):
    caplog.set_level('INFO')
    result,r,raised=asyncio.run(exercise(monkeypatch,tmp_path,mode))
    assert result['phase']==expected
    if mode in ('early_stop','indefinite'):
        assert result['elapsed_sec']<4
        assert 'CANLI_TEST_TAMAMLANDI' not in caplog.text
        assert 'penceresi (4s) tamamlandı' not in caplog.text
    if mode=='drain_limit':assert len(r.executor.positions)==1 # no forced close
    if mode=='cancel':assert isinstance(raised,asyncio.CancelledError)
    if mode=='loop_exception':assert isinstance(raised,RuntimeError)
