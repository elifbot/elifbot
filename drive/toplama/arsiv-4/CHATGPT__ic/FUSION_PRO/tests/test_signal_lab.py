import numpy as np, pandas as pd
from src.strategy import analyze

def strong_bull_df(n=260):
    t=np.arange(n); x=100+0.16*t+2*np.sin(t/7)
    return pd.DataFrame({'ts':t*300000,'open':x-0.2,'high':x+1.0,'low':x-1.0,'close':x,'volume':100+2*t,'trades':200,'taker_buy_volume':65+1.2*t})

def cfg():
    import yaml
    return yaml.safe_load(open('config.yaml'))

def test_strong_bull_market_can_generate_tradeable_signal():
    s={'price':141.0,'spread_bps':2.0,'funding':0.0,'oi':101,'oi_prev':100,'depth_imbalance':0.20,'data_age_sec':0,'funding_guard_active':False}
    a=analyze(strong_bull_df(),s,cfg())
    assert a['side']=='LONG'
    assert not a['vetoes']
    assert a['score']>=cfg()['strategy']['min_score']
    assert a['edge_bps']>=cfg()['strategy']['min_edge_bps']
