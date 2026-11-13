import numpy as np, pandas as pd

def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0); rs=up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,np.nan); return 100-100/(1+rs)
def atr(df,n=14):
    pc=df.close.shift(); tr=pd.concat([df.high-df.low,(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/n,adjust=False).mean()
def macd(s):
    m=ema(s,12)-ema(s,26); sig=ema(m,9); return m,sig,m-sig
def adx(df,n=14):
    h,l,c=df.high,df.low,df.close; up=h.diff(); dn=-l.diff(); tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atrv=tr.ewm(alpha=1/n,adjust=False).mean(); p=(up.where((up>dn)&(up>0),0)).ewm(alpha=1/n,adjust=False).mean(); m=(dn.where((dn>up)&(dn>0),0)).ewm(alpha=1/n,adjust=False).mean(); pdi=100*p/atrv; mdi=100*m/atrv; dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan); return dx.ewm(alpha=1/n,adjust=False).mean()
def bollinger(s,n=20,k=2):
    mid=s.rolling(n).mean(); sd=s.rolling(n).std(); return mid,mid+k*sd,mid-k*sd
def vwap(df,n=30):
    pv=(df.close*df.volume).rolling(n).sum(); vv=df.volume.rolling(n).sum(); return pv/vv.replace(0,np.nan)
def stoch(df,n=14):
    lo=df.low.rolling(n).min(); hi=df.high.rolling(n).max(); k=100*(df.close-lo)/(hi-lo).replace(0,np.nan); d=k.rolling(3).mean(); return k,d
def obv(df): return (np.sign(df.close.diff()).fillna(0)*df.volume).cumsum()
def cci(df,n=20):
    tp=(df.high+df.low+df.close)/3; ma=tp.rolling(n).mean(); dev=(tp-ma).abs().rolling(n).mean(); return (tp-ma)/(0.015*dev.replace(0,np.nan))
def zscore(s,n=30):
    m=s.rolling(n).mean(); sd=s.rolling(n).std(); return (s-m)/sd.replace(0,np.nan)
def enrich(df):
    x=df.copy(); x['ema20']=ema(x.close,20); x['ema50']=ema(x.close,50); x['ema200']=ema(x.close,200); x['rsi']=rsi(x.close); x['atr']=atr(x); x['adx']=adx(x); x['macd'],x['macd_sig'],x['macd_hist']=macd(x.close); x['bb_mid'],x['bb_hi'],x['bb_lo']=bollinger(x.close); x['vwap']=vwap(x); x['stoch_k'],x['stoch_d']=stoch(x); x['obv']=obv(x); x['cci']=cci(x); x['vol_z']=zscore(x.volume); x['ret1']=x.close.pct_change(); return x
