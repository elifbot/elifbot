import pandas as pd, numpy as np
from src.indicators import enrich
from src.strategy import analyze
from src.risk import plan

def df():
    n=260; x=np.linspace(100,140,n)+np.sin(np.arange(n)/4); return pd.DataFrame({'ts':np.arange(n)*300000,'open':x,'high':x+1,'low':x-1,'close':x,'volume':np.linspace(100,200,n),'trades':100,'taker_buy_volume':np.linspace(55,110,n)})
def cfg():
    import yaml; return yaml.safe_load(open('config.yaml'))
def test_indicators_no_crash(): assert enrich(df()).iloc[-1].ema20>0
def test_strategy_returns_contract():
    a=analyze(df(),{'price':140,'spread_bps':2,'funding':0,'oi':100,'oi_prev':100,'depth_imbalance':0.2,'data_age_sec':0},cfg()); assert a['side'] in {'LONG','SHORT','FLAT'}
def test_risk_positive():
    a={'side':'LONG','entry':100,'stop':95,'target':110}; p,why=plan(a,1000,cfg()); assert why=='ok' and p['qty']>0

def test_fixed_trade_sizing_contract():
    a={'side':'LONG','entry':100,'stop':99,'target':110}
    p,why=plan(a,1000,cfg()); assert why=='ok'; assert round(p['margin'],2)==50.0; assert round(p['notional'],2)==500.0; assert p['leverage']==10; assert round(p['risk_cash'],2)==20.0
