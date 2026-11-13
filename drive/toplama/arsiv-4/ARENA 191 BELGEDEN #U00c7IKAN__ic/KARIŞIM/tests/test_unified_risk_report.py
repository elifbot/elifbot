import tempfile,unittest
from pathlib import Path
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator
from acar.risk_report import risk_report

class RiskReportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.sim=UnifiedSimulator.create(Path(self.tmp.name)/'unified.sqlite')
  self.rules=MarketRules('BTC','0.1','0.1','0.1','0');book={'symbol':'BTC','observed_at':10,'bids':[['101','2']],'asks':[['101.1','2']]}
  self.sim.open_position('open',symbol='BTC',side='long',quantity='1',stop='99',target='110',leverage='2',next_funding=100,now=10,book_id='b1',book=book,rules=self.rules)
 def tearDown(self):self.tmp.cleanup()
 def test_fresh_equity_notional_and_risk(self):
  r=risk_report(self.sim.snapshot());self.assertEqual(r['gross_notional_at_last_marks'],'101.05');self.assertEqual(r['total_stop_scenario_risk'],'2.2011');self.assertIsNotNone(r['equity_if_fresh']);self.assertFalse(r['warnings'])
 def test_stale_unknown_equity_and_funding_due(self):
  r=risk_report(self.sim.snapshot(),100);self.assertIsNone(r['equity_if_fresh']);self.assertIn('BTC:STALE_MARK',r['warnings']);self.assertIn('BTC:FUNDING_DUE',r['warnings']);self.assertIsNone(r['stop_risk_fraction_if_fresh'])
 def test_monitor_gap_keeps_equity_as_uncertain_even_after_fresh_mark(self):
  self.sim.mark('later','BTC','101',41)
  r=risk_report(self.sim.snapshot());self.assertIn('BTC:MONITORING_GAP',r['warnings']);self.assertIsNone(r['equity_if_fresh']);self.assertTrue(r['positions'][0]['execution_uncertain'])
 def test_closed_uncertain_trade_keeps_equity_warning(self):
  from acar.omnistudio_contract import build_omni_status
  book={'symbol':'BTC','observed_at':41,'bids':[['98','1']],'asks':[['98.1','1']]}
  self.sim.process_book('gap-exit',symbol='BTC',book_id='gap-exit-book',book=book,rules=self.rules,now=41)
  snap=self.sim.snapshot();r=risk_report(snap);o=build_omni_status(snap)
  self.assertIn('EXECUTION_HISTORY_UNCERTAIN',r['warnings']);self.assertIsNone(r['equity_if_fresh']);self.assertTrue(o['account']['uncertainExecutionHistory']);self.assertFalse(o['account']['equityReliable'])
 def test_no_lookback_or_boolean_times(self):
  for value in (9,True,253402300800):
   with self.subTest(value=value),self.assertRaises(ValueError):risk_report(self.sim.snapshot(),value)
 def test_positions_are_not_mutated(self):
  before=self.sim.snapshot();risk_report(before,20);self.assertEqual(before,self.sim.snapshot())
if __name__=='__main__':unittest.main()
