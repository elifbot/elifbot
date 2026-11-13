import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('v78_match',Path(__file__).parents[1]/'tools/v78_kaynak_eslestirme.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def row(id,src,ts,side='LONG',sym='BTCUSDT',exchange='binance',ready=True):
    return dict(id=id,source=src,stage='candidate_dispatch_attempt',ready=ready,signal_ts_ms=ts,side=side,symbol=sym,exchange=exchange)

def test_one_to_one_separate_window_and_no_side_or_exchange_crossmatch():
    rows=[row('a','v4',100000),row('b','v4',101000),row('c','v78',100200),
          row('d','v78',301000),row('e','v78',100000,'SHORT'),row('f','v78',100000,exchange='okx')]
    small=mod.match(rows,5000);wide=mod.match(rows,300000)
    assert small['paired_count']==1 and small['pairs'][0]['v4_id']=='a'
    assert wide['paired_count']==2 and len(wide['unmatched_ids'])==2
    assert small['eligible_counts']=={'v4':2,'v78':4}

def test_not_ready_and_repeated_record_are_not_counted():
    a=row('a','v4',1000);b=row('b','v78',1000)
    got=mod.match([a,a,b,row('c','v4',1000,ready=False)],5000)
    assert got['eligible_counts']=={'v4':1,'v78':1} and got['paired_count']==1

def test_observed_local_window_separate_from_signal_timestamp():
    a=row('a','v4',1000);a['observed_ts_ms']=500
    b=row('b','v78',1001);b['observed_ts_ms']=501
    c=row('c','v4',1002);c['observed_ts_ms']=499
    d=row('d','v78',1003);d['observed_ts_ms']=601
    got=mod.match([a,b,c,d],5000,start_ms=500,end_ms=600)
    assert got['paired_count']==1 and got['eligible_counts']=={'v4':1,'v78':1}
