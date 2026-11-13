from decimal import Decimal as D
import pytest
from acarbot.contract_math import ContractSpec,CurrencyLedger,from_exchange_record

def linear():return ContractSpec('okx_swap','BTC-USDT-SWAP','linear','USDT',D('.01'),D('.1'),D('.1'),D('.1'))
def inverse():return ContractSpec('binance_coinm','BTCUSD_PERP','inverse','BTC',D('100'),D('1'),D('1'),D('.1'))

def test_linear_pnl_long_short_and_contract_multiplier():
    s=linear(); assert s.pnl('LONG','10','50000','51000')==D('100')
    assert s.pnl('SHORT','10','50000','51000')==D('-100')

def test_inverse_pnl_settles_in_btc_not_usdt():
    s=inverse();v=s.pnl('LONG',10,50000,51000)
    assert abs(v-D('0.0003921568627450980392156862745098'))<D('1e-30')
    assert s.pnl('SHORT',10,50000,51000)==v.copy_negate()

def test_qty_floors_to_step_and_min_rejected():
    assert linear().qty('3.29')==D('3.2')
    with pytest.raises(ValueError):linear().qty('0.09')
    assert inverse().qty('1.99')==D('1')

def test_currency_balances_fees_and_funding_reconcile():
    s=inverse();l=CurrencyLedger({'BTC':'1','USDT':'100'})
    p=l.open(s,'LONG',10,50000,'.001',100)
    assert p.entry_fee==D('.00002')
    funding=l.apply_funding(s.market,s.symbol,'evt1',50000,'.0001',200)
    assert funding==D('-.000002')
    with pytest.raises(ValueError):l.apply_funding(s.market,s.symbol,'evt1',50000,'.0001',200)
    closed=l.close(s.market,s.symbol,51000,'.001',300)
    assert closed['currency']=='BTC' and l.balance['USDT']==D('100')
    assert abs(l.balance['BTC']-(D('1')+closed['net']))<D('1e-27')

def test_reject_expired_and_missing_currency_no_fx():
    s=ContractSpec('okx_futures','BTC-USD-TEST','inverse','BTC',D(100),D(1),D(1),D('.1'),1000)
    l=CurrencyLedger({'USDT':100})
    with pytest.raises(ValueError):l.open(s,'LONG',1,50000,.001,100)
    l=CurrencyLedger({'BTC':1})
    with pytest.raises(ValueError):l.open(s,'LONG',1,50000,.001,1000)
    l.open(s,'LONG',1,50000,.001,100)
    with pytest.raises(ValueError):l.close(s.market,s.symbol,51000,.001,1000)
    assert (s.market,s.symbol) in l.positions

def test_metadata_coinm_and_okx_linear_inverse():
    b={'symbol':'BTCUSD_PERP','contractStatus':'TRADING','baseAsset':'BTC','quoteAsset':'USD','marginAsset':'BTC','contractType':'PERPETUAL','contractSize':100,'filters':[{'filterType':'LOT_SIZE','stepSize':'1','minQty':'1'},{'filterType':'PRICE_FILTER','tickSize':'.1'}]}
    spec=from_exchange_record('binance_coinm',b);assert spec.kind=='inverse' and spec.face==100 and spec.settlement=='BTC'
    o={'instId':'ETH-USDT-SWAP','state':'live','ctType':'linear','settleCcy':'USDT','ctValCcy':'ETH','ctVal':'0.01','ctMult':'2','lotSz':'0.1','minSz':'0.1','tickSz':'0.01','expTime':''}
    spec=from_exchange_record('okx_swap',o);assert spec.kind=='linear' and spec.face==D('.02')
    o.update(instId='BTC-USD-SWAP',ctType='inverse',settleCcy='BTC',ctValCcy='USD',ctVal='100',ctMult='1')
    spec=from_exchange_record('okx_swap',o);assert spec.kind=='inverse' and spec.face==100
    o['ctValCcy']='BTC'
    with pytest.raises(ValueError):from_exchange_record('okx_swap',o)

def test_malformed_prices_and_side_fail_closed():
    for x in ['NaN','Infinity','0','-1']:
        with pytest.raises(ValueError):linear().pnl('LONG',1,1,x)
    with pytest.raises(ValueError):linear().pnl('UNKNOWN',1,1,2)

def test_short_positive_funding_receives():
    assert inverse().funding_delta('SHORT',10,50000,'.0001')==D('.000002')
