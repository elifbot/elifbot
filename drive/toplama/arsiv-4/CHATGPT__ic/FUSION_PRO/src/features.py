import numpy as np

def taker_imbalance(df,n=20):
    total=df.volume.rolling(n).sum(); buy=df.taker_buy_volume.rolling(n).sum(); return float(((2*buy-total)/total.replace(0,np.nan)).iloc[-1])
def volume_zscore(df,n=30):
    v=df.volume; mu=v.rolling(n).mean(); sd=v.rolling(n).std(); return float(((v.iloc[-1]-mu.iloc[-1])/sd.iloc[-1]) if sd.iloc[-1] else 0.0)
def bb_width_pct(row): return float((row.bb_hi-row.bb_lo)/row.close*100) if row.close else 0.0
def oi_price_context(price_now, price_prev, oi_now, oi_prev):
    pr=(price_now/price_prev-1) if price_prev else 0; oi=(oi_now/oi_prev-1) if oi_prev else 0
    if pr>0 and oi>0: label='long_build'
    elif pr<0 and oi>0: label='short_build'
    elif pr>0 and oi<0: label='short_cover'
    elif pr<0 and oi<0: label='long_unwind'
    else: label='neutral'
    return pr,oi,label
def expected_edge_bps(atr_pct, score, spread_bps, fee_bps, slippage_bps):
    gross=max(0.0, atr_pct*10000*0.22*(score/10)); return gross-spread_bps-fee_bps-slippage_bps
