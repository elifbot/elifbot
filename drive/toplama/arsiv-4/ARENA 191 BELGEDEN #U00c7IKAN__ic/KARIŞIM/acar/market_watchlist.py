"""Bulk snapshot -> bounded OKX watchlist configuration; no network or trade."""
from decimal import Decimal,ROUND_DOWN,localcontext
from .depth_research import dec,fmt
from .okx_public_adapter import parse_instrument

def make_watchlist(report,*,now_ms,target_notional,leverage,min_notional,count=4,poll_seconds=10):
 if not isinstance(report,dict) or report.get('schema')!='acar.market-universe.v1' or report.get('mode')!='PUBLIC_READ_ONLY_NO_PAPER':raise ValueError('unknown report format')
 if type(now_ms) is not int or type(report.get('captured_at_ms')) is not int or not -2000<=now_ms-report['captured_at_ms']<=120000:raise ValueError('report stale or future')
 if type(count) is not int or not 1<=count<=4 or type(poll_seconds) is not int or not 5<=poll_seconds<=30:raise ValueError('invalid worker limits')
 budget=dec(target_notional,'target_notional',positive=True);lev=dec(leverage,'leverage',positive=True);minimum=dec(min_notional,'min_notional',nonnegative=True)
 if budget>250 or lev>3 or minimum>budget:raise ValueError('input exceeds paper risk settings')
 rows=report.get('markets')
 if not isinstance(rows,list) or len(rows)>20000:raise ValueError('invalid markets')
 ranked=[];seen=set()
 for r in rows:
  if not isinstance(r,dict):raise ValueError('invalid market row')
  if r.get('venue')!='OKX' or r.get('asset_class')!='CRYPTO_AS_REPORTED_BY_OKX' or r.get('market_rule_type')!='normal':continue
  symbol=r.get('symbol')
  if symbol in seen:raise ValueError('duplicate market')
  seen.add(symbol)
  try:
   t=r['ticker'];ts=t['timestamp_ms']
   if type(ts) is not int or not -2000<=now_ms-ts<=30000:continue
   if t.get('status')!='FRESH':continue
   bid=dec(t['bid'],'bid',positive=True);ask=dec(t['ask'],'ask',positive=True);last=dec(t['last'],'last',positive=True);volume=dec(t['base_volume_24h'],'volume',nonnegative=True)
   if bid>ask:continue
   spec={'instId':symbol,'instType':'SWAP','state':'live','ctType':'linear','settleCcy':'USDT','ctValCcy':r['contract_value_currency'],
         'instCategory':'1','ruleType':'normal','ctVal':r['contract_value'],'ctMult':r['contract_multiplier'],'lotSz':r['contract_lot'],'minSz':r['contract_min'],'tickSz':r['price_tick']}
   instrument=parse_instrument({'code':'0','data':[spec]},symbol,min_notional=fmt(minimum))
   with localcontext() as ctx:
    ctx.prec=80
    if (ask-bid)/((ask+bid)/2)*10000>30:continue
    step=Decimal(instrument.rules.qty_step);minqty=Decimal(instrument.rules.min_qty)
    qty=((budget/ask/step).to_integral_value(rounding=ROUND_DOWN))*step
    if qty<minqty or qty<=0 or qty*ask<minimum:continue
    dec(fmt(qty),'quantity',positive=True)
    score=volume*last
   ranked.append((score,symbol,fmt(qty)))
  except (ValueError,KeyError,TypeError,ArithmeticError):continue
 ranked.sort(key=lambda x:(-x[0],x[1]));chosen=ranked[:count]
 if not chosen:raise ValueError('no eligible fresh OKX candidates')
 config={'poll_seconds':poll_seconds,'instruments':[{'symbol':s,'quantity':q,'leverage':fmt(lev),'min_notional':fmt(minimum)} for _,s,q in chosen]}
 return config,{'selected':len(chosen),'symbols':[s for _,s,_ in chosen],
  'selection_method':'OKX ticker 24h base volume × last price approximation; not exact turnover, not a signal',
  'warning':'Indicative snapshot only; actual price, lot, minimum, depth, funding and risk must be revalidated. No paper run started.'}
