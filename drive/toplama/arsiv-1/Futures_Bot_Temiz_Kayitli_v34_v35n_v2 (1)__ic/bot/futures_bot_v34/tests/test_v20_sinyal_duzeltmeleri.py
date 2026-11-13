"""v20: genislik kapisi baglamdan bagimsiz, teyitli giris, stop asmasi, kademeli erken hata."""
from __future__ import annotations
import time
from types import SimpleNamespace
import pytest
import ws_bot
from scanner.ws_scanner import SpikeDetector, Sinyal

def _detektor(**kw):
    ayar=dict(ret_pencere_ms=60_000, ret_min_pct=0.5, rvol_min=5.0, min_hacim_usd=1_000,
              baglam_aktif=False, min_genislik_oran=0.04)
    ayar.update(kw); return SpikeDetector(**ayar)

def _dusen_akis(d):
    fiyat=100.0; sinyal=None
    for sn in range(0, 181):
        ts=1_700_000_000_000 + sn*1000
        fiyat*= (1-0.00012 if sn<120 else 1-0.002)
        sinyal = d.besle_fiyat("okx","TEST-USDT-SWAP",fiyat,10_000_000,ts) or sinyal
        sinyal = d.besle_hacim_kumulatif("okx","TEST-USDT-SWAP", 1_000_000 + sn*2000.0 + max(0,sn-120)**2*3000, ts) or sinyal
    return sinyal

def test_genislik_kapisi_baglam_kapaliyken_de_kapatir():
    d=_detektor()
    assert d.genislik_oran == 0.0
    assert _dusen_akis(d) is None  # v19'da sinyal uretiliyordu (hata)

def test_genislik_yeterliyken_sinyal_gecer():
    d=_detektor(); d.genislik_oran=0.05
    assert _dusen_akis(d) is not None

@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    bots=[]
    def _yap(**kw):
        ayar=dict(strateji="fade", tp=99.0, sl=2.0, tut_dk=240.0, giris_modu="market", min_genislik=0.0, acilis_freni=0)
        ayar.update(kw)
        b=ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}), sure_dk=0, binance_mod="rest", **ayar)
        bots.append(b); return b
    yield _yap
    for b in bots: b.olay_yazici.close()

def _s(symbol="BTCUSDT", yon="LONG", fiyat=100.0):
    return Sinyal(ts_ms=int(time.time()*1000), exchange="binance", symbol=symbol, yon=yon, etiket="T", fiyat=fiyat, ret_pct=-0.6, rvol=6.0, hacim_usd=10000.0, gecen_ms=60000)

def test_teyit_olmadan_acilmaz_geri_cekilince_acilir(bot_yap):
    b=bot_yap(teyit_aktif=True)
    assert b._pozisyon_ac(_s())=="bekliyor:teyit"
    assert b.portfoy.open_count()==0
    t0=int(time.time()*1000)
    b._fiyat_guncelle("binance","BTCUSDT",99.0,t0)          # uc yenilenir, teyit yok
    assert b.portfoy.open_count()==0
    b._fiyat_guncelle("binance","BTCUSDT",99.2,t0+1000)     # %0.20 geri cekilme > %0.15
    assert b.portfoy.open_count()==1 and b.teyit_acilan==1

def test_teyit_suresi_dolunca_iptal(bot_yap):
    b=bot_yap(teyit_aktif=True, teyit_bekle_sn=30.0)
    s=_s(); assert b._pozisyon_ac(s)=="bekliyor:teyit"
    b._fiyat_guncelle("binance","BTCUSDT",99.5,s.ts_ms+31_000)
    assert b.portfoy.open_count()==0 and b.teyit_iptal==1

def test_ilk_30sn_erken_hata(bot_yap):
    b=bot_yap(teyit_aktif=False)
    assert b._pozisyon_ac(_s())=="acildi"
    t0=int(time.time()*1000)
    b.portfoy.positions[("binance","BTCUSDT")].opened_at=t0-20_000  # 20 sn once
    b._fiyat_guncelle("binance","BTCUSDT",99.4,t0)  # -%0.6 (eski 90sn kurali yakalamazdi)
    b._cikisleri_kontrol_et(t0)
    assert b.kapanan==1 and b.erken_hata_kapanan==1

def test_stop_asmasi_kapanisi_kotulestirir(bot_yap):
    b=bot_yap(teyit_aktif=False, stop_asma_pct=0.10)
    assert b._pozisyon_ac(_s())=="acildi"
    t0=int(time.time()*1000)
    rec=b._kapat_ve_kaydet("binance","BTCUSDT",98.0,t0,"stop_loss")
    assert rec is not None and rec.exit_price == pytest.approx(98.0*0.999, rel=1e-9)

def test_teyit_edilen_pozisyonun_acilis_saati_teyit_zamanidir(bot_yap):
    b=bot_yap(teyit_aktif=True)
    s=_s()
    assert b._pozisyon_ac(s)=="bekliyor:teyit"
    b._fiyat_guncelle("binance","BTCUSDT",99.0,s.ts_ms+10_000)
    b._fiyat_guncelle("binance","BTCUSDT",99.2,s.ts_ms+20_000)
    assert b.portfoy.positions[("binance","BTCUSDT")].opened_at == s.ts_ms+20_000
