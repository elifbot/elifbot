import argparse, pandas as pd, numpy as np
from .config import load_config
from .strategy import analyze

def run(path,symbol):
    df=pd.read_csv(path); required={'ts','open','high','low','close','volume'}
    miss=required-set(df.columns)
    if miss: raise ValueError(f'CSV eksik: {miss}')
    cfg=load_config(); eq=cfg['paper']['initial_cash']; trades=[]
    for i in range(210,len(df)-1):
        hist=df.iloc[:i].copy(); snap={'price':float(hist.close.iloc[-1]),'bid':float(hist.close.iloc[-1]),'ask':float(hist.close.iloc[-1]),'spread_bps':2,'funding':0,'oi':1,'oi_prev':1,'depth_imbalance':0,'data_age_sec':0}
        a=analyze(hist,snap,cfg)
        if a['side']=='FLAT' or a['vetoes']: continue
        nxt=float(df.close.iloc[i+1]); pnl=(nxt-a['entry']) if a['side']=='LONG' else (a['entry']-nxt); ret=pnl/a['entry']; trades.append(ret)
    arr=np.array(trades); print({'symbol':symbol,'trades':len(arr),'net_return':float(arr.sum()) if len(arr) else 0,'win_rate':float((arr>0).mean()) if len(arr) else 0,'avg_trade':float(arr.mean()) if len(arr) else 0,'max_loss_streak':max_streak(arr)})
def max_streak(a):
    best=cur=0
    for x in a:
        cur=cur+1 if x<0 else 0; best=max(best,cur)
    return best
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--csv',required=True); p.add_argument('--symbol',default='BTCUSDT'); a=p.parse_args(); run(a.csv,a.symbol)
