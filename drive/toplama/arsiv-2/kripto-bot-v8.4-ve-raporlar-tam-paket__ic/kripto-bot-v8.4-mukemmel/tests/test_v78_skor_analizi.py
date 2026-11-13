"""Same-input offline comparison of adapter and authentic Drive v7.8 MoneyFlow."""
import importlib.util,sys,time
from pathlib import Path
from unittest.mock import patch
import pytest
from scanner.v78_flow_adapter import legacy_flow_snapshot

ORIGINAL=str(Path(__file__).parent/'reference'/'v78_moneyflow_original.py')
spec=importlib.util.spec_from_file_location('drive_v78_moneyflow_reference',ORIGINAL)
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)

def events_for(directions,now):
    n=len(directions);return [(now-(n-1-i)*1000,1. if side else 0.,0. if side else 1.,100. if side else 0.,0. if side else 100.) for i,side in enumerate(directions)]

def original_score(events,now):
    m=module.MoneyFlow('test',window_sec=300,compact_history=True)
    for ts,ab,sb,au,su in events:
        base=ab+sb;usd=au+su;m.add_trade(usd/base,base,is_buyer_maker=bool(sb),ts=ts/1000)
    return m.snapshot(include_vpvr=False)

@pytest.mark.parametrize('directions',[[True]*60,[False]*60,[i%2==0 for i in range(60)],[False]*45+[True]*15])
def test_same_trade_only_input_exactly_matches_drive(directions):
    now=1800000000000;events=events_for(directions,now)
    with patch('time.time',return_value=now/1000):
        got=legacy_flow_snapshot(events,now);old=original_score(events,now)
    assert got['score']==old['score'] and got['score_components']==old['score_components']
    assert got['buy_usdt']==old['buy_usdt'] and got['sell_usdt']==old['sell_usdt']

def test_short_term_buys_not_equal_to_5min_score():
    now=1800000000000;events=events_for([False]*45+[True]*15,now)
    with patch('time.time',return_value=now/1000):snap=legacy_flow_snapshot(events,now)
    assert all(e[1]>0 for e in events[-15:])
    assert snap['score']<0 and abs(snap['score'])<50

def test_strong_one_way_trade_only_can_reach_threshold():
    now=1800000000000;events=events_for([True]*60,now)
    with patch('time.time',return_value=now/1000):snap=legacy_flow_snapshot(events,now)
    assert snap['score']==56 and snap['score_components']['taker_delta']==42
    assert snap['score_components']['cvd_direction']==14

def test_older_whale_within_5min_preserved_without_adapter_truncation():
    now=1800000000000
    events=[]
    for i in range(3000):
        ts=now-299000+int(i*299000/2999)
        events.append((ts,1500.,0.,150000.,0.) if i==0 else (ts,0.,1.,0.,100.))
    with patch('time.time',return_value=now/1000):
        adapter=legacy_flow_snapshot(events,now);persistent=original_score(events,now)
    assert persistent['whale_buy_usdt']==150000 and adapter['whale_buy_usdt']==150000
    assert persistent['score_components']['whale_balance']==24
    assert adapter['score_components']['whale_balance']==24
    assert adapter['score']==persistent['score']

def test_old_whale_preserves_50_point_gate_on_identical_trade_sequence():
    now=1800000000000;events=[]
    for i in range(3000):
        ts=now-299000+int(i*299000/2999)
        if i==0:row=(ts,1500.,0.,150000.,0.)
        elif i<1000:row=(ts,1.,0.,100.,0.)
        elif i<1600:row=(ts,0.,1.,0.,100.)
        else:row=(ts,1.,0.,100.,0.)
        events.append(row)
    with patch('time.time',return_value=now/1000):
        adapter=legacy_flow_snapshot(events,now);persistent=original_score(events,now)
    assert adapter['score']==54.8 and persistent['score']==54.8
    assert abs(adapter['score'])>=50 and adapter['score']==persistent['score']
