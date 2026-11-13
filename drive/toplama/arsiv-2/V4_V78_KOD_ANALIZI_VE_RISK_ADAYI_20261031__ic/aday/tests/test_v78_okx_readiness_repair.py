"""No-network synthetic tests of opt-in OKX readiness repair."""
import asyncio,time
from types import SimpleNamespace
import pytest
from scanner.ws_scanner import SpikeDetector
from scanner.ind_aktif import kapali_mum_ekle,kapsam
from scanner.v78_okx_readiness import diagnose,repair_missing
from test_v78_onarim_regresyon import bot_factory


def fixture(det,exchange,sym,now,missing=()):
    d=det.durum(exchange,sym);d.son_fiyat=100.;d.son_fiyat_ts=now
    end=now//60000-1
    for mid in range(end-59,end+1):
        if mid not in missing:assert kapali_mum_ekle(d,mid,102,98,100,1,100)
    return d

def row(mid,*,closed='1',high='102',low='98',close='100',base='1',quote='100',ts_delta=0):
    return [str(mid*60000+ts_delta),'100',high,low,close,'1',base,quote,closed]

class FakeResponse:
    def __init__(self,rows,status=200,on_json=None,code='0'):self.rows=rows;self.status=status;self.on_json=on_json;self.code=code
    async def __aenter__(self):return self
    async def __aexit__(self,*a):return None
    async def json(self):
        if self.on_json:self.on_json()
        return {'code':self.code,'data':self.rows}
class FakeSession:
    def __init__(self,make):self.make=make;self.requests=[]
    def get(self,url,params,timeout):self.requests.append((url,params));return self.make(params['instId'])


def test_diagnose_missing_stale_and_future_without_mutation():
    now=int(time.time()*1000);end=now//60000-1;det=SpikeDetector();det.ind_aktif=True
    d=fixture(det,'okx','A',now,missing=[end-3]);old=dict(d.ind_mum);d.son_fiyat_ts=now-30000
    out=diagnose(det,['A','ABSENT'],now)
    assert out[0]['symbol']=='A' and out[0]['missing_count']==1
    assert 'kapali_mum_eksik' in out[0]['reasons'] and 'fiyat_bayat' in out[0]['reasons']
    assert out[1]['reasons']==['sembol_durumu_yok'] and d.ind_mum==old


def test_add_only_valid_fully_closed_missing_rows():
    now=int(time.time()*1000);end=now//60000-1;det=SpikeDetector();det.ind_aktif=True
    missing=[end-1,end-2,end-3,end-4];d=fixture(det,'okx','A',now,missing)
    original=d.ind_mum[end]
    rows=[row(end-1),row(end-2,closed='0'),row(end-3,base='0',quote='5'),
          row(end-4,ts_delta=2),row(end,close='101'),row(end+1)]
    sess=FakeSession(lambda _:FakeResponse(rows))
    out=asyncio.run(repair_missing(sess,det,['A'],now_ms=now,pace_sec=0))
    assert out['added']==1 and out['completed']==0 and end-1 in d.ind_mum
    assert end-2 not in d.ind_mum and end-3 not in d.ind_mum and end-4 not in d.ind_mum
    assert d.ind_mum[end]==original and end+1 not in d.ind_mum


def test_conflicting_duplicate_rows_rejected():
    now=int(time.time()*1000);end=now//60000-1;det=SpikeDetector();det.ind_aktif=True
    d=fixture(det,'okx','A',now,missing=[end-4]);sess=FakeSession(lambda _:FakeResponse([row(end-4),row(end-4,quote='101')]))
    out=asyncio.run(repair_missing(sess,det,['A'],now_ms=now,pace_sec=0))
    assert out['conflict_minutes']==1 and out['added']==0 and end-4 not in d.ind_mum


def test_data_arriving_during_await_is_never_overwritten():
    now=int(time.time()*1000);end=now//60000-1;det=SpikeDetector();det.ind_aktif=True
    d=fixture(det,'okx','A',now,missing=[end-4])
    def stream_update():assert kapali_mum_ekle(d,end-4,102,98,101,1,101)
    sess=FakeSession(lambda _:FakeResponse([row(end-4)],on_json=stream_update))
    out=asyncio.run(repair_missing(sess,det,['A'],now_ms=now,pace_sec=0))
    assert out['added']==0 and out['completed']==1 and d.ind_mum[end-4][2]==101


@pytest.mark.parametrize('status,code',[(429,'0'),(500,'0'),(200,'1')])
def test_fail_closed_on_http_or_response_error(status,code):
    now=int(time.time()*1000);end=now//60000-1;det=SpikeDetector();det.ind_aktif=True
    d=fixture(det,'okx','A',now,missing=[end-1]);sess=FakeSession(lambda _:FakeResponse([row(end-1)],status=status,code=code))
    out=asyncio.run(repair_missing(sess,det,['A'],now_ms=now,pace_sec=0))
    assert out['errors']==1 and out['added']==0 and end-1 not in d.ind_mum
    assert out['http_429']==int(status==429)


def test_no_missing_no_network_call():
    now=int(time.time()*1000);det=SpikeDetector();det.ind_aktif=True;fixture(det,'okx','A',now)
    sess=FakeSession(lambda _:pytest.fail('no request expected'))
    out=asyncio.run(repair_missing(sess,det,['A'],now_ms=now,pace_sec=0))
    assert out['targets']==0 and not sess.requests


def test_actual_v4_readiness_19_of_22_becomes_ready_after_valid_repair(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);now=int(time.time()*1000);end=now//60000-1
    syms=[f'S{i:02d}' for i in range(22)]
    for i,s in enumerate(syms):fixture(b.detektor,'okx',s,now,missing=[end-4] if i<3 else [])
    fixture(b.detektor,'binance','BN',now)
    b._oturum=FakeSession(lambda _:FakeResponse([row(end-4)]));b.indikator_hazirlik_zamanasimi_dk=.1
    monkeypatch.setattr(b,'durum_yaz',lambda:None)
    async def go():
        await b._indikator_hazirligini_bekle(SimpleNamespace(semboller=syms),SimpleNamespace(semboller=['BN']),[])
    asyncio.run(go())
    assert b.indikator_hazir and b.indikator_okx_onarim['attempts']==1
    assert b.indikator_okx_onarim['last_result']['added']==3
    assert len(b.indikator_okx_onarim['initial_unready'])==3
    assert b.indikator_kapsam_son['borsalar']['okx']['mum_ve_fiyat_hazir']==22


def test_disabled_flag_does_not_repair_or_lower_readiness(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch,False);now=int(time.time()*1000);end=now//60000-1
    syms=[f'S{i:02d}' for i in range(22)]
    for i,s in enumerate(syms):fixture(b.detektor,'okx',s,now,missing=[end-4] if i<3 else [])
    fixture(b.detektor,'binance','BN',now)
    b._oturum=FakeSession(lambda _:pytest.fail('off must not request'));b.indikator_hazirlik_zamanasimi_dk=.001
    monkeypatch.setattr(b,'durum_yaz',lambda:None)
    with pytest.raises(RuntimeError,match='zamanasimi'):
        asyncio.run(b._indikator_hazirligini_bekle(SimpleNamespace(semboller=syms),SimpleNamespace(semboller=['BN']),[]))
    assert not b.indikator_hazir and b.indikator_okx_onarim['attempts']==0 and not b._oturum.requests

def test_invalid_closed_candles_keep_real_gate_closed(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);now=int(time.time()*1000);end=now//60000-1
    syms=[f'S{i:02d}' for i in range(22)]
    for i,s in enumerate(syms):fixture(b.detektor,'okx',s,now,missing=[end-4] if i<3 else [])
    fixture(b.detektor,'binance','BN',now)
    b._oturum=FakeSession(lambda _:FakeResponse([row(end-4,closed='0')]))
    b.indikator_hazirlik_zamanasimi_dk=.02;monkeypatch.setattr(b,'durum_yaz',lambda:None)
    with pytest.raises(RuntimeError,match='zamanasimi'):
        asyncio.run(b._indikator_hazirligini_bekle(SimpleNamespace(semboller=syms),SimpleNamespace(semboller=['BN']),[]))
    assert not b.indikator_hazir and b.indikator_okx_onarim['last_result']['added']==0
    assert b.indikator_kapsam_son['borsalar']['okx']['mum_ve_fiyat_hazir']==19


def test_repair_does_not_make_stale_price_fresh():
    now=int(time.time()*1000);end=now//60000-1;det=SpikeDetector();det.ind_aktif=True
    d=fixture(det,'okx','A',now,missing=[end-4]);d.son_fiyat_ts=now-30000
    sess=FakeSession(lambda _:FakeResponse([row(end-4)]))
    out=asyncio.run(repair_missing(sess,det,['A'],now_ms=now,pace_sec=0))
    assert out['added']==1 and d.son_fiyat_ts==now-30000
    assert 'fiyat_bayat' in diagnose(det,['A'],now)[0]['reasons']
