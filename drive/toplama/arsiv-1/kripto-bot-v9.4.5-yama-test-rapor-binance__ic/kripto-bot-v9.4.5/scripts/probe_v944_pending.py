"""Synthetic local HTTP probe. No market subscriptions and no exchange orders.

Every Runner gets its own disposable fixture DB. Ages/accounts/feed timestamps
are intentionally injected ONLY into those fixture DBs/objects, never a live run.
"""
import asyncio,json,os,time,tempfile
from pathlib import Path
from types import SimpleNamespace
import aiohttp
from src.live_runner import DualVenueLiveRunner
from src.config import load_config
from src.risk import Position
from src.health_reporting import TABLES


async def run_probe(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    samples=[]
    for table in TABLES:
        r=DualVenueLiveRunner(load_config(),port=0,report_prefix=str((directory/table).resolve()))
        r.start_ts=time.time()-900
        st=r.store
        pos=Position('BTC/USDT','LONG',100,1,99,leverage=10,margin_usdt=10,exchange='binance')
        st.prepare_paper_open('fixture-seed',{'symbol':pos.symbol})
        st.commit_paper_open('fixture-seed',pos,{'balance':999.9,'start_balance':1000.,'total_fees_usdt':.1,'total_funding_usdt':0.},
            {pos.symbol:{'position_id':'fixture-seed','entry_fee_usdt':.1,'funding_usdt':0.}}, {}, {pos.symbol:time.time()})
        r.executor.positions[pos.symbol]=pos
        r.engine.metrics['signals_evaluated']=4972
        r.engine.v94_router=SimpleNamespace(rejections={'ONE_ATTEMPT_PER_CLOSED_BAR':4596,'CLOSED_HTF_DISAGREEMENT':29})
        web=await r.start_web_server();port=web.addresses[0][1]
        try:
            async with aiohttp.ClientSession() as sess:
                async def get(case,expected,*,stale=False):
                    now=time.time();r.engine._last_feed_ts=now
                    for z in r.venue_stats.values():z.update(last_ts=now,last_bbo_ts=now,last_trade_ts=now,ticks=1,bbo_updates=1)
                    if stale:r.venue_stats['okx']['last_trade_ts']=now-120
                    with st._conn() as c:before=list(c.iterdump())
                    async with sess.get(f'http://127.0.0.1:{port}/health') as resp:
                        code=resp.status;body=await resp.json()
                    with st._conn() as c:after=list(c.iterdump())
                    row={'table':table,'case':case,'http_status':code,'body':body,'durable_db_unchanged_by_health':before==after,'synthetic':True}
                    samples.append(row)
                    assert code==expected,row
                    assert before==after,row
                    return body
                await get('committed_baseline',200)
                stale=await get('trade_tape_stale',503,stale=True)
                assert 'OKX_TRADE_TAPE_STALE' in stale['alarms']
                await get('feed_recovered',200)
                op='fixture-'+table
                if table=='paper_intents':st.prepare_paper_open(op,{'symbol':'ETH/USDT'})
                elif table=='paper_close_intents':st.prepare_paper_close(op,'BTC/USDT',1)
                elif table=='paper_funding_intents':st.prepare_paper_funding(op,'BTC/USDT',{'delta':.1,'old_balance':999.9,'old_funding':0,'old_clock':1,'new_clock':2,'qty':1})
                else:st.prepare_paper_layer(op,'BTC/USDT',{'original_qty':1,'requested_qty':1,'old_balance':999.9,'old_fee':.1})
                body=await get('young_owned_pending',200)
                assert body['ledger_status']=='IN_FLIGHT' and body['ledger_reconciled'] is False
                assert any(p['operation_id']==op and p['table']==table and p['owned_by_this_process'] and p['age_sec']<15 for p in body['pending_operations'])
                assert not st.verify_paper_ledger_integrity()['ok']
                async with sess.get(f'http://127.0.0.1:{port}/api/state') as resp:
                    state=await resp.json();assert resp.status==200
                assert state['evaluation_telemetry']['evaluation_calls_total']==4972
                assert state['evaluation_telemetry']['retry_suppressed_total']==4596
                assert state['evaluation_telemetry']['non_retry_evaluation_calls']==376
                st._health_pending_tokens[(table,op)]=(os.getpid(),time.monotonic()-16)
                expired=await get('pending_timeout',503)
                assert 'pending_timeout' in expired['ledger_reason']
                st._health_pending_tokens.clear()
                unowned=await get('pending_unowned',503)
                assert 'pending_unowned' in unowned['ledger_reason']
                st._health_pending_tokens[(table,op)]=(os.getpid(),time.monotonic())
                with st._conn() as c:
                    original=c.execute("SELECT value FROM bot_meta WHERE key='paper_account'").fetchone()[0]
                    account=json.loads(original);account['balance']+=1
                    c.execute("UPDATE bot_meta SET value=? WHERE key='paper_account'",(json.dumps(account),))
                corrupt=await get('cash_corruption_not_hidden',503)
                assert 'cash_conservation_mismatch' in corrupt['ledger_reason']
                with st._conn() as c:c.execute("UPDATE bot_meta SET value=? WHERE key='paper_account'",(original,))
                await get('pending_restored',200)
                if table=='paper_intents':
                    st.cancel_unfilled_paper_open(op,'ETH/USDT')
                    after=await get('explicit_unfilled_cancel',200)
                    assert after['ledger_status']=='RECONCILED'
                    assert st.verify_paper_ledger_integrity()['ok']
        finally:
            await web.cleanup();await r.broker.close()
            if hasattr(st,'close'):st.close()
    report={'scope':'isolated synthetic HTTP; not natural live PENDING or exchange fills','http_samples':len(samples),'young_owned_pending_200_cases':sum(x['case']=='young_owned_pending' for x in samples),'all_health_requests_durable_db_unchanged':all(x['durable_db_unchanged_by_health'] for x in samples),'controlled_pending_http_verified':True,'pending_in_flight_observed_live':False,'natural_entry_fill_or_close_observed':False,'real_money_approved':False}
    (directory/'http_samples.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in samples)+'\n')
    (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    print(json.dumps(asyncio.run(run_probe(args.output)),ensure_ascii=False,indent=2))
