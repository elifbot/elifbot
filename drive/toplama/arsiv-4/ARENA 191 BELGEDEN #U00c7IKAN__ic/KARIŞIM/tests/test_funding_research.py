import unittest
from dataclasses import replace
from acar.funding_research import Settlement,apply_settlement
class FundingResearchTests(unittest.TestCase):
 def setUp(self):
  self.e=Settlement('OKX','BTC-USDT-SWAP',1000,1002,.001,100,True)
  self.p={'id':'position-1','venue':'OKX','instrument':'BTC-USDT-SWAP','side':'long','qty_base':2.,'opened_at':900,'closed_at':None};self.a={'cash':1000.,'applied':{}}
 def test_long_pays_and_short_receives(self):
  a,r=apply_settlement(self.a,self.e,self.p);self.assertAlmostEqual(a['cash'],999.8);self.assertAlmostEqual(r['cash_delta'],-.2)
  p=dict(self.p,side='short');a,r=apply_settlement(self.a,self.e,p);self.assertAlmostEqual(a['cash'],1000.2)
  self.assertEqual(self.a,{'cash':1000.,'applied':{}})
 def test_negative_rate_reverses(self):
  a,r=apply_settlement(self.a,replace(self.e,rate=-.001),self.p);self.assertAlmostEqual(a['cash'],1000.2)
 def test_idempotent_and_conflicting_duplicate_fails(self):
  a,_=apply_settlement(self.a,self.e,self.p);b,r=apply_settlement(a,self.e,self.p);self.assertFalse(r['applied']);self.assertEqual(a,b)
  with self.assertRaises(ValueError):apply_settlement(a,replace(self.e,rate=.002),self.p)
 def test_unconfirmed_missing_and_bad_values_rejected(self):
  for e in [replace(self.e,confirmed=False),replace(self.e,rate=float('nan')),replace(self.e,mark_price=0),replace(self.e,finalized_at=999),replace(self.e,rate=2)]:
   with self.assertRaises(ValueError):apply_settlement(self.a,e,self.p)
 def test_open_and_close_boundary_ambiguous_rejected(self):
  for p in [dict(self.p,opened_at=1000),dict(self.p,closed_at=1000),dict(self.p,qty_base=None),dict(self.p,side='BUY'),dict(self.p,instrument='ETH-USDT-SWAP')]:
   with self.assertRaises(ValueError):apply_settlement(self.a,self.e,p)
 def test_distinct_position_same_settlement_not_deduped(self):
  a,_=apply_settlement(self.a,self.e,self.p);b,r=apply_settlement(a,self.e,dict(self.p,id='p2'));self.assertTrue(r['applied']);self.assertAlmostEqual(b['cash'],999.6)
if __name__=='__main__':unittest.main()
