import asyncio
import json
import time
from types import SimpleNamespace
import pytest
import scanner.ind_aktif as ind
from scanner.ws_scanner import SpikeDetector, Sinyal
from scanner.v7_compare import V7Compare
import ws_bot


def test_band_long_short_boundaries_and_defaults(monkeypatch):
    monkeypatch.setattr(ind,'metrik',lambda *a:{'vwap':100.,'atr_pct':.4})
    d=object()
    assert not ind.giris_karari(d,1,99.85,'LONG')[0]
    assert ind.giris_karari(d,1,99.85,'LONG',vwap_tolerans_pct=.2)[0]
    assert ind.giris_karari(d,1,99.8,'LONG',vwap_tolerans_pct=.2)[0]
    assert not ind.giris_karari(d,1,99.79,'LONG',vwap_tolerans_pct=.2)[0]
    assert not ind.giris_karari(d,1,100.15,'SHORT')[0]
    assert ind.giris_karari(d,1,100.15,'SHORT',vwap_tolerans_pct=.2)[0]
    assert ind.giris_karari(d,1,100.2,'SHORT',vwap_tolerans_pct=.2)[0]
    assert not ind.giris_karari(d,1,100.21,'SHORT',vwap_tolerans_pct=.2)[0]
    assert not ind.giris_karari(d,1,100.,'LONG')[0]


def test_risk_and_invalid_data_fail_closed(monkeypatch):
    monkeypatch.setattr(ind,'metrik',lambda *a:{'vwap':100.,'atr_pct':.09})
    assert ind.giris_karari(object(),1,100,'LONG',vwap_tolerans_pct=.2)[1]=='indikator_atr_dusuk'
    for val in (float('nan'),float('inf'),-.1,.21,'x'):
        assert ind.giris_karari(object(),1,100,'LONG',vwap_tolerans_pct=val)[1]=='indikator_tolerans_gecersiz'
    monkeypatch.setattr(ind,'metrik',lambda *a:None)
    assert ind.giris_karari(object(),1,100,'LONG',vwap_tolerans_pct=.2)[1]=='indikator_veri_yok'


def test_v7_candidate_band_is_active_and_recorded(tmp_path,monkeypatch):
    async def run():
        now=int(time.time()*1000);det=SpikeDetector(baglam_aktif=True,ret_min_pct=.5,rvol_min=5,min_genislik_oran=0)
        det.vwap_tolerans_pct=.2
        d=det.durum('okx','X');d.son_fiyat=100.15;d.son_fiyat_ts=now;d.son_hacim_ts=now
        d.hiz_uzun=100;d.hiz_kisa=600;d.rvol=6;d.ret_2s=.7
        def context(d,ts):d.baglam_ret=.5;d.baglam_vratio=2;d.baglam_vratio3=10;return True
        det.baglam_guncelle=context
        monkeypatch.setattr(ind,'metrik',lambda *a:{'vwap':100.,'atr_pct':.4})
        seen=[]
        async def dispatch(sig):seen.append(sig)
        b=SimpleNamespace(detektor=det,asama='tarama',indikator_hazir=True,yeni_giris_kapali=False,
             profit_protection_csv=str(tmp_path/'profit.csv'),_akis_gorevler=set(),_real_volume=None,_sinyal_dispatch=dispatch)
        observer=V7Compare(b);det.v7_observer=observer
        assert det._degerlendir(d,now) is None # original v37 context remains blocked
        await asyncio.gather(*list(b._akis_gorevler))
        assert len(seen)==1 and seen[0].yon=='LONG'
        row=json.loads(open(observer.path).read());assert row['band_only_pass'] and row['active_vwap_tolerance_pct']==.2
        assert not row['vwap_shadow']['strict_pass'] and row['vwap_shadow']['band_0_20_pass']
    asyncio.run(run())


def test_band_applies_to_final_entry_gate_and_keeps_confirmation(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs'/'ws_olay.csv'))
    det=SpikeDetector();det.ind_aktif=True;det.vwap_tolerans_pct=.2
    monkeypatch.setattr(ind,'metrik',lambda *a:{'vwap':100.,'atr_pct':.4})
    b=ws_bot.Bot(det,teyit_aktif=True,defter_golge=False,funding_aktif=False)
    now=int(time.time()*1000)
    s=Sinyal(ts_ms=now,exchange='okx',symbol='X',yon='LONG',etiket='V7_FADE_ADAY',fiyat=99.85,ret_pct=-.5,rvol=6,hacim_usd=2000,gecen_ms=60000)
    try:
        assert b._pozisyon_ac(s)=='bekliyor:teyit'
        assert b.portfoy.open_count()==0 and len(b.teyit_bekleyen)==1
        b.teyit_bekleyen.clear();det.vwap_tolerans_pct=0
        assert b._pozisyon_ac(s)=='engel:indikator_vwap_yon'
        assert b.portfoy.open_count()==0
    finally:b.olay_yazici.close()


def test_cli_limits_and_requires_experimental_mode(capsys):
    for args in (['--vwap-tolerans-pct','0.21'],['--vwap-tolerans-pct','nan'],['--vwap-tolerans-pct','0.2']):
        with pytest.raises(SystemExit):ws_bot._main(args)
