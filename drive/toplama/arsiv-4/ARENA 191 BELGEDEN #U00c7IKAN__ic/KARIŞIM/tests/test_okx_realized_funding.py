import copy, unittest, urllib.parse
from acar.okx_public_adapter import parse_realized_funding,parse_funding_mark_proxy,PublicClient

class FundingEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.symbol='BTC-USDT-SWAP';self.t=1704080400;self.now=(self.t+120)*1000
  self.row={'instType':'SWAP','instId':self.symbol,'fundingTime':str(self.t*1000),'fundingRate':'0.09','realizedRate':'-0.001'}
  self.history={'code':'0','data':[self.row]}
  self.mark={'code':'0','data':[[str(self.t*1000),'100','102','99','101','1']]}
 def history_parse(self,p):return parse_realized_funding(p,self.symbol,settlement_ts=self.t,now_ms=self.now)
 def mark_parse(self,p):return parse_funding_mark_proxy(p,settlement_ts=self.t,now_ms=self.now)
 def test_uses_realized_not_forecast(self):
  out=self.history_parse(self.history);self.assertEqual(out['rate'],'-0.001');self.assertEqual(out['rate_kind'],'OKX_REALIZED_RATE')
 def test_missing_nonfinite_and_wrong_identity_refused(self):
  for key,value in [('realizedRate',None),('realizedRate','NaN'),('realizedRate','2'),('instId','ETH-USDT-SWAP'),('instType','FUTURES'),('fundingTime',str((self.t-60)*1000))]:
   row=copy.deepcopy(self.row)
   if value is None:del row[key]
   else:row[key]=value
   with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.history_parse({'code':'0','data':[row]})
 def test_duplicates_missing_or_later_funding_fail(self):
  newer=dict(self.row,fundingTime=str((self.t+60)*1000))
  for data in ([],[self.row,self.row],[self.row,newer]):
   with self.subTest(data=data),self.assertRaises(ValueError):self.history_parse({'code':'0','data':data})
 def test_finalization_delay_and_alignment(self):
  for t,now in ((self.t,self.now-1000),(self.t+1,self.now+1000)):
   with self.assertRaises(ValueError):parse_realized_funding(self.history,self.symbol,settlement_ts=t,now_ms=now)
 def test_candle_proxy_not_exact_and_invalid_data(self):
  out=self.mark_parse(self.mark);self.assertEqual(out['mark_price_proxy'],'100');self.assertEqual(out['mark_kind'],'ONE_MINUTE_MARK_OPEN_PROXY_NOT_EXACT')
  for rows in ([],self.mark['data']*2,[[str(self.t*1000),'100','102','99','101','0']],[[str(self.t*1000),'100','98','99','101','1']],[[str((self.t+60)*1000),'100','102','99','101','1']]):
   with self.subTest(rows=rows),self.assertRaises(ValueError):self.mark_parse({'code':'0','data':rows})
 def test_adapter_public_allowlist_and_full_evidence(self):
  seen=[]
  def fake(url):
   u=urllib.parse.urlsplit(url);seen.append(u.path)
   if u.path.endswith('funding-rate-history'):return self.history
   if u.path.endswith('history-mark-price-candles'):return self.mark
   if u.path.endswith('funding-rate'):return {'code':'0','data':[{'instId':self.symbol,'ts':str(self.now),'fundingTime':str((self.t+28800)*1000),'fundingRate':'0.01'}]}
   raise AssertionError(u.path)
  out=PublicClient(fake).realized_settlement(self.symbol,settlement_ts=self.t,now_ms=self.now)
  self.assertEqual((out['rate'],out['mark_price_proxy'],out['next_funding']),('-0.001','100',self.t+28800));self.assertEqual(len(seen),3)
  with self.assertRaises(ValueError):PublicClient(fake).get('/api/v5/market/history-mark-price-candles',{'instId':self.symbol,'key':'secret'})
