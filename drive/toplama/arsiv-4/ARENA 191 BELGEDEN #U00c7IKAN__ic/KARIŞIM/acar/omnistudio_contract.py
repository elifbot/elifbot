"""Salesforce/OmniStudio için salt-okunur örnek JSON; deployment doğrulanmamıştır."""
from .unified_simulator import _condition
from decimal import Decimal,localcontext

def build_omni_status(snapshot,as_of=None):
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('state'),dict):raise ValueError('invalid simulator snapshot')
    s=snapshot['state'];positions=[];t=s['last_time'] if as_of is None else as_of
    if type(t) is not int or t<0 or t>253402300799:raise ValueError('invalid status time')
    historic=any(e.get('kind')=='CLOSE' and e.get('detail',{}).get('execution_uncertain') is True for e in snapshot.get('ledger',[]))
    with localcontext() as ctx:
        ctx.prec=80
        for symbol,p in sorted(s['positions'].items()):
            condition,_,_=_condition(s,p,Decimal(p['mark']),t)
            positions.append({'symbol':symbol,'side':p['side'],'quantity':p['qty'],'entryPrice':p['entry'],
                              'lastMark':p['mark'],'lastMarkTime':p['mark_at'],'executionUncertain':p.get('execution_uncertain',False),'fundingPriceUncertain':p.get('funding_price_uncertain',False),
                              'markStale':p['mark_at']>t or t-p['mark_at']>s['max_age'],
                              'fundingDue':t>=p['next_funding'],'protectionStatus':condition})
    uncertain=historic or any(p['markStale'] or p['executionUncertain'] or p['fundingDue'] for p in positions)
    return {'schemaVersion':'1.0','mode':'PAPER_SIMULATION','asOfTime':t,'lastEventTime':s['last_time'],
            'clockBasis':'WALL_CLOCK' if as_of is not None else 'LAST_EVENT','workerStatus':'NOT_OBSERVED',
            'account':{'cash':s['cash'],'equityAtLastMarks':snapshot['equity_at_last_marks'],'equityReliable':not uncertain,
                       'uncertainExecutionHistory':historic,'entriesLocked':s['entry_locked'],'lockReason':s['lock_reason'],'dailyHalt':s['daily_halt'],'dayStartEquity':s['day_start_equity']},
            'positions':positions,'alertCount':len(snapshot['notifications']),
            'integrationState':'DEPLOYMENT_NOT_VERIFIED',
            'disclaimer':'Sanal simülasyon; Salesforce dağıtımı ve worker sağlığı bu görünümle doğrulanmaz.'}
