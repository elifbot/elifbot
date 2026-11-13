import math,unittest
from acar.data import Bar
from acar.replay import Config
from acar.stress_research import cost_stress
class StressTests(unittest.TestCase):
 def setUp(self):
  self.bars=[]
  for i in range(120):
   o=100+i*.08+math.sin(i/7);c=o+.1
   self.bars.append(Bar(1704067200+i*60,o,max(o,c)+.5,min(o,c)-.5,c,1000))
  self.cfg=Config(initial_cash=1000,max_notional=250)
  self.sc=[{'name':'base','fee_bps':5,'spread_bps':4,'slippage_bps':2},{'name':'stress','fee_bps':20,'spread_bps':10,'slippage_bps':10}]
 def test_equal_cash_and_deterministic(self):
  r=cost_stress(self.bars,self.cfg,self.sc)
  self.assertEqual(r,cost_stress(self.bars,self.cfg,self.sc));self.assertEqual([x['name'] for x in r['scenarios']],['base','stress']);self.assertEqual(r['base_config']['initial_cash'],1000)
 def test_bad_or_duplicate_scenarios_rejected(self):
  for bad in ([],[self.sc[0],self.sc[0]],[dict(self.sc[0],fee_bps=float('nan'))],[dict(self.sc[0],fee_bps=10**400)],[dict(self.sc[0],other=1)]):
   with self.subTest(bad=bad),self.assertRaises(ValueError):cost_stress(self.bars,self.cfg,bad)
 def test_bad_strategy_and_missing_candle_fail(self):
  with self.assertRaises(ValueError):cost_stress(self.bars,self.cfg,self.sc,'unknown')
  with self.assertRaises(ValueError):cost_stress(self.bars[:40]+self.bars[41:],self.cfg,self.sc)
 def test_confluence10_works_without_synthetic_signals(self):
  r=cost_stress(self.bars,self.cfg,self.sc,'confluence10');self.assertTrue(all(x['trade_count']==0 for x in r['scenarios']))
if __name__=='__main__':unittest.main()
