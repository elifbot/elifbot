import asyncio,json
from types import SimpleNamespace
import pytest
from latency_probe_fixed import Probe,start

def runner():return SimpleNamespace(stop_Flag=False,allow_new_entries=True,phase='TEST',executor=SimpleNamespace(positions={}))
def test_sync_result_and_restore(tmp_path):
    p=Probe(runner(),tmp_path/'x');o=SimpleNamespace(f=lambda x:x+1);original=o.f;p.wrap(o,'f');assert o.f(1)==2;assert p.agg['f']['n']==1;p.restore();assert o.f is original

def test_exception_identity_preserved(tmp_path):
    p=Probe(runner(),tmp_path/'x');exc=ValueError('sentinel')
    def fail():raise exc
    o=SimpleNamespace(f=fail);p.wrap(o,'f')
    with pytest.raises(ValueError) as caught:o.f()
    assert caught.value is exc and p.agg['f']['n']==1

def test_async_return_and_cancellation(tmp_path):
    async def scenario():
        p=Probe(runner(),tmp_path/'x')
        async def f():return 7
        async def wait():await asyncio.sleep(10)
        o=SimpleNamespace(f=f,wait=wait);p.wrap(o,'f');p.wrap(o,'wait');assert await o.f()==7
        t=asyncio.create_task(o.wait());await asyncio.sleep(0);t.cancel()
        with pytest.raises(asyncio.CancelledError):await t
        assert p.agg['wait']['n']==1
    asyncio.run(scenario())

def test_double_wrap_refused(tmp_path):
    p=Probe(runner(),tmp_path/'x');o=SimpleNamespace(f=lambda:None);p.wrap(o,'f')
    with pytest.raises(RuntimeError):p.wrap(o,'f')
    o.f();assert p.agg['f']['n']==1

def test_final_flush_subsecond(tmp_path):
    async def scenario():
        r=runner();p=Probe(r,tmp_path/'nested'/'x',period=.01).launch();o=SimpleNamespace(f=lambda:2);p.wrap(o,'f');o.f();await asyncio.sleep(.03);r.stop_Flag=True;await p.task;await p.close()
        rows=[json.loads(x) for x in p.path.read_text().splitlines()];assert rows[-1]['final'] and rows[-1]['stats']['f']['n']==1 and rows[-1]['window_elapsed_ms']>0
    asyncio.run(scenario())

def test_immediate_close_flushes(tmp_path):
    async def scenario():
        p=Probe(runner(),tmp_path/'x').launch();o=SimpleNamespace(f=lambda:2);p.wrap(o,'f');o.f();await p.close();rows=[json.loads(x) for x in p.path.read_text().splitlines()];assert rows[-1]['final'] and rows[-1]['stats']['f']['n']==1
    asyncio.run(scenario())

def test_path_error_is_immediate(tmp_path):
    r=runner();p=Probe(r,tmp_path)
    with pytest.raises(IsADirectoryError):p.launch()

def test_task_failure_sets_stop(tmp_path):
    async def scenario():
        r=runner();p=Probe(r,tmp_path/'x',period=.001,flush_sec=.001)
        def fail(*a,**k):raise OSError('test disk error')
        p.flush=fail;p.launch();await asyncio.sleep(.03);assert p.task.done() and p.failed and r.stop_Flag and not r.allow_new_entries;await p.close()
    asyncio.run(scenario())

def test_class_method_restore_keeps_descriptor(tmp_path):
    class X:
        def f(self,x):return x+1
    o=X();p=Probe(runner(),tmp_path/'x');p.wrap(o,'f');assert o.f(2)==3;p.restore();assert 'f' not in o.__dict__ and o.f(3)==4

def test_distinct_probe_buckets(tmp_path):
    p=Probe(runner(),tmp_path/'a');q=Probe(runner(),tmp_path/'b');a=SimpleNamespace(f=lambda:0);b=SimpleNamespace(f=lambda:0);p.wrap(a,'f');q.wrap(b,'f');a.f();assert p.agg['f']['n']==1 and not q.agg

def test_start_idempotent_and_unwrap(tmp_path):
    async def scenario():
        class Ex:
            positions={}
            async def on_price_tick(self,*a,**k):return None
        class En:
            async def on_trade(self,*a,**k):return None
            async def evaluate_and_route(self,*a,**k):return None
        r=runner();r.executor=Ex();r.engine=En()
        p=start(r,tmp_path/'x');assert start(r,tmp_path/'x') is p
        await r.executor.on_price_tick('X',1);assert p.agg['on_price_tick']['n']==1
        await p.close();assert 'on_price_tick' not in r.executor.__dict__
    asyncio.run(scenario())
