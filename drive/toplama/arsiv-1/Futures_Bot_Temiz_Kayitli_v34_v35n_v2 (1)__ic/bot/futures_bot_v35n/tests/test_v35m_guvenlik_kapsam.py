"""Gerçek detektör + sentetik saat; güvenlik/kapsam ölçütleri, dış ağ yok."""
from unittest.mock import patch
from scanner.aggtrade_input import BinanceAggTradeInput
from scanner.ws_scanner import SpikeDetector, BinanceRestAkisi


def after_gap(seconds):
    with patch('scanner.aggtrade_input.time.time') as clock:
        d=SpikeDetector(baglam_aktif=False);a=BinanceAggTradeInput(d,lambda _:None)
        a.connection(['TESTUSDT'],True)
        for t in range(1000,1125):
            clock.return_value=t;a.trade('binance','TESTUSDT',100,1,'buy',t*1000)
        state=d.durum('binance','TESTUSDT');assert state.hiz_uzun>0
        for t in range(1124+seconds,1124+seconds+11):
            clock.return_value=t;a.trade('binance','TESTUSDT',100,1,'buy',t*1000)
        return d,a,state


def test_21_saniye_bosluk_kapatilir():
    d,a,s=after_gap(21)
    assert s.hiz_uzun == 0 and s.rvol == 0
    assert d.kapi_sayaclari.get('hacim_pencere_gap_binance',0)>0


def test_20_saniye_esigi_dahil_kapali():
    # Yama yorumunda '20s+' deniyor; uygulama >20000 olduğu için eşitlik açık.
    _,_,s=after_gap(20)
    assert s.hiz_uzun == 0 and s.rvol == 0


def test_19_saniye_dogrulanmamis_bosluk_fail_closed():
    # Daha sıkı H-01 kabulü: teslimat kanıtı yokken süre eşiği güven kanıtı değil.
    _,_,s=after_gap(19)
    assert s.hiz_uzun == 0 and s.rvol == 0


def test_okx_davranisi_korunur():
    d=SpikeDetector(baglam_aktif=False);s=d.durum('okx','TEST-USDT-SWAP')
    s.hacimler.extend([(20_000,100.0),(130_000,500.0),(140_000,550.0)])
    assert d._oranlari_hesapla(s,140_000) is True


def test_binance_proxy_davranisi_korunur():
    # BinanceRestAkisi varsayılanı proxy'dir; d.exchange tek başına kaynak değildir.
    d=SpikeDetector(baglam_aktif=False);rest=BinanceRestAkisi(d,lambda _:None)
    assert rest.hacim_kaynagi == 'proxy'
    s=d.durum('binance','TESTUSDT')
    s.hacimler.extend([(20_000,100.0),(130_000,500.0),(140_000,550.0)])
    assert d._oranlari_hesapla(s,140_000) is True
