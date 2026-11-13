"""Read-only health policy. Never authorizes a financial operation or recovery.

Only this StateStore instance's process-local, newly prepared intents have a
bounded 15s reporting grace. The production ledger is NEVER edited by this view.
Strict recovery validation is run unchanged on an in-memory SQLite snapshot;
only eligible intents are hidden in that disposable copy, to validate the
committed account/fees/funding/positions independently of outstanding work.
"""
from __future__ import annotations
from contextlib import contextmanager
import math
import os
import sqlite3
import time

PENDING_HEALTH_GRACE_SEC = 15.0
TABLES = ('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents')


def ledger_health_snapshot(store, *, now_s=None, now_monotonic=None):
    now = time.time() if now_s is None else float(now_s)
    mono = time.monotonic() if now_monotonic is None else float(now_monotonic)
    snapshot = sqlite3.connect(':memory:')
    snapshot.row_factory = sqlite3.Row
    try:
        # No production transaction, row, timestamp, status, or account is changed.
        source = sqlite3.connect(store.db_path.resolve().as_uri()+'?mode=ro', uri=True)
        try:
            source.backup(snapshot)
        finally:
            source.close()
        positions = sorted(row['symbol'] for row in snapshot.execute('SELECT symbol FROM open_positions'))
        tokens = getattr(store, '_health_pending_tokens', {})
        pending=[]; errors=[]; current=set()
        for table in TABLES:
            for row in snapshot.execute('SELECT operation_id,created_at FROM '+table+" WHERE status='PENDING'").fetchall():
                key=(table,row['operation_id']);current.add(key);token=tokens.get(key)
                created=row['created_at']
                valid=isinstance(created,(float,int)) and math.isfinite(created) and 0<created<=now+0.5
                wall_age=max(0.,now-created) if valid else None
                owned=bool(token and token[0]==os.getpid())
                local_age=mono-token[1] if owned else None
                time_ok=valid and owned and math.isfinite(local_age) and local_age>=0
                age=max(wall_age,local_age) if time_ok else wall_age
                eligible=bool(time_ok and age<PENDING_HEALTH_GRACE_SEC)
                if not valid:reason='pending_timestamp_invalid:'+table
                elif not owned:reason='pending_unowned_or_restarted:'+table
                elif not time_ok:reason='pending_clock_invalid:'+table
                elif not eligible:reason=f'pending_timeout:{table}(age={age:.3f}s,limit=15s)'
                else:reason='pending_in_flight:'+table
                pending.append({'table':table,'operation_id':row['operation_id'],'owned_by_this_process':owned,
                                'age_sec':age,'health_grace_eligible':eligible,'reason':reason})
                if eligible:
                    # This DELETE affects only :memory:, never the production database.
                    snapshot.execute('DELETE FROM '+table+' WHERE operation_id=?',(row['operation_id'],))
                else:errors.append(reason)
        # Bound observation memory; never delete durable journals or recovery locks.
        for key in list(tokens):
            if key not in current:tokens.pop(key,None)
        from .state_store import StateStore
        check=StateStore.__new__(StateStore)
        @contextmanager
        def use_snapshot():
            yield snapshot
        check._conn=use_snapshot
        committed=check.verify_paper_ledger_integrity()  # unchanged fail-closed verifier
        ok=bool(committed.get('ok',False)) and not errors
        reason=errors[0] if errors else (('pending_in_flight' if pending else committed.get('reason','ok')) if ok else committed.get('reason','unknown_ledger_failure'))
        return {'ok':ok,'reconciled':ok and not pending,'status':('IN_FLIGHT' if pending else 'RECONCILED') if ok else 'DEGRADED',
                'reason':reason,'pending_operations':pending,'db_positions':positions,'committed_ledger_check':committed,
                'pending_health_grace_sec':PENDING_HEALTH_GRACE_SEC}
    except Exception as exc:
        return {'ok':False,'reconciled':False,'status':'DEGRADED','reason':'ledger_health_exception:'+type(exc).__name__,
                'pending_operations':[],'db_positions':[]}
    finally:
        snapshot.close()


def operational_health_snapshot(engine, *, max_feed_lag_sec=20.0):
    now=time.time();lag=max(0.,now-float(engine._last_feed_ts or now))
    mem=set(getattr(engine.executor,'positions',{}));store=getattr(engine.executor,'state_store',None)
    ledger={'ok':True,'reconciled':True,'status':'NOT_CONFIGURED','reason':'no_store','pending_operations':[],'db_positions':sorted(mem)}
    if store is not None and hasattr(store,'load_positions'):
        try:
            if hasattr(store,'paper_ledger_health_snapshot'):
                ledger=store.paper_ledger_health_snapshot()
            else:
                strict=store.verify_paper_ledger_integrity() if hasattr(store,'verify_paper_ledger_integrity') else {'ok':True}
                ledger={'ok':bool(strict.get('ok',False)),'reconciled':bool(strict.get('ok',False)),
                        'status':'RECONCILED' if strict.get('ok') else 'DEGRADED','reason':strict.get('reason','ok'),
                        'pending_operations':[],'db_positions':sorted((store.load_positions() or {}).keys())}
        except Exception as exc:
            ledger={**ledger,'ok':False,'reconciled':False,'status':'DEGRADED','reason':'ledger_health_exception:'+type(exc).__name__}
    db=set(ledger['db_positions']);alarms=[];warnings=[]
    if lag>max_feed_lag_sec:alarms.append(f'FEED_LATENCY_ALARM({lag:.1f}s>{max_feed_lag_sec:.1f}s)')
    if mem!=db:alarms.append(f'POSITION_SET_MISMATCH(mem={sorted(mem)},db={sorted(db)})')
    if not ledger['ok']:alarms.append('LEDGER_INTEGRITY_ERROR(reason='+str(ledger['reason'])+')')
    if ledger['ok'] and ledger['status']=='IN_FLIGHT':warnings.append('PENDING_IN_FLIGHT_WITHIN_15S_HEALTH_GRACE')
    cb=getattr(engine.executor,'circuit_breaker',None)
    if cb is not None and getattr(cb,'tripped',False):alarms.append(f'CIRCUIT_BREAKER_TRIPPED({getattr(cb,"reason","")})')
    return {'healthy':not alarms,'feed_lag_sec':round(lag,2),'ledger_reconciled':bool(mem==db and ledger['reconciled']),
            'ledger_status':ledger['status'] if mem==db else 'DEGRADED','ledger_reason':ledger['reason'],
            'committed_ledger_valid':bool(ledger['ok']),'pending_operations':ledger['pending_operations'],
            'memory_open_count':len(mem),'sqlite_open_count':len(db),'alarms':alarms,'warnings':warnings}
