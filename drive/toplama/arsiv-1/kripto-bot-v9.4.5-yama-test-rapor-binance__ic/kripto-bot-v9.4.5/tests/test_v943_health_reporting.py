import json,os,time,sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.state_store import StateStore
from src.risk import Position
from src.health_reporting import ledger_health_snapshot,operational_health_snapshot,TABLES


def seed(store):
    pos=Position('BTC/USDT','LONG',100,1,99,leverage=10,margin_usdt=10,exchange='binance')
    store.prepare_paper_open('seed',{'symbol':pos.symbol})
    store.commit_paper_open('seed',pos,{'balance':999.9,'start_balance':1000.,'total_fees_usdt':.1,'total_funding_usdt':0.},
        {pos.symbol:{'position_id':'seed','entry_fee_usdt':.1,'funding_usdt':0.}}, {}, {pos.symbol:time.time()})
    assert store.verify_paper_ledger_integrity()['ok']
    return pos


def prepare(store,kind):
    if kind=='paper_intents':store.prepare_paper_open('op',{'symbol':'ETH/USDT'})
    elif kind=='paper_close_intents':store.prepare_paper_close('op','BTC/USDT',1)
    elif kind=='paper_funding_intents':store.prepare_paper_funding('op','BTC/USDT',{'delta':.1,'old_balance':999.9,'old_funding':0,'old_clock':1,'new_clock':2,'qty':1})
    else:store.prepare_paper_layer('op','BTC/USDT',{'original_qty':1,'requested_qty':1,'old_balance':999.9,'old_fee':.1})


@pytest.mark.parametrize('kind',TABLES)
def test_all_prepared_intents_registered_and_strict_recovery_unchanged(tmp_path,kind):
    st=StateStore(tmp_path/'s.db');seed(st);prepare(st,kind)
    assert st._health_pending_tokens[(kind,'op')][0]==os.getpid()
    assert st.verify_paper_ledger_integrity()=={'ok':False,'reason':'pending_intent:'+kind}
    before=None
    with st._conn() as c:before=list(c.iterdump())
    view=st.paper_ledger_health_snapshot()
    assert view['ok'] and view['status']=='IN_FLIGHT' and not view['reconciled']
    with st._conn() as c:assert list(c.iterdump())==before
    assert not st.verify_paper_ledger_integrity()['ok']


@pytest.mark.parametrize('kind',TABLES)
@pytest.mark.parametrize('age,ok',[(0,True),(14.999,True),(15.,False),(16.,False)])
def test_fifteen_second_boundary_for_all_journals(tmp_path,kind,age,ok):
    st=StateStore(tmp_path/'s.db');seed(st);prepare(st,kind)
    with st._conn() as c:c.execute('UPDATE '+kind+' SET created_at=1000 WHERE operation_id=\'op\'')
    st._health_pending_tokens[(kind,'op')]=(os.getpid(),500.)
    view=ledger_health_snapshot(st,now_s=1000+age,now_monotonic=500+age)
    assert view['ok']==ok
    if not ok:assert view['reason'].startswith('pending_timeout:')


@pytest.mark.parametrize('kind',TABLES)
def test_restart_or_foreign_store_cannot_claim_fresh_pending(tmp_path,kind):
    st=StateStore(tmp_path/'s.db');seed(st);prepare(st,kind)
    restarted=StateStore(tmp_path/'s.db')
    assert not restarted.verify_paper_ledger_integrity()['ok']
    view=restarted.paper_ledger_health_snapshot()
    assert not view['ok'] and view['reason']=='pending_unowned_or_restarted:'+kind


def test_first_ever_order_pending_has_valid_empty_committed_baseline(tmp_path):
    st=StateStore(tmp_path/'s.db');st.prepare_paper_open('op',{'symbol':'BTC/USDT'})
    assert st.paper_ledger_health_snapshot()['ok']
    assert not st.verify_paper_ledger_integrity()['ok']
    st.cancel_unfilled_paper_open('op','BTC/USDT')
    assert st.paper_ledger_health_snapshot()['status']=='RECONCILED'
    assert not st._health_pending_tokens


@pytest.mark.parametrize('corruption,reason', [('balance','cash_conservation_mismatch'),('total_fees_usdt','fee_mismatch'),('total_funding_usdt','funding_mismatch')])
def test_real_account_corruption_is_not_hidden_by_young_pending(tmp_path,corruption,reason):
    st=StateStore(tmp_path/'s.db');seed(st);prepare(st,'paper_close_intents')
    with st._conn() as c:
        acc=json.loads(c.execute("SELECT value FROM bot_meta WHERE key='paper_account'").fetchone()[0]);acc[corruption]+=1
        c.execute("UPDATE bot_meta SET value=? WHERE key='paper_account'",(json.dumps(acc),))
    view=st.paper_ledger_health_snapshot()
    assert not view['ok'] and reason in view['reason']
    engine=SimpleNamespace(_last_feed_ts=time.time(),executor=SimpleNamespace(positions={'BTC/USDT':None},state_store=st,circuit_breaker=None))
    op=operational_health_snapshot(engine)
    assert not op['healthy'] and any(reason in x for x in op['alarms'])
    assert not any('POSITION_SET_MISMATCH' in x for x in op['alarms'])


def test_true_position_set_mismatch_is_never_tolerated(tmp_path):
    st=StateStore(tmp_path/'s.db');seed(st);prepare(st,'paper_close_intents')
    e=SimpleNamespace(_last_feed_ts=time.time(),executor=SimpleNamespace(positions={},state_store=st,circuit_breaker=None))
    op=operational_health_snapshot(e)
    assert not op['healthy'] and any(x.startswith('POSITION_SET_MISMATCH') for x in op['alarms'])


def test_clock_rollback_or_other_pid_does_not_extend_grace(tmp_path):
    st=StateStore(tmp_path/'s.db');st.prepare_paper_open('op',{'symbol':'BTC/USDT'})
    st._health_pending_tokens[('paper_intents','op')]=(-1,time.monotonic())
    assert not st.paper_ledger_health_snapshot()['ok']
    st._health_pending_tokens[('paper_intents','op')]=(os.getpid(),time.monotonic()-16)
    assert 'pending_timeout' in st.paper_ledger_health_snapshot()['reason']


def test_unified_trading_and_strict_verifier_ast_unchanged():
    import ast
    root=Path(__file__).resolve().parents[1]
    before=root/'reports/v943_reference_sources'
    for name,excluded in [('src/unified_engine.py',{'operational_health_snapshot'}),('src/state_store.py',{'__init__','paper_ledger_health_snapshot','prepare_paper_open','prepare_paper_close','prepare_paper_funding','prepare_paper_layer'})]:
        old=ast.parse((before/name).read_text());new=ast.parse((root/name).read_text())
        olddefs={n.name:ast.dump(n,include_attributes=False) for cls in old.body if isinstance(cls,ast.ClassDef) for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name not in excluded}
        newdefs={n.name:ast.dump(n,include_attributes=False) for cls in new.body if isinstance(cls,ast.ClassDef) for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name not in excluded}
        assert olddefs==newdefs


def test_binance_endpoint_fields_do_not_overwrite_each_other():
    import asyncio
    from src.live_runner import DualVenueLiveRunner
    r=DualVenueLiveRunner.__new__(DualVenueLiveRunner)
    r.symbols=['BTC/USDT'];r.binance_pure_symbols={'BTC/USDT'};r.cfg={'v94':{'enabled':True}}
    r.venue_stats={'binance':{'endpoint':'see stream-specific endpoints'}}
    class Ctx:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def __aiter__(self):return self
        async def __anext__(self):r.stop_Flag=True;raise StopAsyncIteration
    class Session:
        def ws_connect(self,url,**kwargs):return Ctx()
    async def check():
        for suffix in ('aggTrade','bookTicker'):
            r.stop_Flag=False
            await r._binance_single_ws(Session(),suffix,suffix)
    asyncio.run(check())
    assert r.venue_stats['binance']['endpoint_aggTrade']=='fstream.binance.com/market'
    assert r.venue_stats['binance']['endpoint_bookTicker']=='fstream.binance.com/public'
    assert r.venue_stats['binance']['endpoint']=='see stream-specific endpoints'


def test_health_http_pending_grace_timeout_and_reason(tmp_path):
    import asyncio,aiohttp
    from src.live_runner import DualVenueLiveRunner
    from src.config import load_config
    async def check():
        r=DualVenueLiveRunner(load_config(),port=0,report_prefix=str(tmp_path/'http_health'))
        r.start_ts=time.time()-900
        def fresh():
            now=time.time();r.engine._last_feed_ts=now
            for z in r.venue_stats.values():z.update(last_ts=now,last_bbo_ts=now,last_trade_ts=now,ticks=1,bbo_updates=1)
        web=await r.start_web_server();port=web.addresses[0][1]
        try:
            async with aiohttp.ClientSession() as sess:
                async def get():
                    fresh()
                    async with sess.get(f'http://127.0.0.1:{port}/health') as resp:return resp.status,await resp.json()
                assert (await get())[0]==200
                r.store.prepare_paper_open('op',{'symbol':'BTC/USDT'})
                status,data=await get()
                assert status==200 and data['ledger_status']=='IN_FLIGHT' and not data['ledger_reconciled']
                assert not r.store.verify_paper_ledger_integrity()['ok']
                r.store._health_pending_tokens[('paper_intents','op')]=(os.getpid(),time.monotonic()-16)
                status,data=await get();assert status==503 and 'pending_timeout' in data['ledger_reason']
                assert 'reason=pending_timeout' in data['alarms'][0]
                r.store._health_pending_tokens.clear()
                status,data=await get();assert status==503 and 'pending_unowned' in data['ledger_reason']
                r.store.cancel_unfilled_paper_open('op','BTC/USDT')
                status,data=await get();assert status==200 and data['ledger_status']=='RECONCILED'
        finally:
            await web.cleanup();await r.broker.close()
    asyncio.run(check())


def test_prepare_and_init_only_add_observation_registry_assignments():
    import ast,copy
    root=Path(__file__).resolve().parents[1]
    old=ast.parse((root/'reports/v943_reference_sources/src/state_store.py').read_text())
    new=ast.parse((root/'src/state_store.py').read_text())
    def methods(tree):
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='StateStore')
        return {x.name:x for x in cls.body if isinstance(x,ast.FunctionDef)}
    before=methods(old);after=methods(new)
    names=['__init__','prepare_paper_open','prepare_paper_close','prepare_paper_funding','prepare_paper_layer']
    for name in names:
        method=copy.deepcopy(after[name])
        def observer(statement):
            if not isinstance(statement,ast.Assign):return False
            target=statement.targets[0]
            if isinstance(target,ast.Subscript):target=target.value
            return isinstance(target,ast.Attribute) and target.attr=='_health_pending_tokens'
        method.body=[s for s in method.body if not observer(s)]
        assert ast.dump(method,include_attributes=False)==ast.dump(before[name],include_attributes=False)
