"""v36 önerisinin gerçek detektörle veri güvenliği ve sınır kabulü; dış ağ yok."""
from unittest.mock import patch
import pytest
from scanner.aggtrade_input import BinanceAggTradeInput
from scanner.ws_scanner import SpikeDetector, BinanceRestAkisi


def after_gap(seconds):
    with patch('scanner.aggtrade_input.time.time') as clock:
        d=SpikeDetector(baglam_aktif=False); a=BinanceAggTradeInput(d,lambda _: None)
        a.connection(['TESTUSDT'],True)
        for t in range(1000,1125):
            clock.return_value=t;a.trade('binance','TESTUSDT',100,1,'buy',t*1000)
        s=d.durum('binance','TESTUSDT'); assert s.hiz_uzun > 0
        for t in range(1124+seconds,1124+seconds+11):
            clock.return_value=t;a.trade('binance','TESTUSDT',100,1,'buy',t*1000)
        return d,a,s


def test_120_saniye_esigi_dahil_kapali():
    d,_,s=after_gap(120)
    assert s.hiz_uzun == 0 and s.rvol == 0
    assert d.kapi_sayaclari.get('hacim_pencere_gap_aggtrade',0)>0


def test_71_saniye_dogrulanmamis_aralik_fail_closed():
    # Teslimat/süreklilik doğrulaması olmadan pencere yeniden kullanılamaz.
    # Bu test sessizliğin gerçekte kayıp olduğunu iddia etmez.
    _,_,s=after_gap(71)
    assert s.hiz_uzun == 0 and s.rvol == 0


def test_19_saniye_dogrulanmamis_aralik_fail_closed():
    _,_,s=after_gap(19)
    assert s.hiz_uzun == 0 and s.rvol == 0


@pytest.mark.parametrize('age_ms,accepted,stale', [(2001,1,0),(5000,1,0),(5001,0,1)])
def test_gecmis_olay_zamani_esik(age_ms,accepted,stale):
    d=SpikeDetector(baglam_aktif=False);a=BinanceAggTradeInput(d,lambda _:None)
    a.connection(['TESTUSDT'],True)
    with patch('scanner.aggtrade_input.time.time',return_value=1000.0):
        a.trade('binance','TESTUSDT',100,1,'buy',1_000_000-age_ms)
    assert (a.accepted,a.stale)==(accepted,stale)


def test_gelecek_2_saniye_sinirini_korur():
    d=SpikeDetector(baglam_aktif=False);a=BinanceAggTradeInput(d,lambda _:None)
    a.connection(['TESTUSDT'],True)
    with patch('scanner.aggtrade_input.time.time',return_value=1000.0):
        a.trade('binance','TESTUSDT',100,1,'buy',1_002_001)
    assert (a.accepted,a.stale)==(0,1)


def test_sirasiz_veri_red():
    d=SpikeDetector(baglam_aktif=False);a=BinanceAggTradeInput(d,lambda _:None)
    a.connection(['TESTUSDT'],True)
    with patch('scanner.aggtrade_input.time.time',return_value=1000.0):
        a.trade('binance','TESTUSDT',100,1,'buy',1_000_000)
        a.trade('binance','TESTUSDT',100,1,'buy',999_999)
    assert (a.accepted,a.stale)==(1,1)


def test_kaynaklar_korunur():
    d=SpikeDetector(baglam_aktif=False);rest=BinanceRestAkisi(d,lambda _:None)
    assert rest.hacim_kaynagi=='proxy'
    for exchange,symbol in [('binance','TESTUSDT'),('okx','TEST-USDT-SWAP')]:
        s=d.durum(exchange,symbol);s.hacimler.extend([(20_000,100),(130_000,500),(140_000,550)])
        assert d._oranlari_hesapla(s,140_000) is True
