import asyncio
import json
import math
from types import SimpleNamespace
import pytest
import ws_bot
from scanner.regime_shadow import evaluate, fetch_candles, _frame
from scanner.aggtrade_shadow import AggTradeShadow
from scanner.binance_flow import BinanceAggTradeFlow
from scanner.ws_scanner import Sinyal
from reports.regime_ablation import analyze

DAY=86_400_000

def makebars(n,duration=60000,start=DAY,exchange='binance'):
    rows=[]
    for i in range(n):
        c=100 + i*.01 + math.sin(i*.4)*.2
        o=c-.02;h=c+.3;l=c-.3;vol=10+(i%7)
        if exchange=='binance':rows.append([start+i*duration,o,h,l,c,vol,start+(i+1)*duration-1,vol*c,0,0,0,0])
        else:rows.append([str(start+i*duration),str(o),str(h),str(l),str(c),'100',str(vol),str(vol*c),'1'])
    return rows

def test_regime_complete_and_no_lookahead():
    one=makebars(180);fifteen=makebars(100,900000,start=0)
    ts=DAY+180*60000
    result=evaluate(one,fifteen,'binance',ts,101.5,0.5)
    assert result['metrics']['fresh_1m'] is True
    assert result['gates']['vwap_yakin'] is not None
    assert result['gates']['bb_dar'] is not None
    assert result['gates']['atr_alti'] is not None
    assert result['gates']['hacimsiz'] is not None
    future=makebars(10,start=ts)
    after=evaluate(one+future,fifteen,'binance',ts,101.5,0.5)
    assert result==after

def test_15m_trend_and_missing_closed_candles_unknown():
    ts=DAY*2;one=makebars(200,start=ts-200*60000);fifteen=makebars(100,900000,start=ts-100*900000)
    result=evaluate(one,fifteen,'binance',ts,102,0.5)
    assert result['metrics']['fresh_15m'] and result['gates']['trend_rejimi'] is not None
    assert result['gates']['vwap_yakin'] is None # utc session is empty at exact midnight
    missing=evaluate(one[:-1],fifteen[:-1],'binance',ts,102,0.5)
    assert all(v is None for v in missing['gates'].values())

def test_okx_candle_confirmation_gap_and_day_unknown():
    rows=makebars(120,exchange='okx');ts=DAY+120*60000
    assert evaluate(rows,[],'okx',ts,101,1)['gates']['vwap_yakin'] is not None
    rows[-1][8]='0'
    assert evaluate(rows,[],'okx',ts,101,1)['gates']['bb_dar'] is None
    rows[-1][8]='1';rows.pop(50)
    assert evaluate(rows,[],'okx',ts,101,1)['gates']['vwap_yakin'] is None

def test_nan_and_invalid_ohlcv_do_not_produce_silent_values():
    rows=makebars(180);rows[-1][2]=float('nan')
    got=evaluate(rows,[],'binance',DAY+180*60000,101,1)
    assert got['metrics']['fresh_1m'] is False
    with pytest.raises(ValueError):evaluate([],[],'binance',0,float('nan'),1)

def test_duplicate_conflicting_candle_fails_closed():
    a=makebars(2);b=a[-1].copy();b[4]+=0.01
    with pytest.raises(ValueError,match='cakisan'):_frame(a+[b],'binance',60000,DAY+120000)

def test_constant_volume_zscore_is_unknown():
    rows=makebars(100)
    for r in rows:r[7]=1000
    r=evaluate(rows,[],'binance',DAY+100*60000,101,1)
    assert r['gates']['hacimsiz'] is None

def test_aggtrade_second_bucket_no_future_leak_and_bounded():
    s=AggTradeShadow();s.add('BTC',100,1,100050);s.add('BTC',100,2,100900)
    assert s.snapshot('BTC',100600)['status']=='unknown'
    snap=s.snapshot('BTC',101000);assert snap['usd_10s']==300
    s.add('BTC',100,1,100800);assert s.out_of_order==1
    for t in range(101000,400000,1000):s.add('BTC',100,1,t)
    assert len(s._events['BTC'])<=181
    s.add('BTC',float('nan'),1,500000);assert s.invalid==1

def test_aggtrade_parser_rejects_bad_side_nan_and_unsubscribed():
    output=[];f=BinanceAggTradeFlow(['BTCUSDT'],lambda *x:output.append(x))
    good={'e':'aggTrade','s':'BTCUSDT','a':1,'p':'100','q':'1','T':100000,'m':False}
    f._isle(json.dumps(good));assert len(output)==1 and output[0][4]=='buy'
    f._isle(json.dumps({**good,'a':2,'m':'false'}));f._isle(json.dumps({**good,'a':3,'p':'NaN'}))
    f._isle(json.dumps({**good,'a':4,'s':'OTHERUSDT'}));assert len(output)==1

def test_ablation_matches_by_identity_and_preserves_unknown():
    e={'exchange':'binance','symbol':'BTCUSDT','side':'LONG','opened_at':1}
    rows=[{'kind':'close',**e,'realized_pnl':2}, {'kind':'entry',**e},
          {'kind':'features',**e,'gates':{'bb_dar':True,'vwap_yakin':False}}]
    r=analyze(rows);assert r['gates']['bb_dar']['block']['pnl_sum']==2
    assert r['gates']['vwap_yakin']['pass']['count']==1
    assert r['gates']['trend_rejimi']['unknown']['count']==1
    with pytest.raises(ValueError,match='yinelenen'):analyze(rows+rows[:1])

class R:
    def __init__(self,body):self.body=body
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    def raise_for_status(self):pass
    async def json(self):return self.body
class Session:
    def __init__(self):self.calls=[]
    def get(self,url,**kw):self.calls.append((url,kw));return R({'code':'0','data':[]} if 'okx.com' in url else [])

def test_fetch_parameters_stop_at_asof_and_redirects_disabled():
    s=Session();asyncio.run(fetch_candles(s,'binance','BTCUSDT',123456789,'1m'))
    assert s.calls[0][1]['params']['endTime']==123456788 and s.calls[0][1]['allow_redirects'] is False
    asyncio.run(fetch_candles(s,'okx','BTC-USDT-SWAP',123456789,'15m'))
    assert s.calls[1][1]['allow_redirects'] is False

def test_shadow_not_used_to_block_entry(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs/o.csv'))
    b=ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0,durumlar={}),min_genislik=0,giris_modu="market",indikator_golge=True)
    s=Sinyal(ts_ms=100000,exchange='binance',symbol='BTCUSDT',yon='LONG',etiket='T',fiyat=100,ret_pct=-1,rvol=6,hacim_usd=10000,gecen_ms=60000)
    assert b._pozisyon_ac(s)=='acildi'
    assert ('binance','BTCUSDT') in b.portfoy.positions
    out=[json.loads(x) for x in (tmp_path/'logs/indikator_shadow.jsonl').read_text().splitlines()]
    assert [x['kind'] for x in out]==['entry','features'] and out[1]['error']=='network_session_unavailable'
    b.olay_yazici.close()

def test_shadow_partial_fetch_failure_preserves_other_gates(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs/o.csv'))
    b=ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0,durumlar={}),min_genislik=0,giris_modu="market",indikator_golge=True)
    ts=DAY+120*60000
    s=Sinyal(ts_ms=ts,exchange='binance',symbol='BTCUSDT',yon='LONG',etiket='T',fiyat=101,ret_pct=-1,rvol=6,hacim_usd=10000,gecen_ms=60000)
    async def fake(signal,interval):
        if interval=='15m':raise OSError('network')
        return makebars(120)
    monkeypatch.setattr(b,'_regime_mum_al',fake)
    asyncio.run(b._regime_hesapla(s,{'exchange':'binance','symbol':'BTCUSDT','side':'LONG','opened_at':ts}))
    row=json.loads((tmp_path/'logs/indikator_shadow.jsonl').read_text())
    assert row['gates']['atr_alti'] is not None and row['gates']['trend_rejimi'] is None
    assert '15m' in row['data_errors']
    b.olay_yazici.close()
