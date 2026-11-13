import asyncio,math,time
from unittest.mock import AsyncMock
from scanner.v78_metrics import AgeHistogram,PaperMetrics
from scanner.v78_flow_adapter import observation_last_closed_end
from test_v78_onarim_regresyon import bot_factory,bootstrap_candidate


def active(b):b.asama='tarama';b.baslangic=time.time()

def test_nearest_rank_quantiles_negative_and_overflow():
    h=AgeHistogram(-5000,20000)
    for n in [-20,0,50,100]:h.add(n)
    assert h.status()['p50_ms']==0 and h.status()['p95_ms']==100
    assert h.status()['min_ms']==-20 and h.status()['max_ms']==100
    h.add(30000)
    assert h.status()['p50_ms'] is None and h.status()['p95_ms'] is None and h.status()['overflow']==1

def test_only_measurement_phase_and_each_exchange(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);m=b.eski_v78_motor.metrics
    m.on_taker('binance',int(time.time()*1000)-100)
    assert m.taker['binance'].count==0
    active(b);n=int(time.time()*1000)
    m.on_taker('binance',n-100);m.on_taker('okx',n-200)
    s=m.status()
    assert s['taker_book_insertion_age']['binance']['n']==1
    assert s['taker_book_insertion_age']['okx']['n']==1
    assert 100<=s['taker_book_insertion_age']['binance']['max_ms']<1000
    assert s['hook_calls']['taker']==2 and s['errors']==0

def test_actual_accepted_book_trades_measured_not_rejected(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);m=b.eski_v78_motor;s='TESTUSDT';b._v78_binance_connection([s],True)
    active(b);n=int(time.time()*1000)
    b._binance_akis_trade('binance',s,100,1,'buy',n)
    b._binance_akis_trade('binance',s,100,1,'buy',n-10000)
    assert m.metrics.taker['binance'].count==1 and b._real_volume.stale==1

def test_scored_symbols_unique_score_hist_and_components(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);active(b);key,d=bootstrap_candidate(b,monkeypatch,'okx');m=b.eski_v78_motor
    m.candles=AsyncMock(return_value={'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}})
    asyncio.run(m.cycle());m.last_attempt.clear();asyncio.run(m.cycle())
    s=m.metrics.status()
    assert s['score_evaluation_count']==2 and s['scored_unique_count']==1
    assert s['scored_unique_by_exchange']['okx']==1
    assert sum(s['score_histogram_tenths'].values())==2
    assert 'taker_delta' in s['score_component_sum'] and s['taker_latest_at_score_age']['okx']['n']==2

def test_candle_observation_accept_reject_unknown_and_bounds(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);active(b);m=b.eski_v78_motor.metrics;n=int(time.time()*1000)
    m.on_candle('response_received','okx','A',n-300000)
    m.on_candle('closed_rejected','okx','A',n-300000,'gap')
    m.on_candle('fetch_failed','okx','A',None,'timeout')
    for _ in range(300):m.on_candle('cache_served','okx','A',n-300000)
    s=m.status()
    assert s['candle_event_counts']['okx:response_received']==1
    assert s['candle_event_counts']['okx:closed_rejected']==1
    assert s['candle_age_unknown_counts']['okx:fetch_failed']==1
    assert 300000<=s['candle_age_ms']['okx:closed_rejected']['max_ms']<301000
    assert len(s['candle_last_events'])==256 and b.eski_v78_motor.stats['candle_detail_overflow']==47

def test_observed_closed_end_rejects_open_and_bad_rows():
    now=900000
    rows=[[0,'10','11','9','10','1','0','0','1'],[300000,'10','11','9','10','1','0','0','0'],[600000,'10','11','9','10','1','0','0','1']]
    assert observation_last_closed_end('okx',rows,now)==300000

def test_audit_hook_timing_scan_only_and_empty_is_unknown(tmp_path,monkeypatch):
    from scanner.ws_scanner import Sinyal
    b=bot_factory(tmp_path,monkeypatch);m=b.eski_v78_motor
    s=Sinyal(int(time.time()*1000),'binance','BTCUSDT','LONG','ANI_YUKSELIS',100,1,2,1000,2000)
    assert m.audit.timing_status()['n']==0 and m.audit.timing_status()['p95_us'] is None
    b._v78_say(s,'candidate_dispatch_attempt')
    assert m.audit.timing_status()['n']==0
    active(b);b._v78_say(s,'enrichment_rejected')
    assert m.audit.timing_status()['n']==1 and m.audit.timing_status()['p95_us']>=0

def test_truncation_and_old_whale_risk_count(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);active(b);m=b.eski_v78_motor.metrics
    old=(int(time.time()*1000)-1000,1001,0,100100,0)
    events=[old]+[(old[0]+1,0,1,0,100)]*2000
    class Flow:son_ts=old[0]+1
    snap={'score':1,'score_components':{'taker_delta':1},'window_coverage_sec':1,'whale_buy_usdt':0,'whale_sell_usdt':0}
    m.on_score('binance','X',snap,Flow(),events)
    out=m.status()
    assert out['score_truncated_last_2000_count']==1
    assert out['score_truncated_older_whale_observations']==1

def test_observer_error_disables_only_source_and_is_reported(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);active(b);m=b.eski_v78_motor
    m.metrics.on_taker('binance','bad_timestamp')
    assert m.metrics.metrics_errors==1 and m.watchdog_stopped.is_set()
    assert not b.durdu and m.status()['stop_reason']=='metrics_error'

def test_unrepresentable_taker_age_stops_source_and_percentiles_unknown(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);active(b);m=b.eski_v78_motor
    m.metrics.on_taker('binance',int(time.time()*1000)-30000)
    assert m.watchdog_stopped.is_set() and not b.durdu
    assert m.status()['stop_reason']=='histogram_overflow'
    assert m.metrics.status()['taker_book_insertion_age']['binance']['p95_ms'] is None

def test_observations_do_not_change_synthetic_source_signal(tmp_path,monkeypatch):
    b1=bot_factory(tmp_path/'one',monkeypatch);active(b1);bootstrap_candidate(b1,monkeypatch,'okx')
    b2=bot_factory(tmp_path/'two',monkeypatch);active(b2);bootstrap_candidate(b2,monkeypatch,'okx')
    b2.eski_v78_motor.metrics.on_score=lambda *a,**k:None
    b2.eski_v78_motor.metrics.on_candle=lambda *a,**k:None
    for b in (b1,b2):
        b.eski_v78_motor.candles=AsyncMock(return_value={'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}})
        asyncio.run(b.eski_v78_motor.cycle())
    assert b1._sinyal_dispatch.await_count==b2._sinyal_dispatch.await_count==1
    x=b1._sinyal_dispatch.await_args.args[0];y=b2._sinyal_dispatch.await_args.args[0]
    assert (x.exchange,x.symbol,x.yon,x.etiket,x.fiyat)==(y.exchange,y.symbol,y.yon,y.etiket,y.fiyat)
    assert b1.eski_v78_motor.metrics.status()['score_evaluation_count']==1
    assert b2.eski_v78_motor.metrics.status()['score_evaluation_count']==0
