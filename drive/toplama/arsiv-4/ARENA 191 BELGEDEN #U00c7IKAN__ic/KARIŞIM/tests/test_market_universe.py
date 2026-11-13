import copy,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from acar.market_universe import normalize_okx,normalize_binance,scan,fetch_public
from market_universe_cli import main

NOW=1700000000000

def okxrow(base='BTC'):
 return {'instId':base+'-USDT-SWAP','instType':'SWAP','state':'live','ctType':'linear','settleCcy':'USDT','ctValCcy':base,'instCategory':'1','ruleType':'normal','ctVal':'0.01','ctMult':'1','lotSz':'1','minSz':'1','tickSz':'0.1'}
def okxtick(base='BTC',ts=NOW):
 return {'instId':base+'-USDT-SWAP','last':'100','bidPx':'99.9','askPx':'100.1','volCcy24h':'12','ts':str(ts)}
def bnrow(base='BTC'):
 return {'symbol':base+'USDT','baseAsset':base,'quoteAsset':'USDT','marginAsset':'USDT','underlyingType':'COIN','contractType':'PERPETUAL','status':'TRADING','filters':[{'filterType':'PRICE_FILTER','tickSize':'0.1'}]}
def bntick(base='BTC',ts=NOW):
 return {'symbol':base+'USDT','lastPrice':'100','quoteVolume':'1200','closeTime':ts}
def fixture():
 return {'OKX_INSTRUMENTS':{'code':'0','data':[okxrow()]},'OKX_TICKERS':{'code':'0','data':[okxtick()]},'BINANCE_INSTRUMENTS':{'symbols':[bnrow()]},'BINANCE_TICKERS':[bntick()]}

class UniverseTests(unittest.TestCase):
 def test_two_venues_do_not_merge_or_claim_binance_engine(self):
  r=scan(fetch=fixture().__getitem__,clock_ms=lambda:NOW)
  self.assertEqual(r['mode'],'PUBLIC_READ_ONLY_NO_PAPER');self.assertEqual(r['counts']['total_contracts'],2)
  self.assertEqual([(x['venue'],x['symbol']) for x in r['markets']],[('OKX','BTC-USDT-SWAP'),('BINANCE','BTCUSDT')])
  self.assertTrue(r['markets'][0]['okx_preliminary_candidate']);self.assertFalse(r['markets'][1]['paper_engine_connected'])
 def test_http_451_is_explicit_and_other_exchange_preserved(self):
  d=fixture();seen=[]
  def fetch(k):
   seen.append(k)
   if k=='BINANCE_INSTRUMENTS':raise urllib.error.HTTPError('x',451,'blocked',{},None)
   return d[k]
  r=scan(fetch=fetch,clock_ms=lambda:NOW)
  self.assertEqual(r['counts']['by_venue'],{'OKX':1});self.assertEqual(r['endpoints']['BINANCE_INSTRUMENTS']['http_status'],451)
  self.assertNotIn('BINANCE_TICKERS',seen);self.assertEqual(r['endpoints']['BINANCE_TICKERS']['status'],'SKIPPED_METADATA_UNAVAILABLE')
 def test_okx_only_selection_never_requests_binance(self):
  d=fixture();seen=[]
  def fetch(key):seen.append(key);return d[key]
  r=scan(fetch=fetch,clock_ms=lambda:NOW,venues=('OKX',))
  self.assertEqual(seen,['OKX_INSTRUMENTS','OKX_TICKERS']);self.assertEqual(r['endpoints']['BINANCE_INSTRUMENTS']['status'],'SKIPPED_BY_SELECTION')
 def test_explicit_public_host_does_not_automatically_fallback(self):
  d=fixture();r=scan(fetch=d.__getitem__,clock_ms=lambda:NOW,binance_host='www')
  self.assertEqual(r['binance_public_host'],'https://www.binance.com')
  with self.assertRaises(ValueError):scan(fetch=d.__getitem__,clock_ms=lambda:NOW,binance_host='untrusted')
 def test_binance_coin_category_and_unknown_are_not_conflated(self):
  b=bnrow('ETH');b['underlyingType']='INDEX';c=bnrow('DOGE');c.pop('underlyingType')
  result,exc=normalize_binance({'symbols':[bnrow(),b,c]},[bntick()],NOW)
  self.assertEqual(len(result),1);self.assertEqual(exc['NON_COIN_OR_UNKNOWN_UNDERLYING'],2)
 def test_ticker_failure_does_not_hide_metadata_or_claim_candidates(self):
  d=fixture()
  def fetch(k):
   if k=='OKX_TICKERS':raise OSError('network')
   return d[k]
  r=scan(fetch=fetch,clock_ms=lambda:NOW)
  self.assertEqual(r['markets'][0]['ticker']['status'],'MISSING');self.assertFalse(r['markets'][0]['okx_preliminary_candidate'])
  self.assertEqual(r['endpoints']['OKX_TICKERS']['status'],'ERROR')
 def test_stale_future_and_invalid_quotes_not_candidates(self):
  for row,expected in [(okxtick(ts=NOW-120001),'STALE'),(okxtick(ts=NOW+2001),'FUTURE'),(dict(okxtick(),bidPx='101'),'INVALID'),(dict(okxtick(),last='NaN'),'INVALID')]:
   r,_=normalize_okx({'code':'0','data':[okxrow()]},{'code':'0','data':[row]},NOW)
   self.assertEqual(r[0]['ticker']['status'],expected);self.assertFalse(r[0]['okx_preliminary_candidate'])
 def test_excludes_unsupported_contracts_and_engine_metadata(self):
  bad=okxrow('ETH');bad['ctType']='inverse';unsupported=okxrow('SOL');unsupported['ctMult']='2'
  result,exc=normalize_okx({'code':'0','data':[okxrow(),bad,unsupported]},{'code':'0','data':[okxtick(),okxtick('SOL')]},NOW)
  self.assertEqual(len(result),2);self.assertEqual(exc['NOT_LIVE_LINEAR_USDT_SWAP'],1);self.assertFalse(result[1]['okx_engine_metadata_compatible'])
 def test_non_crypto_unknown_categories_and_premarket_are_not_selected(self):
  stock=okxrow('AAPL');stock['instCategory']='3';unknown=okxrow('GOLD');unknown.pop('instCategory');premarket=okxrow('ETH');premarket['ruleType']='pre_market'
  result,exc=normalize_okx({'code':'0','data':[okxrow(),stock,unknown,premarket]},{'code':'0','data':[okxtick(),okxtick('ETH')]},NOW)
  self.assertEqual(exc['NON_CRYPTO_OR_UNKNOWN_CATEGORY'],2);self.assertEqual(len(result),2);self.assertFalse(result[1]['okx_preliminary_candidate'])
 def test_malformed_tickers_leave_instruments_available(self):
  d=fixture();d['OKX_TICKERS']['data'].append(okxtick())
  r=scan(fetch=d.__getitem__,clock_ms=lambda:NOW)
  self.assertEqual(r['endpoints']['OKX_TICKERS']['status'],'ERROR');self.assertEqual(r['counts']['by_venue']['OKX'],1);self.assertEqual(r['markets'][0]['ticker']['status'],'MISSING')
 def test_binance_only_usdt_trading_perpetual(self):
  unsupported=bnrow('ETH');unsupported['contractType']='CURRENT_QUARTER'
  result,exc=normalize_binance({'symbols':[bnrow(),unsupported]},[bntick()],NOW)
  self.assertEqual(len(result),1);self.assertEqual(exc['NOT_TRADING_USDT_PERPETUAL'],1);self.assertEqual(result[0]['ticker']['timestamp_kind'],'24H_WINDOW_CLOSE')
 def test_binance_unicode_and_quarterly_symbols_are_handled_safely(self):
  coin=bnrow('龙虾');quarter=bnrow('BTC');quarter['symbol']='BTCUSDT_261225';quarter['contractType']='CURRENT_QUARTER'
  result,excluded=normalize_binance({'symbols':[coin,quarter]},[bntick('龙虾')],NOW)
  self.assertEqual(result[0]['symbol'],'龙虾USDT');self.assertEqual(excluded['NOT_TRADING_USDT_PERPETUAL'],1)
 def test_duplicate_symbol_invalidates_venue(self):
  d=fixture();d['OKX_INSTRUMENTS']['data'].append(okxrow())
  r=scan(fetch=d.__getitem__,clock_ms=lambda:NOW)
  self.assertEqual(r['endpoints']['OKX_INSTRUMENTS']['status'],'INVALID_PAYLOAD');self.assertEqual(r['counts']['by_venue'],{'BINANCE':1})
 def test_bulk_more_than_one_thousand_without_truncation(self):
  rows=[bnrow('C'+str(i)) for i in range(1400)];ticks=[bntick('C'+str(i)) for i in range(1400)]
  result,_=normalize_binance({'symbols':rows},ticks,NOW);self.assertEqual(len(result),1400)
 def test_oversized_and_unrecognized_endpoints_rejected(self):
  with self.assertRaises(ValueError):normalize_binance({'symbols':[bnrow()]*20001},[],NOW)
  with self.assertRaises(ValueError):fetch_public('BINANCE_ORDER')
 def test_output_does_not_overwrite_or_network_before_reservation(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'report.json';path.write_text('old')
   with patch('market_universe_cli.scan') as f:self.assertEqual(main(['--out',str(path)]),2);f.assert_not_called()
   self.assertEqual(path.read_text(),'old')
 def test_output_only_public_data(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'report.json';r=scan(fetch=fixture().__getitem__,clock_ms=lambda:NOW)
   with patch('market_universe_cli.scan',return_value=r):self.assertEqual(main(['--out',str(path)]),0)
   self.assertEqual(json.loads(path.read_text())['counts']['total_contracts'],2)
if __name__=='__main__':unittest.main()
