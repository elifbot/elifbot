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
