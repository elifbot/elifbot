import importlib.util
from pathlib import Path
P=Path('/home/user/analiz_raporu/vwap_cvd/aday_sonrasi_analiz.py')
spec=importlib.util.spec_from_file_location('replay',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_after_signal_and_same_bar_conservative_stop():
    ts=10*60000+12000
    r={'ts_ms':ts,'v7_fade_direction':'LONG'}
    bars=[[i*60000,100,101,99,100] for i in range(11,16)]
    sim,reason=m.simulation(r,bars,17*60000)
    assert reason is None and sim['entry_ts']==11*60000 and sim['reason']=='sl'
    assert sim['net_pct']<0

def test_no_future_or_missing_bars():
    r={'ts_ms':60001,'v7_fade_direction':'SHORT'}
    bars=[[i*60000,100,100,100,100] for i in range(2,7)]
    assert m.simulation(r,bars,6*60000)[1]=='5m_not_closed'
    assert m.simulation(r,bars[:-1],8*60000)[1]=='missing_candles'
