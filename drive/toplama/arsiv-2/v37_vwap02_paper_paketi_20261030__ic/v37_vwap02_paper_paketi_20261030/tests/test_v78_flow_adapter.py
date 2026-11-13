import asyncio
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from scanner.v78_flow_adapter import closed_5m, legacy_flow_snapshot, LegacyFlowAdapter, FIVE_MIN_MS
from scanner.v78_strategy import Strategy

def rows(now):
    end=now//FIVE_MIN_MS-1
    return [[(end-i)*FIVE_MIN_MS,'100','102','99','101','10', (end-i+1)*FIVE_MIN_MS-1] for i in reversed(range(201))]

def test_candles_only_closed_and_contiguous():
    now=int(time.time()*1000)
    rs=rows(now); df=closed_5m('binance',rs,now)
    assert len(df)==200 and df.timestamp.is_monotonic_increasing
    bad=rs[:100]+rs[101:]
    with pytest.raises(ValueError): closed_5m('binance',bad,now)
    with pytest.raises(ValueError): closed_5m('binance',rs,now+900_000)

def test_real_v78_moneyflow_and_strategy_formula():
    now=int(time.time()*1000)
    events=deque((now-39_000+i*1000,1.,0.,100.,0.) for i in range(40))
    snap=legacy_flow_snapshot(events,now)
    assert snap['score']>=50
    st=Strategy(w_ind=.4,w_flow=.3,w_news=.15,w_ml=0)
    # raw score <55, but old flow trigger turns the signal LONG.
    signal=st.combine(20,snap['score'],0.0,None, market_context={'entry_allowed':True})
    assert signal['raw_signal']=='BEKLE' and signal['trigger']=='PARA_GIRISI' and signal['signal']=='LONG'

def test_adapter_requires_enrichment(tmp_path,monkeypatch):
    import ws_bot
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot,'OLAY_CSV',str(tmp_path/'logs'/'ws_olay.csv'))
    with pytest.raises(ValueError,match='zenginleştirme'):
        ws_bot.Bot(SimpleNamespace(),v78_akis_tetik=True,sinyal_zenginlestirme=False)

def test_cycle_no_dispatch_when_no_fresh_flow(tmp_path):
    class Empty:
        _kayitlar={}
    b=SimpleNamespace(profit_protection_csv=str(tmp_path/'foo.csv'), indikator_hazir=True,yeni_giris_kapali=False,akis=Empty(), detektor=SimpleNamespace(durumlar={}), _sinyal_dispatch=AsyncMock())
    motor=LegacyFlowAdapter(b)
    asyncio.run(motor.cycle())
    b._sinyal_dispatch.assert_not_awaited()

def test_cycle_uses_own_symbol_reconnect_start(tmp_path,monkeypatch):
    import scanner.v78_flow_adapter as mod
    from scanner.money_flow import AkisDefteri
    now=int(time.time()*1000)
    book=AkisDefteri()
    for i in range(40): book.binance_ekle('AUSDT',100,100,'buy',now-39000+i*1000)
    # Second scanned symbol is deliberately unready and has a future cutoff.
    book.binance_ekle('BUSDT',100,0.01,'buy',now)
    first=SimpleNamespace(son_fiyat=100.,son_fiyat_ts=now,hiz_uzun=1.,_flow_start_ms=now-60000)
    second=SimpleNamespace(son_fiyat=100.,son_fiyat_ts=now,hiz_uzun=1.,_flow_start_ms=now+100000)
    b=SimpleNamespace(profit_protection_csv=str(tmp_path/'foo.csv'),indikator_hazir=True,yeni_giris_kapali=False,akis=book,detektor=SimpleNamespace(durumlar={('binance','AUSDT'):first,('binance','BUSDT'):second},tazelik_ms=8000), _real_volume=SimpleNamespace(connected={'AUSDT','BUSDT'}))
    got=[]
    def capture(events, timestamp):
        got.append(list(events));return {'score':0}
    monkeypatch.setattr(mod,'legacy_flow_snapshot',capture)
    asyncio.run(LegacyFlowAdapter(b).cycle())
    assert len(got)==1 and len(got[0])==40
