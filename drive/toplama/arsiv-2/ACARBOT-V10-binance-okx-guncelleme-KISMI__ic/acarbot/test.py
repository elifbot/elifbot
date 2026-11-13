"""Ağsız testler: python -m pytest acarbot/test.py"""
from omnistudio.core.types import Candle, Side, Quote
from acarbot.strategy import decide, closed_candles, ema_series, bollinger
from acarbot.ledger import Ledger

def bars(n=260):
    return [Candle('BTC_USDT','gateio',i*300000,100+i*.1,101+i*.1,99+i*.1,100+i*.1,100 if i<n-1 else 200,True) for i in range(n)]

def test_ema(): assert ema_series([1,2,3],3)==[1,1.5,2.25]
def test_bollinger(): assert bollinger([4]*20)==(4,4)
def test_closed_does_not_use_open_bar():
    c=bars(); now=c[-1].open_ms+1
    assert len(closed_candles(c,now))==259
    assert closed_candles(c,now)[-1]==c[-2]
def test_warmup(): assert decide(bars(10), 3000000).reason=='INSUFFICIENT_CLOSED_BARS'
def test_trend_long():
    c=bars(); r=decide(c,c[-1].open_ms+300001)
    assert r.side is Side.LONG and r.volume_ratio==2

def test_stale_is_rejected():
    c=bars(); assert decide(c,c[-1].open_ms+400000).reason=='STALE_CANDLE'

def test_gap_is_rejected():
    c=bars(); del c[-10]; assert decide(c,c[-1].open_ms+300001).reason=='CANDLE_GAP'

def test_volume_required():
    c=bars(); c[-1]=Candle('BTC_USDT','gateio',c[-1].open_ms,126,127,125,126,1,True)
    assert decide(c,c[-1].open_ms+300001).reason=='VOLUME_CONFIRMATION'

def test_ledger_long_costs_and_stop():
    l=Ledger(); q=Quote('gateio','BTC_USDT',99.99,100.01,1000)
    p=l.open(q,Side.LONG,1,1000); assert p and p.entry>q.ask
    result=l.on_quote(Quote('gateio','BTC_USDT',97,97.02,2000),2000)
    assert result.reason=='STOP_LOSS' and result.net<0 and result.exit_fee>0
    assert not l.positions and len(l.closed)==1

def test_ledger_short_profit():
    l=Ledger(); p=l.open(Quote('gateio','ETH_USDT',100,100.01,1000),Side.SHORT,1,1000)
    q=Quote('gateio','ETH_USDT',94.7,94.8,2000); x=l.on_quote(q,2000)
    assert p and x.reason=='TAKE_PROFIT' and x.net>0

def test_no_duplicate_symbol():
    l=Ledger(); q=Quote('gateio','BTC_USDT',100,100.01,1000)
    assert l.open(q,Side.LONG,1,1000); assert l.open(q,Side.LONG,1,1001) is None

def test_trailing_stop_only_tightens():
    l=Ledger(); p=l.open(Quote('gateio','BTC_USDT',100,100.01,1000),Side.LONG,1,1000)
    old=p.stop
    l.on_quote(Quote('gateio','BTC_USDT',102.8,102.81,2000),2000)
    assert p.breakeven and p.stop>old and p.stop>p.entry
    tightened=p.stop
    l.on_quote(Quote('gateio','BTC_USDT',102.7,102.71,3000),3000)
    assert p.stop==tightened

def test_crypto_universe_not_metals_or_stocks():
    from acarbot.runner import CRYPTO_UNIVERSE
    assert 'BTC_USDT' in CRYPTO_UNIVERSE and 'XAU_USDT' not in CRYPTO_UNIVERSE and 'QQQ_USDT' not in CRYPTO_UNIVERSE

def test_invalid_ohlc_is_rejected():
    c=bars(); v=c[-1]
    c[-1]=Candle(v.symbol,v.exchange,v.open_ms,v.open,v.open-1,v.low,v.close,v.quote_volume,True)
    assert decide(c,v.open_ms+300001).reason=='BAD_CANDLE'

def test_exchange_discovery_filters_inactive_and_keys_separate():
    from acarbot.futures_market import instruments
    b=instruments('binance_usdm',{'symbols':[{'symbol':'BTCUSDT','status':'TRADING','marginAsset':'USDT','contractType':'PERPETUAL'},{'symbol':'OLD','status':'BREAK'}]})
    o=instruments('okx_swap',{'code':'0','data':[{'instId':'BTC-USDT-SWAP','state':'live','ctType':'linear','settleCcy':'USDT','ctVal':'0.01'},{'instId':'OLD','state':'suspend'}]})
    assert len(b)==len(o)==1 and b[0].key!=o[0].key

def test_okx_candle_closed_and_quote_volume():
    from acarbot.futures_market import candles,Instrument
    ins=Instrument('okx','okx_swap','BTC-USDT-SWAP','USDT','linear','0.01','live')
    data={'code':'0','data':[['300000','10','12','9','11','500','5','55','0'],['0','9','11','8','10','200','2','20','1']]}
    rows=candles(ins,data); assert rows[0].closed and not rows[1].closed and rows[0].quote_volume==20

def test_usdm_coinm_volume_units():
    from acarbot.futures_market import candles,Instrument
    r=[[0,'100','101','99','100','1',299999,'2']]
    a=Instrument('binance','binance_usdm','X','USDT','PERPETUAL','','TRADING')
    b=Instrument('binance','binance_coinm','X','BTC','PERPETUAL','','TRADING')
    assert candles(a,r)[0].quote_volume==2 and candles(b,r)[0].quote_volume==200

def test_invalid_exchange_response_fails_closed():
    from acarbot.futures_market import instruments
    import pytest
    with pytest.raises(ValueError): instruments('okx_swap',{'code':'1','msg':'bad'})
    with pytest.raises(ValueError): instruments('binance_usdm',{})

def test_paper_trade_excludes_inverse_and_expiry():
    from acarbot.futures_market import Instrument
    from acarbot.futures_paper import paper_eligible
    assert paper_eligible(Instrument('okx','okx_swap','BTC-USDT-SWAP','USDT','linear','0.01','live'))
    assert not paper_eligible(Instrument('okx','okx_swap','BTC-USD-SWAP','BTC','inverse','100','live'))
    assert not paper_eligible(Instrument('okx','okx_futures','BTC-USD-X','USD','linear','1','live'))
    assert paper_eligible(Instrument('binance','binance_usdm','BTCUSDT','USDT','PERPETUAL','','TRADING'))
