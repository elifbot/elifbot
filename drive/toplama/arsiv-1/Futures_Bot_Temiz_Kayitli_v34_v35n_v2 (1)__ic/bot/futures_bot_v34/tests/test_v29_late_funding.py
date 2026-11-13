import asyncio,csv,json
from types import SimpleNamespace
import pytest
import ws_bot
from data.extended.funding_events import FundingWatcher

class Resp:
    def __init__(self,data):self.data=data
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def raise_for_status(self):pass
    async def json(self):return self.data
class Session:
    def __init__(self,fn):self.fn=fn
    def get(self,url,params,timeout,**kw):return Resp(self.fn(url,params))

def rows(*times):
    return [{'symbol':'BTCUSDT','fundingTime':t,'fundingRate':'0.001','markPrice':'100'} for t in times]

@pytest.fixture
def factory(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs/o.csv'))
    made=[]
    def make():
        b=ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0,durumlar={}),min_genislik=0)
        made.append(b);return b
    yield make
    for b in made:
        if not b.olay_yazici.closed:b.olay_yazici.close()

def makeclosed(b):
    assert b.portfoy.open_position('binance','BTCUSDT','LONG',100,25,leverage=5,now_ms=100000).ok
    return b._kapat_ve_kaydet('binance','BTCUSDT',100,200000,'test')

def watcher(b,tmp):
    return FundingWatcher(b.portfoy,journal_path=str(tmp/'f.csv'),on_change=b._funding_state_kaydet,on_materialize=b._funding_csv_mutabakat)

def csv_rows(b):return b.ticaret.read_rows(b.ticaret.path)

def test_late_closed_event_updates_balance_csv_and_restart_once(factory,tmp_path):
    b=factory();rec=makeclosed(b);old=b.portfoy.balance
    w=watcher(b,tmp_path);asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),210000))
    assert w.applied==1 and w.errors==0
    assert rec.funding_fee==pytest.approx(.125) and b.portfoy.balance==pytest.approx(old-.125)
    assert b.portfoy.balance-1000==pytest.approx(rec.realized_pnl)
    row=csv_rows(b)[0];assert float(row['funding_fee'])==pytest.approx(.125)
    assert float(row['realized_pnl'])==pytest.approx(rec.realized_pnl) and row['funding_label'].startswith('funding kısmi')
    b2=factory();assert b2._durum_yukle()==0
    w2=watcher(b2,tmp_path);asyncio.run(w2.poll_once(Session(lambda u,p:rows(150000)),230000))
    assert w2.applied==0 and b2.portfoy.balance==pytest.approx(b.portfoy.balance)
    assert len(csv_rows(b2))==1 and len(list(csv.DictReader(open(tmp_path/'f.csv'))))==1

def test_later_older_event_is_not_hidden_by_max_cursor(factory,tmp_path):
    b=factory();r=makeclosed(b);w=watcher(b,tmp_path)
    asyncio.run(w.poll_once(Session(lambda u,p:rows(170000)),210000))
    asyncio.run(w.poll_once(Session(lambda u,p:rows(150000,170000)),220000))
    assert w.applied==2 and set(r.funding_event_ts)=={150000,170000}
    assert r.funding_fee==pytest.approx(.25)
    assert b.portfoy.balance-1000==pytest.approx(float(csv_rows(b)[0]['realized_pnl']))

def test_closed_event_does_not_charge_reopened_position(factory,tmp_path):
    b=factory();old=makeclosed(b)
    assert b.portfoy.open_position('binance','BTCUSDT','SHORT',100,25,leverage=5,now_ms=210000).ok
    new=b.portfoy.positions[('binance','BTCUSDT')]
    w=watcher(b,tmp_path);asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),230000))
    assert old.funding_fee==pytest.approx(.125) and new.funding_fee==0

def test_close_during_network_response_applies_to_old_closed_not_new(factory,tmp_path):
    b=factory();assert b.portfoy.open_position('binance','BTCUSDT','LONG',100,25,leverage=5,now_ms=100000).ok
    w=watcher(b,tmp_path);first=[True]
    async def events(session,pos,now):
        if first[0]:
            first[0]=False;b._kapat_ve_kaydet('binance','BTCUSDT',100,200000,'test')
            assert b.portfoy.open_position('binance','BTCUSDT','SHORT',100,25,leverage=5,now_ms=205000).ok
        return [(150000,.001,100.,'binance_event_mark')]
    w._events=events;asyncio.run(w.poll_once(None,210000))
    assert w.applied==1 and b.portfoy.closed_trades[0].funding_fee==pytest.approx(.125)
    assert b.portfoy.positions[('binance','BTCUSDT')].funding_fee==0

def test_state_save_failure_does_not_commit_late_fee(factory,tmp_path):
    b=factory();r=makeclosed(b);old=b.portfoy.balance;w=watcher(b,tmp_path)
    def fail():raise OSError('disk full')
    w.on_change=fail;asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),210000))
    assert w.applied==0 and w.errors==1 and r.funding_event_ts==[] and r.funding_fee==0
    assert b.portfoy.balance==old and not b.portfoy.funding_outbox
    w.on_change=b._funding_state_kaydet;asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),220000))
    assert w.applied==1 and r.funding_fee==pytest.approx(.125)

def test_csv_failure_repairs_on_restart_without_double_fee(factory,tmp_path):
    b=factory();r=makeclosed(b);old=b.portfoy.balance;w=watcher(b,tmp_path)
    def fail():raise OSError('csv disk')
    w.on_materialize=fail;asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),210000))
    assert w.applied==1 and w.errors==1 and b.portfoy.balance==pytest.approx(old-.125)
    assert csv_rows(b)[0]['funding_fee']=='bilinmiyor'
    b2=factory();b2._durum_yukle()
    assert float(csv_rows(b2)[0]['funding_fee'])==pytest.approx(.125)
    w2=watcher(b2,tmp_path);asyncio.run(w2.poll_once(Session(lambda u,p:rows(150000)),220000))
    assert w2.applied==0 and b2.portfoy.balance==pytest.approx(b.portfoy.balance)

def test_unaffordable_closed_funding_is_error_not_clipped(factory,tmp_path):
    b=factory();r=makeclosed(b);b.portfoy.balance=.01;w=watcher(b,tmp_path)
    asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),210000))
    assert w.applied==0 and w.errors==1 and r.funding_fee==0 and b.portfoy.balance==.01

def test_close_state_failure_rolls_back_memory(factory,monkeypatch):
    b=factory();assert b.portfoy.open_position('binance','BTCUSDT','LONG',100,25,leverage=5,now_ms=100000).ok
    before=b.portfoy.balance
    def fail(*args,**kw):raise OSError('state disk')
    monkeypatch.setattr(b,'_durum_kaydet',fail)
    with pytest.raises(OSError):b._kapat_ve_kaydet('binance','BTCUSDT',100,200000,'test')
    assert b.portfoy.balance==before and ('binance','BTCUSDT') in b.portfoy.positions
    assert not b.portfoy.closed_trades and b.kapanan==0

def test_old_state_with_closed_positions_fails_safe(factory,tmp_path):
    b=factory();(tmp_path/'logs').mkdir(exist_ok=True)
    (tmp_path/'logs/ws_state.json').write_text(json.dumps({'surum':18,'balance':1000,'kapanan':1,'positions':[]}))
    with pytest.raises(ValueError,match='migration'):b._durum_yukle()

def test_okx_late_realized_rate_and_approx_mark(factory,tmp_path):
    b=factory();assert b.portfoy.open_position('okx','BTC-USDT-SWAP','SHORT',100,25,leverage=5,now_ms=100000).ok
    r=b._kapat_ve_kaydet('okx','BTC-USDT-SWAP',100,200000,'test');old=b.portfoy.balance
    def feed(url,params):
        if 'funding-rate-history' in url:return {'code':'0','data':[{'instId':'BTC-USDT-SWAP','fundingTime':'120000','realizedRate':'0.002'}]}
        return {'code':'0','data':[['120000','102','103','101','102','1']]}
    w=watcher(b,tmp_path);asyncio.run(w.poll_once(Session(feed),210000))
    assert w.errors==0 and w.applied==1 and r.funding_fee==pytest.approx(-.255)
    assert b.portfoy.balance==pytest.approx(old+.255)

def test_closed_state_survives_csv_failure_before_restart(factory,monkeypatch):
    b=factory();assert b.portfoy.open_position('binance','BTCUSDT','LONG',100,25,leverage=5,now_ms=100000).ok
    monkeypatch.setattr(b.ticaret,'sync_trades',lambda x: (_ for _ in ()).throw(OSError('csv failed')))
    r=b._kapat_ve_kaydet('binance','BTCUSDT',100,200000,'test')
    assert r is not None and b.kapanan==1 and b.kayit_hatalari==1
    b2=factory();b2._durum_yukle()
    assert len(b2.portfoy.closed_trades)==1 and len(csv_rows(b2))==1
    assert b2.portfoy.balance==pytest.approx(b.portfoy.balance)

def test_journal_failure_retries_without_double_closed_fee(factory,tmp_path,monkeypatch):
    b=factory();r=makeclosed(b);old=b.portfoy.balance;w=watcher(b,tmp_path)
    real=w._write_event
    monkeypatch.setattr(w,'_write_event',lambda e: (_ for _ in ()).throw(OSError('disk')))
    asyncio.run(w.poll_once(Session(lambda u,p:rows(150000)),210000))
    assert w.applied==1 and w.errors==1 and len(b.portfoy.funding_outbox)==1
    assert b.portfoy.balance==pytest.approx(old-.125)
    b2=factory();b2._durum_yukle();w2=watcher(b2,tmp_path)
    asyncio.run(w2.poll_once(Session(lambda u,p:rows(150000)),220000))
    assert w2.applied==0 and not b2.portfoy.funding_outbox
    assert b2.portfoy.balance==pytest.approx(old-.125)
    assert len(list(csv.DictReader(open(tmp_path/'f.csv'))))==1

def test_open_late_older_timestamp_is_deduplicated(factory,tmp_path):
    b=factory();assert b.portfoy.open_position('binance','BTCUSDT','LONG',100,25,leverage=5,now_ms=100000).ok
    w=watcher(b,tmp_path)
    asyncio.run(w.poll_once(Session(lambda u,p:rows(170000)),180000))
    asyncio.run(w.poll_once(Session(lambda u,p:rows(150000,170000)),190000))
    pos=b.portfoy.positions[('binance','BTCUSDT')]
    assert w.applied==2 and set(pos.funding_event_ts)=={150000,170000}
    assert pos.funding_fee==pytest.approx(.25) and pos.last_funding_ts==170000
