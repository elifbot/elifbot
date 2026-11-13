"""v37 aktif paper kapısı: kapalı mum, yön, ATR, kaynak ve hata testi."""
import asyncio, json
from unittest.mock import patch
import pytest
from scanner.ind_aktif import kapali_mum_ekle, metrik, giris_karari, aggtrade_ekle
from scanner.ws_scanner import SpikeDetector, OKXAkisi, binance_dakika_onbellegi, okx_dakika_onbellegi
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


def test_kopma_indikator_gecmisini_temizler():
    det=SpikeDetector();s=det.durum('binance','X');doldur(s)
    inp=BinanceAggTradeInput(det,lambda x:None);inp.connection(['X'],False)
    assert not s.ind_mum and s.ind_acik_mum is None


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
