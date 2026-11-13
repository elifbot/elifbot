import tempfile,unittest,threading,subprocess,sys
from unittest.mock import patch
import acar.unified_simulator as core
from pathlib import Path
from acar.data import Bar
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator
from acar.unified_bot import OfflineUnifiedBot
class UnifiedBotTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.sim=UnifiedSimulator.create(Path(self.temp.name)/'db.sqlite',max_age=30);self.bot=OfflineUnifiedBot(self.sim)
  self.bars=[Bar(1704067200+i*60,100+i,101+i,99+i,100.5+i,10) for i in range(220)]
  self.now=self.bars[-1].timestamp+60;self.rules=MarketRules('BTC','0.1','0.1','0.1','0')
  self.book={'symbol':'BTC','observed_at':self.now,'bids':[['319.4','1']],'asks':[['319.6','1']]}
 def tearDown(self):self.temp.cleanup()
 def open(self,command_id="open1",**kw):
  args=dict(symbol='BTC',bars=self.bars,quantity='0.2',leverage='2',next_funding=self.now+100,now=self.now,book_id='b1',book=self.book,rules=self.rules)
  return self.bot.on_candles(command_id,**dict(args,**kw))
 def test_real_strategy_signal_opens_in_integrated_ledger(self):
  r=self.open();self.assertEqual(r['action'],'OPEN');self.assertEqual(r['signal']['side'],'long');self.assertEqual(self.sim.snapshot()['state']['positions']['BTC']['qty'],'0.2')
 def test_signal_retry_rejects_changed_source_bars(self):
  first=self.open();before=self.sim.snapshot();bars=self.bars.copy();b=bars[0];bars[0]=Bar(b.timestamp,b.open,b.high,b.low,b.close,b.volume+1)
  with self.assertRaisesRegex(ValueError,'conflict'):self.open(bars=bars)
  self.assertEqual(self.sim.snapshot(),before);self.assertEqual(len(first['order']['signal_fingerprint']),64)
 def test_optional_correlated_position_gate(self):
  self.open();rules=MarketRules('ETH','0.1','0.1','0.1','0');book={'symbol':'ETH','observed_at':self.now,'bids':[['319.4','1']],'asks':[['319.6','1']]}
  args=dict(symbol='ETH',bars=self.bars,quantity='0.2',leverage='2',next_funding=self.now+100,now=self.now,book_id='e1',book=book,rules=rules)
  self.assertEqual(self.bot.on_candles('eth1',**args,correlation_histories={})['reason'],'CORRELATION_UNKNOWN')
  r=self.bot.on_candles('eth2',**args,correlation_histories={'BTC':self.bars})
  self.assertEqual(r['reason'],'CORRELATED_EXPOSURE');self.assertNotIn('ETH',self.sim.snapshot()['state']['positions'])
 def test_future_or_stale_bars_never_open(self):
  self.assertEqual(self.open(now=self.now-1)['reason'],'BAR_NOT_CLOSED_OR_STALE')
  self.assertEqual(self.open(command_id='open2',now=self.now+31)['reason'],'BAR_NOT_CLOSED_OR_STALE')
  self.assertFalse(self.sim.snapshot()['state']['positions'])
 def test_no_trade_event_advances_clock_and_replay_is_idempotent(self):
  r=self.open(bars=self.bars[:100]);self.assertEqual(r['reason'],'INSUFFICIENT_BARS')
  self.assertEqual(self.sim.snapshot()['state']['last_time'],self.now)
  self.assertEqual(self.open(bars=self.bars[:100]),r)
  with self.assertRaisesRegex(ValueError,'conflict'):self.open(bars=self.bars[:99])
  with self.assertRaisesRegex(ValueError,'monotonic'):self.open(command_id='older',now=self.now-1,bars=self.bars[:100])
 def test_short_history_fails_closed(self):
  self.assertEqual(self.open(bars=self.bars[:100])['reason'],'INSUFFICIENT_BARS')
 def test_auto_stop_fills_partial_and_locks(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
  r=self.bot.on_book('stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  self.assertEqual(r['action'],'CLOSE');self.assertEqual(r['order']['status'],'PARTIAL_IOC');self.assertEqual(self.sim.snapshot()['state']['positions']['BTC']['qty'],'0.1');self.assertTrue(self.sim.snapshot()['state']['entry_locked'])
  with self.assertRaises(ValueError):self.sim.clear_entry_lock('unlock',self.now+1)
 def test_stop_retry_is_idempotent_even_after_partial(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
  kw=dict(symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  first=self.bot.on_book('stop',**kw);before=self.sim.snapshot();again=self.bot.on_book('stop',**kw)
  self.assertEqual(first,again);self.assertEqual(before,self.sim.snapshot())
  changed=dict(book,bids=[['315','0.2']])
  with self.assertRaises(ValueError):self.bot.on_book('stop',**dict(kw,book=changed))
 def test_stop_retry_is_idempotent_after_full_close(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','1']],'asks':[['315.2','1']]}
  kw=dict(symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  first=self.bot.on_book('stop',**kw);before=self.sim.snapshot();again=self.bot.on_book('stop',**kw)
  self.assertEqual(first,again);self.assertEqual(before,self.sim.snapshot())
 def test_process_kill_during_close_rolls_back_and_restarts(self):
  self.open();before=self.sim.snapshot()
  script="""import os,sys
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator
import acar.unified_simulator as core
sim=UnifiedSimulator(sys.argv[1]);original=core._event
def fail(c,kind,delta,detail):
 original(c,kind,delta,detail)
 if kind=='CLOSE':os._exit(77)
core._event=fail
now=int(sys.argv[2]);book={'symbol':'BTC','observed_at':now,'bids':[['315','0.1']],'asks':[['315.2','1']]}
sim.process_book('stop',symbol='BTC',book_id='b2',book=book,rules=MarketRules('BTC','0.1','0.1','0.1','0'),now=now)
"""
  p=subprocess.run([sys.executable,'-c',script,str(self.sim.path),str(self.now+1)],capture_output=True,text=True,timeout=10)
  self.assertEqual(p.returncode,77,p.stderr)
  recovered=UnifiedSimulator(self.sim.path);self.assertEqual(recovered.snapshot(),before)
  book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
  self.assertEqual(recovered.process_book('stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)['action'],'CLOSE')
 def test_process_kill_after_commit_retry_has_no_second_fill(self):
  self.open()
  script="""import os,sys
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator
sim=UnifiedSimulator(sys.argv[1]);now=int(sys.argv[2]);book={'symbol':'BTC','observed_at':now,'bids':[['315','0.1']],'asks':[['315.2','1']]}
sim.process_book('stop',symbol='BTC',book_id='b2',book=book,rules=MarketRules('BTC','0.1','0.1','0.1','0'),now=now)
os._exit(78)
"""
  p=subprocess.run([sys.executable,'-c',script,str(self.sim.path),str(self.now+1)],capture_output=True,text=True,timeout=10)
  self.assertEqual(p.returncode,78,p.stderr)
  reopened=UnifiedSimulator(self.sim.path);before=reopened.snapshot()
  book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
  result=reopened.process_book('stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  self.assertEqual(result['action'],'CLOSE');self.assertEqual(reopened.snapshot(),before)
  self.assertEqual(sum(e['kind']=='CLOSE' for e in before['ledger']),1)
 def test_fault_after_close_event_rolls_back_mark_fill_and_lock(self):
  self.open();before=self.sim.snapshot();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
  kw=dict(symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  original=core._event
  def fail_after_insert(c,kind,delta,detail):
   original(c,kind,delta,detail)
   if kind=='CLOSE':raise RuntimeError('injected failure')
  with patch('acar.unified_simulator._event',side_effect=fail_after_insert):
   with self.assertRaisesRegex(RuntimeError,'injected'):self.bot.on_book('stop',**kw)
  self.assertEqual(self.sim.snapshot(),before)
  self.assertEqual(self.bot.on_book('stop',**kw)['order']['status'],'PARTIAL_IOC')
 def test_simultaneous_identical_protection_event_commits_once(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
  kw=dict(symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1);barrier=threading.Barrier(2);out=[];errors=[]
  def worker():
   try:barrier.wait();out.append(self.bot.on_book('stop',**kw))
   except Exception as e:errors.append(str(e))
  ts=[threading.Thread(target=worker) for _ in range(2)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertFalse(errors);self.assertEqual(len(out),2);self.assertEqual(out[0],out[1]);self.assertEqual(sum(e['kind']=='CLOSE' for e in self.sim.snapshot()['ledger']),1)
 def test_no_liquidity_does_not_consume_book_id(self):
  self.open();weak={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.01']],'asks':[['315.2','1']]}
  kw=dict(symbol='BTC',book_id='b2',book=weak,rules=self.rules,now=self.now+1)
  self.assertEqual(self.bot.on_book('stop-weak',**kw)['action'],'LOCK')
  full=dict(weak,bids=[['315','1']])
  self.assertEqual(self.bot.on_book('stop-strong',**dict(kw,book=full))['action'],'CLOSE')
 def test_auto_stop_full_exit_then_explicit_unlock_if_needed(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','1']],'asks':[['315.2','1']]}
  r=self.bot.on_book('stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  self.assertEqual(r['action'],'CLOSE');self.assertFalse(self.sim.snapshot()['state']['positions'])
 def test_missing_funding_locks_without_imaginary_closure(self):
  self.open();now=self.now+100;book=dict(self.book,observed_at=now)
  r=self.bot.on_book('fund',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=now)
  self.assertEqual(r['protection']['status'],'FUNDING_DUE_UNKNOWN');self.assertTrue(self.sim.snapshot()['state']['entry_locked']);self.assertIn('BTC',self.sim.snapshot()['state']['positions'])
  with self.assertRaises(ValueError):self.sim.clear_entry_lock('unlock',now)
 def test_gap_tags_uncertain_exit_and_keeps_entry_lock(self):
  self.open(next_funding=self.now+1000);now=self.now+31
  book={'symbol':'BTC','observed_at':now,'bids':[['315','1']],'asks':[['315.2','1']]}
  r=self.bot.on_book('gap-stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=now)
  self.assertEqual(r['action'],'CLOSE');self.assertTrue(r['order']['execution_uncertain'])
  s=self.sim.snapshot();self.assertTrue(s['state']['entry_locked']);self.assertTrue(any(e['kind']=='MONITORING_GAP' for e in s['ledger']))
 def test_gap_without_stop_blocks_new_entries_and_unlock(self):
  self.open(next_funding=self.now+1000);now=self.now+31;book=dict(self.book,observed_at=now)
  self.assertEqual(self.bot.on_book('gap',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=now)['action'],'MONITOR')
  state=self.sim.snapshot()['state'];self.assertTrue(state['entry_locked']);self.assertTrue(state['positions']['BTC']['execution_uncertain'])
  with self.assertRaisesRegex(ValueError,'uncertain'):self.sim.clear_entry_lock('unlock',now)
 def test_liquidation_model_executes_against_observed_book(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['150','1']],'asks':[['150.1','1']]}
  r=self.bot.on_book('liquidate',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  self.assertEqual(r['protection']['status'],'LIQUIDATION_MODEL');self.assertEqual(r['order']['reason'],'LIQUIDATION');self.assertFalse(self.sim.snapshot()['state']['positions'])
 def test_funding_lock_can_only_clear_after_explicit_settlement(self):
  self.open(next_funding=self.now+10);now=self.now+10;book=dict(self.book,observed_at=now)
  self.bot.on_book('fund',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=now)
  self.sim.settle_funding('settle',symbol='BTC',settlement_ts=now,finalized_at=now,rate='0.001',mark_price='319.5',next_funding=now+100,now=now)
  self.assertFalse(self.sim.clear_entry_lock('unlock',now)['locked'])
 def test_protection_without_liquidity_locks(self):
  self.open();book={'symbol':'BTC','observed_at':self.now+1,'bids':[['315','0.01']],'asks':[['315.2','1']]}
  r=self.bot.on_book('stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=self.now+1)
  self.assertEqual(r['action'],'LOCK');self.assertEqual(r['reason'],'PROTECTIVE_EXECUTION_FAILED');self.assertIn('BTC',self.sim.snapshot()['state']['positions'])
if __name__=='__main__':unittest.main()
