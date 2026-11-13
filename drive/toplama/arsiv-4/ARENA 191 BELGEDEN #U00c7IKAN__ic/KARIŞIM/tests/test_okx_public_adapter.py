import copy,tempfile,unittest
from pathlib import Path
from acar.okx_public_adapter import parse_instrument,parse_book,parse_candles,parse_upcoming_funding,make_entry_event,PublicClient
from acar.unified_simulator import UnifiedSimulator
from unified_cli import event_execute

class OKXAdapterTests(unittest.TestCase):
 def setUp(self):
  self.symbol='BTC-USDT-SWAP';self.now=1704080400000
  self.instrument_payload={'code':'0','data':[{'instId':self.symbol,'instType':'SWAP','ctType':'linear','state':'live','settleCcy':'USDT','ctValCcy':'BTC','instCategory':'1','ruleType':'normal','ctVal':'0.01','ctMult':'1','lotSz':'1','minSz':'2','tickSz':'0.1'}]}
  self.inst=parse_instrument(self.instrument_payload,self.symbol,min_notional='5')
  self.book={'code':'0','data':[{'ts':str(self.now),'bids':[['319.4','10','0','1']],'asks':[['319.6','10','0','1']]}]}
  self.fund={'code':'0','data':[{'instId':self.symbol,'ts':str(self.now),'fundingTime':str(self.now+1000000),'fundingRate':'0.001'}]}
 def test_real_transport_uses_post_response_clock(self):
  from unittest.mock import patch
  payload=copy.deepcopy(self.book);payload['data'][0]['ts']=str(self.now+100)
  c=PublicClient(lambda url:payload);c._throttle=True
  with patch('acar.okx_public_adapter.time.time_ns',return_value=(self.now+200)*1000000):
   out=c.book(self.inst,now_ms=self.now)
  self.assertEqual(out['source_ts_ms'],self.now+100)
 def test_contract_units_to_base(self):
  self.assertEqual(self.inst.rules.qty_step,'0.01');self.assertEqual(self.inst.rules.min_qty,'0.02');self.assertEqual(self.inst.rules.min_notional,'5')
  b=parse_book(self.book,self.inst,now_ms=self.now)
  self.assertEqual(b['book']['bids'],[['319.4','0.1']]);self.assertEqual(b['book']['asks'][0][1],'0.1')
 def test_same_timestamp_same_identifier(self):
  a=parse_book(self.book,self.inst,now_ms=self.now);other=copy.deepcopy(self.book);other['data'][0]['asks'][0][1]='20'
  b=parse_book(other,self.inst,now_ms=self.now);self.assertEqual(a['book_id'],b['book_id'])
 def test_reject_unsupported_contracts_and_uncertainty(self):
  for field,value in [('ctType','inverse'),('instCategory','3'),('ruleType','pre_market'),('ctMult','2'),('ctValCcy','USDT'),('state','suspend'),('instId','ETH-USDT-SWAP'),('ctVal',''),('lotSz','0'),('minSz','1.5')]:
   p=copy.deepcopy(self.instrument_payload);p['data'][0][field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):parse_instrument(p,self.symbol,min_notional='5')
  with self.assertRaises(ValueError):parse_instrument(self.instrument_payload,self.symbol,min_notional=None)
 def test_reject_malformed_and_stale_books(self):
  for change in ({'ts':str(self.now+1)},{'ts':str(self.now-20001)},{'asks':[['319.6','0']]},{'bids':[['320','1']]},{'bids':[['319.4','0.5']]}):
   p=copy.deepcopy(self.book);p['data'][0].update(change)
   with self.subTest(change=change),self.assertRaises(ValueError):parse_book(p,self.inst,now_ms=self.now)
 def candle_rows(self):
  start=1704067200
  rows=[]
  for i in range(220):
   ts=(start+i*60)*1000;price=100+i
   rows.append([str(ts),str(price),str(price+1),str(price-1),str(price+.5),'500','10','1000','1'])
  return rows
 def test_candles_use_base_volume_and_filter_open(self):
  rows=self.candle_rows();rows.append([str(self.now),'320','321','319','320','10','20','200','0'])
  bars=parse_candles({'code':'0','data':list(reversed(rows))},now_ms=self.now);self.assertEqual(len(bars),220);self.assertEqual(bars[0].volume,10)
 def test_invalid_or_gapped_candles_fail(self):
  rows=self.candle_rows()
  for bad in (rows[:100]+rows[101:],rows+[rows[-1]],rows+[[str(self.now),'320','321','319','320','10','20','200','1']]):
   with self.assertRaises(ValueError):parse_candles({'code':'0','data':bad},now_ms=self.now)
 def test_forecast_not_settlement_and_missing_rate(self):
  f=parse_upcoming_funding(self.fund,self.symbol,now_ms=self.now);self.assertEqual(f['kind'],'PREDICTED_NOT_SETTLED')
  p=copy.deepcopy(self.fund);p['data'][0]['fundingRate']='0';self.assertEqual(parse_upcoming_funding(p,self.symbol,now_ms=self.now)['rate'],'0')
  del p['data'][0]['fundingRate']
  with self.assertRaises(ValueError):parse_upcoming_funding(p,self.symbol,now_ms=self.now)
 def test_data_to_unified_engine_with_fake_http_only(self):
  bars=parse_candles({'code':'0','data':self.candle_rows()},now_ms=self.now)
  book=parse_book(self.book,self.inst,now_ms=self.now);f=parse_upcoming_funding(self.fund,self.symbol,now_ms=self.now)
  event=make_entry_event(event_id='okx-demo',instrument=self.inst,bars=bars,book_snapshot=book,funding=f,quantity='0.02',leverage='2',now_ms=self.now)
  with tempfile.TemporaryDirectory() as d:
   sim=UnifiedSimulator.create(Path(d)/'new.sqlite');r=event_execute(sim,event)
   self.assertEqual(r['action'],'OPEN');self.assertIn(self.symbol,sim.snapshot()['state']['positions'])
 def test_entry_blocks_near_funding(self):
  bars=parse_candles({'code':'0','data':self.candle_rows()},now_ms=self.now);b=parse_book(self.book,self.inst,now_ms=self.now);f=parse_upcoming_funding(self.fund,self.symbol,now_ms=self.now)
  f['next_funding']=self.now//1000+599
  with self.assertRaises(ValueError):make_entry_event(event_id='x',instrument=self.inst,bars=bars,book_snapshot=b,funding=f,quantity='0.02',leverage='2',now_ms=self.now)
 def test_paged_history_covers_full_utc_day_and_warmup(self):
  import urllib.parse
  start=1704067200;allrows=[]
  for i in range(600):
   price=100+i*.01;allrows.append([str((start+i*60)*1000),str(price),str(price+1),str(price-1),str(price+.1),'500','10','1000','1'])
  calls=[]
  def fake(url):
   calls.append(url);u=urllib.parse.urlsplit(url);q=urllib.parse.parse_qs(u.query)
   if u.path.endswith('/candles'):rows=allrows[-300:]
   elif u.path.endswith('/history-candles'):
    before=int(q['after'][0]);rows=[r for r in allrows if int(r[0])<before][-100:]
   else:raise AssertionError('unexpected path')
   return {'code':'0','data':list(reversed(rows))}
  client=PublicClient(fake);bars=client.complete_history(self.symbol,now_ms=(start+600*60)*1000)
  self.assertEqual(len(bars),600);self.assertEqual(bars[0].timestamp,start);self.assertEqual(len(calls),4)
 def test_paged_history_nonprogress_fails_closed(self):
  rows=self.candle_rows();recent=rows[-100:]
  c=PublicClient(lambda _url:{'code':'0','data':list(reversed(recent))})
  with self.assertRaises(ValueError):c.complete_history(self.symbol,now_ms=self.now)
 def test_client_uses_only_public_allowlisted_get(self):
  calls=[]
  def fake(url):calls.append(url);return self.instrument_payload
  c=PublicClient(fake);self.assertEqual(c.instrument(self.symbol,min_notional='5'),self.inst)
  self.assertEqual(len(calls),1);self.assertTrue(calls[0].startswith('https://www.okx.com/api/v5/public/instruments?'))
  with self.assertRaises(ValueError):c.get('/api/v5/trade/order',{})
  with self.assertRaises(ValueError):c.get('/api/v5/market/books',{'instId':self.symbol,'secret':'X'})
 def test_mismatched_funding_symbol_rejected(self):
  f=copy.deepcopy(self.fund);f['data'][0]['instId']='ETH-USDT-SWAP'
  with self.assertRaises(ValueError):parse_upcoming_funding(f,self.symbol,now_ms=self.now)
if __name__=='__main__':unittest.main()
