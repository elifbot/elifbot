import asyncio
from reports.funding_reconcile import reconcile_rows
from data.extended.funding_events import FundingWatcher


def test_reconcile_closed_long_with_fee_and_entry_exit_costs(monkeypatch):
    async def events(self,session,pos,now):
        return [(150000,0.001,100.0,'binance_event_mark')]
    monkeypatch.setattr(FundingWatcher,'_events',events)
    r={'exchange':'binance','symbol':'BTCUSDT','side':'LONG','opened_at':'100000',
       'closed_at':'200000','qty_base':'2','gross_pnl':'4','entry_fee':'0.1','exit_fee':'0.2'}
    got=asyncio.run(reconcile_rows([r],object()))[0]
    assert got['funding_reconciled']==0.2 and got['pnl_reconciled']==3.5
    assert got['funding_source']=='binance_event_mark'


def test_failure_is_unknown_not_zero(monkeypatch):
    async def events(*args): raise RuntimeError('network')
    monkeypatch.setattr(FundingWatcher,'_events',events)
    r={'exchange':'binance','symbol':'BTCUSDT','side':'LONG','opened_at':'100',
       'closed_at':'200','qty_base':'2','gross_pnl':'4','entry_fee':'0.1','exit_fee':'0.2'}
    got=asyncio.run(reconcile_rows([r],object()))[0]
    assert got['funding_reconciled']=='bilinmiyor' and 'network' in got['funding_error']
