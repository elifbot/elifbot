import asyncio
import pytest
from portfolio.orderbook_shadow import measure, snapshot

def test_buy_asks_sell_bids_and_partial_book():
    bid=[['99','1'],['98','1']]; ask=[['101','1'],['102','1']]
    buy=measure(bid,ask,'LONG',150)
    sell=measure(bid,ask,'SHORT',150)
    assert buy['vwap']==pytest.approx((101+0.5*102)/1.5)
    assert sell['vwap']==pytest.approx((99+0.5*98)/1.5)
    assert buy['complete'] and sell['complete']
    partial=measure(bid,ask,'LONG',500)
    assert not partial['complete'] and partial['fill_fraction']==pytest.approx(0.4)

def test_okx_contract_multiplier():
    book=measure([['99', '100']],[['101','100']], 'LONG',100, factor=0.01)
    assert book['filled_qty'] == pytest.approx(1) and book['complete']

def test_crossed_or_empty_book_rejected():
    with pytest.raises(ValueError): measure([['100','1']],[['99','1']],'LONG',100)
    with pytest.raises(ValueError): measure([], [['100','1']],'SHORT',100)

class R:
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    def raise_for_status(self): pass
    async def json(self): return {'E':1000,'bids':[['99','2']],'asks':[['101','2']]}
class S:
    def get(self,*args,**kwargs): return R()

def test_stale_book_is_rejected():
    with pytest.raises(ValueError,match='bayat'):
        asyncio.run(snapshot(S(),'binance','BTCUSDT','LONG',100,now_ms=10000))
