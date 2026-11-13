import asyncio
import pytest
from data.extended.funding_events import FundingWatcher, PARTIAL
from portfolio.paper_futures import PaperPortfolio
from logger.trade_logger import TradeLogger

class Resp:
    def __init__(self, data): self.data = data
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    def raise_for_status(self): pass
    async def json(self): return self.data

class Session:
    def __init__(self, fn): self.fn=fn
    def get(self,url,params,timeout,**kwargs): return Resp(self.fn(url,params))

def portfolio(ex='binance',sym='BTCUSDT',side='LONG',t=100_000):
    p=PaperPortfolio(starting_balance=1000)
    assert p.open_position(ex,sym,side,100,25,leverage=5,now_ms=t).ok
    return p

def test_binance_funding_dedup_and_no_old_mark_overwrite(tmp_path):
    p=portfolio(); pos=p.positions[('binance','BTCUSDT')]
    p.mark_price('binance','BTCUSDT',111,201000)
    before=p.balance
    rows=[{'symbol':'BTCUSDT','fundingTime':200000,'fundingRate':'0.001','markPrice':'105'}]
    session=Session(lambda url,params: rows)
    w=FundingWatcher(p,journal_path=str(tmp_path/'funding.csv'))
    asyncio.run(w.poll_once(session,210000)); asyncio.run(w.poll_once(session,220000))
    assert p.balance == pytest.approx(before-105*pos.qty_base*0.001)
    assert pos.last_price == 111 and pos.last_price_ts == 201000
    assert pos.last_funding_ts == 200000 and pos.funding_label == PARTIAL
    assert w.applied == 1
    assert len((tmp_path/'funding.csv').read_text().splitlines()) == 2
    r=p.close_position('binance','BTCUSDT',111,now_ms=230000)
    assert TradeLogger(str(tmp_path/'trades.csv'))._row(r)['funding_fee'] == pytest.approx(105*pos.qty_base*0.001)

def test_new_position_never_pays_earlier_event():
    p=portfolio(t=300000); before=p.balance
    w=FundingWatcher(p)
    session=Session(lambda url,params:[{'symbol':'BTCUSDT','fundingTime':200000,'fundingRate':'0.001','markPrice':'105'}])
    asyncio.run(w.poll_once(session,400000))
    assert p.balance == before and w.applied == 0

def test_okx_realized_rate_and_minute_open_approximation():
    p=portfolio('okx','BTC-USDT-SWAP',side='SHORT',t=100000)
    before=p.balance; pos=p.positions[('okx','BTC-USDT-SWAP')]
    def result(url,params):
        if 'funding-rate-history' in url:
            return {'code':'0','data':[{'instId':'BTC-USDT-SWAP','fundingTime':'120000','realizedRate':'0.002'}]}
        return {'code':'0','data':[['120000','102','103','101','102','1']]}
    w=FundingWatcher(p);asyncio.run(w.poll_once(Session(result),180000))
    assert p.balance == pytest.approx(before+102*pos.qty_base*0.002)
    assert pos.funding_label == PARTIAL and pos.last_funding_ts == 120000

def test_bad_data_no_silent_zero_or_dedup_advance():
    p=portfolio();w=FundingWatcher(p)
    asyncio.run(w.poll_once(Session(lambda u,p:{'code':-1003}),200000))
    assert w.errors == 1 and w.last_error and w.applied == 0
    assert p.positions[('binance','BTCUSDT')].last_funding_ts == 0
