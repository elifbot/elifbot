"""Gönderilen kabul senaryolarının v27 sözleşmesine göre düzeltilmiş hali.
Kapalı pozisyona geç funding hakkı ayrıca pozitif senaryo olarak denenir.
"""
import asyncio
from types import SimpleNamespace
import pytest
import ws_bot
from config import ALLOWED_HOSTS, ALLOWED_PATHS
from data.extended.funding_events import FundingWatcher
from logger.trade_logger import TradeLogger, FUNDING_APPLIED_LABELS
from portfolio.paper_futures import LONG, PaperPortfolio

class Response:
    def __init__(self, body): self.body=body
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    def raise_for_status(self): pass
    async def json(self): return self.body

class Session:
    def __init__(self, rows): self.rows=rows; self.calls=[]
    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append((url,params,kwargs))
        return Response(self.rows)

def rows(ts=150000):
    return [{'symbol':'BTCUSDT','fundingTime':ts,'fundingRate':'0.001','markPrice':'100'}]

def new_portfolio(opened=100000):
    p=PaperPortfolio(1000)
    assert p.open_position('binance','BTCUSDT',LONG,100,25,leverage=5,now_ms=opened).ok
    return p

@pytest.fixture
def bots(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs'/'olay.csv'))
    made=[]
    def create():
        b=ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0,durumlar={}),min_genislik=0)
        made.append(b);return b
    yield create
    for b in made: b.olay_yazici.close()

def test_watcher_state_restart_dedup(tmp_path,bots):
    b=bots();assert b.portfoy.open_position('binance','BTCUSDT',LONG,100,25,leverage=5,now_ms=100000).ok
    w=FundingWatcher(b.portfoy,journal_path=str(tmp_path/'f.csv'),on_change=lambda:b._durum_kaydet(strict=True))
    asyncio.run(w.poll_once(Session(rows()),160000))
    assert w.applied==1 and not w.errors
    before=b.portfoy.balance
    b2=bots();assert b2._durum_yukle()==1
    w2=FundingWatcher(b2.portfoy,journal_path=str(tmp_path/'f.csv'),on_change=lambda:b2._durum_kaydet(strict=True))
    asyncio.run(w2.poll_once(Session(rows()),200000))
    assert w2.applied==0 and b2.portfoy.balance==pytest.approx(before)
    assert b2.portfoy.positions[('binance','BTCUSDT')].last_funding_ts==150000

def test_late_event_after_close_is_not_misapplied(tmp_path):
    p=new_portfolio(); rec=p.close_position('binance','BTCUSDT',100,now_ms=160000)
    assert p.balance==pytest.approx(1000+rec.realized_pnl)
    s=Session(rows());w=FundingWatcher(p,journal_path=str(tmp_path/'f.csv'))
    asyncio.run(w.poll_once(s,200000))
    assert w.applied==1 and s.calls
    assert p.balance==pytest.approx(1000+rec.realized_pnl)

def test_late_closed_position_funding_should_be_reconciled(tmp_path):
    p=new_portfolio();rec=p.close_position('binance','BTCUSDT',100,now_ms=160000)
    w=FundingWatcher(p,journal_path=str(tmp_path/'f.csv'))
    asyncio.run(w.poll_once(Session(rows()),200000))
    assert rec.funding_fee == pytest.approx(0.125)
    assert p.balance == pytest.approx(1000+rec.realized_pnl)

def test_reopened_same_key_gets_no_old_event(tmp_path):
    p=new_portfolio();w=FundingWatcher(p,journal_path=str(tmp_path/'f.csv'))
    asyncio.run(w.poll_once(Session(rows()),160000)); assert w.applied==1
    old=p.positions[('binance','BTCUSDT')];p.close_position('binance','BTCUSDT',100,now_ms=170000)
    assert p.open_position('binance','BTCUSDT',LONG,100,25,leverage=5,now_ms=180000).ok
    pos=p.positions[('binance','BTCUSDT')];assert pos is not old
    asyncio.run(w.poll_once(Session(rows()),200000))
    assert w.applied==1 and pos.funding_fee==0 and pos.last_funding_ts==0

def test_csv_balance_reconciliation(tmp_path):
    p=new_portfolio();w=FundingWatcher(p,journal_path=str(tmp_path/'f.csv'))
    asyncio.run(w.poll_once(Session(rows()),160000))
    rec=p.close_position('binance','BTCUSDT',101,now_ms=200000)
    logger=TradeLogger(str(tmp_path/'trades.csv'));logger.log_trades([rec]); row=logger.read_rows(logger.path)[0]
    assert rec.funding_label in FUNDING_APPLIED_LABELS
    assert row['funding_label']=='funding kısmi / doğrulanmamış'
    assert float(row['funding_fee'])==pytest.approx(rec.funding_fee)
    assert p.balance-1000==pytest.approx(float(row['realized_pnl']))

def test_missing_mark_is_error_not_zero(tmp_path):
    p=new_portfolio();w=FundingWatcher(p,journal_path=str(tmp_path/'f.csv'))
    missing=[{'symbol':'BTCUSDT','fundingTime':150000,'fundingRate':'0.001'}]
    asyncio.run(w.poll_once(Session(missing),200000))
    assert w.errors==1 and 'markPrice' in w.last_error and not w.applied
    assert p.positions[('binance','BTCUSDT')].last_funding_ts==0

def test_allowlist_covers_requested_paths_and_blocks_redirect(tmp_path):
    assert {'/fapi/v1/fundingRate','/api/v5/public/funding-rate-history',
            '/api/v5/market/history-mark-price-candles','/fapi/v1/depth',
            '/api/v5/market/books'} <= ALLOWED_PATHS
    assert {'fapi.binance.com','www.binance.com','www.okx.com'} <= ALLOWED_HOSTS
    p=new_portfolio();s=Session(rows());w=FundingWatcher(p,journal_path=str(tmp_path/'f.csv'))
    asyncio.run(w.poll_once(s,200000));assert s.calls[0][2]['allow_redirects'] is False
