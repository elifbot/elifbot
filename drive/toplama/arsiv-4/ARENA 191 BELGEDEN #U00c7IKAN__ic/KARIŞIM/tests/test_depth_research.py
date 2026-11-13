import copy,unittest
from dataclasses import replace
from acar.depth_research import MarketRules,estimate_depth

class DepthResearchTests(unittest.TestCase):
 def setUp(self):
  self.book={'symbol':'BTC-USDT-SWAP','observed_at':100,'bids':[['99','0.5'],['98','1']], 'asks':[['101','0.4'],['102','0.3']]}
  self.rules=MarketRules('BTC-USDT-SWAP','0.1','1','0.1','0')
  self.args=dict(book=self.book,rules=self.rules,side='buy',quantity='0.6',now=101,max_age=5,fee_rate='0.001')
 def run_case(self,**changes):return estimate_depth(**dict(self.args,**changes))
 def test_buy_weighted_depth_and_fee(self):
  before=copy.deepcopy(self.book);r=self.run_case()
  self.assertEqual((r['filled_qty'],r['remaining_qty'],r['notional'],r['average_price'],r['fee_estimate']),('0.6','0','60.8','101.333333333333','0.0608'))
  self.assertEqual(self.book,before)
 def test_sell_depth_and_partial(self):
  r=self.run_case(side='sell',quantity='2');self.assertEqual((r['status'],r['filled_qty'],r['remaining_qty'],r['notional']),('PARTIAL','1.5','0.5','147.5'))
 def test_limit_blocks_higher_level(self):
  r=self.run_case(limit_price='101');self.assertEqual((r['status'],r['filled_qty'],r['remaining_qty']),('PARTIAL','0.4','0.2'))
 def test_sell_limit_and_no_fill(self):
  r=self.run_case(side='sell',limit_price='100');self.assertEqual(r['status'],'UNFILLED');self.assertIsNone(r['average_price'])
 def test_age_boundary_and_sell_limit(self):
  self.assertEqual(self.run_case(now=105)['status'],'FILLED')
  r=self.run_case(side='sell',quantity='1',limit_price='99')
  self.assertEqual((r['status'],r['filled_qty'],r['remaining_qty']),('PARTIAL','0.5','0.5'))
 def test_extreme_values_fail_closed(self):
  for changes in ({'quantity':10**400},{'fee_rate':10**400},{'now':float('inf')}):
   with self.subTest(changes=changes),self.assertRaises(ValueError):self.run_case(**changes)
 def test_unknown_stale_or_future(self):
  for changes in ({'now':106},{'now':99},{'max_age':None},{'fee_rate':None}):
   with self.subTest(changes=changes),self.assertRaises(ValueError):self.run_case(**changes)
 def test_invalid_rules(self):
  for changes in ({'quantity':'0.15'},{'limit_price':'101.5'},{'quantity':True},{'fee_rate':'NaN'},{'rules':replace(self.rules,min_qty='0.7')},{'rules':replace(self.rules,min_notional='100')}):
   with self.subTest(changes=changes),self.assertRaises(ValueError):self.run_case(**changes)
 def test_bad_books(self):
  for book in ({'symbol':'X','observed_at':100,'bids':[['99','1']],'asks':[['101','1']]},dict(self.book,bids=[]),dict(self.book,asks=[['98','1']]),dict(self.book,asks=[['102','1'],['101','1']]),dict(self.book,bids=[['99','1'],['99','2']]),dict(self.book,asks=[['101','0']])):
   with self.subTest(book=book),self.assertRaises(ValueError):self.run_case(book=book)
 def test_small_untradeable_level_is_not_filled(self):
  r=self.run_case(book=dict(self.book,asks=[['101','0.09'],['102','0.3']]));self.assertEqual(r['filled_qty'],'0.3');self.assertEqual(r['average_price'],'102')
if __name__=='__main__':unittest.main()
