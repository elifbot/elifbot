import time
import pytest
from scanner.aggtrade_input import BinanceAggTradeInput
from scanner.ws_scanner import SpikeDetector, BinanceRestAkisi
from scanner.binance_flow import BinanceAggTradeFlow
import json

@pytest.fixture
def source():
    d=SpikeDetector(baglam_aktif=False)
    return d,BinanceAggTradeInput(d,lambda s:None)

def test_no_connected_source_no_volume(source,monkeypatch):
    d,a=source;monkeypatch.setattr(time,'time',lambda:1000.)
    a.trade('binance','BTCUSDT',100,2,'buy',1000000)
    assert a.accepted==0 and ('binance','BTCUSDT') not in d.durumlar

def test_disconnect_rewarms_live_volume_but_preserves_closed_history(source,monkeypatch):
    d,a=source;monkeypatch.setattr(time,'time',lambda:1000.)
    a.connection(['BTCUSDT'],True)
    a.trade('binance','BTCUSDT',100,2,'buy',1000000)
    pos=d.durum('binance','BTCUSDT');assert pos.son_hacim_ts==1000000
    pos.dakika_kapanis.append((1,100));pos.dakika_hacim.append((1,100))
    a.connection(['BTCUSDT'],False)
    assert not pos.hacimler and pos.son_hacim_ts==0
    assert list(pos.dakika_hacim)==[(1,100)] and list(pos.dakika_kapanis)==[(1,100)]
    a.trade('binance','BTCUSDT',100,2,'buy',1000000)
    assert a.accepted==1
    a.connection(['BTCUSDT'],True)
    assert pos.rvol==0 and pos._volume_full_warmup_ms==120000
    assert a.resets==0 and a.partial_resets>=2

def test_stale_packet_rejected_without_reset_or_history_loss(source,monkeypatch):
    d,a=source;monkeypatch.setattr(time,'time',lambda:1000.);a.connection(['BTCUSDT'],True)
    a.trade('binance','BTCUSDT',100,2,'buy',1000000)
    p=d.durum('binance','BTCUSDT');p.dakika_hacim.append((1,50))
    before=dict(a.acc);volume_rows=list(p.hacimler);context_rows=list(p.dakika_hacim)
    a.trade('binance','BTCUSDT',100,2,'buy',990000)
    assert a.stale==1 and a.resets==0
    assert dict(a.acc)==before and list(p.hacimler)==volume_rows
    assert list(p.dakika_hacim)==context_rows
    assert a.stale_reasons['gecikmis_5sn_ustu']==1
    assert a.stale_by_symbol['BTCUSDT']==1

def test_no_retroactive_120_second_rvol_before_full_window(source,monkeypatch):
    d,a=source;now=[1000.];monkeypatch.setattr(time,'time',lambda:now[0]);a.connection(['BTCUSDT'],True)
    for i in range(119):
        now[0]=1000+i;a.trade('binance','BTCUSDT',100,1,'buy',int(now[0]*1000))
    p=d.durum('binance','BTCUSDT');assert p.rvol==0
    now[0]=1120;a.trade('binance','BTCUSDT',100,1,'buy',1120000)
    assert p.rvol>0

def test_aggtrade_input_uses_deltas_of_real_quote_value(source,monkeypatch):
    d,a=source;now=[1000.];monkeypatch.setattr(time,'time',lambda:now[0]);a.connection(['BTCUSDT'],True)
    a.trade('binance','BTCUSDT',100,2,'buy',1000000);now[0]=1001
    a.trade('binance','BTCUSDT',110,3,'sell',1001000)
    assert a.acc['BTCUSDT']==pytest.approx(530)
    assert d.durum('binance','BTCUSDT')._kum_birikim==pytest.approx(330)

def test_rest_volume_source_explicit_and_default_proxy():
    d=SpikeDetector(); assert BinanceRestAkisi(d,lambda s:None).hacim_kaynagi=='proxy'
    assert BinanceRestAkisi(d,lambda s:None,hacim_kaynagi='aggtrade').hacim_kaynagi=='aggtrade'
    with pytest.raises(ValueError):BinanceRestAkisi(d,lambda s:None,hacim_kaynagi='other')

def test_flow_bad_payload_does_not_advance_aggregate_id():
    out=[];f=BinanceAggTradeFlow(['BTCUSDT'],lambda *x:out.append(x))
    row={'e':'aggTrade','s':'BTCUSDT','a':8,'p':'NaN','q':'1','T':1000,'m':False}
    f._isle(json.dumps(row));assert not out and 'BTCUSDT' not in f._son_id

def test_suspected_aggregate_id_gap_uses_partial_gap_callback():
    states=[];gaps=[];out=[]
    f=BinanceAggTradeFlow(['BTCUSDT'],lambda *x:out.append(x),
        state_cb=lambda s,on:states.append((s,on)),
        gap_cb=lambda s,reason:gaps.append((s,reason)))
    row={'e':'aggTrade','s':'BTCUSDT','a':8,'p':'100','q':'1','T':1000,'m':False}
    f._isle(json.dumps(row));f._isle(json.dumps({**row,'a':10,'T':1001}))
    assert f.supheli_id_boslugu==1 and states==[]
    assert gaps==[('BTCUSDT','aggregate_id_gap')]
    assert f.supheli_id_boslugu_sembol['BTCUSDT']==1
    assert len(out)==2

def test_callback_failure_fail_closes_affected_symbol():
    states=[]
    def bad(*args): raise RuntimeError('injected')
    f=BinanceAggTradeFlow(['BTCUSDT'],bad,state_cb=lambda s,on:states.append((s,on)))
    f._isle(json.dumps({'e':'aggTrade','s':'BTCUSDT','a':1,'p':'100','q':'1','T':1000,'m':False}))
    assert f.callback_hata_sayisi==1 and states==[(['BTCUSDT'],False)]

def test_aggtrade_mode_never_runs_proxy_volume_loop(monkeypatch):
    import asyncio
    d=SpikeDetector(baglam_aktif=False); b=BinanceRestAkisi(d,lambda s:None,onbellek=False,hacim_kaynagi='aggtrade')
    calls=[]
    async def base(session):calls.append('base')
    async def symbols(session):calls.append('symbols');return 0
    async def price(session):calls.append('price')
    async def volume(session):calls.append('proxy');raise AssertionError('sessiz proxy fallback')
    monkeypatch.setattr(b,'_taban_sec',base);monkeypatch.setattr(b,'sembolleri_yukle',symbols)
    monkeypatch.setattr(b,'_fiyat_dongusu',price);monkeypatch.setattr(b,'_hacim_dongusu',volume)
    asyncio.run(b.calistir(object()))
    assert calls==['base','symbols','price'] and b.hazir.is_set()

def test_real_volume_full_warmup_with_jitter_does_not_freeze(source,monkeypatch):
    d,a=source;clock=[1000.];monkeypatch.setattr(time,'time',lambda:clock[0]);a.connection(['BTCUSDT'],True)
    for i in range(125):
        clock[0]=1000+i*1.013
        a.trade('binance','BTCUSDT',100,1,'buy',int(clock[0]*1000))
    assert d.durum('binance','BTCUSDT').rvol>0

def test_failed_signal_task_disables_symbol(monkeypatch):
    import asyncio
    async def run():
        d=SpikeDetector(baglam_aktif=False)
        async def bad(sig):raise RuntimeError('injected')
        a=BinanceAggTradeInput(d,bad);a.connection(['BTCUSDT'],True)
        monkeypatch.setattr(d,'besle_hacim_kumulatif',lambda *args:object())
        monkeypatch.setattr(time,'time',lambda:1000.)
        a.trade('binance','BTCUSDT',100,1,'buy',1000000)
        await asyncio.gather(*list(a.tasks),return_exceptions=True)
        assert a.signal_errors==1 and 'BTCUSDT' not in a.connected
    asyncio.run(run())
