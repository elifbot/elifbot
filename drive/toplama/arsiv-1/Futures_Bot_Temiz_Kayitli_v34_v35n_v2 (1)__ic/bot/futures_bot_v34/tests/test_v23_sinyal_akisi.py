from scanner.ws_scanner import SpikeDetector

def _besle(period_ms):
    d = SpikeDetector(baglam_aktif=False, isinma_ms=30_000)
    for i in range(14):
        ts = 1_700_000_000_000 + i * period_ms
        d.besle_fiyat('binance', 'TEST', 100.0, 0.0, ts)
        d.besle_hacim_kumulatif('binance', 'TEST', i * 2_000.0, ts)
    return d

def test_geciken_binance_hacim_penceresi_hesaplanir():
    for period in (10_001, 10_100, 10_500):
        d = _besle(period).durum('binance', 'TEST')
        assert d.hiz_uzun > 0 and d.hiz_kisa > 0
        assert 0.9 < d.rvol < 1.1

def test_asiri_gecikmeli_hacim_bayat_oranla_sinyal_uretmez():
    det = _besle(10_100)
    d = det.durum('binance', 'TEST')
    ts = d.son_hacim_ts + 30_000
    det.besle_hacim_kumulatif('binance', 'TEST', 100_000, ts)
    assert d.hiz_uzun == 0 and d.rvol == 0

def test_binance_on_saniyelik_hacim_tazedir_ancak_daha_eski_reddedilir():
    det = SpikeDetector(baglam_aktif=False, min_hacim_usd=0, ret_min_pct=5)
    d = det.durum('binance', 'X')
    d.son_hacim_ts = 1_000_000
    d.son_fiyat_ts = 1_010_000
    d.hiz_uzun = d.hiz_kisa = d.rvol = 1
    det._degerlendir(d, 1_010_000)
    assert det.kapi_borsa['binance'].get('ret_esik', 0) == 1
    d.son_fiyat_ts = 1_016_000
    det._degerlendir(d, 1_016_000)
    assert det.kapi_borsa['binance'].get('bayat_hacim', 0) == 1
