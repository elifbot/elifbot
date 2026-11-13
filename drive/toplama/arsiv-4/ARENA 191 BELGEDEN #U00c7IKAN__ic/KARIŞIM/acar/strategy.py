"""Yalnız mevcut ve geçmiş kapanışlardan hesaplanan gösterge oyları."""
from dataclasses import dataclass

def ema(values, period):
    if not values or period<1: raise ValueError('geçersiz EMA girdisi')
    a=2/(period+1); v=values[0]
    for x in values[1:]: v=a*x+(1-a)*v
    return v

def rsi(values, period=14):
    if len(values)<period+1: return None
    changes=[b-a for a,b in zip(values,values[1:])]
    gain=sum(max(0,x) for x in changes[:period])/period
    loss=sum(max(0,-x) for x in changes[:period])/period
    for x in changes[period:]:
        gain=(gain*(period-1)+max(0,x))/period
        loss=(loss*(period-1)+max(0,-x))/period
    if loss==0: return 50.0 if gain==0 else 100.0
    return 100-100/(1+gain/loss)

def atr(bars, period=14):
    if len(bars)<period+1: return None
    trs=[max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(bars,bars[1:])]
    v=sum(trs[:period])/period
    for x in trs[period:]: v=(v*(period-1)+x)/period
    return v

def closed_htf_closes(bars, factor):
    """UTC'ye hizalı, tam ve kesintisiz yüksek zaman pencerelerinin kapanışları.

    Mum zamanları açılış zamanıdır; dizi sonundaki eksik kova kullanılmaz.
    Stratejinin içinde çağırıldığından bars yalnızca görülmüş mumları içerir.
    """
    if isinstance(factor,bool) or not isinstance(factor,int) or factor<2: raise ValueError('factor >=2')
    if len(bars)<factor or len(bars)<2: return []
    interval=bars[1].timestamp-bars[0].timestamp
    if interval<=0: return []
    width=interval*factor; result=[]; i=0
    while i+factor<=len(bars):
        first=bars[i].timestamp
        if first%width:
            i+=1;continue
        bucket=bars[i:i+factor]
        if all(b.timestamp==first+j*interval for j,b in enumerate(bucket)):
            result.append(bucket[-1].close)
            i+=factor
        else:
            i+=1
    return result

@dataclass(frozen=True)
class Signal:
    side: str
    atr: float
    votes: dict

class Confluence:
    """EMA, RSI, MACD, hacim ve tamamlanmış üst zaman dilimi filtresi.
    Üst zaman kovaları UTC zamanına hizalı, tam ve kesintisiz olmalıdır.
    """
    def __init__(self, threshold=3, higher_factor=5):
        if not isinstance(threshold,int) or isinstance(threshold,bool) or threshold not in (2,3,4): raise ValueError('threshold 2..4')
        if not isinstance(higher_factor,int) or isinstance(higher_factor,bool) or higher_factor<2: raise ValueError('higher_factor >=2')
        self.threshold=threshold; self.higher_factor=higher_factor
    def __call__(self,bars):
        if len(bars)<max(35, 10*self.higher_factor): return None
        closes=[b.close for b in bars]; last=bars[-1]
        a=atr(bars); r=rsi(closes)
        if not a or a<=0 or r is None: return None
        ef,es=ema(closes,9),ema(closes,21)
        macd=ema(closes,12)-ema(closes,26)
        avg_vol=sum(b.volume for b in bars[-21:-1])/20
        # Sadece tam bitmiş üst zaman dilimi gruplarının kapanışlarını kullan.
        completed=closed_htf_closes(bars,self.higher_factor)
        if len(completed)<10: return None
        higher=ema(completed,10)
        for side,sign in [('long',1),('short',-1)]:
            votes={'ema': sign*(ef-es)>0,
                   'rsi': 50<r<75 if sign==1 else 25<r<50,
                   'macd': sign*macd>0,
                   'volume': last.volume>avg_vol}
            if sum(votes.values())>=self.threshold and sign*(completed[-1]-higher)>0:
                return Signal(side,a,votes)
        return None

class Breakout:
    """Geçmiş kanaldan çıkış + hacim ve EMA eğilimi, yalnız kapanışta."""
    def __init__(self, period=20):
        if isinstance(period,bool) or not isinstance(period,int) or period<5: raise ValueError('breakout period >= 5')
        self.period=period
    def __call__(self,bars):
        if len(bars)<max(self.period+1,35): return None
        current=bars[-1]; history=bars[-self.period-1:-1]
        closes=[b.close for b in bars]; a=atr(bars)
        if not a or a<=0:return None
        average_volume=sum(b.volume for b in history)/len(history)
        volume_ok=current.volume>average_volume
        avg=ema(closes,21)
        if current.close>max(b.high for b in history) and current.close>avg and volume_ok:
            return Signal('long',a,{'channel_break':True,'ema':True,'volume':True})
        if current.close<min(b.low for b in history) and current.close<avg and volume_ok:
            return Signal('short',a,{'channel_break':True,'ema':True,'volume':True})
        return None
