"""İzole settlement hesabı; çalışan deftere veya borsa akışına bağlı değildir.
Olay/mark kesinleşmiş olmalı. Aksi durumda muhasebeyi reddeder.
"""
from dataclasses import dataclass,asdict
from math import isfinite
from copy import deepcopy
import json,re

def _finite(x):
 try:return isinstance(x,(float,int)) and not isinstance(x,bool) and isfinite(x)
 except OverflowError:return False
@dataclass(frozen=True)
class Settlement:
 venue: str
 instrument: str
 settlement_ts: int
 finalized_at: int
 rate: float
 mark_price: float
 confirmed: bool

def apply_settlement(account,event,position):
 """Aynı settlement+position id için en fazla bir kez etki; girdi değişmez.

 account={'cash': float, 'applied': {key: payload}}, position={'id', 'side',
 'venue', 'instrument', 'qty_base', 'opened_at', 'closed_at'}; None closed_at = hâlâ açık.
 """
 if not isinstance(account,dict) or not isinstance(event,Settlement) or not isinstance(position,dict):raise ValueError('invalid input')
 if not _finite(account.get('cash')) or not isinstance(account.get('applied'),dict):raise ValueError('invalid account')
 if not event.confirmed or type(event.confirmed) is not bool:raise ValueError('funding not confirmed')
 if not isinstance(event.venue,str) or not event.venue.strip() or not isinstance(event.instrument,str) or not event.instrument.strip():raise ValueError('invalid market')
 if not re.fullmatch(r'[A-Z0-9_-]+',event.venue) or not re.fullmatch(r'[A-Z0-9_-]+',event.instrument):raise ValueError('market not canonical')
 if position.get('venue')!=event.venue or position.get('instrument')!=event.instrument:raise ValueError('position market mismatch')
 if type(event.settlement_ts) is not int or type(event.finalized_at) is not int or event.settlement_ts<=0 or event.finalized_at<event.settlement_ts:raise ValueError('invalid settlement time')
 if not _finite(event.rate) or abs(event.rate)>1 or not _finite(event.mark_price) or event.mark_price<=0:raise ValueError('invalid rate or mark')
 if not isinstance(position.get('id'),str) or not position['id'].strip() or position.get('side') not in ('long','short') or not _finite(position.get('qty_base')) or position['qty_base']<=0:raise ValueError('invalid position')
 opened=position.get('opened_at');closed=position.get('closed_at')
 if not _finite(opened) or opened<0 or opened>=event.settlement_ts or (closed is not None and (not _finite(closed) or closed<=event.settlement_ts)):
  raise ValueError('position not demonstrably open at settlement')
 key=json.dumps([event.venue,event.instrument,event.settlement_ts,position['id']],ensure_ascii=True,separators=(',',':'))
 # Fields are compared in full; no same-key revision accepted silently.
 payload={'event':asdict(event),'position':{'id':position['id'],'venue':position['venue'],'instrument':position['instrument'],'side':position['side'],'qty_base':position['qty_base'],'opened_at':opened,'closed_at':closed}}
 result=deepcopy(account)
 if key in result['applied']:
  old=result['applied'][key]
  if not isinstance(old,dict) or old.get('payload')!=payload:raise ValueError('conflicting settlement replay')
  return result,{'applied':False,'reason':'DUPLICATE','key':key,'cash_delta':0.0}
 delta=-(1 if position['side']=='long' else -1)*event.rate*position['qty_base']*event.mark_price
 if not isfinite(delta) or not isfinite(result['cash']+delta):raise ValueError('nonfinite cash flow')
 result['cash']+=delta;result['applied'][key]={'payload':payload,'cash_delta':delta}
 return result,{'applied':True,'reason':'APPLIED','key':key,'cash_delta':delta}
