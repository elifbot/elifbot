import asyncio
import csv
from types import SimpleNamespace
from pathlib import Path
import pytest
import ws_bot
from data.feed_utils import is_url_allowed
from data.extended.funding_events import FundingWatcher, PARTIAL
from logger.trade_logger import TradeLogger, FIELDS
from portfolio.paper_futures import PaperPortfolio

class Resp:
    def __init__(self, body): self.body = body
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def raise_for_status(self): pass
    async def json(self): return self.body

class Session:
    def __init__(self, body): self.body = body; self.calls = []
    def get(self, url, params, timeout, **kwargs):
        self.calls.append((url, kwargs))
        return Resp(self.body(url, params) if callable(self.body) else self.body)

def rows():
    return [{'symbol':'BTCUSDT', 'fundingTime':200000, 'fundingRate':'0.001', 'markPrice':'105'}]

def open_pos(p, t=100000, symbol='BTCUSDT'):
    assert p.open_position('binance', symbol, 'LONG', 100, 25, leverage=5, now_ms=t).ok
    return p.positions[('binance',symbol)]

@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs'/'olay.csv'))
    bots=[]
    def make():
        b=ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0,durumlar={}),min_genislik=0)
        bots.append(b); return b
    yield make
    for b in bots: b.olay_yazici.close()

def watch(bot, journal):
    return FundingWatcher(bot.portfoy, journal_path=str(journal), on_change=lambda:bot._durum_kaydet(strict=True))

def test_watcher_restart_is_once_and_csv_balance_matches(factory,tmp_path):
    b=factory(); pos=open_pos(b.portfoy); start=b.portfoy.starting_balance
    b._durum_kaydet(strict=True)
    w=watch(b,tmp_path/'funding.csv'); asyncio.run(w.poll_once(Session(rows()),210000))
    assert w.applied==1 and w.errors==0
    restored=factory(); assert restored._durum_yukle()==1
    before=restored.portfoy.balance
    w2=watch(restored,tmp_path/'funding.csv'); asyncio.run(w2.poll_once(Session(rows()),220000))
    assert w2.applied==0 and restored.portfoy.balance==before
    rec=restored.portfoy.close_position('binance','BTCUSDT',100,now_ms=230000)
    lg=TradeLogger(str(tmp_path/'trade.csv')); lg.log_trades([rec]); row=lg.read_rows(lg.path)[0]
    assert row['funding_label']==PARTIAL
    assert float(row['funding_fee'])==pytest.approx(105*pos.qty_base*.001)
    assert restored.portfoy.balance-start==pytest.approx(float(row['realized_pnl']))
    assert len(list(csv.DictReader(open(tmp_path/'funding.csv'))))==1

def test_failed_journal_retry_survives_close_and_restart(factory,tmp_path,monkeypatch):
    b=factory(); open_pos(b.portfoy); journal=tmp_path/'funding.csv'
    w=watch(b,journal)
    monkeypatch.setattr(w,'_write_event',lambda event: (_ for _ in ()).throw(OSError('disk full')))
    asyncio.run(w.poll_once(Session(rows()),210000))
    assert w.applied==1 and w.errors==1 and len(b.portfoy.funding_outbox)==1
    balance=b.portfoy.balance
    b.portfoy.close_position('binance','BTCUSDT',100,now_ms=220000)
    b._durum_kaydet(strict=True)
    b2=factory(); assert b2._durum_yukle()==0
    w2=watch(b2,journal); asyncio.run(w2.poll_once(Session([]),230000))
    assert not b2.portfoy.funding_outbox and len(list(csv.DictReader(open(journal))))==1
    assert b2.portfoy.balance==pytest.approx(balance+25-0.0625)

def test_retry_after_journal_write_before_outbox_clear(factory,tmp_path,monkeypatch):
    b=factory(); open_pos(b.portfoy); journal=tmp_path/'funding.csv'; w=watch(b,journal)
    original=w._write_event
    def interrupted(e): original(e); raise OSError('after replace')
    monkeypatch.setattr(w,'_write_event',interrupted)
    asyncio.run(w.poll_once(Session(rows()),210000))
    assert len(b.portfoy.funding_outbox)==1
    b2=factory(); b2._durum_yukle(); w2=watch(b2,journal)
    asyncio.run(w2.poll_once(Session(rows()),220000))
    assert not b2.portfoy.funding_outbox and w2.applied==0
    assert len(list(csv.DictReader(open(journal))))==1

def test_failed_state_write_rolls_back_and_retry(factory,tmp_path,monkeypatch):
    b=factory(); pos=open_pos(b.portfoy); b._durum_kaydet(strict=True); initial=b.portfoy.balance
    w=watch(b,tmp_path/'funding.csv'); real=w.on_change
    w.on_change=lambda: (_ for _ in ()).throw(OSError('disk'))
    asyncio.run(w.poll_once(Session(rows()),210000))
    assert b.portfoy.balance==initial and pos.last_funding_ts==0 and not b.portfoy.funding_outbox and w.applied==0
    w.on_change=real; asyncio.run(w.poll_once(Session(rows()),210000))
    assert w.applied==1 and pos.last_funding_ts==200000

def test_closure_during_request_and_reopen_same_key_does_not_charge():
    p=PaperPortfolio(); old=open_pos(p); w=FundingWatcher(p)
    async def events(session,pos,now):
        p.close_position('binance','BTCUSDT',100,now_ms=150000)
        open_pos(p,t=160000)
        return [(200000,.001,105,'mock')]
    w._events=events
    asyncio.run(w.poll_once(None,210000))
    assert w.applied==0 and p.positions[old.key] is not old
    assert p.positions[old.key].funding_fee==0

def test_position_closed_before_poll_is_reconciled():
    p=PaperPortfolio();open_pos(p);p.close_position('binance','BTCUSDT',100,now_ms=205000)
    w=FundingWatcher(p);s=Session(rows());asyncio.run(w.poll_once(s,210000))
    assert w.applied==1 and s.calls # Kapanmadan önceki olay artık kapanan işleme uygulanır.

def test_mark_prices_invalid_or_missing_are_not_silent():
    for row in [dict(symbol='BTCUSDT',fundingTime=200000,fundingRate='0.001'), dict(symbol='BTCUSDT',fundingTime=200000,fundingRate='0.001',markPrice='nan')]:
        p=PaperPortfolio();pos=open_pos(p);w=FundingWatcher(p)
        asyncio.run(w.poll_once(Session([row]),210000))
        assert w.applied==0 and w.last_error and pos.last_funding_ts==0
    p=PaperPortfolio(); assert p.open_position('okx','BTC-USDT-SWAP','LONG',100,25,leverage=5,now_ms=100000).ok
    def answer(url,params):
        if 'funding-rate-history' in url: return {'code':'0','data':[{'instId':'BTC-USDT-SWAP','fundingTime':'120000','realizedRate':'0.001'}]}
        return {'code':'0','data':[]}
    w=FundingWatcher(p);asyncio.run(w.poll_once(Session(answer),180000))
    assert w.applied==0 and w.last_error and p.positions[('okx','BTC-USDT-SWAP')].last_funding_ts==0

def test_allowlist_is_enforced_without_redirect_or_bad_hosts():
    p=PaperPortfolio();open_pos(p);w=FundingWatcher(p,binance_base='https://evil.example/fapi/v1');s=Session(rows())
    asyncio.run(w.poll_once(s,210000));assert not s.calls and 'PermissionError' in w.last_error
    assert all(is_url_allowed(url) for url in ['https://www.binance.com/fapi/v1/fundingRate','https://www.okx.com/api/v5/public/funding-rate-history','https://www.okx.com/api/v5/market/history-mark-price-candles'])
    assert not is_url_allowed('https://www.binance.com:444/fapi/v1/fundingRate')
    assert not is_url_allowed('https://user@www.binance.com/fapi/v1/fundingRate')
    w=FundingWatcher(p);s=Session(rows());asyncio.run(w.poll_once(s,210000))
    assert s.calls[0][1]['allow_redirects'] is False

def test_insufficient_funding_rejected_without_hiding_cost():
    p=PaperPortfolio();pos=open_pos(p);p.balance=1
    with pytest.raises(ValueError,match='yetersiz'): p.apply_funding('binance','BTCUSDT',1,100)
    assert p.balance==1 and pos.funding_fee==0 and pos.last_funding_ts==0

def test_last_price_not_modified_by_direct_call():
    p=PaperPortfolio();pos=open_pos(p);p.mark_price('binance','BTCUSDT',111,199000)
    p.apply_funding('binance','BTCUSDT',.001,105)
    assert (pos.last_price,pos.last_price_ts)==(111,199000)

def test_local_filename_and_old_csv_migration(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);p=PaperPortfolio();open_pos(p)
    w=FundingWatcher(p,journal_path='funding.csv');asyncio.run(w.poll_once(Session(rows()),210000))
    assert Path('funding.csv').exists()
    fields=[x for x in FIELDS if x!='funding_label']
    with open('trade.csv','w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerow(dict.fromkeys(fields,'x'))
    lg=TradeLogger('trade.csv');assert lg.read_rows(lg.path)[0]['funding_label']=='eski kayıt / doğrulanmamış'

def test_open_timestamp_boundary_is_explicitly_excluded():
    p=PaperPortfolio();pos=open_pos(p,t=200000);w=FundingWatcher(p)
    s=Session([{'symbol':'BTCUSDT','fundingTime':200000,'fundingRate':'0.001','markPrice':'105'}])
    asyncio.run(w.poll_once(s,210000))
    assert w.applied==0 and pos.last_funding_ts==0
