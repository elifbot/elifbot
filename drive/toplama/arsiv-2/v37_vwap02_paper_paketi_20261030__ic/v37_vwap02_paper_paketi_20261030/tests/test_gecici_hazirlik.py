import pytest
from ws_bot import Bot
from types import SimpleNamespace

def det():
    return SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={})

def kaps(bn,ok):
    return {'borsalar':{'binance':{'toplam':100,'mum_ve_fiyat_hazir':bn},'okx':{'toplam':100,'mum_ve_fiyat_hazir':ok}}}

def test_varsayilan_kati_90_korunur():
    bot = Bot(det())
    assert not bot._indikator_kapsam_hazir(kaps(90, 91))
    assert not bot._indikator_kapsam_hazir(kaps(91, 90))
    assert bot._indikator_kapsam_hazir(kaps(91, 91))

def test_paper_esikler_her_borsa_icin_bagimsiz():
    bot = Bot(det(), indikator_hazirlik_okx_min=50, indikator_hazirlik_binance_min=70)
    assert bot._indikator_kapsam_hazir(kaps(70, 50))
    assert not bot._indikator_kapsam_hazir(kaps(69, 50))
    assert not bot._indikator_kapsam_hazir(kaps(70, 49))
    assert not bot._indikator_kapsam_hazir({'borsalar': {}})

@pytest.mark.parametrize('value', [-1, 101, float('nan')])
def test_gecersiz_esik_kabul_edilmez(value):
    with pytest.raises(ValueError):
        Bot(det(), indikator_hazirlik_okx_min=value)
