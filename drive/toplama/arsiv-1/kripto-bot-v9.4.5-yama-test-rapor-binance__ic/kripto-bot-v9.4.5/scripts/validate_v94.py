"""Freeze first, then open the sealed, non-overlapping historical validation block.
No selection or retuning is permitted from validation outcomes.
"""
from dataclasses import asdict
from pathlib import Path
import gzip,hashlib,json,time
import pandas as pd
from src.adaptive_policy import AdaptivePolicy
from backtests.chronological_portfolio import ChronologicalPortfolioEngine

ROOT=Path(__file__).resolve().parent.parent
R=ROOT/'reports';FREEZE=R/'v94_freeze_manifest.json'


def tracked():
    return [p for folder in ('src','scanner','portfolio','backtests','strategies','scripts','tests','configs')
        for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json')]+[ROOT/'pyproject.toml',ROOT/'requirements.txt']


def freeze():
    if FREEZE.exists():raise RuntimeError('Already frozen. Do not overwrite an existing validation freeze.')
    metadata=json.loads((R/'v94_sealed_data_metadata.json').read_text())
    config=json.loads((ROOT/'configs/v9-canonical-production.json').read_text())
    payload={'edition':'9.4.1', 'frozen_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'params_frozen':True,
        'selected_policy':config['v94']['policy'],'sealed_data':metadata,
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked()},
        'development_report_sha256':hashlib.sha256((R/'v94_development_results.json').read_bytes()).hexdigest(),
        'test_design':'Unseen retrospective historical block; not prospective chronological OOS. Last 4200 bars after 600 warmup.',
        'promotion_criteria':'No automatic real-money approval. Negative net, negative stress, low sample or data issues => reject.'}
    prior=R/'v94_0_interrupted/v94_freeze_manifest.json'
    if prior.exists():
        old=json.loads(prior.read_text())
        invariant=['src/v94_core.py','src/adaptive_policy.py','src/v94_live_risk.py','src/v94_live_router.py','src/risk.py','src/flow_exit_manager.py','src/executor.py','src/unified_engine.py','src/live_runner.py','backtests/chronological_portfolio.py','strategies/v93_flow_strategy.py','src/strategy.py','strategies/base.py']
        for name in invariant:
            if payload['source_sha256'][name]!=old['source_sha256'][name]:
                raise RuntimeError('Measurement-only amendment changed a decision/risk/replay rule: '+name)
        if payload['selected_policy']!=old['selected_policy']:raise RuntimeError('Policy changed in measurement-only amendment')
        payload['source_equality_proof']={name:{'v94_0_sha256':old['source_sha256'][name],'v94_1_sha256':payload['source_sha256'][name],'identical':True} for name in invariant}
        payload['measurement_only_amendment']={'prior_manifest_sha256':hashlib.sha256(prior.read_bytes()).hexdigest(),
            'decision_risk_replay_source_unchanged':invariant,'reason':'Prior run interrupted before any complete result. Add matured denominators, per-side gate audit and cost-scenario labels; no policy changes.'}
    from src.gate_statistics import DEFAULT_CRITERIA
    criteria=json.loads((ROOT/'configs/v941_validation_criteria.json').read_text())
    if criteria!=DEFAULT_CRITERIA:raise RuntimeError('Report implementation and preregistered criteria differ')
    payload['success_criteria_before_restart']=criteria
    payload['independence_disclosure']='Criteria are informed by v9.3/user analysis and set before the v9.4.1 restarted validation. This is exploratory retrospective validation, not fully independent confirmatory OOS. The interrupted prior process may have computed partial unsaved results; no complete result was reviewed or used to retune.'
    FREEZE.write_text(json.dumps(payload,indent=2));return payload


def integrity(manifest):
    changed=[s for s,h in manifest['source_sha256'].items() if hashlib.sha256((ROOT/s).read_bytes()).hexdigest()!=h]
    if changed:raise RuntimeError(f'Frozen source changed: {changed}')
    if hashlib.sha256((R/'v94_sealed_historical_holdout.json.gz').read_bytes()).hexdigest()!=manifest['sealed_data']['sha256']:raise RuntimeError('Data hash mismatch')


def main():
    manifest=json.loads(FREEZE.read_text()) if FREEZE.exists() else freeze()
    integrity(manifest)
    if (R/'v94_historical_validation.json').exists():raise RuntimeError('Validation already evaluated. Read the saved report, do not rerun for selection.')
    payload=json.loads(gzip.decompress((R/'v94_sealed_historical_holdout.json.gz').read_bytes()))
    frames={s:pd.DataFrame(rows) for s,rows in payload['frames'].items()}
    indices=[tuple(f.open_time) for f in frames.values()]
    if len(set(indices))!=1 or any(b-a!=300000 for a,b in zip(indices[0],indices[0][1:])):raise RuntimeError('Unsynchronized or gapped data')
    for f in frames.values():
        if len(f)!=4800 or not f.isna().sum().sum()==0:raise RuntimeError('Incomplete data')
    start=indices[0][600];end=indices[0][-1]+300000
    policy=AdaptivePolicy(**manifest['selected_policy']);cache={};results={};started=time.monotonic()
    checkpoint=R/'v94_validation_progress.json'
    if checkpoint.exists():
        previous=json.loads(checkpoint.read_text())
        if previous['freeze']!=manifest:raise RuntimeError('Checkpoint belongs to another frozen run')
        results=previous['arms']
        print('RESUME_FIXED_ARMS',list(results),flush=True)
    arms=[('v94',{}),('v93_on_corrected_clock',{'legacy':True})]+[(f'without_{fam}',{'disabled':fam}) for fam in ('TREND','FLOW','MARKET','ADAPTIVE_EXIT')]+[
        ('slippage_8bps',{'slippage_bps':8.}),('slippage_15bps',{'slippage_bps':15.}),('extra_bar_delay',{'slippage_bps':8.,'delay_bars':2}),('no_fee_no_slippage_funding_on',{'slippage_bps':0.,'fee_rate':0.})]
    partial={'freeze':manifest,'arms':results,'funding_status':payload['funding_status'],'elapsed_sec':0.,'complete':False}
    for name,options in arms:
        if name in results:continue
        engine=ChronologicalPortfolioEngine(frames,policy=policy,funding_events=payload['funding'],**options)
        engine.feature_cache=cache
        result=engine.run(start,end);cache=engine.feature_cache
        results[name]=result
        print(name,result['trade_count'],round(result['net_pnl'],4),'DD',round(result['max_equity_drawdown_usdt'],4),flush=True)
        if abs(result['net_pnl']-result['trade_net_sum'])>1e-6:raise RuntimeError('Wallet/trade reconciliation failed')
        partial={'freeze':manifest,'arms':results,'funding_status':payload['funding_status'],'elapsed_sec':time.monotonic()-started,'complete':False}
        temporary=R/'v94_validation_progress.tmp'
        temporary.write_text(json.dumps(partial,indent=2));temporary.replace(checkpoint)
    from scripts.audit_v94_gates import audit
    gate_audit=audit(frames,policy,start,end,cache)
    (R/'v941_gate_cohort_audit.json').write_text(json.dumps(gate_audit,indent=2))
    print('GATE_AUDIT_COMPLETE',len(gate_audit['cohorts']),flush=True)
    integrity(manifest)
    from src.gate_statistics import confidence
    portfolio=results['v94'];day_equity={}
    for point in portfolio['equity_curve']:day_equity[(int(point['ts'])-1)//86400000]=point['equity']
    if day_equity:day_equity[max(day_equity)]=portfolio['ending_equity']
    previous=1000.;daily_rows=[]
    for day,value in sorted(day_equity.items()):
        change=value-previous;previous=value
        daily_rows.append({'day':day,'symbol':'PORTFOLIO','gross_bps':change,'net_base_bps':change,'net_stress_bps':change})
    portfolio_ci=confidence(daily_rows,min_n=10,min_symbols=1,min_days=10)
    criteria=manifest['success_criteria_before_restart']
    checks={'min_closed_trades':portfolio['trade_count']>=criteria['candidate_min_closed_trades'],
        'positive_base_net':portfolio['net_pnl']>0,
        'positive_all_stress_nets':all(results[a]['net_pnl']>0 for a in criteria['candidate_required_stress_arms']),
        'equity_drawdown_within_cap':portfolio['max_equity_drawdown_usdt']<=criteria['candidate_max_equity_drawdown_usdt'],
        'daily_clustered_ci_positive':portfolio_ci['ci_95'] is not None and portfolio_ci['ci_95']['net_base_bps'][0]>0,
        'funding_data_complete':all(status=='FETCHED' for status in payload['funding_status'].values())}
    report={**partial,'success_checks':checks,'research_criteria_passed':all(checks.values()),
        'portfolio_daily_change_ci_usdt':portfolio_ci,'real_money_approved':False,'complete':True,'test_start_ms':int(start),'test_end_ms':int(end),'bars_per_symbol_test':4200,
        'decision':'RESEARCH_CRITERIA_FAILED_REAL_MONEY_REJECTED' if not all(checks.values()) else 'RESEARCH_CRITERIA_PASSED_REAL_MONEY_STILL_NOT_APPROVED',
        'selection_after_validation':False,'source_integrity':'UNCHANGED',
        'limitations':['Older historical block is not temporally forward of development data.','Eight fixed symbols have survivorship/selection bias.','Exposure and universe differ between historical 8-symbol replay and full-universe live scanner.','One historical block is not rolling walk-forward.','Live fills and tick stop paths differ from 5m OHLC replay; shared decision formula does not imply identical fills.','Ablations share upstream features and are descriptive, not independent causal trials.','Cross-wallet gap losses are capped by inherited paper liquidation accounting; severe gap tails may be understated.']}
    (R/'v94_historical_validation.json').write_text(json.dumps(report,indent=2))
    print('COMPLETE',report['decision'],'elapsed',report['elapsed_sec'],flush=True)
    return report
if __name__=='__main__':main()
