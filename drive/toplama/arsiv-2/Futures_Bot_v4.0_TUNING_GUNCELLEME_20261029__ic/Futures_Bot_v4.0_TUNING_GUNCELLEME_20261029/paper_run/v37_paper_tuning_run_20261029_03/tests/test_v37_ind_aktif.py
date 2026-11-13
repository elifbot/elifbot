"""v37 aktif paper kapısı: kapalı mum, yön, ATR, kaynak ve hata testi."""
import asyncio, json
from unittest.mock import patch
import pytest
from scanner.ind_aktif import kapali_mum_ekle, metrik, giris_karari, aggtrade_ekle
from scanner.ws_scanner import (SpikeDetector, OKXAkisi, binance_dakika_onbellegi,
                                binance_indikator_mum_eksiklerini_doldur,
                                okx_dakika_onbellegi)
from scanner.aggtrade_input import BinanceAggTradeInput

END=2000
NOW=(END+1)*60_000 + 1000

def doldur(d, low=99.8, high=100.2):
    for mid in range(END-59, END+1):
        assert kapali_mum_ekle(d,mid,high,low,100,10,1000)


def test_vwap_atr_esik_ve_yon():
    s=SpikeDetector().durum('okx','X');doldur(s)
    assert metrik(s,NOW,101)['vwap']==pytest.approx(100)
    assert metrik(s,NOW,101)['atr_pct']==pytest.approx(0.4/101*100)
    assert giris_karari(s,NOW,101,'LONG')[0]
    assert not giris_karari(s,NOW,101,'SHORT')[0]
    assert giris_karari(s,NOW,99,'SHORT')[0]
    assert not giris_karari(s,NOW,99,'LONG')[0]
    assert not giris_karari(s,NOW,100,'LONG')[0]
    assert not giris_karari(s,NOW,100,'SHORT')[0]


def test_dusuk_atr_reddedilir():
    s=SpikeDetector().durum('okx','X');doldur(s,99.99,100.01)
    assert giris_karari(s,NOW,100.01,'LONG')[1]=='indikator_atr_dusuk'


def test_sifir_ve_birim_hatasi_reddedilir():
    s=SpikeDetector().durum('okx','X')
    assert not kapali_mum_ekle(s,1,101,99,100,1,1000)
    assert not kapali_mum_ekle(s,1,101,99,100,0,100)
    assert not kapali_mum_ekle(s,1,float('nan'),99,100,1,100)
    assert giris_karari(s,NOW,100,'LONG')[1]=='indikator_veri_yok'


def test_eksik_bayat_mum_fail_closed():
    s=SpikeDetector().durum('okx','X');doldur(s)
    assert metrik(s,NOW,100) is not None
    assert metrik(s,NOW+60_000,100) is None
    del s.ind_mum[END-30]
    assert metrik(s,NOW,100) is None


def test_fade_giris_yonu_dedektorde_dogru_cevrilir():
    d=SpikeDetector(baglam_aktif=False,ret_min_pct=.1,rvol_min=1,min_hacim_usd=0,soguma_ms=0)
    d.ind_aktif=True;d.ind_strateji='fade';s=d.durum('okx','X');doldur(s)
    s.son_fiyat=99;s.son_fiyat_ts=NOW;s.son_hacim_ts=NOW
    s.hiz_uzun=10;s.hiz_kisa=30;s.rvol=3;s.ret_2s=1
    # Piyasa LONG, fade gerçek giriş SHORT: 99 < 100, izin.
    result=d._degerlendir(s,NOW)
    assert result and result.yon=='LONG'
    d.ind_strateji='momentum';s.son_sinyal_ts=0
    assert d._degerlendir(s,NOW) is None
    assert d.kapi_sayaclari['indikator_vwap_yon']>=1


def test_aggtrade_kismi_ilk_mum_atilir_sonraki_tam():
    d=SpikeDetector().durum('binance','X')
    aggtrade_ekle(d,1_000*60_000+40_000,100,1)
    aggtrade_ekle(d,1_001*60_000+1_000,101,2)
    aggtrade_ekle(d,1_001*60_000+2_000,99,1)
    aggtrade_ekle(d,1_002*60_000+1_000,100,1)
    assert 1000 not in d.ind_mum
    assert d.ind_mum[1001]==pytest.approx((101,99,99,3,301))


def test_kopma_kapanmis_indikator_gecmisini_korur_yarim_mumu_atar():
    det=SpikeDetector();s=det.durum('binance','X');doldur(s)
    before=dict(s.ind_mum)
    s.ind_acik_mum={'mid':END+1,'high':101,'low':99,'close':100,'base':1,'quote':100,'tam':True}
    inp=BinanceAggTradeInput(det,lambda x:None)
    inp.connection(['X'],True);inp.connection(['X'],False)
    assert s.ind_mum==before and s.ind_acik_mum is None
    assert inp.resets==0 and inp.partial_resets==2


def test_teyitli_giriste_aktif_kapi_tekrar_kontrol():
    from ws_bot import Bot
    from scanner.ws_scanner import Sinyal
    d=SpikeDetector();d.ind_aktif=True
    b=Bot(d,teyit_aktif=False,defter_golge=False)
    s=Sinyal(ts_ms=NOW,exchange='okx',symbol='X',yon='LONG',etiket='X',fiyat=101,ret_pct=1,rvol=3,hacim_usd=2000,gecen_ms=60_000)
    assert b._pozisyon_ac(s,teyitli=True)=='engel:indikator_veri_yok'
    assert b.portfoy.open_count()==0


class Response:
    def __init__(self,data):self.data=data
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def json(self):return self.data

class Session:
    def __init__(self,data):self.data=data;self.calls=[]
    def get(self,url,params,timeout):
        self.calls.append((url,params));return Response(self.data)


def test_binance_mevcut_on_dolgu_65_kapali_ohlcv():
    det=SpikeDetector();det.ind_aktif=True
    rows=[[str(m*60000),'100','100.2','99.8','100','10',str((m+1)*60000-1),'1000'] for m in range(END-63,END+2)]
    sess=Session(rows)
    with patch('scanner.ws_scanner.time.time',return_value=NOW/1000),patch('scanner.ws_scanner.asyncio.sleep',new=lambda *_: asyncio.sleep(0)):
        # Avoid patched sleep recursion: bekleme=0 and a dedicated async no-op.
        pass
    async def nop(*args):return None
    with patch('scanner.ws_scanner.time.time',return_value=NOW/1000),patch('scanner.ws_scanner.asyncio.sleep',new=nop):
        assert asyncio.run(binance_dakika_onbellegi(sess,det,{'X'},adet=65,bekleme=0))==1
    assert len(sess.calls)==1 and sess.calls[0][1]['limit']=='65'
    assert metrik(det.durum('binance','X'),NOW,101) is not None


def test_binance_eksik_gosterge_mumu_restten_doldurulur_tamponlar_korunur():
    det=SpikeDetector();det.ind_aktif=True
    s=det.durum('binance','X');doldur(s)
    missing_mid=END-2
    del s.ind_mum[missing_mid]
    s.son_fiyat=101;s.son_fiyat_ts=NOW
    closes_before=list(s.dakika_kapanis)
    volumes_before=list(s.dakika_hacim)
    row=[str(missing_mid*60000),'100','100.2','99.8','100','10',
         str((missing_mid+1)*60000-1),'1000']
    sess=Session([row])
    async def nop(*args):return None
    with patch('scanner.ws_scanner.time.time',return_value=NOW/1000),patch('scanner.ws_scanner.asyncio.sleep',new=nop):
        result=asyncio.run(binance_indikator_mum_eksiklerini_doldur(
            sess,det,{'X'},simdi_ms=NOW,taban='https://fapi.binance.com/fapi/v1',
            es_zamanli=1,bekleme=0))
    assert result['sembol_bosluklu']==1
    assert result['mum_eklenen']==1 and result['sembol_tamamlanan']==1
    assert result['hata']==0
    assert metrik(s,NOW,101) is not None
    assert list(s.dakika_kapanis)==closes_before
    assert list(s.dakika_hacim)==volumes_before
    assert sess.calls[0][1]['startTime']==str(missing_mid*60000)
    assert sess.calls[0][1]['endTime']==str((missing_mid+1)*60000-1)


def test_okx_mevcut_on_dolgu_65_kapali_ohlcv():
    det=SpikeDetector();det.ind_aktif=True
    rows=[[str(m*60000),'100','100.2','99.8','100','0','10','1000','1'] for m in range(END-63,END+1)]
    sess=Session({'data':rows})
    async def nop(*args):return None
    with patch('scanner.ws_scanner.asyncio.sleep',new=nop):
        assert asyncio.run(okx_dakika_onbellegi(sess,det,['X'],adet=65))==1
    assert len(sess.calls)==1 and sess.calls[0][1]['limit']=='65'
    assert metrik(det.durum('okx','X'),NOW,101) is not None


def test_okx_candle_ws_kapanis_islenir():
    det=SpikeDetector();det.ind_aktif=True
    async def cb(_):return None
    stream=OKXAkisi(det,['X'],cb)
    row=[str(END*60000),'100','100.2','99.8','100','0','10','1000','1']
    asyncio.run(stream._isle(json.dumps({'arg':{'channel':'candle1m','instId':'X'},'data':[row]})))
    assert END in det.durum('okx','X').ind_mum


def test_gosterge_hazirlik_sayaclari():
    from scanner.ind_aktif import kapsam
    det=SpikeDetector();det.ind_aktif=True
    a=det.durum('okx','A');a.son_fiyat=101;a.son_fiyat_ts=NOW;doldur(a)
    b=det.durum('binance','B');b.son_fiyat=101;b.son_fiyat_ts=NOW-100000;doldur(b)
    c=det.durum('binance','C');c.son_fiyat=101;c.son_fiyat_ts=NOW
    k=kapsam(det,NOW)
    assert (k['toplam'],k['mum_hazir'],k['mum_ve_fiyat_hazir'])==(3,2,1)
    assert k['borsalar']['okx']['mum_ve_fiyat_hazir']==1
    assert k['borsalar']['okx']['hazir_yuzde']==100.0


def test_kapsam_paydasi_beklenen_tum_sembolleri_icerir():
    from scanner.ind_aktif import kapsam
    det=SpikeDetector();det.ind_aktif=True
    evren={'okx':{f'O{i}' for i in range(10)},'binance':{f'B{i}' for i in range(10)}}
    for exchange,prefix in (('okx','O'),('binance','B')):
        for i in range(9):
            s=det.durum(exchange,f'{prefix}{i}')
            s.son_fiyat=101;s.son_fiyat_ts=NOW;doldur(s)
    k=kapsam(det,NOW,evren)
    for exchange in ('okx','binance'):
        b=k['borsalar'][exchange]
        assert (b['toplam'],b['mum_ve_fiyat_hazir'])==(10,9)
        assert b['hazir_yuzde']==90.0


def test_hazirlik_esigi_yuzde_90dan_buyuk_olmali():
    from ws_bot import Bot
    bot=Bot.__new__(Bot)
    bot.indikator_hazirlik_oran=90.0
    def report(okx_ready,okx_total,bnc_ready,bnc_total):
        return {'borsalar':{
            'okx':{'toplam':okx_total,'mum_ve_fiyat_hazir':okx_ready},
            'binance':{'toplam':bnc_total,'mum_ve_fiyat_hazir':bnc_ready},
        }}
    assert not bot._indikator_kapsam_hazir(report(9,10,10,10))
    assert not bot._indikator_kapsam_hazir(report(10,10,9,10))
    assert bot._indikator_kapsam_hazir(report(10,11,10,11))


def test_hazirlik_sirasindaki_sinyaller_test_orneklemine_girmez():
    from ws_bot import Bot
    from scanner.ws_scanner import Sinyal
    det=SpikeDetector();det.ind_aktif=True
    bot=Bot(det,defter_golge=False,funding_aktif=False)
    s=Sinyal(ts_ms=NOW,exchange='okx',symbol='X',yon='LONG',etiket='X',
             fiyat=100,ret_pct=1,rvol=3,hacim_usd=1000,gecen_ms=2000)
    assert bot.baslangic is None
    asyncio.run(bot.sinyal(s))
    assert bot.indikator_hazirlik_sinyal_red==1
    assert bot.sinyal_sayisi==0
    assert bot.portfoy.open_count()==0
