from scanner.vwap_cvd_shadow import vwap_shadow,flow_shadow
from scanner.money_flow import AkisDefteri

def test_bands_only_shadow_atr_remains_required():
    v={'vwap':100,'atr_pct':.5}
    x=vwap_shadow(99.85,'LONG',v)
    assert not x['strict_pass'] and not x['band_0_10_pass'] and x['band_0_20_pass']
    assert vwap_shadow(100.15,'SHORT',v)['band_0_20_pass']
    assert not vwap_shadow(100.5,'LONG',{'vwap':100,'atr_pct':.09})['band_0_20_pass']
    assert vwap_shadow(100,'LONG',v)['strict_pass'] is False
    assert vwap_shadow(100,'LONG',None)['available'] is False

def test_flow_observes_only_past_and_does_not_mutate_original():
    ts=1000000;b=AkisDefteri()
    for t in (ts-3000,ts-2000,ts-1000):b.ekle('binance','X',100,10,'buy',t)
    b.ekle('binance','X',100,100,'sell',ts+2000)
    before=list(b._kayitlar[('binance','X')].olaylar);original_last=b._kayitlar[('binance','X')].son_ts
    x=flow_shadow(b,'binance','X',ts,'LONG')
    assert x['accepted'] is True and x['cvd15_usd']==3000
    assert before==list(b._kayitlar[('binance','X')].olaylar) and original_last==b._kayitlar[('binance','X')].son_ts
    assert x['mode']=='diagnostic_only'

def test_missing_flow_is_not_invented():
    x=flow_shadow(AkisDefteri(),'binance','X',1000000,'SHORT')
    assert x['available'] is False and x['reason']=='orderflow_unavailable'
