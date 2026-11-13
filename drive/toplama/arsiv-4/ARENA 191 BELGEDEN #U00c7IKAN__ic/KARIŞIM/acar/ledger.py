"""PAPER defterin aritmetik ve alan bütünlüğü; gerçek borsa mutabakatı değildir."""
import math

def _num(value,nonnegative=False,positive=False):
 return (isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
         and (not nonnegative or value>=0) and (not positive or value>0))

def audit_ledger(state,trades):
 issues=[]
 if not isinstance(state,dict):return {'ok':False,'issues':['STATE_INVALID'],'warnings':[]}
 if not _num(state.get('initial_cash'),positive=True):issues.append('INITIAL_CASH_INVALID')
 if not _num(state.get('cash')):issues.append('CASH_INVALID')
 count=state.get('trade_count')
 if isinstance(count,bool) or not isinstance(count,int) or count<0:issues.append('TRADE_COUNT_INVALID')
 elif count!=len(trades):issues.append('TRADE_COUNT_MISMATCH')
 nets=[]
 for i,t in enumerate(trades):
  if not isinstance(t,dict):issues.append(f'TRADE_INVALID_{i}');continue
  if t.get('side') not in ('long','short'):issues.append(f'TRADE_SIDE_INVALID_{i}')
  if not all(_num(t.get(k),positive=True) for k in ('entry','exit','qty')):issues.append(f'TRADE_PRICE_QTY_INVALID_{i}')
  if not all(_num(t.get(k)) for k in ('gross','net')) or not _num(t.get('fees'),nonnegative=True):
   issues.append(f'TRADE_MONEY_INVALID_{i}');continue
  if not math.isclose(t['net'],t['gross']-t['fees'],rel_tol=1e-9,abs_tol=1e-7):issues.append(f'TRADE_NET_MISMATCH_{i}')
  if all(_num(t.get(k),positive=True) for k in ('entry','exit','qty')) and t.get('side') in ('long','short'):
   gross=(t['exit']-t['entry'])*t['qty']*(1 if t['side']=='long' else -1)
   if not math.isclose(t['gross'],gross,rel_tol=1e-9,abs_tol=1e-7):issues.append(f'TRADE_GROSS_MISMATCH_{i}')
  nets.append(t['net'])
 p=state.get('position');entry_fee=0
 if p is not None:
  if not isinstance(p,dict):issues.append('POSITION_INVALID')
  else:
   if p.get('side') not in ('long','short'):issues.append('POSITION_SIDE_INVALID')
   if not all(_num(p.get(k),positive=True) for k in ('entry','qty','stop','target','entry_time')):issues.append('POSITION_FIELDS_INVALID')
   if not _num(p.get('entry_fee'),nonnegative=True):issues.append('POSITION_FEE_INVALID')
   else:entry_fee=p['entry_fee']
 expected=None
 if _num(state.get('initial_cash'),positive=True) and _num(state.get('cash')) and len(nets)==len(trades):
  expected=state['initial_cash']+math.fsum(nets)-entry_fee
  if not math.isclose(state['cash'],expected,rel_tol=1e-9,abs_tol=1e-7):issues.append('CASH_MISMATCH')
 warnings=[]
 if state.get('funding_unaccounted'):warnings.append('FUNDING_NOT_ACCOUNTED')
 if state.get('monitoring_uncertain') or (p and state.get('halt_reason') in ('KOTASYON_KESINTISI','KACIRILMIS_MUM','BAYAT_MUM')):
  warnings.append('MONITORING_GAP')
 if any(isinstance(t,dict) and t.get('execution_uncertain') for t in trades):warnings.append('UNCERTAIN_EXIT_RECORDED')
 return {'ok':not issues,'issues':issues,'warnings':warnings,'expected_cash':expected,'trade_count':len(trades),'scope':'paper_arithmetic_only'}
