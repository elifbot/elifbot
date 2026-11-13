import unittest
from acar.binance_public_data import BinancePublicDetails,parse_candles,parse_depth,parse_premium
NOW=1700000040000
class BinanceDetailsTests(unittest.TestCase):
 def setUp(self):
  self.base=NOW//60000*60000
  self.depth={'lastUpdateId':123,'E':NOW-1,'bids':[['100','1'],['99','2']],'asks':[['101','1'],['102','2']]}
  self.premium={'symbol':'BTCUSDT','time':NOW-1,'nextFundingTime':NOW+3600000,'markPrice':'100','indexPrice':'100','lastFundingRate':'0.001'}
 def test_closed_candles_only_and_gaps_fail(self):
  def candle(t):return [t,'100','101','99','100','10',t+59999]
  out=parse_candles([candle(self.base-60000),candle(self.base)],now_ms=self.base+1000)
  self.assertEqual(len(out),1)
  with self.assertRaises(ValueError):parse_candles([candle(self.base-180000),candle(self.base-60000)],now_ms=self.base)
 def test_depth_and_bad_time_sort_or_cross(self):
  self.assertEqual(parse_depth(self.depth,symbol='BTCUSDT',now_ms=NOW)['last_update_id'],123)
  for bad in (dict(self.depth,E=NOW+1),dict(self.depth,bids=[['98','1'],['99','1']]),dict(self.depth,asks=[['99','1']])):
   with self.assertRaises(ValueError):parse_depth(bad,symbol='BTCUSDT',now_ms=NOW)
 def test_premium_never_claims_settlement(self):
  p=parse_premium(self.premium,symbol='BTCUSDT',now_ms=NOW);self.assertEqual(p['rate_semantics'],'LATEST_RATE_NOT_SETTLEMENT_PROOF')
  with self.assertRaises(ValueError):parse_premium(dict(self.premium,nextFundingTime=NOW),symbol='BTCUSDT',now_ms=NOW)
 def test_complete_history_requires_full_utc_day_and_warmup(self):
  start=1699920000
  def candle(t):return [t*1000,'100','101','99','100','10',t*1000+59999]
  rows=[candle(start+i*60) for i in range(300)]
  c=BinancePublicDetails(lambda url:rows)
  bars=c.complete_history('BTCUSDT',now_ms=(start+300*60)*1000)
  self.assertEqual(len(bars),300);self.assertEqual(bars[0].timestamp,start)
  bad=BinancePublicDetails(lambda url:rows[10:])
  with self.assertRaisesRegex(ValueError,'incomplete UTC history'):bad.complete_history('BTCUSDT',now_ms=(start+300*60)*1000)
 def test_host_option_is_explicit_and_fixed(self):
  seen=[];c=BinancePublicDetails(lambda url:(seen.append(url) or self.depth),binance_host='www')
  c.depth('BTCUSDT',now_ms=NOW);self.assertTrue(seen[0].startswith('https://www.binance.com/fapi/v1/depth?'))
  with self.assertRaises(ValueError):BinancePublicDetails(binance_host='example.com')
 def test_real_transport_checks_post_response_clock(self):
  from unittest.mock import patch
  response=dict(self.depth,E=NOW+100);c=BinancePublicDetails(lambda url:response);c._throttle=True
  with patch('acar.binance_public_data.time.time_ns',return_value=(NOW+200)*1000000):
   out=c.depth('BTCUSDT',now_ms=NOW)
  self.assertEqual(out['event_time_ms'],NOW+100)
 def test_fixed_get_allowlist_and_input(self):
  seen=[];c=BinancePublicDetails(transport=lambda url:(seen.append(url) or self.depth))
  c.depth('BTCUSDT',now_ms=NOW)
  self.assertTrue(seen[0].startswith('https://fapi.binance.com/fapi/v1/depth?'))
  with self.assertRaises(ValueError):c.get('order',symbol='BTCUSDT')
  with self.assertRaises(ValueError):c.get('depth',symbol='BTCUSDT&key=x',limit=20)
  with self.assertRaises(ValueError):c.get('klines',symbol='BTCUSDT',limit=1501)
if __name__=='__main__':unittest.main()
