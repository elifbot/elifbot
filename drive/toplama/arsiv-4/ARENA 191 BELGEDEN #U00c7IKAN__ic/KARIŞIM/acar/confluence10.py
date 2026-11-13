"""Araştırma amaçlı 10 özellikli puanlama. Canlı PAPER kararına bağlı değildir.
Kapalı, kesintisiz 1 dakikalık mum ve UTC gününün tamamı zorunludur.
Eski HTML/Python sürümleriyle birebir parite iddia edilmez.
"""
import math
from .data import validate_bars
from .strategy import Signal,rsi,atr

def ema_series(values,period):
 if not values or not isinstance(period,int) or isinstance(period,bool) or period<1:raise ValueError('EMA girdisi')
 alpha=2/(period+1);out=[float(values[0])]
 for x in values[1:]:out.append(out[-1]+alpha*(x-out[-1]))
 return out

def _wilder_series(values,period):
 out=[None]*len(values)
 if len(values)<period:return out
 prev=sum(values[:period])/period;out[period-1]=prev
 for i in range(period,len(values)):
  prev=(prev*(period-1)+values[i])/period;out[i]=prev
 return out

def _sma_nullable(values,period):
 out=[None]*len(values)
 for i in range(period-1,len(values)):
  window=values[i-period+1:i+1]
  if all(x is not None for x in window):out[i]=sum(window)/period
 return out

def adx(bars,period=14):
 if len(bars)<period*2+1:return None
 trs=[];plus=[];minus=[]
 for a,b in zip(bars,bars[1:]):
  tr=max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close));up=b.high-a.high;down=a.low-b.low
  trs.append(tr);plus.append(up if up>down and up>0 else 0.0);minus.append(down if down>up and down>0 else 0.0)
 st=_wilder_series(trs,period);sp=_wilder_series(plus,period);sm=_wilder_series(minus,period);dx=[]
 for t,p,m in zip(st,sp,sm):
  if t is None:continue
  if t<=0:dx.append(0.0);continue
  pdi=100*p/t;mdi=100*m/t;dx.append(100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0.0)
 result=_wilder_series(dx,period)
 return result[-1] if result and result[-1] is not None else None

def stochastic(bars,period=14,smooth=3):
 raw=[None]*len(bars)
 for i in range(period-1,len(bars)):
  lo=min(b.low for b in bars[i-period+1:i+1]);hi=max(b.high for b in bars[i-period+1:i+1]);raw[i]=100*(bars[i].close-lo)/(hi-lo) if hi>lo else 50.0
 k=_sma_nullable(raw,smooth);d=_sma_nullable(k,smooth)
 return k,d

def obv(bars):
 out=[0.0]
 for a,b in zip(bars,bars[1:]):out.append(out[-1]+b.volume if b.close>a.close else out[-1]-b.volume if b.close<a.close else out[-1])
 return out

def cci(bars,period=20):
 if len(bars)<period:return None
 x=[(b.high+b.low+b.close)/3 for b in bars[-period:]];mean=sum(x)/period;dev=sum(abs(v-mean) for v in x)/period
 return (x[-1]-mean)/(0.015*dev) if dev else 0.0

def supertrend_direction(bars,period=10,multiplier=3.0):
 if len(bars)<period+1:return None
 tr=[bars[0].high-bars[0].low]+[max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(bars,bars[1:])]
 avgs=_wilder_series(tr,period);upper=lower=None;direction=1
 for i,b in enumerate(bars):
  a=avgs[i]
  if a is None:continue
  mid=(b.high+b.low)/2;up=mid+multiplier*a;lo=mid-multiplier*a
  if upper is None:upper,lower=up,lo;direction=1 if b.close>=mid else -1;continue
  old_up,old_lo=upper,lower;previous=bars[i-1].close
  upper=up if up<old_up or previous>old_up else old_up
  lower=lo if lo>old_lo or previous<old_lo else old_lo
  if direction<0 and b.close>upper:direction=1
  elif direction>0 and b.close<lower:direction=-1
 return direction

def daily_vwap(bars):
 if not bars:return None
 start=bars[-1].timestamp//86400*86400;today=[b for b in bars if b.timestamp>=start]
 if not today or today[0].timestamp!=start:return None
 if any(x.timestamp!=start+i*60 for i,x in enumerate(today)):return None
 vol=sum(x.volume for x in today)
 return sum(((x.high+x.low+x.close)/3)*x.volume for x in today)/vol if vol>0 else None

def confluence_snapshot(bars,threshold=4):
 if isinstance(threshold,bool) or not isinstance(threshold,int) or not 2<=threshold<=8:raise ValueError('threshold 2..8')
 if not bars or len(bars)<220:return {'ready':False,'reason':'INSUFFICIENT_BARS','votes':{}}
 try:validate_bars(bars,60)
 except ValueError:return {'ready':False,'reason':'INVALID_CANDLES','votes':{}}
 closes=[b.close for b in bars];cur=closes[-1]
 vwap=daily_vwap(bars);ad=adx(bars);rs=rsi(closes);at=atr(bars);cc=cci(bars);trend=supertrend_direction(bars)
 k,d=stochastic(bars);ob=obv(bars);obmean=sum(ob[-10:])/10
 if vwap is None:return {'ready':False,'reason':'INCOMPLETE_UTC_VWAP','votes':{},'vwap':None}
 if any(x is None for x in (ad,rs,at,cc,trend,k[-1],k[-2],d[-1],d[-2])) or at<=0:
  return {'ready':False,'reason':'INDICATOR_UNAVAILABLE','votes':{}}
 e20=ema_series(closes,20);e50=ema_series(closes,50);e200=ema_series(closes,200)
 f=ema_series(closes,12);slow=ema_series(closes,26);macd=[x-y for x,y in zip(f,slow)];sig=ema_series(macd,9)
 mean=sum(closes[-20:])/20;sd=math.sqrt(sum((x-mean)**2 for x in closes[-20:])/20)
 votes={
 'ema':1 if e20[-1]>e50[-1]>e200[-1] else -1 if e20[-1]<e50[-1]<e200[-1] else 0,
 'macd_cross':1 if macd[-2]<=sig[-2] and macd[-1]>sig[-1] else -1 if macd[-2]>=sig[-2] and macd[-1]<sig[-1] else 0,
 'rsi':1 if rs>55 else -1 if rs<45 else 0,
 'adx_ema':(1 if e20[-1]>e50[-1] else -1 if e20[-1]<e50[-1] else 0) if ad>25 else 0,
 'stochastic':1 if k[-2]<=d[-2] and k[-1]>d[-1] and k[-1]<80 else -1 if k[-2]>=d[-2] and k[-1]<d[-1] and k[-1]>20 else 0,
 'obv':1 if ob[-1]>obmean and ob[-1]>ob[-2] else -1 if ob[-1]<obmean and ob[-1]<ob[-2] else 0,
 'cci':1 if 0<cc<100 else -1 if -100<cc<0 else 0,
 'supertrend':trend,
 'vwap':1 if cur>vwap else -1 if cur<vwap else 0,
 'bollinger':1 if cur>mean+2*sd else -1 if cur<mean-2*sd else 0}
 score=sum(votes.values());side='long' if score>=threshold else 'short' if score<=-threshold else 'hold'
 return {'ready':True,'reason':'OK','side':side,'score':score,'threshold':threshold,'votes':votes,
         'indicators':{'rsi':rs,'atr':at,'adx':ad,'cci':cc,'vwap':vwap,'stochastic_k':k[-1]},
         'bar_close':bars[-1].timestamp+60,'notice':'Araştırma; canlı karar ve eski sürüm paritesi değildir.'}

class ResearchConfluence10:
 def __init__(self,threshold=4):self.threshold=threshold
 def __call__(self,bars):
  r=confluence_snapshot(bars,self.threshold)
  return Signal(r['side'],r['indicators']['atr'],r['votes']) if r['ready'] and r['side'] in ('long','short') else None
