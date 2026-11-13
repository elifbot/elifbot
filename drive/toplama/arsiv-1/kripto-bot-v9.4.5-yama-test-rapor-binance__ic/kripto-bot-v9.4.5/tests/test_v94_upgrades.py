from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import numpy as np
import pandas as pd
import pytest
from src.v94_core import features,closed_htf_direction,market_context,V94DecisionCore
from src.adaptive_policy import AdaptivePolicy
from src.v94_live_risk import V94RiskManager
from src.v94_live_router import V94LiveRouter
from src.risk import Position
from src.live_runner import DualVenueLiveRunner
from backtests.chronological_portfolio import ChronologicalPortfolioEngine


def frame(n=180):
    c=np.full(n,100.)
    return pd.DataFrame(dict(open_time=1790000100000+np.arange(n)*300000,
        open=c.copy(),high=c+.02,low=c-.02,close=c,volume=np.full(n,1000.),taker_buy_quote=np.full(n,650.)))


def good_feature():
    return replace(features(frame()),close=100.,atr=.25,ema9=99.9,ema21=99.8,ema50=99.5,
        slope=.2,rsi=60.,efficiency=.5,flow_score=20.,last_delta=.2,rvol=1.2,vwap_z=.5,
        dir15=1,dir60=1,breakout_up=False,reclaim_up=True,real_taker=True,valid=True)


def test_decision_symmetric_and_explicit():
    c=V94DecisionCore();f=good_feature();ctx={'leader_count':2,'leader_ret_1h_pct':0,'breadth':0}
    assert c.decide(f,ctx)['side']=='LONG'
    short=replace(f,ema9=100.1,ema21=100.2,ema50=100.5,slope=-.2,rsi=40.,flow_score=-20.,
        last_delta=-.2,dir15=-1,dir60=-1,reclaim_up=False,reclaim_down=True)
    assert c.decide(short,ctx)['side']=='SHORT'


@pytest.mark.parametrize('field,value,reason',[
    ('real_taker',False,'REAL_TAKER_UNAVAILABLE'),('valid',False,'INVALID_OR_GAPPED_CANDLES'),
    ('flow_score',-10.,'INSUFFICIENT_REAL_FLOW'),('dir15',-1,'CLOSED_HTF_DISAGREEMENT'),
    ('efficiency',.05,'LOW_TREND_EFFICIENCY'),('rsi',80.,'RSI_EXHAUSTION')])
def test_entry_guard_reasons(field,value,reason):
    assert V94DecisionCore().decide(replace(good_feature(),**{field:value}),{'leader_count':2})['reason']==reason


def test_market_opposition_requires_joint_evidence():
    c=V94DecisionCore();f=good_feature()
    assert c.decide(f,{'leader_count':2,'leader_ret_1h_pct':-1,'breadth':0})['side']=='LONG'
    assert c.decide(f,{'leader_count':2,'leader_ret_1h_pct':-1,'breadth':-.5})['side']=='HOLD'
    assert c.decide(f,{'leader_count':1})['reason']=='LEADERS_UNAVAILABLE_OR_STALE'


def test_complete_htf_ignores_partial_bucket_changes():
    f=frame(181);f['close']=np.linspace(100,110,len(f));f.high=f.close+.05;f.low=f.close-.05;f.open=f.close
    ts=int(f.open_time.iloc[-1])+300000
    a=closed_htf_direction(f,ts,60)
    g=f.copy();last_bucket=int(g.open_time.iloc[-1])//3600000
    g.loc[g.open_time//3600000==last_bucket,'close']*=5
    assert closed_htf_direction(g,ts,60)==a


def test_gaps_and_impossible_ohlc_are_invalid():
    f=frame();f.loc[50,'open_time']+=300000
    assert not features(f).valid
    f=frame();f.loc[50,'high']=1
    assert not features(f).valid


def test_market_context_excludes_stale_leaders():
    f=frame();ts=int(f.open_time.iloc[-1])
    assert market_context({'BTCUSDT':f,'ETHUSDT':f.iloc[:-1]},ts)['leader_count']==1


def test_prefix_future_invariance():
    f=frame(240);a=features(f.iloc[:180]);f.loc[180:,'close']*=10
    assert features(f.iloc[:180])==a


@pytest.mark.parametrize('side',['LONG','SHORT'])
def test_tactical_stop_and_ratchet_have_noise_room(side):
    p=AdaptivePolicy();stop=p.initial_stop(side,100,.25)
    assert abs(stop-100)==pytest.approx(.45)
    untouched=p.ratchet(side=side,entry=100,qty=5,atr=.25,mfe_usdt=2,old_stop=stop,
        mark=100.4 if side=='LONG' else 99.6,fees_usdt=.35)
    assert untouched==stop
    tightened=p.ratchet(side=side,entry=100,qty=5,atr=.25,mfe_usdt=5,old_stop=stop,
        mark=101 if side=='LONG' else 99,fees_usdt=.35)
    assert tightened>100 if side=='LONG' else tightened<100


def test_live_and_replay_share_exact_ratchet_formula():
    r=V94RiskManager(leverage=10);p=Position('BTC/USDT','LONG',100,5,99.55,leverage=10,atr_pct=.25,entry_fee_usdt=.175,exit_fee_pct=.035)
    expected=r.policy.ratchet(side='LONG',entry=100,qty=5,atr=.25,mfe_usdt=5,old_stop=99.55,mark=101,fees_usdt=.35)
    r.update(p,101)
    assert p.stop==pytest.approx(expected)


def test_existing_stop_hit_is_checked_before_new_ratchet():
    r=V94RiskManager(leverage=10);p=Position('BTC/USDT','LONG',100,5,100.5,leverage=10,atr_pct=.25,mfe_usdt=10)
    assert r.update(p,100.3)['action']=='close'


def test_next_open_entry_bar_stop_and_net_reconciliation():
    f=frame(130);f.loc[120,'low']=99.
    e=ChronologicalPortfolioEngine({'BTCUSDT':f})
    signal_ts=int(f.open_time.iloc[119])
    e.core.decide=lambda feat,ctx:{'side':'LONG' if feat.ts==signal_ts else 'HOLD','reason':'test'}
    result=e.run(signal_ts,int(f.open_time.iloc[124]))
    assert result['trade_count']==1
    t=result['trades'][0]
    assert t['opened_at']==int(f.open_time.iloc[120])
    assert t['closed_at']==int(f.open_time.iloc[120])+300000
    assert t['reason']=='TACTICAL_STOP'
    assert result['net_pnl']==pytest.approx(result['trade_net_sum'])


def test_intrabar_exit_cash_cannot_fund_earlier_open_entry():
    f=frame(130);f.loc[120,'low']=99.
    e=ChronologicalPortfolioEngine({'BTCUSDT':f,'ETHUSDT':frame(130)},policy=replace(AdaptivePolicy(),total_risk_fraction=1,directional_risk_fraction=1))
    ts=int(f.open_time.iloc[120])
    e.wallet.open_position('BACKTEST','BTCUSDT','LONG',100,50,leverage=10,now_ms=ts-300000,stop_price=99.5)
    e.wallet.balance=125.
    e.meta['BTCUSDT']={'atr':.02,'initial_risk':2.5}
    e.pending['ETHUSDT']={'kind':'ENTRY','side':'LONG','execute_ts':ts,'atr':.02,'strength':10,'signal_close':100,'signal_ts':ts}
    e.core.decide=lambda *a:{'side':'HOLD','reason':'test'}
    result=e.run(ts,ts+300000)
    assert all(t['symbol']!='ETHUSDT' for t in result['trades'])
    assert any(k.startswith('WALLET_') for k in result['rejections'])


def test_fake_okx_neutral_flow_is_not_true_taker(monkeypatch):
    monkeypatch.setattr('src.live_runner.time.time',lambda:10000)
    rows=[[i*300000,100,101,99,100,10,1000,5,float('nan')] for i in range(30)]
    out=DualVenueLiveRunner._rows_to_df(rows)
    assert out.taker_buy_quote.isna().all()


def test_live_router_never_mutates_closed_frame_or_retries_same_bar():
    f=frame();before=f.copy(deep=True)
    ex=SimpleNamespace(positions={},set_atr=lambda *a:None)
    engine=SimpleNamespace(executor=ex)
    router=V94LiveRouter(engine,AdaptivePolicy());ts=int(f.open_time.iloc[-1])+300000
    asyncio.run(router.evaluate('binance','BTCUSDT',f,mark_price=100,now_ms=ts))
    again=asyncio.run(router.evaluate('binance','BTCUSDT',f,mark_price=100,now_ms=ts))
    assert again['reason']=='ONE_ATTEMPT_PER_CLOSED_BAR'
    pd.testing.assert_frame_equal(f,before)


def test_funding_debits_existing_position_once_and_reconciles():
    f=frame(130);ts=int(f.open_time.iloc[120]);rate=.001
    e=ChronologicalPortfolioEngine({'BTCUSDT':f},funding_events={'BTCUSDT':[{'fundingTime':ts,'fundingRate':rate}]})
    e.wallet.open_position('BACKTEST','BTCUSDT','LONG',100,50,leverage=10,now_ms=ts-300000,stop_price=99.5)
    e.meta['BTCUSDT']={'atr':.02,'initial_risk':2.5}
    e.core.decide=lambda *a:{'side':'HOLD','reason':'test'}
    result=e.run(ts,ts+300000)
    assert result['funding_cost']==pytest.approx(.5)
    assert result['net_pnl']==pytest.approx(result['trade_net_sum'])


def test_delayed_exit_is_not_postponed_every_bar():
    f=frame(135);ts=int(f.open_time.iloc[120])
    e=ChronologicalPortfolioEngine({'BTCUSDT':f},delay_bars=2)
    e.wallet.open_position('BACKTEST','BTCUSDT','LONG',100,50,leverage=10,now_ms=ts-900000,stop_price=99.5)
    e.meta['BTCUSDT']={'atr':.02,'initial_risk':2.5}
    e.core.exit_decision=lambda *a:{'should_exit':True,'exit_kind':'TEST_COMMITTED_EXIT'}
    e.core.decide=lambda *a:{'side':'HOLD','reason':'test'}
    result=e.run(ts,ts+5*300000)
    assert result['trades'][0]['closed_at']==ts+2*300000
    assert result['trades'][0]['reason']=='TEST_COMMITTED_EXIT'
