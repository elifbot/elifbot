"""Offline integration of Drive v7.8 signal into actual V4 Bot dispatch."""
import asyncio, time
from unittest.mock import AsyncMock, Mock
import pytest
import ws_bot
from scanner.ws_scanner import SpikeDetector
import scanner.v78_flow_adapter as legacy


def newbot(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(ws_bot, 'TABAN', str(tmp_path))
    monkeypatch.setattr(ws_bot.Bot, '_olay_dosyasi_hazirla', lambda self: None)
    det=SpikeDetector(); det.ind_aktif=True
    opts=dict(strateji='momentum',sinyal_zenginlestirme=True,risk_limitleri=True,
              binance_hacim_kaynagi='aggtrade',teyit_aktif=True,eski_v78_paper=True,
              sadece_kayit=True,defter_golge=False)
    opts.update(overrides)
    b=ws_bot.Bot(det,**opts)
    b.olay_csv=Mock(); b.olay_yazici=Mock()
    monkeypatch.setattr(b,'_akis_sinyal_yaz',lambda *a:None)
    monkeypatch.setattr(b,'_zengin_sinyal_say',lambda *a:None)
    monkeypatch.setattr(b,'_zengin_sinyal_yaz',lambda *a:None)
    return b


def test_default_source_is_off(tmp_path,monkeypatch):
    b=newbot(tmp_path,monkeypatch,eski_v78_paper=False)
    assert b.eski_v78_motor is None and not b.eski_v78_paper

@pytest.mark.parametrize('alter',[
 {'strateji':'fade'}, {'sinyal_zenginlestirme':False}, {'risk_limitleri':False},
 {'binance_hacim_kaynagi':'proxy'}, {'teyit_aktif':False}])
def test_cannot_enable_with_protections_off(tmp_path,monkeypatch,alter):
    with pytest.raises(ValueError,match='v78 paper'):
        newbot(tmp_path,monkeypatch,**alter)

def test_inactive_indicators_forbidden(tmp_path,monkeypatch):
    det=SpikeDetector()
    with pytest.raises(ValueError,match='v78 paper'):
        ws_bot.Bot(det,eski_v78_paper=True, strateji='momentum',sinyal_zenginlestirme=True,
                   risk_limitleri=True,binance_hacim_kaynagi='aggtrade',teyit_aktif=True)

@pytest.mark.parametrize('direction',[1,-1])
@pytest.mark.parametrize('accepted',[False,True])
def test_real_old_score_reaches_real_v4_signal_path(tmp_path,monkeypatch,direction,accepted):
    b=newbot(tmp_path,monkeypatch); b.indikator_hazir=True
    now=int(time.time()*1000); key=('okx','SYNTH-USDT-SWAP')
    b.eski_v78_motor.okx_connection_change(key[1],True); b.detektor.durum(*key)._flow_start_ms=now-40000
    for i in range(40):b.akis.ekle(*key,100,100,'buy' if direction==1 else 'sell',now-39000+i*1000)
    d=b.detektor.durum(*key);d.son_fiyat=100.;d.son_fiyat_ts=now;d.hiz_uzun=1.;d.son_hacim_ts=now;d.ret_2s=0.;d.rvol=2.
    m=b.eski_v78_motor
    monkeypatch.setattr(legacy,'giris_karari',lambda *a,**k:(True,'synthetic_pass',{}))
    m.candles=AsyncMock(return_value={'score':20.0*direction,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}})
    capture=[];m.record=lambda row:capture.append(row)
    b._zengin_sinyali_degerlendir=AsyncMock(return_value={'accepted':accepted,'reasons':[] if accepted else ['synthetic_risk_reject']})
    original=b._pozisyon_ac;b._pozisyon_ac=Mock(wraps=original)
    async def go():
        await m.cycle()
        if b._akis_gorevler: await asyncio.gather(*list(b._akis_gorevler))
    asyncio.run(go())
    assert m.stats['dispatched']==1 and b.sinyal_sayisi==1
    assert capture[0]['flow_score']*direction>=50
    assert capture[0]['side']==('LONG' if direction==1 else 'SHORT')
    assert capture[0]['trigger']==('PARA_GIRISI' if direction==1 else 'PARA_CIKISI')
    assert b._zengin_sinyali_degerlendir.await_count==1
    assert b._pozisyon_ac.call_count == (1 if accepted else 0)
    assert not b.portfoy.positions and not b.bekleyen


def test_stale_or_unready_does_not_dispatch(tmp_path,monkeypatch):
    b=newbot(tmp_path,monkeypatch);b.indikator_hazir=False
    b._sinyal_dispatch=AsyncMock();asyncio.run(b.eski_v78_motor.cycle())
    b._sinyal_dispatch.assert_not_awaited()

@pytest.mark.parametrize('direction',[1,-1])
def test_real_indicator_and_flow_together_with_fake_http(tmp_path,monkeypatch,direction):
    import math
    b=newbot(tmp_path,monkeypatch);b.indikator_hazir=True
    now=int(time.time()*1000);key=('okx','FIXTURE-USDT-SWAP')
    b.eski_v78_motor.okx_connection_change(key[1],True); b.detektor.durum(*key)._flow_start_ms=now-40000
    for i in range(40):b.akis.ekle(*key,100,100,'buy' if direction==1 else 'sell',now-39000+i*1000)
    d=b.detektor.durum(*key);d.son_fiyat=100.;d.son_fiyat_ts=now;d.hiz_uzun=1.;d.son_hacim_ts=now;d.ret_2s=0.;d.rvol=2.
    last=(now//300000-1)*300000;rows=[]
    for i in range(200):
        t=last-(199-i)*300000;o=100+direction*i*.03+math.sin(i*.6)*.05;c=o+direction*.05
        rows.append([str(t),str(o),str(max(o,c)+.06),str(min(o,c)-.06),str(c),'3000' if i>195 else '1000','0','0','1'])
    class Response:
        async def __aenter__(self):return self
        async def __aexit__(self,*a):return None
        def raise_for_status(self):pass
        async def json(self):return {'code':'0','data':rows}
    class FakeSession:
        def get(self,*a,**k):return Response()
    b._oturum=FakeSession();m=b.eski_v78_motor
    monkeypatch.setattr(legacy,'giris_karari',lambda *a,**k:(True,'synthetic_pass',{}))
    b._zengin_sinyali_degerlendir=AsyncMock(return_value={'accepted':False,'reasons':['synthetic_risk_reject']})
    capture=[];m.record=lambda row:capture.append(row)
    async def go():
        await m.cycle()
        if b._akis_gorevler:await asyncio.gather(*list(b._akis_gorevler))
    asyncio.run(go())
    assert m.stats['candle_fetch_ok']==1 and m.stats['dispatched']==1
    assert capture[0]['flow_score']*direction>=50 and capture[0]['technical_score']*direction>=10
    assert b._zengin_sinyali_degerlendir.await_count==1 and not b.portfoy.positions


def test_stale_price_or_insufficient_continuity_does_not_reach_decision(tmp_path,monkeypatch):
    b=newbot(tmp_path,monkeypatch);b.indikator_hazir=True
    n=int(time.time()*1000);key=('okx','STALE-SWAP');d=b.detektor.durum(*key)
    b.eski_v78_motor.okx_connection_change(key[1],True);d._flow_start_ms=n-40000
    d.son_fiyat=100.;d.son_fiyat_ts=n-30000;d.hiz_uzun=1.;d.son_hacim_ts=n
    for i in range(40):b.akis.ekle(*key,100,100,'buy',n-39000+i*1000)
    b._sinyal_dispatch=AsyncMock();asyncio.run(b.eski_v78_motor.cycle())
    b._sinyal_dispatch.assert_not_awaited()
    d.son_fiyat_ts=int(time.time()*1000)
    while b.akis._kayitlar[key].olaylar and b.akis._kayitlar[key].olaylar[0][0]<n-5000:b.akis._kayitlar[key].olaylar.popleft()
    asyncio.run(b.eski_v78_motor.cycle());b._sinyal_dispatch.assert_not_awaited()
