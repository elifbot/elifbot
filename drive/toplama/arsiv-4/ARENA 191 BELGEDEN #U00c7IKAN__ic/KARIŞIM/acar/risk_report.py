"""Salt-okunur birleşik araştırma defteri risk görünümü.
Bu bir yatırım önerisi veya borsa marj/likidasyon hesaplayıcısı değildir.
"""
from decimal import Decimal,localcontext
from .depth_research import fmt
from .unified_simulator import _condition,_equity

D=Decimal

def risk_report(snapshot,as_of=None):
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('state'),dict):raise ValueError('invalid snapshot')
    s=snapshot['state'];t=s['last_time'] if as_of is None else as_of
    if type(t) is not int or t<s['last_time'] or t>253402300799:raise ValueError('invalid risk report time')
    warnings=[];items=[];gross=D(0);total_risk=D(0)
    if any(e.get('kind')=='CLOSE' and e.get('detail',{}).get('execution_uncertain') is True for e in snapshot.get('ledger',[])):warnings.append('EXECUTION_HISTORY_UNCERTAIN')
    with localcontext() as ctx:
        ctx.prec=80
        for symbol,p in sorted(s['positions'].items()):
            qty=D(p['qty']);entry=D(p['entry']);mark=D(p['mark']);sign=D(1 if p['side']=='long' else -1)
            stale=(p['mark_at']>t or t-p['mark_at']>s['max_age']);due=t>=p['next_funding']
            if p.get('funding_price_uncertain'):warnings.append(symbol+':FUNDING_PRICE_PROXY')
            elif p.get('execution_uncertain'):warnings.append(symbol+':MONITORING_GAP')
            if stale:warnings.append(symbol+':STALE_MARK')
            if due:warnings.append(symbol+':FUNDING_DUE')
            notional=qty*mark;gross+=notional
            stop_risk=qty*(max(D(0),(entry-D(p['stop']))*sign)+entry*D(s['settings']['fee_rate'])*2);total_risk+=stop_risk
            status,isolated,maintenance=_condition(s,p,mark,t)
            items.append({'symbol':symbol,'side':p['side'],'notional_at_last_mark':fmt(notional),'stop_scenario_risk':fmt(stop_risk),
                          'mark_at':p['mark_at'],'mark_stale':stale,'funding_due':due,'execution_uncertain':p.get('execution_uncertain',False),'protection_status':status,
                          'isolated_equity_estimate':fmt(isolated),'maintenance_estimate':fmt(maintenance),
                          'maintenance_buffer_estimate':fmt(isolated-maintenance)})
        eq=_equity(s)
        if not warnings and eq<=0:warnings.append('NONPOSITIVE_EQUITY')
        can_estimate=not warnings
        return {'mode':'OFFLINE_ESTIMATE','as_of':t,'cash':s['cash'],'equity_if_fresh':fmt(eq) if can_estimate else None,
                'gross_notional_at_last_marks':fmt(gross),'total_stop_scenario_risk':fmt(total_risk),
                'stop_risk_fraction_if_fresh':fmt(total_risk/eq) if can_estimate else None,
                'entry_locked':s['entry_locked'],'daily_halt':s['daily_halt'],'positions':items,'warnings':warnings,
                'notice':'Sabit ücret/stop ve basit teminat varsayımları; gap, likidite, cross-margin ve borsa likidasyon riskini sınırlamaz.'}
