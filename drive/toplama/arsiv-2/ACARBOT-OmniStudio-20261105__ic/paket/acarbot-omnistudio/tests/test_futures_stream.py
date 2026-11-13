from acarbot.futures_market import Instrument
from acarbot.futures_stream import parse_binance,parse_okx,Store,valid

def test_coinm_volume_is_contracts_times_face():
    i=Instrument('binance','binance_coinm','BTCUSD_PERP','BTC','PERPETUAL','100','TRADING')
    raw={'e':'kline','k':{'s':'BTCUSD_PERP','i':'5m','t':300000,'o':'10','h':'12','l':'9','c':'11','v':'20','q':'1.5','x':True}}
    row=parse_binance(i,raw);assert row[5]==2000 and row[6] and valid(row)

def test_okx_quote_volume_and_confirm_field():
    i=Instrument('okx','okx_swap','BTC-USDT-SWAP','USDT','linear','0.01','live')
    p={'arg':{'channel':'candle5m','instId':i.symbol},'data':[['300000','10','12','9','11','500','5','55','1']]}
    r=parse_okx(i,p)[0];assert r[5]==55 and r[6] is True and valid(r)

def test_store_deduplicates_and_records_gap(tmp_path):
    i=Instrument('okx','okx_swap','BTC-USDT-SWAP','USDT','linear','1','live');s=Store(tmp_path/'x.db')
    row=(300000,10.,12.,9.,11.,55.,True)
    assert s.insert(i,row,600100)=='inserted'
    assert s.insert(i,row,600200)=='duplicate'
    row2=(900000,10.,12.,9.,11.,55.,True)
    assert s.insert(i,row2,1200100)=='gap'
    s.close();s=Store(tmp_path/'x.db')
    assert s.last[(i.market,i.symbol)]==900000
    assert s.db.execute('select count(*) from candles').fetchone()[0]==2
    assert s.db.execute('select count(*) from incidents').fetchone()[0]==1
    s.close()

def test_open_partial_candle_is_not_final():
    i=Instrument('okx','okx_swap','BTC-USDT-SWAP','USDT','linear','1','live')
    p={'arg':{'channel':'candle5m','instId':i.symbol},'data':[['300000','10','12','9','11','50','5','55','0']]}
    assert parse_okx(i,p)[0][6] is False

def test_stream_paper_merge_deduplicates_sorts_and_rejects_open():
    import pytest
    from omnistudio.core.types import Candle
    from acarbot.futures_stream_paper import merge_bar
    a=Candle('A','m',0,1,2,.5,1,10,True)
    b=Candle('A','m',300000,1,2,.5,1,10,True)
    changed=Candle('A','m',300000,1,2,.5,1.5,10,True)
    assert merge_bar([b],a)==[a,b]
    assert merge_bar([a,b],changed)==[a,changed]
    with pytest.raises(ValueError):merge_bar([a],Candle('A','m',600000,1,2,.5,1,10,False))

def test_gap_expected_is_bounded_and_explicit():
    import pytest
    from acarbot.futures_backfill import expected_gap
    assert expected_gap(0,900000)=={300000,600000}
    assert expected_gap(0,300000)==set()
    with pytest.raises(ValueError):expected_gap(0,300000*252)
    with pytest.raises(ValueError):expected_gap(1,900000)

def test_backfill_coinm_volume_uses_contracts_not_approx_close():
    from acarbot.futures_backfill import normalize_rows
    i=Instrument('binance','binance_coinm','BTCUSD_PERP','BTC','PERPETUAL','100','TRADING')
    row=[300000,'100','102','99','101','3',599999,'2']
    r=normalize_rows(i,[row])[0]
    assert r[5]==300
