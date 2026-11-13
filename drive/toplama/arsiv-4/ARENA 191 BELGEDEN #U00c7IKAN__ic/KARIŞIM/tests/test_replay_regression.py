import math
import unittest
from dataclasses import replace
from acar.data import Bar,validate_bars
from acar.replay import Config,PaperEngine
from acar.strategy import Signal,ema,rsi,atr,Confluence

def bar(i,o=100,h=101,l=99,c=100,v=100):return Bar(1704067200+i*60,o,h,l,c,v)
class Once:
    def __init__(self,side='long',a=1):self.side=side;self.a=a
    def __call__(self,bars):
        return Signal(self.side,self.a,{'test':True}) if len(bars)==1 else None
class EngineTests(unittest.TestCase):
    def base(self,**kw):return replace(Config(fee_bps=0,spread_bps=0,slippage_bps=0,cooldown_bars=0,max_hold_bars=50),**kw)
    def test_next_bar_entry_and_same_bar_collision_stop_first(self):
        r=PaperEngine(self.base(),Once()).run([bar(0),bar(1,100,104,98,100),bar(2)])
        t=r['trades'][0];self.assertEqual(t['reason'],'STOP');self.assertEqual(t['entry_time'],1704067260);self.assertEqual(t['signal_time'],t['entry_time']);self.assertAlmostEqual(t['exit'],98.5)
    def test_short_collision_stop_first(self):
        r=PaperEngine(self.base(),Once('short')).run([bar(0),bar(1,100,102,96,100)])
        self.assertEqual(r['trades'][0]['reason'],'STOP');self.assertAlmostEqual(r['trades'][0]['exit'],101.5)
    def test_gap_stop_is_worse_than_stop(self):
        bars=[bar(0),bar(1,100,100.2,99.8,100),bar(2,95,96,94,95)]
        r=PaperEngine(self.base(),Once()).run(bars);self.assertEqual(r['trades'][0]['exit'],95)
    def test_cash_trade_reconciles_with_fees(self):
        cfg=self.base(fee_bps=5,spread_bps=4,slippage_bps=2)
        r=PaperEngine(cfg,Once()).run([bar(0),bar(1,100,104,99,103),bar(2)])
        self.assertAlmostEqual(r['net_pnl'],sum(x['net_pnl'] for x in r['trades']),places=9)
        self.assertGreater(r['trades'][0]['entry_fee'],0);self.assertGreater(r['trades'][0]['exit_fee'],0)
    def test_size_cap(self):
        r=PaperEngine(self.base(max_notional=200),Once()).run([bar(0),bar(1)])
        t=r['trades'][0];self.assertLessEqual(t['entry']*t['qty'],200+1e-10)
    def test_final_signal_is_not_filled(self):
        r=PaperEngine(self.base(),lambda bars: Signal('long',1,{}) if len(bars)==2 else None).run([bar(0),bar(1)])
        self.assertEqual(r['trade_count'],0)
    def test_end_of_data_closes_and_fees_accounted(self):
        r=PaperEngine(self.base(),Once()).run([bar(0),bar(1,100,100.1,99.9,100.05)])
        self.assertEqual(r['trades'][0]['reason'],'END_OF_DATA');self.assertEqual(r['equity_curve'][-1]['equity'],r['ending_cash'])
    def test_max_hold(self):
        r=PaperEngine(self.base(max_hold_bars=1),Once()).run([bar(0),bar(1,100,100.1,99.9,100)])
        self.assertEqual(r['trades'][0]['reason'],'MAX_HOLD')
    def test_halt_blocks_future_entries(self):
        cfg=self.base(risk_fraction=.05,daily_loss_fraction=.001,max_notional=10000)
        r=PaperEngine(cfg,lambda bars: Signal('long',1,{})).run([bar(0),bar(1,100,101,98,99),bar(2),bar(3)])
        self.assertEqual(r['trade_count'],1);self.assertTrue(any(e['type']=='DAILY_HALT' for e in r['events']))
    def test_invalid_config(self):
        for cfg in [self.base(risk_fraction=float('nan')),self.base(initial_cash=0),self.base(fee_bps=-1),self.base(interval=0),self.base(max_hold_bars=0)]:
            with self.assertRaises(ValueError):PaperEngine(cfg,Once())
    def test_invalid_candles_fail_closed(self):
        for series in [[bar(0),bar(2)],[bar(0),bar(0)],[bar(0,h=99)],[bar(0,v=-1)],[bar(0,c=float('nan'))]]:
            with self.assertRaises(ValueError):validate_bars(series,60)
    def test_indicators(self):
        self.assertAlmostEqual(ema([5]*30,9),5);self.assertEqual(rsi(list(range(30))),100);self.assertEqual(rsi([4]*30),50);self.assertIsNone(atr([bar(0)]))
    def test_strategy_prefix_independence(self):
        bars=[bar(i,100+i*.1,101+i*.1,99+i*.1,100.05+i*.1,100+(i%7)) for i in range(120)]
        s=Confluence(); a=s(bars[:95]); b=s(list(bars[:95]));self.assertEqual(a,b)
        self.assertIsNone(s(bars[:20]))
    def test_zero_atr_signal_rejected(self):
        r=PaperEngine(self.base(),Once(a=0)).run([bar(0),bar(1)])
        self.assertEqual(r['trade_count'],0);self.assertTrue(any(e['type']=='ENTRY_BLOCKED' for e in r['events']))
if __name__=='__main__':unittest.main()

class ResearchTests(unittest.TestCase):
    def test_shadow_ledgers_are_independent_and_deterministic(self):
        from acar.research import compare_thresholds
        bars=[bar(i,100+i*.02,100.5+i*.02,99.5+i*.02,100.1+i*.02,100+i%8) for i in range(70)]
        cfg=Config()
        x=compare_thresholds(bars,cfg);y=compare_thresholds(bars,cfg)
        self.assertEqual(x,y);self.assertEqual(set(x['results']),{'2','3','4'})
        self.assertTrue(all(z['starting_cash']==cfg.initial_cash for z in x['results'].values()))
    def test_future_bars_do_not_change_past_signals(self):
        data=[bar(i,100+i*.01,101+i*.01,99+i*.01,100.1+i*.01,100+i%7) for i in range(90)]
        altered=data[:70]+[bar(i,300+i*.01,301+i*.01,299+i*.01,300.1+i*.01,100+i%7) for i in range(70,90)]
        s=Confluence(threshold=2)
        for n in range(50,71): self.assertEqual(s(data[:n]),s(altered[:n]))

class DynamicStopTests(unittest.TestCase):
    def test_trail_only_applies_after_closing_bar(self):
        cfg=Config(fee_bps=0,spread_bps=0,slippage_bps=0,target_atr=10,trailing_atr=1,max_hold_bars=10,cooldown_bars=0)
        bars=[bar(0),bar(1,100,102.2,99,102),bar(2,102,102.1,100.5,101)]
        r=PaperEngine(cfg,Once()).run(bars)
        self.assertEqual(r['trades'][0]['reason'],'STOP')
        self.assertEqual(r['trades'][0]['exit_time'],bars[2].timestamp+60)
        self.assertAlmostEqual(r['trades'][0]['exit'],101)
        self.assertTrue(any(e['type']=='STOP_UPDATE' for e in r['events']))
    def test_short_stop_only_moves_down(self):
        cfg=Config(fee_bps=0,spread_bps=0,slippage_bps=0,target_atr=10,trailing_atr=1,max_hold_bars=10)
        bars=[bar(0),bar(1,100,101,97.8,98),bar(2,98,99.5,97.9,99)]
        r=PaperEngine(cfg,Once('short')).run(bars)
        self.assertEqual(r['trades'][0]['reason'],'STOP');self.assertAlmostEqual(r['trades'][0]['exit'],99)
