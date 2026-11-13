"""Descriptive fixed-horizon gate audit, strictly separate from decisions/selection.

Only single-family-only blockers are compared; no replacement gate is added.
Forward prices are accessed here for LABELS, never in the trading core.
"""
from collections import defaultdict
from dataclasses import asdict
import numpy as np
from src.v94_core import V94DecisionCore,market_context,features


def audit(frames,policy,start_ms,end_ms,cache=None):
    cache=cache if cache is not None else {}
    indexes={s:{int(t):i for i,t in enumerate(f.open_time)} for s,f in frames.items()}
    times=sorted(set.intersection(*(set(x) for x in indexes.values())))
    times=[t for t in times if start_ms<=t<end_ms]
    core=V94DecisionCore(policy)
    without={fam:V94DecisionCore(policy,disabled=fam) for fam in ('TREND','FLOW','MARKET')}
    cohorts=[]
    for ts in times:
        prefixes={s:f.iloc[max(0,indexes[s][ts]-599):indexes[s][ts]+1] for s,f in frames.items()}
        ctx=market_context(prefixes,ts)
        for sym,df in frames.items():
            i=indexes[sym][ts]
            f=cache.get((sym,i))
            if f is None:f=features(prefixes[sym])
            base=core.decide(f,ctx)
            decisions=[]
            if base['side'] in ('LONG','SHORT'):decisions=[('BASE_ACCEPTED_REFERENCE',base)]
            else:
                for family,other in without.items():
                    alt=other.decide(f,ctx)
                    if alt['side'] in ('LONG','SHORT'):decisions.append(('SINGLE_BLOCKER_'+family,alt))
            for group,dec in decisions:
                row={'group':group,'symbol':sym,'decision_bar_open_ms':ts,'side':dec['side'],
                     'base_reason':base['reason'],'matured_15m':False,'signed_gross_15m_bps':None,
                     'cost_scenario_15m_bps':None,'stress_cost_scenario_15m_bps':None,'tactical_stop_bps':policy.risk_distance(f.close,f.atr)/f.close*10000,'observed_bar_mae_15m_bps':None,'observed_bar_mfe_15m_bps':None}
                if i+3<len(df) and int(df.open_time.iloc[i+3])+300000<=end_ms:
                    sign=1 if dec['side']=='LONG' else -1
                    close=float(df.close.iloc[i]);future=float(df.close.iloc[i+3])
                    gross=(future/close-1)*10000*sign
                    high=float(df.high.iloc[i+1:i+4].max());low=float(df.low.iloc[i+1:i+4].min())
                    best=(high/close-1)*10000 if sign==1 else (1-low/close)*10000
                    worst=(low/close-1)*10000 if sign==1 else (1-high/close)*10000
                    row.update(matured_15m=True,signed_gross_15m_bps=gross,cost_scenario_15m_bps=gross-14.5,stress_cost_scenario_15m_bps=gross-24.5,
                               observed_bar_mae_15m_bps=min(0,worst),observed_bar_mfe_15m_bps=max(0,best))
                cohorts.append(row)
    summary={}
    for group in sorted({r['group'] for r in cohorts}):
        sides={}
        for side in ('LONG','SHORT'):
            rows=[r for r in cohorts if r['group']==group and r['side']==side]
            mature=[r for r in rows if r['matured_15m']]
            avg=lambda key:float(np.mean([r[key] for r in mature])) if mature else None
            sides[side]={'unique_symbol_bar_n':len(rows),'matured_15m_n':len(mature),'censored_15m_n':len(rows)-len(mature),
                'mean_gross_mark_return_bps':avg('signed_gross_15m_bps'),'mean_cost_scenario_mark_return_bps':avg('cost_scenario_15m_bps'),
                'mean_stress_8bps_per_side_mark_return_bps':avg('stress_cost_scenario_15m_bps'),
                'mean_bar_mae_bps':avg('observed_bar_mae_15m_bps'),'worst_bar_mae_bps':min((r['observed_bar_mae_15m_bps'] for r in mature),default=None),
                'initial_tactical_stop_barrier_touches':sum(r['observed_bar_mae_15m_bps']<=-r['tactical_stop_bps'] for r in mature),
                'emergency_8pct_barrier_touches':sum(r['observed_bar_mae_15m_bps']<=-800 for r in mature),
                'mean_bar_mfe_bps':avg('observed_bar_mfe_15m_bps')}
            from src.gate_statistics import confidence
            observations=[{'day':(int(r['decision_bar_open_ms'])+300000)//86400000,'symbol':r['symbol'],
                'gross_bps':r['signed_gross_15m_bps'],'net_base_bps':r['cost_scenario_15m_bps'],
                'net_stress_bps':r['stress_cost_scenario_15m_bps']} for r in mature]
            sides[side]['confidence']=confidence(observations)
        summary[group]=sides
    return {'summary_by_side':summary,'cohorts':cohorts,'cost_scenario_roundtrip_bps':14.5,'stress_cost_scenario_roundtrip_bps':24.5,
            'interpretation':'Opportunity-cost hints only. Not executed profit, not a causal treatment effect, no automatic gate removal.',
            'limitations':['Overlapping 15m horizons and common market factors make cohorts dependent.',
                'Single-only blockers exclude candidates rejected by several families.',
                'Mark returns omit maker fills, stop paths, portfolio capacity and funding.',
                'BASE_ACCEPTED_REFERENCE is descriptive, not a randomized matched control.'],
            'does_not_change_trade_decisions':True}
