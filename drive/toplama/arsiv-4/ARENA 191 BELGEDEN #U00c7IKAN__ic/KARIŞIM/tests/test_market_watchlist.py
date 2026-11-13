import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from acar.market_universe import scan
from acar.market_watchlist import make_watchlist
from market_watchlist_cli import main
from public_paper_loop import load_config
from test_market_universe import fixture,NOW

class WatchlistTests(unittest.TestCase):
 def setUp(self):self.report=scan(fetch=fixture().__getitem__,clock_ms=lambda:NOW)
 def config(self,**kw):
  params={'now_ms':NOW,'target_notional':'20','leverage':'2','min_notional':'5'};params.update(kw)
  return make_watchlist(self.report,**params)
 def test_generates_compatible_config_and_does_not_select_binance(self):
  config,summary=self.config();self.assertEqual(summary['symbols'],['BTC-USDT-SWAP']);self.assertEqual(config['instruments'][0]['quantity'],'0.19')
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'c.json';path.write_text(json.dumps(config));self.assertEqual(load_config(path),config)
 def test_stale_future_missing_and_excess_risk_refused(self):
  for kwargs in ({'now_ms':NOW+120001},{'now_ms':NOW-2001},{'target_notional':'251'},{'leverage':'4'},{'count':5},{'min_notional':'21'}):
   with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.config(**kwargs)
  self.report['markets'][0]['ticker']['timestamp_ms']=NOW-30001
  with self.assertRaises(ValueError):self.config()
 def test_no_eligible_minimum_notional_or_crossed_ticker(self):
  self.report['markets'][0]['contract_min']='100000'
  with self.assertRaises(ValueError):self.config()
  self.report['markets'][0]['contract_min']='1';self.report['markets'][0]['ticker']['bid']='101'
  with self.assertRaises(ValueError):self.config()
 def test_report_cannot_write_over_input(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'in.json';p.write_text(json.dumps(self.report));old=p.read_text()
   with patch('market_watchlist_cli.time.time_ns',return_value=NOW*1000000):
    self.assertEqual(main(['--report',str(p),'--out',str(p),'--target-notional','20','--leverage','2','--min-notional','5']),2)
   self.assertEqual(p.read_text(),old)
 def test_selection_respects_volume_rank_and_four_limit(self):
  initial=self.report['markets'][0];self.report['markets']=[]
  for i in range(6):
   x=copy.deepcopy(initial);base='C'+str(i);x['symbol']=base+'-USDT-SWAP';x['base']=base;x['contract_value_currency']=base;x['ticker']['base_volume_24h']=str(i+1);self.report['markets'].append(x)
  config,summary=self.config();self.assertEqual(summary['symbols'],['C5-USDT-SWAP','C4-USDT-SWAP','C3-USDT-SWAP','C2-USDT-SWAP']);self.assertEqual(len(config['instruments']),4)
if __name__=='__main__':unittest.main()
