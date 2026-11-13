from .indicators import enrich

def bias(df):
    x=enrich(df); r=x.iloc[-1]
    if r.ema20>r.ema50 and r.ema50>r.ema200 and r.close>r.vwap: return 'LONG'
    if r.ema20<r.ema50 and r.ema50<r.ema200 and r.close<r.vwap: return 'SHORT'
    return 'NEUTRAL'
def consensus(frames):
    votes=[bias(df) for df in frames]
    if votes.count('LONG')>=2 and votes.count('SHORT')==0:return 'LONG'
    if votes.count('SHORT')>=2 and votes.count('LONG')==0:return 'SHORT'
    if votes.count('LONG') and votes.count('SHORT'):return 'MIXED'
    return 'NEUTRAL'
