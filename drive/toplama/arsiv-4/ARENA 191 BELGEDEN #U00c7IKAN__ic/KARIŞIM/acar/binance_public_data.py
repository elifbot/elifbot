"""Read-only Binance USD-M details for research; NOT linked to PAPER execution.
Endpoint availability and interpretations must be validated in the user's region.
"""
import json,re,threading,time,urllib.parse,urllib.request
from decimal import Decimal
from .data import Bar,validate_bars
from .depth_research import dec,fmt
from .market_universe import NoRedirect

BASE='https://fapi.binance.com';PATHS={'klines':'/fapi/v1/klines','depth':'/fapi/v1/depth','premium':'/fapi/v1/premiumIndex'}
def symbol_ok(symbol):
 if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z0-9]{1,25}USDT',symbol):raise ValueError('invalid Binance USDT symbol')
 return symbol

def parse_candles(rows,*,now_ms):
 if type(now_ms) is not int or not isinstance(rows,list) or len(rows)>1500:raise ValueError('invalid candles')
 bars=[]
 for r in rows:
  if not isinstance(r,list) or len(r)<7 or type(r[0]) is not int or type(r[6]) is not int:raise ValueError('invalid kline row')
  t=r[0]
  if t<0 or t%60000 or r[6]!=t+59999:raise ValueError('invalid candle time')
  if t>now_ms:raise ValueError('future candle')
  if t+60000>now_ms:continue
  try:bars.append(Bar(t//1000,float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])))
  except (ValueError,TypeError,OverflowError):raise ValueError('invalid OHLCV') from None
 if not bars:raise ValueError('no closed candles')
 bars.sort(key=lambda b:b.timestamp);validate_bars(bars,60);return bars

def parse_depth(payload,*,symbol,now_ms,max_age_ms=20000):
 symbol_ok(symbol)
 if not isinstance(payload,dict) or type(now_ms) is not int or type(max_age_ms) is not int or not 0<=max_age_ms<=60000:raise ValueError('invalid depth')
 ts=payload.get('E');update=payload.get('lastUpdateId')
 if type(ts) is not int or type(update) is not int or update<0 or ts>now_ms or now_ms-ts>max_age_ms:raise ValueError('invalid or stale depth time')
 def side(key,reverse):
  rows=payload.get(key)
  if not isinstance(rows,list) or not 1<=len(rows)<=1000:raise ValueError('empty depth')
  result=[];prev=None
  for row in rows:
   if not isinstance(row,list) or len(row)!=2:raise ValueError('invalid depth level')
   px=dec(row[0],'price',positive=True);qty=dec(row[1],'quantity',positive=True)
   if prev is not None and (px>=prev if reverse else px<=prev):raise ValueError('depth not strictly sorted')
   result.append([fmt(px),fmt(qty)]);prev=px
  return result
 bids=side('bids',True);asks=side('asks',False)
 if Decimal(bids[0][0])>Decimal(asks[0][0]):raise ValueError('crossed book')
 return {'venue':'BINANCE','symbol':symbol,'event_time_ms':ts,'last_update_id':update,'bids':bids,'asks':asks,
         'warning':'Public snapshot; no contract sizing, execution or order-book stream guarantee.'}

def parse_premium(payload,*,symbol,now_ms,max_age_ms=60000):
 symbol_ok(symbol)
 if not isinstance(payload,dict) or payload.get('symbol')!=symbol or type(now_ms) is not int or type(max_age_ms) is not int or not 0<=max_age_ms<=600000:raise ValueError('invalid premium response')
 ts=payload.get('time');nxt=payload.get('nextFundingTime')
 if type(ts) is not int or type(nxt) is not int or ts>now_ms or now_ms-ts>max_age_ms or nxt<=now_ms:raise ValueError('stale premium data')
 mark=dec(payload.get('markPrice'),'markPrice',positive=True);index=dec(payload.get('indexPrice'),'indexPrice',positive=True);rate=dec(payload.get('lastFundingRate'),'lastFundingRate')
 if abs(rate)>1:raise ValueError('invalid funding rate')
 return {'symbol':symbol,'time_ms':ts,'next_funding_time_ms':nxt,'mark_price':fmt(mark),'index_price':fmt(index),
         'last_funding_rate':fmt(rate),'rate_semantics':'LATEST_RATE_NOT_SETTLEMENT_PROOF'}

class BinancePublicDetails:
 def __init__(self,transport=None,*,binance_host='fapi'):
  if binance_host not in ('fapi','www'):raise ValueError('invalid Binance public host')
  self.base='https://'+binance_host+'.binance.com';self.transport=transport or self._request;self._lock=threading.Lock();self._last=0.;self._throttle=transport is None
 @staticmethod
 def _request(url):
  req=urllib.request.Request(url,headers={'User-Agent':'ACAR-Market-Research/1','Accept':'application/json'})
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=15) as r:
   raw=r.read(2_000_001)
   if len(raw)>2_000_000:raise ValueError('response too large')
   return json.loads(raw.decode('utf-8'))
 def get(self,kind,*,symbol,limit=None):
  symbol_ok(symbol)
  if kind not in PATHS:raise ValueError('endpoint not permitted')
  params={'symbol':symbol}
  if kind=='klines':
   if type(limit) is not int or not 1<=limit<=1500:raise ValueError('invalid candle limit')
   params.update(interval='1m',limit=limit)
  elif kind=='depth':
   if type(limit) is not int or limit not in (5,10,20,50,100):raise ValueError('invalid depth limit')
   params['limit']=limit
  elif limit is not None:raise ValueError('unexpected limit')
  url=self.base+PATHS[kind]+'?'+urllib.parse.urlencode(params)
  with self._lock:
   if self._throttle:
    delay=.25-(time.monotonic()-self._last)
    if delay>0:time.sleep(delay)
   try:return self.transport(url)
   finally:self._last=time.monotonic()
 def _observation_clock(self,requested_ms):
  if type(requested_ms) is not int:raise ValueError('invalid clock')
  return time.time_ns()//1_000_000 if self._throttle else requested_ms
 def candles(self,symbol,*,now_ms,limit=300):
  raw=self.get('klines',symbol=symbol,limit=limit);return parse_candles(raw,now_ms=self._observation_clock(now_ms))
 def complete_history(self,symbol,*,now_ms,minimum=220):
  if type(minimum) is not int or minimum<220 or minimum>1500:raise ValueError('invalid warmup')
  bars=self.candles(symbol,now_ms=now_ms,limit=1500)
  last=bars[-1].timestamp;required=min((last//86400)*86400,last-(minimum-1)*60)
  if bars[0].timestamp>required:raise ValueError('incomplete UTC history')
  selected=[b for b in bars if b.timestamp>=required]
  validate_bars(selected,60)
  if len(selected)<minimum or selected[0].timestamp!=required:raise ValueError('insufficient history')
  return selected
 def depth(self,symbol,*,now_ms,limit=20):
  raw=self.get('depth',symbol=symbol,limit=limit);return parse_depth(raw,symbol=symbol,now_ms=self._observation_clock(now_ms))
 def premium(self,symbol,*,now_ms):
  raw=self.get('premium',symbol=symbol);return parse_premium(raw,symbol=symbol,now_ms=self._observation_clock(now_ms))
