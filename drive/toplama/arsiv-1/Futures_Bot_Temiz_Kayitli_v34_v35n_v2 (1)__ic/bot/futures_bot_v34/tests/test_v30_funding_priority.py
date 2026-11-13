"""P0-1 sentetik testler; canlı public sonuç veya gerçek emir değil."""
import asyncio,csv
import pytest
from test_v29_late_funding import factory,watcher,csv_rows

@pytest.fixture(params=[('binance','BTCUSDT'),('okx','BTC-USDT-SWAP')])
def market(request):return request.param

def closed(bot,market):
    ex,sym=market
    assert bot.portfoy.open_position(ex,sym,'LONG',100,25,leverage=5,now_ms=100000).ok
    return bot._kapat_ve_kaydet(ex,sym,100,200000,'test')

def synthetic(w):
    async def events(session,pos,now):return [(150000,.001,100.,'sentetik')]
    w._events=events

@pytest.mark.parametrize('prefix',['F7_restart_before_event'])
def test_delayed_event_after_restart_before_first_poll(factory,tmp_path,market,prefix):
    b=factory();closed(b,market);old=b.portfoy.balance
    b2=factory();b2._durum_yukle();w=watcher(b2,tmp_path);synthetic(w)
    asyncio.run(w.poll_once(None,210000))
    assert w.applied==1 and w.errors==0 and b2.portfoy.balance==pytest.approx(old-.125)
    assert b2.portfoy.closed_trades[0].funding_fee==pytest.approx(.125)
    assert float(csv_rows(b2)[0]['funding_fee'])==pytest.approx(.125)
    assert len(list(csv.DictReader(open(tmp_path/'f.csv'))))==1
    asyncio.run(w.poll_once(None,220000));assert w.applied==1

def test_F9_cannot_pay_funding_keeps_state(factory,tmp_path,market):
    b=factory();r=closed(b,market);b.portfoy.balance=.01;w=watcher(b,tmp_path);synthetic(w)
    asyncio.run(w.poll_once(None,210000))
    assert w.applied==0 and w.errors==1 and r.funding_fee==0 and b.portfoy.balance==.01
    assert not b.portfoy.funding_outbox

def test_F11_state_failure_retry(factory,tmp_path,market):
    b=factory();r=closed(b,market);old=b.portfoy.balance;w=watcher(b,tmp_path);synthetic(w)
    def fail():raise OSError('sentetik disk full')
    w.on_change=fail;asyncio.run(w.poll_once(None,210000))
    assert w.errors==1 and w.applied==0 and r.funding_fee==0 and b.portfoy.balance==old
    w.on_change=b._funding_state_kaydet;asyncio.run(w.poll_once(None,220000))
    assert w.applied==1 and r.funding_fee==pytest.approx(.125)
    assert b.portfoy.balance==pytest.approx(old-.125)

def test_F11_journal_failure_restart_retry(factory,tmp_path,market,monkeypatch):
    b=factory();r=closed(b,market);old=b.portfoy.balance;w=watcher(b,tmp_path);synthetic(w)
    monkeypatch.setattr(w,'_write_event',lambda event: (_ for _ in ()).throw(OSError('sentetik journal IO')))
    asyncio.run(w.poll_once(None,210000));assert w.applied==1 and w.errors==1
    assert len(b.portfoy.funding_outbox)==1 and b.portfoy.balance==pytest.approx(old-.125)
    b2=factory();b2._durum_yukle();w2=watcher(b2,tmp_path);synthetic(w2)
    asyncio.run(w2.poll_once(None,220000));assert w2.applied==0 and not b2.portfoy.funding_outbox
    assert b2.portfoy.balance==pytest.approx(old-.125)
    assert len(list(csv.DictReader(open(tmp_path/'f.csv'))))==1

def test_F11_csv_failure_restart_reconciliation(factory,tmp_path,market):
    b=factory();closed(b,market);old=b.portfoy.balance;w=watcher(b,tmp_path);synthetic(w)
    def fail():raise OSError('sentetik CSV IO')
    w.on_materialize=fail;asyncio.run(w.poll_once(None,210000))
    assert w.applied==1 and w.errors==1 and b.portfoy.balance==pytest.approx(old-.125)
    b2=factory();b2._durum_yukle()
    assert float(csv_rows(b2)[0]['funding_fee'])==pytest.approx(.125)
    assert b2.portfoy.balance==pytest.approx(old-.125)
