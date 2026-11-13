"""Read-only, bulk futures discovery. No orders, no SQLite, no trading decisions.

OKX and Binance instruments are distinct venue-specific contracts, never merged
by base name. Prices are snapshots, not executable quotes or verified fills.
"""
import json,re,time,urllib.error,urllib.request
from collections import Counter
from decimal import Decimal,InvalidOperation,localcontext
from .okx_public_adapter import parse_instrument,symbol_ok

URLS={
 'OKX_INSTRUMENTS':'https://www.okx.com/api/v5/public/instruments?instType=SWAP',
 'OKX_TICKERS':'https://www.okx.com/api/v5/market/tickers?instType=SWAP',
 'BINANCE_INSTRUMENTS':'https://fapi.binance.com/fapi/v1/exchangeInfo',
 'BINANCE_TICKERS':'https://fapi.binance.com/fapi/v1/ticker/24hr',
}
MAX_BYTES=8_000_000;MAX_ROWS=20000
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def fetch_public(key,*,binance_host='fapi'):
 """Fixed GET URLs only. No redirects, retries, private endpoints or secrets."""
 if key not in URLS or binance_host not in ('fapi','www'):raise ValueError('endpoint or host not allowed')
 url=URLS[key]
 if key.startswith('BINANCE_') and binance_host=='www':url=url.replace('https://fapi.binance.com/','https://www.binance.com/',1)
 req=urllib.request.Request(url,headers={'User-Agent':'ACAR-Market-Research/1','Accept':'application/json'})
 with urllib.request.build_opener(NoRedirect()).open(req,timeout=15) as response:
  payload=response.read(MAX_BYTES+1)
  if len(payload)>MAX_BYTES:raise ValueError('response too large')
  return json.loads(payload.decode('utf-8'))

def _rows(obj,kind):
 if kind.startswith('OKX'):
  if not isinstance(obj,dict) or obj.get('code')!='0':raise ValueError('OKX error response')
  rows=obj.get('data')
 elif kind=='BINANCE_INSTRUMENTS':
  if not isinstance(obj,dict):raise ValueError('invalid Binance metadata')
  rows=obj.get('symbols')
 else:rows=obj
 if not isinstance(rows,list) or len(rows)>MAX_ROWS:raise ValueError('invalid or oversized rows')
 if any(not isinstance(x,dict) for x in rows):raise ValueError('invalid row')
 return rows

def _number(x,*,positive=False):
 if not isinstance(x,str) or len(x)>50:raise ValueError('invalid numeric string')
 try:d=Decimal(x)
 except InvalidOperation:raise ValueError('invalid number') from None
 if not d.is_finite() or abs(d.as_tuple().exponent)>40 or len(d.as_tuple().digits)>40 or (d<=0 if positive else d<0):raise ValueError('invalid numeric value')
 return d

def _time(value):
 if isinstance(value,str) and value.isdigit() and len(value)<=15:value=int(value)
 if type(value) is not int or not 0<value<=253402300799999:raise ValueError('invalid timestamp')
 return value

def _ticker_status(ts,now_ms,max_age_ms=120000):
 # A small explicit clock tolerance is not taken as a guarantee of accuracy.
 age=now_ms-ts
 if age < -2000:return 'FUTURE',age
 return ('STALE' if age>max_age_ms else 'FRESH'),age

def _unique(rows,key):
 result={}
 for r in rows:
  symbol=r.get(key)
  if not isinstance(symbol,str) or not 1<=len(symbol)<=50 or any(not (ch.isalnum() or ch in '-_') for ch in symbol):raise ValueError('invalid symbol')
  if symbol in result:raise ValueError('duplicate symbol')
  result[symbol]=r
 return result

def _okx_ticker(raw,now_ms):
 if raw is None:return {'status':'MISSING'}
 try:
  last=_number(raw['last'],positive=True);bid=_number(raw['bidPx'],positive=True);ask=_number(raw['askPx'],positive=True)
  if bid>ask:raise ValueError('crossed ticker')
  vol=_number(raw['volCcy24h']);ts=_time(raw['ts']);status,age=_ticker_status(ts,now_ms)
  with localcontext() as ctx:
   ctx.prec=60;spread=(ask-bid)/((ask+bid)/2)*10000
  return {'status':status,'timestamp_ms':ts,'age_ms':age,'last':str(last),'bid':str(bid),'ask':str(ask),'spread_bps':str(spread.quantize(Decimal('0.0001'))),'base_volume_24h':str(vol)}
 except (KeyError,ValueError,ArithmeticError):return {'status':'INVALID'}

def _binance_ticker(raw,now_ms):
 if raw is None:return {'status':'MISSING'}
 try:
  last=_number(raw['lastPrice'],positive=True);vol=_number(raw['quoteVolume']);ts=_time(raw['closeTime']);status,age=_ticker_status(ts,now_ms)
  # Binance closeTime is the 24h window end, not an order book observation.
  return {'status':status,'timestamp_ms':ts,'timestamp_kind':'24H_WINDOW_CLOSE','age_ms':age,'last':str(last),'quote_volume_24h':str(vol)}
 except (KeyError,ValueError,ArithmeticError):return {'status':'INVALID'}

def normalize_okx(instruments,tickers,now_ms):
 inst=_unique(_rows(instruments,'OKX_INSTRUMENTS'),'instId')
 ticks=_unique(_rows(tickers,'OKX_TICKERS'),'instId') if tickers is not None else {}
 result=[];exclusions=Counter()
 for symbol,x in sorted(inst.items()):
  if x.get('instType')!='SWAP' or x.get('state')!='live' or x.get('ctType')!='linear' or x.get('settleCcy')!='USDT':
   exclusions['NOT_LIVE_LINEAR_USDT_SWAP']+=1;continue
  # OKX documents instCategory=1 as crypto; unknown values fail closed.
  if x.get('instCategory')!='1':exclusions['NON_CRYPTO_OR_UNKNOWN_CATEGORY']+=1;continue
  base=x.get('ctValCcy')
  if not isinstance(base,str) or not re.fullmatch(r'[A-Z0-9]{1,30}',base):exclusions['INVALID_BASE']+=1;continue
  ticker=_okx_ticker(ticks.get(symbol),now_ms);compatible=False
  try:
   symbol_ok(symbol);parse_instrument({'code':'0','data':[x]},symbol,min_notional='0');compatible=True
  except (ValueError,TypeError,KeyError,ArithmeticError):pass
  screen=compatible and x.get('ruleType')=='normal' and ticker.get('status')=='FRESH' and Decimal(ticker['spread_bps'])<=30
  result.append({'venue':'OKX','symbol':symbol,'base':base,'quote':'USDT','product':'PERPETUAL','asset_class':'CRYPTO_AS_REPORTED_BY_OKX','market_rule_type':x.get('ruleType'),
   'contract_value':x.get('ctVal'),'contract_value_currency':base,'contract_multiplier':x.get('ctMult'),
   'contract_lot':x.get('lotSz'),'contract_min':x.get('minSz'),'price_tick':x.get('tickSz'),
   'ticker':ticker,'okx_engine_metadata_compatible':compatible,'okx_preliminary_candidate':screen})
 return result,dict(exclusions)

def normalize_binance(instruments,tickers,now_ms):
 inst=_unique(_rows(instruments,'BINANCE_INSTRUMENTS'),'symbol')
 ticks=_unique(_rows(tickers,'BINANCE_TICKERS'),'symbol') if tickers is not None else {}
 result=[];exclusions=Counter()
 for symbol,x in sorted(inst.items()):
  if x.get('status')!='TRADING' or x.get('contractType')!='PERPETUAL' or x.get('marginAsset')!='USDT' or x.get('quoteAsset')!='USDT':
   exclusions['NOT_TRADING_USDT_PERPETUAL']+=1;continue
  if x.get('underlyingType')!='COIN':exclusions['NON_COIN_OR_UNKNOWN_UNDERLYING']+=1;continue
  base=x.get('baseAsset')
  if not isinstance(base,str) or not 1<=len(base)<=30 or not all(ch.isalnum() for ch in base):exclusions['INVALID_BASE']+=1;continue
  # Filters retained as exchange metadata; never interpreted as trade permission.
  filters=x.get('filters');filters=filters if isinstance(filters,list) else []
  selected=[f for f in filters if isinstance(f,dict) and f.get('filterType') in ('PRICE_FILTER','LOT_SIZE','MARKET_LOT_SIZE','MIN_NOTIONAL','NOTIONAL')]
  result.append({'venue':'BINANCE','symbol':symbol,'base':base,'quote':'USDT','product':'PERPETUAL',
   'asset_class':'COIN_AS_REPORTED_BY_BINANCE','filters':selected,'ticker':_binance_ticker(ticks.get(symbol),now_ms),'paper_engine_connected':False})
 return result,dict(exclusions)

def scan(fetch=None,clock_ms=None,binance_host='fapi',venues=('OKX','BINANCE')):
 """Fetch at most four bulk endpoints once; isolated failures stay explicit."""
 if binance_host not in ('fapi','www'):raise ValueError('invalid Binance host')
 if not isinstance(venues,(tuple,list)) or not venues or len(set(venues))!=len(venues) or any(v not in ('OKX','BINANCE') for v in venues):raise ValueError('invalid venue selection')
 clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)
 if fetch is None:fetch=lambda key:fetch_public(key,binance_host=binance_host)
 results={};statuses={}
 for key in URLS:
  if key.split('_',1)[0] not in venues:
   statuses[key]={'status':'SKIPPED_BY_SELECTION'};continue
  # If metadata failed, don't waste ticker weight or imply partial coverage.
  if key.endswith('TICKERS') and key.replace('TICKERS','INSTRUMENTS') not in results:
   statuses[key]={'status':'SKIPPED_METADATA_UNAVAILABLE'};continue
  try:
   obj=fetch(key);rows=_rows(obj,key)
   if key.endswith('TICKERS'):_unique(rows,'instId' if key.startswith('OKX') else 'symbol')
   results[key]=obj;statuses[key]={'status':'OK'}
  except urllib.error.HTTPError as e:statuses[key]={'status':'HTTP_ERROR','http_status':e.code}
  except (OSError,ValueError,TypeError,KeyError,UnicodeError,json.JSONDecodeError) as e:statuses[key]={'status':'ERROR','error_type':type(e).__name__}
 now=clock_ms()
 if type(now) is not int or now<=0:raise ValueError('invalid clock')
 markets=[];exclusions={}
 for venue,fn in (('OKX',normalize_okx),('BINANCE',normalize_binance)):
  ikey=venue+'_INSTRUMENTS';tkey=venue+'_TICKERS'
  if ikey not in results:continue
  try:
   parsed,exc=fn(results[ikey],results.get(tkey),now);markets.extend(parsed);exclusions[venue]=exc
  except (ValueError,TypeError,KeyError,ArithmeticError):
   statuses[ikey]={'status':'INVALID_PAYLOAD'};exclusions[venue]={'ALL_REJECTED':True}
 counts=Counter(m['venue'] for m in markets)
 counts_per_ticker=Counter(m['venue']+':'+m['ticker']['status'] for m in markets)
 return {'schema':'acar.market-universe.v1','captured_at_ms':now,'mode':'PUBLIC_READ_ONLY_NO_PAPER','endpoints':statuses,
  'binance_public_host':'https://'+('www' if binance_host=='www' else 'fapi')+'.binance.com',
  'counts':{'total_contracts':len(markets),'by_venue':dict(counts),'ticker_status':dict(counts_per_ticker),
   'okx_preliminary_candidates':sum(m.get('okx_preliminary_candidate',False) for m in markets)},
  'exclusions':exclusions,'markets':markets,
  'warnings':['Snapshots are not executable quotes, strategy signals or paper trades.',
              'Same base across exchanges is not necessarily the same asset or contract; asset classification is the venue declaration.',
              'www.binance.com/fapi is an explicit compatibility option; not listed as the documented USD-M REST base. No permission or compliance guarantee.',
              'Binance market data and research only; no Binance paper engine or settlement integration.',
              'OKX candidate requires fresh full history, depth, funding and all risk checks before any later paper test.']}
