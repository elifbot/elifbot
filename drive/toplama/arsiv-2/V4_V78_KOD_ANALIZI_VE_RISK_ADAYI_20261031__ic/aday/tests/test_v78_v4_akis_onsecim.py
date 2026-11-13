"""Offline synthetic trigger proof; mocks candles/dispatch, never measures real PnL."""
import asyncio,time
from unittest.mock import AsyncMock
import pytest
import ws_bot
import scanner.v78_flow_adapter as legacy
from scanner.signal_intel import flow_confirmation,FLOW_IMBALANCE_RATIO
from scanner.ws_scanner import SpikeDetector


def build(tmp_path,monkeypatch,aligned,side='LONG',favorable=65):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
    detector=SpikeDetector();detector.ind_aktif=True
    bot=ws_bot.Bot(detector,strateji='momentum',sinyal_zenginlestirme=True,
        risk_limitleri=True,binance_hacim_kaynagi='aggtrade',teyit_aktif=True,
        eski_v78_paper=True,v78_v4_akis_onsecim=aligned,sadece_kayit=True,defter_golge=False)
    now=int(time.time()*1000);sym='TESTUSDT';key=('binance',sym)
    bot.indikator_hazir=True;bot._v78_binance_connection([sym],True)
    d=detector.durum(*key);d._flow_start_ms=now-46_000;d.son_fiyat=100.;d.son_fiyat_ts=now
    d.hiz_uzun=1.;d.son_hacim_ts=now;d.ret_2s=0.;d.rvol=2.
    good,bad=('buy','sell') if side=='LONG' else ('sell','buy')
    for i in range(600):bot.akis.ekle(*key,100,1,good,now-45000+int(i*29000/599))
    for i in range(100):bot.akis.ekle(*key,100,1,bad if i<100-favorable else good,now-14500+int(i*14000/99))
    bot._sinyal_dispatch=AsyncMock();m=bot.eski_v78_motor;m.record=lambda row:None
    monkeypatch.setattr(legacy,'giris_karari',lambda *a:(True,'synthetic_gate',{}))
    m.candles=AsyncMock(return_value={'score':20. if side=='LONG' else -20.,'_closed_5m_end_ms':now-300000,'snapshot':{'entry_allowed':True}})
    return bot,m,key,now

@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_default_extra_prefilter_blocks_flow_eligible_synthetic_candidate(tmp_path,monkeypatch,side):
    b,m,key,now=build(tmp_path,monkeypatch,False,side)
    assert flow_confirmation(b.akis,*key,now,side).accepted
    snap=legacy.legacy_flow_snapshot(b.akis._kayitlar[key].olaylar,now)
    assert abs(snap['score'])>=50 and abs(b.akis.anlik(*key,now,15).cvd_usd/b.akis.anlik(*key,now,15).toplam_usd)==.3
    asyncio.run(m.cycle())
    assert m.status()['candidate_preselection_mode']=='original_0_5'
    assert m.stats['flow_evaluated']==0 and b._sinyal_dispatch.await_count==0

@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_optional_aligned_prefilter_dispatches_synthetic_candidate(tmp_path,monkeypatch,side):
    b,m,key,now=build(tmp_path,monkeypatch,True,side)
    assert flow_confirmation(b.akis,*key,now,side).accepted
    asyncio.run(m.cycle())
    assert m.status()['candidate_preselection_mode']=='v4_flow_ratio_aligned'
    assert m.min_abs_imbalance==pytest.approx((FLOW_IMBALANCE_RATIO-1)/(FLOW_IMBALANCE_RATIO+1))
    assert m.stats['flow_evaluated']==1 and b._sinyal_dispatch.await_count==1
    assert b._sinyal_dispatch.await_args.args[0].yon==side

@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_aligned_source_still_blocks_insufficient_v4_ratio(tmp_path,monkeypatch,side):
    b,m,key,now=build(tmp_path,monkeypatch,True,side,favorable=55)
    assert not flow_confirmation(b.akis,*key,now,side).accepted
    asyncio.run(m.cycle());assert m.stats['flow_evaluated']==0 and b._sinyal_dispatch.await_count==0

def test_option_cannot_be_enabled_without_opt_in_source(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
    with pytest.raises(ValueError,match='yalnız'):
        ws_bot.Bot(SpikeDetector(),v78_v4_akis_onsecim=True,eski_v78_paper=False)

def test_new_mode_retains_post_await_connection_guard(tmp_path,monkeypatch):
    b,m,key,now=build(tmp_path,monkeypatch,True)
    async def disconnected(*a):
        b._v78_binance_connection([key[1]],False)
        return {'score':20.,'_closed_5m_end_ms':now-300000,'snapshot':{'entry_allowed':True}}
    m.candles=disconnected;asyncio.run(m.cycle())
    assert b._sinyal_dispatch.await_count==0
