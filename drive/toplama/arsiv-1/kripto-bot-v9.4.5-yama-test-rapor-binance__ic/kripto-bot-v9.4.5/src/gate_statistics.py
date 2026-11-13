"""Reporting-only statistics; never imported by strategy/risk/exit code.
Two-calendar-day moving-block bootstrap, clustering concurrent symbols together.
"""
from __future__ import annotations
import numpy as np

DEFAULT_CRITERIA={
    'min_matured_per_gate_side':50,'min_distinct_symbols':3,'min_distinct_utc_days':10,
    'bootstrap_draws':10000,'moving_block_days':2,'familywise_alpha':0.05,
    'predeclared_gate_side_hypotheses':6,'stress_net_lower_bound_bps':1.0,
    'base_roundtrip_fee_bps':7.0,'base_slippage_bps_per_side':3.0,
    'stress_slippage_bps_per_side':8.0,'reference_spread_bps':1.5,
    'candidate_min_closed_trades':100,'candidate_max_equity_drawdown_usdt':50.0,
    'candidate_required_stress_arms':['slippage_8bps','slippage_15bps','extra_bar_delay'],
    'real_money_approval':False,
}


def confidence(rows,*,criteria=None,min_n=None,min_symbols=None,min_days=None):
    c={**DEFAULT_CRITERIA,**(criteria or {})}
    minimum_n=c['min_matured_per_gate_side'] if min_n is None else min_n
    minimum_symbols=c['min_distinct_symbols'] if min_symbols is None else min_symbols
    minimum_days=c['min_distinct_utc_days'] if min_days is None else min_days
    days=sorted({int(r['day']) for r in rows});symbols={r['symbol'] for r in rows}
    result={'matured_n':len(rows),'distinct_symbols':len(symbols),'distinct_utc_days':len(days),
            'ci_95':None,'simultaneous_familywise_95_ci':None,
            'method':'10000-draw two-calendar-day moving-block bootstrap, all symbols clustered by UTC day',
            'limitations':'Descriptive stationarity-dependent intervals; short sample, overlapping horizons and regime shifts remain limitations.'}
    if len(rows)<minimum_n or len(symbols)<minimum_symbols or len(days)<minimum_days:
        return {**result,'status':'INSUFFICIENT_EVIDENCE','positive_opportunity_cost_evidence':False}
    all_days=np.arange(min(days),max(days)+1);D=len(all_days)
    counts=np.zeros(D);totals=np.zeros((D,3))
    for r in rows:
        idx=int(r['day'])-int(all_days[0]);counts[idx]+=1
        totals[idx]+=np.array([r['gross_bps'],r['net_base_bps'],r['net_stress_bps']])
    block=int(c['moving_block_days']);B=int(c['bootstrap_draws'])
    rng=np.random.default_rng(941)
    starts=rng.integers(0,max(1,D-block+1),size=(B,(D+block-1)//block))
    indices=(starts[:,:,None]+np.arange(block)).reshape(B,-1)[:,:D]
    indices=np.minimum(indices,D-1)
    den=counts[indices].sum(axis=1);num=totals[indices].sum(axis=1)
    values=num[den>0]/den[den>0,None]
    alpha=float(c['familywise_alpha']);hyp=int(c['predeclared_gate_side_hypotheses'])
    keys=['gross_bps','net_base_bps','net_stress_bps']
    regular=np.quantile(values,[.025,.975],axis=0)
    adjusted=np.quantile(values,[alpha/(2*hyp),1-alpha/(2*hyp)],axis=0)
    result.update(status='DESCRIPTIVE_INTERVAL_AVAILABLE',valid_bootstrap_draws=len(values),
                  ci_95={k:regular[:,i].tolist() for i,k in enumerate(keys)},
                  simultaneous_familywise_95_ci={k:adjusted[:,i].tolist() for i,k in enumerate(keys)})
    result['positive_opportunity_cost_evidence']=bool(adjusted[0,2]>c['stress_net_lower_bound_bps'])
    result['interpretation']='Threshold flag is not a causal gate-removal decision or real-money approval.'
    return result
