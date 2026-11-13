import math,unittest
from dataclasses import replace
from acar.data import Bar
from acar.confluence10 import adx,cci,confluence_snapshot,daily_vwap,stochastic,obv,supertrend_direction,ResearchConfluence10
from acar.portfolio import Limits,evaluate_portfolio

def series(n=240,start=1704067200,flat=False):
 out=[]
 for i in range(n):
  o=100+(0 if flat else i*.05+math.sin(i/5)*.2); c=o if flat else o+.08*math.sin(i/3)
  out.append(Bar(start+i*60,o,max(o,c)+.2,min(o,c)-.2,c,100+i%7))
 return out
class TenVoteTests(unittest.TestCase):
 def test_insufficient_history_fails_closed(self):
  self.assertFalse(confluence_snapshot(series(219))['ready']);self.assertEqual(confluence_snapshot(series(219))['reason'],'INSUFFICIENT_BARS')
 def test_full_votes_and_finite_range(self):
  s=confluence_snapshot(series());self.assertTrue(s['ready']);self.assertEqual(len(s['votes']),10)
  self.assertEqual(s['score'],sum(s['votes'].values()));self.assertTrue(all(x in (-1,0,1) for x in s['votes'].values()));self.assertTrue(0<=s['indicators']['adx']<=100)
 def test_partial_day_prevents_decision(self):
  s=confluence_snapshot(series(start=1704067200+60));self.assertFalse(s['ready']);self.assertEqual(s['reason'],'INCOMPLETE_UTC_VWAP');self.assertIsNone(ResearchConfluence10()(series(start=1704067260)))
 def test_future_tail_cannot_change_prefix(self):
  b=series(260);old=confluence_snapshot(b[:240]);b[-1]=Bar(b[-1].timestamp,130,131,129,130,200);self.assertEqual(old,confluence_snapshot(b[:240]))
 def test_duplicate_mum_rejected(self):
  b=series();b[-1]=Bar(b[-2].timestamp,b[-1].open,b[-1].high,b[-1].low,b[-1].close,b[-1].volume)
  self.assertEqual(confluence_snapshot(b)['reason'],'INVALID_CANDLES')
 def test_flat_inputs_and_ranged_indicators(self):
  b=series(flat=True);self.assertEqual(adx(b),0.0);self.assertEqual(cci(b),0.0)
  k,d=stochastic(b);self.assertTrue(0<=k[-1]<=100 and 0<=d[-1]<=100);self.assertTrue(all(x==0 for x in obv(b)));self.assertIn(supertrend_direction(b),(-1,1));self.assertIsNotNone(daily_vwap(b))
 def test_zero_volume_day_not_false_zero_vwap(self):
  b=series();b=[Bar(x.timestamp,x.open,x.high,x.low,x.close,0) for x in b];self.assertIsNone(daily_vwap(b));self.assertEqual(confluence_snapshot(b)['reason'],'INCOMPLETE_UTC_VWAP')
 def test_linear_trend_numeric_fixture(self):
  bars=[Bar(1704067200+i*60,100+i,101+i,99+i,100.5+i,10) for i in range(220)]
  result=confluence_snapshot(bars)
  self.assertEqual(result['indicators']['adx'],100.0)
  self.assertAlmostEqual(result['indicators']['vwap'],209.66666666666666,places=9)
  self.assertEqual(result['votes'],{'ema':1,'macd_cross':0,'rsi':1,'adx_ema':1,'stochastic':0,'obv':1,'cci':0,'supertrend':1,'vwap':1,'bollinger':0})
  self.assertEqual((result['side'],result['score']),('long',6))
 def test_prefix_no_lookahead_at_replay_boundary(self):
  b=series(260);strategy=ResearchConfluence10();prefix=b[:230];changed=b[:230]+[Bar(x.timestamp,x.open,x.high*2,x.low,x.close,x.volume) for x in b[230:]]
  self.assertEqual(strategy(prefix),strategy(changed[:230]))
 def test_utc_new_day_and_missing_bar(self):
  b=series(1441);r=confluence_snapshot(b);self.assertTrue(r['ready'])
  last=b[-1];self.assertAlmostEqual(r['indicators']['vwap'],(last.high+last.low+last.close)/3)
  b=series();del b[100];self.assertEqual(confluence_snapshot(b)['reason'],'INVALID_CANDLES')
 def test_boolean_and_string_price_fail_closed(self):
  for value in (True,'100',10**400):
   b=series();last=b[-1];b[-1]=Bar(last.timestamp,value,last.high,last.low,last.close,last.volume)
   self.assertEqual(confluence_snapshot(b)['reason'],'INVALID_CANDLES')
 def test_threshold_validation(self):
  for x in (True,0,9,3.5):
   with self.assertRaises(ValueError):confluence_snapshot(series(),x)
class PortfolioTests(unittest.TestCase):
 def p(self,asset='BTC',side='long',entry=100,stop=99,qty=1,mark=100):return {'asset':asset,'side':side,'entry':entry,'stop':stop,'qty':qty,'mark':mark}
 def test_accept_valid_candidate(self):self.assertTrue(evaluate_portfolio(1000,[],self.p())['allowed'])
 def test_duplicate_asset_across_venues(self):self.assertEqual(evaluate_portfolio(1000,[self.p()],self.p())['reason'],'DUPLICATE_ASSET')
 def test_single_risk_cap(self):self.assertEqual(evaluate_portfolio(1000,[],self.p(qty=10))['reason'],'MAX_PER_POSITION_NOTIONAL')
 def test_missing_and_bad_numbers_fail_closed(self):
  p=self.p();del p['mark'];self.assertEqual(evaluate_portfolio(1000,[],p)['reason'],'POSITION_DATA_UNKNOWN')
  self.assertEqual(evaluate_portfolio(float('nan'),[],self.p())['reason'],'INVALID_EQUITY')
  self.assertEqual(evaluate_portfolio(10**400,[],self.p())['reason'],'INVALID_EQUITY')
  self.assertEqual(evaluate_portfolio(1000,[],self.p(asset='btc'))['reason'],'ASSET_NOT_CANONICAL')
 def test_initial_stop_wrong_side_rejected(self):
  self.assertEqual(evaluate_portfolio(1000,[],self.p(stop=101))['reason'],'INVALID_INITIAL_STOP')
 def test_stop_risk_counts_cost_for_trailing(self):
  old=self.p(asset='ETH',entry=100,stop=101,qty=1);result=evaluate_portfolio(1000,[old],self.p(),replace(Limits(),total_risk_fraction=.05))
  self.assertTrue(result['allowed']);self.assertGreater(result['total_stop_risk'],result['candidate_stop_risk'])
 def test_directional_cap_across_assets(self):
  lim=replace(Limits(),directional_risk_fraction=.003,total_risk_fraction=.1,max_per_asset=2)
  self.assertEqual(evaluate_portfolio(1000,[self.p(asset='ETH',qty=2)],self.p(qty=1),lim)['reason'],'DIRECTION_RISK')
 def test_opposite_direction_does_not_erase_total_risk(self):
  lim=replace(Limits(),total_risk_fraction=.003,directional_risk_fraction=.1,max_per_asset=2)
  self.assertEqual(evaluate_portfolio(1000,[self.p(asset='ETH',qty=2)],self.p(side='short',stop=101),lim)['reason'],'TOTAL_RISK')
if __name__=='__main__':unittest.main()
