"""v9.3 causality, global gates, flow and profit-protection regression tests."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig
from portfolio.paper_futures import Position
from src.flow_exit_manager import FlowTrendExitManager
from src.global_market_regime import GlobalMarketRegimeAnchor, compute_candle_orderflow
from src.live_runner import DualVenueLiveRunner
from strategies.base import StrategyBase, SignalResult, HOLD
from strategies.v93_flow_strategy import CausalMarketPanel, V93CanonicalFlowStrategy


def frame(n=100):
    c = 100 + np.arange(n) * 0.03 + np.sin(np.arange(n)) * 0.1
    return pd.DataFrame(dict(open_time=1790000100000+np.arange(n)*300000,
                             open=c-0.01,high=c+0.15,low=c-0.15,close=c,
                             volume=np.full(n,1000.),taker_buy_quote=np.full(n,650.)))


class Hold(StrategyBase):
    NAME = "test"
    USES_DYNAMIC_FLOW_EXIT = True
    def evaluate(self, df):
        return SignalResult(HOLD,self.NAME,"hold")
    def evaluate_exit(self,*args,**kwargs):
        return {"should_exit":False}


def position(side="LONG"):
    return Position("test","BACKTEST",side,100.,5.,50.,10.,0.175,0,
                    stop_price=92. if side == "LONG" else 108.)


@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_ratchet_is_protective_monotone_and_only_next_bar(side):
    e=SimpleBacktestEngine(Hold(),BacktestConfig(leverage=10))
    p=position(side)
    p.mfe_usdt=10
    close=103 if side=="LONG" else 97
    e._ratchet_dynamic_stop_after_bar(p,close)
    stop=p.stop_price
    assert 100<stop<close if side=="LONG" else close<stop<100
    p.mfe_usdt=2.3
    e._ratchet_dynamic_stop_after_bar(p,close)
    assert p.stop_price==stop


def test_new_intrabar_mfe_cannot_retroactively_trigger_stop():
    e=SimpleBacktestEngine(Hold(),BacktestConfig(leverage=10))
    p=position();e.portfolio.positions[p.key]=p
    df=frame(30);df.iloc[-1,df.columns.get_loc("open")]=100
    df.iloc[-1,df.columns.get_loc("high")]=103
    df.iloc[-1,df.columns.get_loc("low")]=99
    df.iloc[-1,df.columns.get_loc("close")]=102
    e._maybe_exit(p,df.iloc[-1],102,int(df.iloc[-1].open_time),df)
    assert not e.portfolio.closed_trades
    assert 100<p.stop_price<102


def test_gap_through_stop_fills_at_adverse_open_not_stop():
    e=SimpleBacktestEngine(Hold(),BacktestConfig(leverage=10))
    p=position();p.stop_price=101;e.portfolio.positions[p.key]=p
    df=frame(30)
    bar=pd.Series(dict(open=98.,high=100.,low=97.,close=99.))
    e._maybe_exit(p,bar,99,10000000,df)
    assert e.portfolio.closed_trades[-1].exit_price <= 98


def test_panel_slices_and_features_ignore_future_perturbations():
    df=frame(); mutated=df.copy();mutated.loc[70:,"close"]*=10
    a=CausalMarketPanel({"BTCUSDT":df});b=CausalMarketPanel({"BTCUSDT":mutated})
    ts=int(df.open_time.iloc[69])
    pd.testing.assert_frame_equal(a.slice_up_to("BTCUSDT",ts),b.slice_up_to("BTCUSDT",ts))
    x=V93CanonicalFlowStrategy(market_panel=a).evaluate(df.iloc[:70])
    y=V93CanonicalFlowStrategy(market_panel=b).evaluate(mutated.iloc[:70])
    assert x.signal==y.signal


def test_true_taker_flow_and_breadth_direction():
    f=frame();buy=compute_candle_orderflow(f)
    f.taker_buy_quote=350.;sell=compute_candle_orderflow(f)
    assert buy["has_real_taker"] and buy["score"]>0>sell["score"]
    g=GlobalMarketRegimeAnchor();g.update_directional_breadth_from_returns([-1,-1,-1,0.5])
    assert g.snapshot()["breadth"]["net_score"] == -0.5


def test_global_bear_blocks_countertrend_long_allows_short():
    g=GlobalMarketRegimeAnchor();g.update_leader("BTC/USDT",frame().assign(close=np.linspace(110,90,100)))
    assert not g.evaluate_global_alignment("SOL/USDT","LONG")["allowed"]
    assert g.evaluate_global_alignment("SOL/USDT","SHORT")["allowed"]


def test_negative_gross_is_not_a_profit_guard_exit():
    r=FlowTrendExitManager().evaluate_open_position(side="LONG",gross_pnl_usdt=-1,
        mfe_usdt=4,roundtrip_fee_usdt=.35,age_sec=60,ind_score=30,flow_score=30,
        combined_score=30,flow_snap={"buy_usdt":2000,"sell_usdt":1000,"cvd_60s":1000},supertrend_dir=1,rsi=60)
    assert r.get("exit_kind") not in ("WAVE_PROFIT_GUARD","NET_BREAKEVEN_SHIELD")


def test_live_forming_candles_are_excluded(monkeypatch):
    monkeypatch.setattr("src.live_runner.time.time",lambda:1200.)
    rows=[[600000,1,2,.5,1,100,100,60],[900000,1,2,.5,1,100,100,60],[1200000,1,2,.5,1,100,100,60]]
    out=DualVenueLiveRunner._rows_to_df(rows)
    assert out.ts.max()==900000
    assert "taker_buy_quote" in out


def test_cached_and_uncached_strategy_agree():
    f=frame();p=CausalMarketPanel({"BTCUSDT":f})
    s=V93CanonicalFlowStrategy(market_panel=p)
    r=s.evaluate(f)
    assert s.evaluate(f).signal==r.signal


def test_divergence_short_cannot_bypass_bullish_local_trend(monkeypatch):
    f=frame()
    s=V93CanonicalFlowStrategy(symbol="XRPUSDT")
    screen=s._compute_fast_screen(f)
    screen.update(rsi=62.,ema50=90.,fast_ind=0.,st_dir=1)
    screen['flow']['score']=-20.
    screen['core']['vwap_atr_z']=1.8
    monkeypatch.setattr(s,'_compute_fast_screen',lambda history:screen)
    monkeypatch.setattr(s,'_compute_full_features',lambda *a,**k:{
        'combined_score':0.,'ind_score':5.,'flow_score':-20.,
        'core':screen['core'],'flow':screen['flow'],
        'mtf':{'trend':'BEARISH','tf_1h':{'trend':'DOWN'}},
        'st_dir':1,'rsi':62.,'atr_pct':.5,'ema20':95.,'ema50':90.})
    monkeypatch.setattr(s,'_update_global_context',lambda *a:None)
    monkeypatch.setattr(s.regime_sm,'detect_bearish_volume_divergence',lambda *a,**k:{'triggered':True})
    assert s.evaluate(f).signal==HOLD


def test_global_bear_requires_real_decoupling_for_long():
    g=GlobalMarketRegimeAnchor()
    g.update_leader('BTC/USDT',frame().assign(close=np.linspace(110,90,100)))
    blocked=g.evaluate_global_alignment('SOL/USDT','LONG',coin_ret_1h_pct=3.,rvol=1.0,
                                         flow_score=10.,mtf_aligned=True)
    exception=g.evaluate_global_alignment('SOL/USDT','LONG',coin_ret_1h_pct=3.,rvol=2.5,
                                           flow_score=50.,mtf_aligned=True,vwap_atr_z=1.)
    assert not blocked['allowed']
    assert exception['allowed']
