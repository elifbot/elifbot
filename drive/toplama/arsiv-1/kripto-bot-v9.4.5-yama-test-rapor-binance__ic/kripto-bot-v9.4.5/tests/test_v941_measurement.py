import json,hashlib
from pathlib import Path
import pytest
from src.counterfactual import CounterfactualTracker


def record(c,side='LONG',**kwargs):
    c.record_blocked_signal(gate='test',symbol='BTC/USDT',side=side,price=100,now_ts=1000,**kwargs)


def test_occurrences_unique_and_matured_denominators_are_different():
    c=CounterfactualTracker();record(c,decision_id=1);record(c,decision_id=1)
    c.on_price_update('BTC/USDT',101,now_ts=1300)
    x=c.summary(now_ts=1300)['gate_asymmetry_and_forward_returns']['test']
    assert x['total']==2 and x['sampled_unique']==1
    assert x['matured_5m_n']==1 and x['matured_15m_n']==0
    assert x['by_side']['LONG']['15m']['pending_n']==1


def test_very_late_quote_is_not_labeled_as_exact_15m():
    c=CounterfactualTracker();record(c)
    c.on_price_update('BTC/USDT',110,now_ts=2000)
    x=c.summary(now_ts=2000)['gate_asymmetry_and_forward_returns']['test']
    assert x['blocked_signal_15m_signed_bps'] is None
    assert x['by_side']['LONG']['15m']['missed_or_unobserved_n']==1


def test_long_short_are_kept_separate_despite_pooled_zero():
    c=CounterfactualTracker();record(c,'LONG',decision_id=1);record(c,'SHORT',decision_id=1)
    c.on_price_update('BTC/USDT',101,now_ts=1900)
    x=c.summary(now_ts=1900)['gate_asymmetry_and_forward_returns']['test']
    assert x['matured_15m_n']==2
    assert x['blocked_signal_15m_signed_bps']==pytest.approx(0)
    assert x['by_side']['LONG']['15m']['signed_gross_mark_return_bps']==pytest.approx(100)
    assert x['by_side']['SHORT']['15m']['signed_gross_mark_return_bps']==pytest.approx(-100)


def test_wrong_venue_and_unlabeled_quotes_do_not_mature_venue_specific_cohort():
    c=CounterfactualTracker();record(c,exchange='binance')
    c.on_price_update('BTC/USDT',110,now_ts=1900,exchange='okx')
    c.on_price_update('BTC/USDT',110,now_ts=1901)
    assert c.summary(now_ts=1901)['gate_asymmetry_and_forward_returns']['test']['matured_15m_n']==0
    c.on_price_update('BTC/USDT',101,now_ts=1902,exchange='binance')
    assert c.summary(now_ts=1902)['gate_asymmetry_and_forward_returns']['test']['matured_15m_n']==1


def test_positive_gross_mark_return_can_be_negative_in_cost_scenario():
    c=CounterfactualTracker();record(c,roundtrip_cost_bps=13)
    c.on_price_update('BTC/USDT',100.05,now_ts=1900)
    x=c.summary(now_ts=1900)['gate_asymmetry_and_forward_returns']['test']['by_side']['LONG']['15m']
    assert x['signed_gross_mark_return_bps']==pytest.approx(5)
    assert x['cost_scenario_mark_return_bps']==pytest.approx(-8)


def test_out_of_order_quote_cannot_rewrite_observed_price_path():
    c=CounterfactualTracker();record(c)
    c.on_price_update('BTC/USDT',101,now_ts=1300)
    c.on_price_update('BTC/USDT',50,now_ts=1200)
    row=c.blocked_signals[0]
    assert row['latest_px']==101 and row['observed_mae_bps']==0


def test_first_event_at_zero_is_not_silently_deduplicated():
    c=CounterfactualTracker()
    c.record_blocked_signal(gate='x',symbol='BTC/USDT',side='LONG',price=100,now_ts=0)
    assert len(c.blocked_signals)==1


def test_measurement_amendment_keeps_trading_core_hashes_unchanged():
    root=Path(__file__).resolve().parents[1]
    old=json.loads((root/'reports/v94_0_interrupted/v94_freeze_manifest.json').read_text())
    for name in ('src/v94_core.py','src/adaptive_policy.py','backtests/chronological_portfolio.py'):
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==old['source_sha256'][name]


def test_confidence_is_unavailable_for_single_day_despite_many_ticks():
    from src.gate_statistics import confidence
    rows=[{'day':1,'symbol':str(i%3),'gross_bps':40,'net_base_bps':25.5,'net_stress_bps':15.5} for i in range(100)]
    x=confidence(rows)
    assert x['ci_95'] is None and x['status']=='INSUFFICIENT_EVIDENCE'


def test_clustered_confidence_reports_adjusted_intervals_when_thresholds_met():
    from src.gate_statistics import confidence
    rows=[{'day':i//6,'symbol':str(i%3),'gross_bps':40+i%2,'net_base_bps':25.5+i%2,'net_stress_bps':15.5+i%2} for i in range(72)]
    x=confidence(rows)
    assert x['ci_95'] is not None
    assert x['simultaneous_familywise_95_ci']['net_stress_bps'][0]<=x['ci_95']['net_stress_bps'][0]
    assert x['positive_opportunity_cost_evidence']


def test_measurement_overlay_returns_original_decision_object_unchanged():
    from src.measurement_overlay import GateMeasurementOverlay
    from src.adaptive_policy import AdaptivePolicy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import asyncio
    original={'signal':'HOLD','reason':'test'}
    e=SimpleNamespace(executor=SimpleNamespace(positions={}),ingest_universe_price=lambda *a:None,
                      on_trade=AsyncMock(return_value=None),evaluate_and_route=AsyncMock(return_value=original))
    overlay=GateMeasurementOverlay(e,AdaptivePolicy());overlay.note_decision=lambda *a:None
    result=asyncio.run(e.evaluate_and_route('binance','BTC/USDT',None))
    assert result is original
