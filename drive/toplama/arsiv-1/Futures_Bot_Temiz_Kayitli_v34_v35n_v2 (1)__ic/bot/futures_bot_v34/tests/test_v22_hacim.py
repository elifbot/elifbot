from scanner.ws_scanner import BinanceRestAkisi, SpikeDetector

def test_degisen_ortalama_gecmis_islemleri_yeniden_degerlemez():
    akis = BinanceRestAkisi(SpikeDetector(), lambda s: None)
    assert akis._hacim_tahmini('BTC', 1_000_000, 100) == 0
    assert akis._hacim_tahmini('BTC', 1_000_000, 300) == 0
    assert akis._hacim_tahmini('BTC', 1_000_002, 300) == 600
    assert akis._hacim_tahmini('BTC', 1_000_003, 20) == 620

def test_sayac_geriye_gittiginde_sahte_artis_yok():
    akis = BinanceRestAkisi(SpikeDetector(), lambda s: None)
    akis._hacim_tahmini('BTC', 100, 10)
    assert akis._hacim_tahmini('BTC', 105, 10) == 50
    assert akis._hacim_tahmini('BTC', 1, 10) == 50
