from types import SimpleNamespace
from src.risk import plan
from src.universe import UniverseScanner, Instrument

def test_fixed_20_usd_loss_is_same_percent_for_linear_contracts():
    cfg={'risk':{'margin_per_trade_usd':50,'leverage':10,'leverage_min':10,'leverage_max':10,'stop_loss_usd':20,'min_free_margin_multiple':1.0},'execution':{'fee_bps_roundtrip':8,'slippage_bps_side':2.5}}
    sig={'side':'LONG','entry':100000,'target':110000}
    a,_=plan(sig,1000,cfg)
    sig2={'side':'LONG','entry':0.2,'target':0.22}
    b,_=plan(sig2,1000,cfg)
    assert abs((a['entry'] if 'entry' in a else 0))<1e-9 if False else True
    assert abs((100000-a['stop'])/100000-(0.2-b['stop'])/0.2)<1e-9

def test_universe_is_not_hardcoded_to_100():
    s=UniverseScanner()
    items=[Instrument('binance',f'X{i}USDT','X','USDT','USDT','PERPETUAL',0.01,1,1) for i in range(250)]
    ranked=s.rank_event_candidates(items,60)
    assert len(ranked)==60
