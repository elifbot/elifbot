import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from acar.data import Bar
from acar.strategy import Signal
from acar.engine import process,initial_state
from acar.store import Store
from acar import market

def seq(n=80,start=1704067200):
 return [Bar(start+60*i,100+i*.1,101+i*.1,99+i*.1,100.1+i*.1,1000) for i in range(n)]
def quote(now,bid=107.99,ask=108.01):return {'time':now,'bid':bid,'ask':ask,'spread_bps':(ask-bid)/((ask+bid)/2)*10000}
def funding(now):return {'rate':0.,'observed':now,'settlement':now+2000}
class AllAgree:
 def __call__(self,bars):return Signal('long',1.0,{'test':True})
class PaperTests(unittest.TestCase):
 def setUp(self):
  self.bars=seq();self.now=self.bars[-1].timestamp+62
  self.state,_,_=process(initial_state(self.now),self.bars,quote(self.now),funding(self.now),self.now)
 def next(self):
  b=self.bars+[Bar(self.bars[-1].timestamp+60,108,109,107,108,1000)];return b,b[-1].timestamp+62
 def test_warmup_does_not_trade(self):
  self.assertIsNone(self.state['position']);self.assertEqual(self.state['trade_count'],0)
 def test_consensus_opens_only_once(self):
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):
   s,e,t=process(self.state,b,quote(now),funding(now),now)
   self.assertIsNotNone(s['position']);self.assertLessEqual(s['position']['qty']*s['position']['entry'],250+1e-9)
   self.assertEqual(len([x for x in e if x['type']=='PAPER_OPEN']),1)
   s2,e2,t2=process(s,b,quote(now+1),funding(now+1),now+1)
   self.assertEqual(s2['position'],s['position']);self.assertFalse(any(x['type']=='PAPER_OPEN' for x in e2))
 def test_missing_funding_blocks(self):
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):
   s,e,_=process(self.state,b,quote(now),None,now)
  self.assertIsNone(s['position']);self.assertTrue(any(x['detail']=='FUNDING_BILINMIYOR' for x in e))
 def test_near_funding_blocks_even_if_rate_favorable(self):
  b,now=self.next();f={'rate':-.001,'settlement':now+100,'observed':now}
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):s,e,_=process(self.state,b,quote(now),f,now)
  self.assertIsNone(s['position']);self.assertTrue(any(x['type']=='BLOCK' for x in e))
 def test_quote_stale_blocks(self):
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):s,e,_=process(self.state,b,quote(now-25),funding(now),now)
  self.assertIsNone(s['position']);self.assertTrue(any(x['detail']=='KOTASYON_BILINMIYOR' for x in e))
 def test_missed_bar_locks_without_past_fills(self):
  b,now=self.next();b=b+[Bar(b[-1].timestamp+60,108,109,107,108,1000)];now+=60
  s,e,t=process(self.state,b,quote(now),funding(now),now)
  self.assertTrue(s['halt']);self.assertEqual(s['halt_reason'],'KACIRILMIS_MUM');self.assertEqual(len(t),0)
 def test_close_accounting_and_recovery(self):
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):s,e,t=process(self.state,b,quote(now),funding(now),now)
  p=s['position'];q=quote(now+10,p['stop']-1,p['stop']-.9)
  s2,e,t=process(s,b,q,funding(now+10),now+10)
  self.assertIsNone(s2['position']);self.assertEqual(t[0]['reason'],'STOP')
  self.assertAlmostEqual(s2['cash']-s2['initial_cash'],t[0]['net'],places=9)
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/'db.sqlite';store=Store(db,now);store.commit(s2,e,t);restored=Store(db,now).load();self.assertEqual(restored,s2);self.assertEqual(store.latest()[1][0],t[0])
 def test_quote_interruption_locks_new_entries(self):
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):s,_,_=process(self.state,b,quote(now),funding(now),now)
  s2,e,_=process(s,b,quote(now+31),funding(now+31),now+31)
  self.assertTrue(s2['halt']);self.assertEqual(s2['halt_reason'],'KOTASYON_KESINTISI')
 def test_settlement_pass_locks_and_flags_unaccounted(self):
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=AllAgree()):s,_,_=process(self.state,b,quote(now),funding(now),now)
  s['last_settlement']=now+1
  s2,_,_=process(s,b,quote(now+2),funding(now+2),now+2)
  self.assertTrue(s2['funding_unaccounted']);self.assertTrue(s2['halt'])
 def test_disagree_never_opens(self):
  class Short:
   def __call__(self,bars):return Signal('short',1,{})
  b,now=self.next()
  with patch('acar.engine.Confluence',return_value=AllAgree()),patch('acar.engine.Breakout',return_value=Short()):s,_,_=process(self.state,b,quote(now),funding(now),now)
  self.assertIsNone(s['position'])
 def test_store_refuses_nan(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'db',self.now);before=store.load();invalid=dict(before,cash=float('nan'))
   with self.assertRaises(ValueError):store.commit(invalid,[],[])
   self.assertEqual(store.load(),before)
class MarketTests(unittest.TestCase):
 def test_candles_exclude_open_and_sort(self):
  rows=[[str(1704067200000+i*60000),'100','101','99','100','1','1','1','1'] for i in range(65)]
  rows.append([str(1704067200000+65*60000),'100','101','99','100','1','1','1','0'])
  with patch('acar.market._get',return_value=list(reversed(rows))):b=market.candles()
  self.assertEqual(len(b),65);self.assertLess(b[0].timestamp,b[-1].timestamp)
 def test_quote_rejects_stale_and_wrong_symbol(self):
  row={'instId':'BTC-USDT-SWAP','bidPx':'99','askPx':'101','ts':'1000000'}
  with patch('acar.market._get',return_value=[row]):
   with self.assertRaises(ValueError):market.quote(now=1100)
  row['instId']='ETH-USDT-SWAP'
  with patch('acar.market._get',return_value=[row]):
   with self.assertRaises(ValueError):market.quote(now=1000)
 def test_missing_funding_rejected_not_zero(self):
  row={'instId':'BTC-USDT-SWAP','fundingTime':'1000000','ts':'900000'}
  with patch('acar.market._get',return_value=[row]):
   with self.assertRaises(ValueError):market.funding(now=1000)
if __name__=='__main__':unittest.main()

class OutageTests(unittest.TestCase):
 def test_position_stop_is_monitored_even_if_candles_absent(self):
  n=1704068000; s=initial_state(n);s['last_bar']=n-100;s['last_quote_time']=n
  s['position']={'side':'long','entry':100,'qty':1,'entry_time':n-20,'entry_fee':.05,'stop':95,'target':110,'signal_bar':n-100}
  s['cash']-=.05
  result,events,trades=process(s,[],quote(n+1,94,94.1),None,n+1)
  self.assertIsNone(result['position']);self.assertEqual(trades[0]['reason'],'STOP');self.assertTrue(result['halt'])

class FundingOutageTests(unittest.TestCase):
 def test_open_position_closes_paper_if_funding_unknown(self):
  n=1704068000;b=seq(80,start=n-80*60);s=initial_state(n);s['last_bar']=b[-1].timestamp;s['last_quote_time']=n
  s['position']={'side':'long','entry':100,'qty':1,'entry_time':n-20,'entry_fee':.05,'stop':95,'target':110,'signal_bar':b[-1].timestamp};s['cash']-=.05
  state,events,trades=process(s,b,quote(n+1,100,100.01),None,n+1)
  self.assertIsNone(state['position']);self.assertEqual(trades[0]['reason'],'FUNDING_BILINMIYOR')
