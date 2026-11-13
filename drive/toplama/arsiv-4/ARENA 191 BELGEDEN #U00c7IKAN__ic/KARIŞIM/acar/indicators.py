"""Kapalı mumlardan yalnız gözlem amaçlı teknik özet; emir kararı vermez."""
from .strategy import ema,rsi,atr,closed_htf_closes

def technical_snapshot(bars):
 if not bars:return {'ready':False,'reason':'CANDLES_UNAVAILABLE'}
 close=[b.close for b in bars];last=bars[-1];ready=len(bars)>=26
 volume_avg=sum(b.volume for b in bars[-21:-1])/20 if len(bars)>=21 else None
 a=atr(bars);r=rsi(close)
 day_start=last.timestamp//86400*86400
 day=[b for b in bars if b.timestamp>=day_start]
 # Son 300 mum UTC gün başına erişmiyorsa kısmi VWAP uydurulmaz.
 complete_day=bool(day and day[0].timestamp==day_start and all(day[i].timestamp==day_start+60*i for i in range(len(day))))
 total_volume=sum(b.volume for b in day) if complete_day else 0
 vwap=(sum(((b.high+b.low+b.close)/3)*b.volume for b in day)/total_volume) if total_volume>0 else None
 higher=closed_htf_closes(bars,5)
 return {'ready':ready,'bar_close':last.timestamp+60,'rsi14':r,'atr14':a,
         'atr_pct':a/last.close*100 if a else None,
         'ema9':ema(close,9) if len(close)>=9 else None,'ema21':ema(close,21) if len(close)>=21 else None,
         'macd_line':ema(close,12)-ema(close,26) if ready else None,
         'relative_volume':last.volume/volume_avg if volume_avg is not None and volume_avg>0 else None,
         'vwap_utc':vwap,'vwap_status':'COMPLETE' if vwap is not None else ('ZERO_VOLUME' if complete_day else 'PARTIAL_DAY'),
         'closed_5m_bars':len(higher),'note':'Bilgi amaçlı özet; işlem onayı veya kârlılık tahmini değildir.'}
