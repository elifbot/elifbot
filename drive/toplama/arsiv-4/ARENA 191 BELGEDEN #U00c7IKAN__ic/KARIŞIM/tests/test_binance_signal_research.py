import unittest
from acar.data import Bar
from binance_signal_research import evaluate

class BinanceResearchTests(unittest.TestCase):
 def test_analysis_is_non_trading_and_uses_closed_data(self):
  start=1704067200
  bars=[Bar(start+i*60,100+i,101+i,99+i,100.5+i,10) for i in range(220)]
  class Fake:
   def complete_history(self,symbol,now_ms):self.symbol=symbol;return bars
  c=Fake();now=(bars[-1].timestamp+60)*1000
  result=evaluate(c,'BTCUSDT',clock_ms=lambda:now)
  self.assertEqual(result['mode'],'PUBLIC_RESEARCH_ONLY_NO_PAPER');self.assertEqual(result['closed_bars'],220);self.assertEqual(c.symbol,'BTCUSDT')
  self.assertTrue(result['research']['ready'])
  with self.assertRaisesRegex(ValueError,'stale'):evaluate(c,'BTCUSDT',clock_ms=lambda:now+31000)
if __name__=='__main__':unittest.main()
