"""Çok varlık için saf risk kontrolü; emir veya borsa bağlantısı içermez.
Açık pozisyonlar güncel pozitif mark fiyatı ve normalize edilmiş kök varlık ister.
Stop riski tahmindir; gap/likidasyon/kısmi dolum riskini sınırlamaz.
"""
from dataclasses import dataclass,asdict
import math

def _finite(x):
 try:return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
 except OverflowError:return False
def _positive(x):return _finite(x) and x>0
@dataclass(frozen=True)
class Limits:
 per_trade_fraction: float=.005
 total_risk_fraction: float=.02
 directional_risk_fraction: float=.01
 gross_notional: float=1000.0
 per_position_notional: float=250.0
 max_positions: int=4
 max_per_asset: int=1
 fee_rate: float=.0005
 slippage_rate: float=.0002
 def validate(self):
  for key in ('per_trade_fraction','total_risk_fraction','directional_risk_fraction'):
   x=getattr(self,key)
   if not _positive(x) or x>1:raise ValueError('invalid '+key)
  if not _positive(self.gross_notional) or not _positive(self.per_position_notional):raise ValueError('invalid notional')
  for k in ('max_positions','max_per_asset'):
   x=getattr(self,k)
   if isinstance(x,bool) or not isinstance(x,int) or x<1:raise ValueError('invalid '+k)
  for k in ('fee_rate','slippage_rate'):
   x=getattr(self,k)
   if not _finite(x) or not 0<=x<=.1:raise ValueError('invalid '+k)

def evaluate_portfolio(equity,positions,candidate,limits=Limits()):
 try:limits.validate()
 except (ValueError,TypeError):return {'allowed':False,'reason':'INVALID_LIMITS'}
 if not _positive(equity):return {'allowed':False,'reason':'INVALID_EQUITY'}
 if not isinstance(positions,list) or not isinstance(candidate,dict):return {'allowed':False,'reason':'INVALID_POSITION_SET'}
 allpos=positions+[candidate]
 for p in allpos:
  if not isinstance(p,dict) or p.get('side') not in ('long','short') or not isinstance(p.get('asset'),str) or not p['asset'].strip() or not all(_positive(p.get(k)) for k in ('entry','stop','qty','mark')):
   return {'allowed':False,'reason':'POSITION_DATA_UNKNOWN'}
  if p['asset']!=p['asset'].strip().upper() or not p['asset'].isalnum():return {'allowed':False,'reason':'ASSET_NOT_CANONICAL'}
 if (candidate['side']=='long' and candidate['stop']>=candidate['entry']) or (candidate['side']=='short' and candidate['stop']<=candidate['entry']):
  return {'allowed':False,'reason':'INVALID_INITIAL_STOP'}
 def risk(p):
  sign=1 if p['side']=='long' else -1
  return (max(0,(p['entry']-p['stop'])*sign)+p['entry']*(2*limits.fee_rate+limits.slippage_rate))*p['qty']
 notional=lambda p:p['mark']*p['qty']
 cr=risk(candidate);gross=sum(notional(p) for p in allpos);total=sum(risk(p) for p in allpos)
 same=sum(risk(p) for p in allpos if p['side']==candidate['side'])
 asset_count=sum(p['asset']==candidate['asset'] for p in allpos)
 checks=[('MAX_POSITIONS',len(allpos)<=limits.max_positions),('DUPLICATE_ASSET',asset_count<=limits.max_per_asset),
         ('MAX_PER_POSITION_NOTIONAL',notional(candidate)<=limits.per_position_notional+1e-9),
         ('MAX_GROSS',gross<=limits.gross_notional+1e-9),('TRADE_RISK',cr<=equity*limits.per_trade_fraction+1e-9),
         ('TOTAL_RISK',total<=equity*limits.total_risk_fraction+1e-9),('DIRECTION_RISK',same<=equity*limits.directional_risk_fraction+1e-9)]
 for reason,ok in checks:
  if not ok:return {'allowed':False,'reason':reason,'candidate_stop_risk':cr,'total_stop_risk':total,'gross_notional':gross,'direction_stop_risk':same}
 return {'allowed':True,'reason':'OK','candidate_stop_risk':cr,'total_stop_risk':total,'gross_notional':gross,'direction_stop_risk':same}
