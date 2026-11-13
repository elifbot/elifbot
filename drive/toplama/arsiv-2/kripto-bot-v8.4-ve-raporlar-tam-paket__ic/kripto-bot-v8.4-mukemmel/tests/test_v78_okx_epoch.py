"""Offline OKX subscription ACK and connection-generation regression."""
import asyncio,json,time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import aiohttp
import pytest
from test_v78_onarim_regresyon import bot_factory,bootstrap_candidate
from scanner.v78_okx_stream import OKXPaperAkisi


def test_okx_disconnected_stale_future_out_of_order_and_valid(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);m=b.eski_v78_motor;sym='TEST-USDT-SWAP';now=int(time.time()*1000)
    b._akis_trade(sym,100,1,'buy',now,1)
    assert ('okx',sym) not in b.akis._kayitlar
    m.okx_connection_change(sym,True);d=b.detektor.durum('okx',sym);d._flow_start_ms=now-30000
    for ts in (now,now-1,now+1000,now-20000):b._akis_trade(sym,100,1,'buy',ts,1)
    assert len(b.akis._kayitlar[('okx',sym)].olaylar)==1
    assert m.stats['okx_stale_future_or_out_of_order']==3
    assert m.stats['okx_book_rejected']==4


def test_okx_reconnect_clears_only_one_symbol(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch,'okx');m=b.eski_v78_motor
    other=('okx','OTHER');b.akis.ekle(*other,100,1,'buy',int(time.time()*1000))
    old=m.okx_epochs[key[1]]
    m.okx_connection_change(key[1],False)
    assert d._flow_start_ms==0 and not b.akis._kayitlar[key].olaylar
    m.okx_connection_change(key[1],True)
    assert d._flow_start_ms>0 and m.okx_epochs[key[1]]==old+2
    assert len(b.akis._kayitlar[other].olaylar)==1 and m.stats['okx_reconnect_symbols']==1

@pytest.mark.parametrize('kind',['disconnect','reconnect'])
def test_okx_disconnect_or_reconnect_during_await_cannot_dispatch(tmp_path,monkeypatch,kind):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch,'okx');m=b.eski_v78_motor
    async def candle(*a):
        m.okx_connection_change(key[1],False)
        if kind=='reconnect':m.okx_connection_change(key[1],True)
        return {'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}}
    m.candles=candle;asyncio.run(m.cycle())
    assert m.stats['okx_connection_changed']==1
    b._sinyal_dispatch.assert_not_awaited()


def test_okx_subscription_ack_required_and_closed_invalidates():
    symbol='TEST-USDT-SWAP'; events=[]; processed=[]
    ack={'event':'subscribe','arg':{'channel':'trades','instId':symbol}}
    trade={'arg':{'channel':'trades','instId':symbol},'data':[{'instId':symbol}]}
    error={'event':'error','arg':{'channel':'trades','instId':symbol}}
    messages=[trade,ack,trade,error,trade]
    class WS:
        async def __aenter__(self):return self
        async def __aexit__(self,*a):return None
        def __aiter__(self):self.it=iter(messages);return self
        async def __anext__(self):
            try:p=next(self.it)
            except StopIteration:raise StopAsyncIteration
            return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data=json.dumps(p))
    class Session:
        def ws_connect(self,*a,**k):return WS()
    stream=OKXPaperAkisi(None,[symbol],None,akis_cb=lambda *a:None,state_cb=lambda syms,up:events.append((tuple(syms),up)))
    stream._abone=AsyncMock()
    async def process(data):processed.append(json.loads(data))
    stream._isle=process
    async def go():
        task=asyncio.create_task(stream._baglanti(Session(),'fake','trades',[symbol],0))
        await asyncio.sleep(.01);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(go())
    assert events==[((symbol,),True),((symbol,),False)]
    assert len(processed)==1


def test_fifteen_second_last_trade_age_not_five():
    from scanner.v78_flow_adapter import LegacyFlowAdapter
    class Flow:pass
    flow=Flow();now=100_000
    flow.olaylar=[(61000,0,0,0,0),(76000,0,0,0,0),(90000,0,0,0,0)]
    assert LegacyFlowAdapter._continuous(flow,now)  # age=10sec; two gaps <=15s
    assert not LegacyFlowAdapter._continuous(flow,now+5001)


def test_invalid_okx_trade_does_not_advance_order_watermark(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);m=b.eski_v78_motor;s='TEST-USDT-SWAP';n=int(time.time()*1000)
    m.okx_connection_change(s,True);b.detektor.durum('okx',s)._flow_start_ms=n-1000
    b._akis_trade(s,float('nan'),1,'buy',n,1)
    b._akis_trade(s,100,1,'buy',n-1,1)
    assert m.stats['okx_invalid_trade']==1 and len(b.akis._kayitlar[('okx',s)].olaylar)==1


def test_stale_closed_candle_after_await_no_dispatch(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);bootstrap_candidate(b,monkeypatch,'okx');m=b.eski_v78_motor
    m.candles=AsyncMock(return_value={'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-321000,'snapshot':{'entry_allowed':True}})
    asyncio.run(m.cycle());assert m.stats['closed_candle_stale_after_await']==1
    b._sinyal_dispatch.assert_not_awaited()


def test_v4_volume_freshness_and_warmup_are_required(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch,'okx');m=b.eski_v78_motor
    m.candles=AsyncMock(return_value={'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}})
    d.son_hacim_ts=int(time.time()*1000)-b.detektor.tazelik_ms-100
    asyncio.run(m.cycle());assert m.stats['v4_volume_not_ready']==1
    b._sinyal_dispatch.assert_not_awaited()
