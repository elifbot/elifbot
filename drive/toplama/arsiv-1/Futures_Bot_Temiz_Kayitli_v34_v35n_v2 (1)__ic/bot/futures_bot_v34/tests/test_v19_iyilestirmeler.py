"""v19: erken hata, basabas/trailing, acilis kapisi, ayni yon kabi, alarm."""
from __future__ import annotations
import time
from types import SimpleNamespace
import pytest
import ws_bot
from scanner.ws_scanner import Sinyal

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

def test_erken_hata_kapatir(bot_yap):
    b=bot_yap(); assert b._pozisyon_ac(_s())=="acildi"
    t0=int(time.time()*1000)
    pos=b.portfoy.positions[("binance","BTCUSDT")]; pos.opened_at=t0-120_000
    b._fiyat_guncelle("binance","BTCUSDT",99.0,t0)
    b._cikisleri_kontrol_et(t0)
    assert b.kapanan==1 and b.erken_hata_kapanan==1

def test_basabas_stop_yukselir(bot_yap):
    b=bot_yap(); assert b._pozisyon_ac(_s())=="acildi"
    t0=int(time.time()*1000)
    b._fiyat_guncelle("binance","BTCUSDT",100.7,t0)
    b._cikisleri_kontrol_et(t0)
    pos=b.portfoy.positions[("binance","BTCUSDT")]
    assert pos.stop_price == pytest.approx(100.30, abs=0.01)  # giris 100 (kayma 0) + %0.30

def test_trailing_stop_fiyati_izler(bot_yap):
    b=bot_yap(); assert b._pozisyon_ac(_s())=="acildi"
    t0=int(time.time()*1000)
    b._fiyat_guncelle("binance","BTCUSDT",102.0,t0); b._cikisleri_kontrol_et(t0)
    pos=b.portfoy.positions[("binance","BTCUSDT")]
    assert pos.stop_price == pytest.approx(101.49, abs=0.01)
    b._fiyat_guncelle("binance","BTCUSDT",101.4,t0+1000); b._cikisleri_kontrol_et(t0+1000)
    assert b.kapanan==1

def test_acilis_kapisi_ve_ayni_yon(bot_yap):
    b=bot_yap(acilis_kap_10dk=2, ayni_yon_kap=0)
    assert b._pozisyon_ac(_s("AUSDT"))=="acildi"
    assert b._pozisyon_ac(_s("BUSDT"))=="acildi"
    assert b._pozisyon_ac(_s("CUSDT"))=="engel:acilis_kapi_10dk"
    b2=bot_yap(ayni_yon_kap=1, acilis_kap_10dk=0)
    assert b2._pozisyon_ac(_s("AUSDT"))=="acildi"
    assert b2._pozisyon_ac(_s("BUSDT"))=="engel:ayni_yon_kap"
    assert b2._pozisyon_ac(_s("CUSDT", yon="SHORT"))=="acildi"
