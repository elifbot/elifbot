import copy,json,sqlite3,tempfile,threading,unittest
from hashlib import sha256
from acar.unified_simulator import pack
from pathlib import Path
from contextlib import closing
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator

class UnifiedTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'unified.sqlite';self.bot=UnifiedSimulator.create(self.path)
  self.rules=MarketRules('BTC','0.1','0.1','0.1','0');self.book={'symbol':'BTC','observed_at':10,'bids':[['101','2']], 'asks':[['101.1','0.5'],['101.2','0.5']]}
 def tearDown(self):self.temp.cleanup()
 def buy(self,**kw):
  args={'symbol':'BTC','side':'long','quantity':'1','stop':'99','target':'110','leverage':'3','next_funding':100,'now':10,'book_id':'b1','book':self.book,'rules':self.rules}
  return self.bot.open_position('open1',**dict(args,**kw))
 def test_open_partial_cash_fee_margin_atomic(self):
  out=self.buy(quantity='1.5');self.assertEqual(out['status'],'PARTIAL_IOC');self.assertEqual(out['filled'],'1')
  s=self.bot.snapshot();self.assertEqual(s['state']['positions']['BTC']['qty'],'1');self.assertEqual(s['ledger'][0]['kind'],'OPEN');self.assertEqual(len(s['notifications']),1)
  self.assertEqual(UnifiedSimulator(self.path).snapshot(),s)
 def test_repeated_command_and_conflict(self):
  self.buy();self.assertEqual(self.buy()['status'],'FILLED');self.assertEqual(len(self.bot.snapshot()['ledger']),1)
  with self.assertRaises(ValueError):self.buy(quantity='0.5')
 def test_failed_order_rolls_back_book_consumption(self):
  before=self.bot.snapshot()
  with self.assertRaises(ValueError):self.buy(stop='102')
  self.assertEqual(self.bot.snapshot(),before);self.assertEqual(self.buy()['status'],'FILLED')
 def test_pre_funding_exit_executes_only_in_explicit_window(self):
  self.buy(next_funding=100)
  normal=dict(self.book,observed_at=11)
  r=self.bot.process_book('before-window',symbol='BTC',book_id='b2',book=normal,rules=self.rules,now=11,funding_exit_before=88)
  self.assertEqual(r['action'],'MONITOR')
  due=dict(self.book,observed_at=12)
  r=self.bot.process_book('window',symbol='BTC',book_id='b3',book=due,rules=self.rules,now=12,funding_exit_before=88)
  self.assertEqual((r['action'],r['order']['reason']),('CLOSE','FUNDING_PREEMPT'));self.assertFalse(self.bot.snapshot()['state']['positions'])
 def test_partial_pre_funding_exit_locks_entries(self):
  self.buy(next_funding=100);book=dict(self.book,observed_at=11,bids=[['101','0.5']])
  r=self.bot.process_book('partial-window',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=11,funding_exit_before=89)
  self.assertEqual(r['order']['reason'],'FUNDING_PREEMPT');self.assertEqual(r['order']['status'],'PARTIAL_IOC');self.assertTrue(self.bot.snapshot()['state']['entry_locked'])
 def test_due_funding_takes_precedence_over_preemptive_exit(self):
  self.buy(next_funding=20);book=dict(self.book,observed_at=20)
  r=self.bot.process_book('already-due',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=20,funding_exit_before=180)
  self.assertEqual(r['protection']['status'],'FUNDING_DUE_UNKNOWN');self.assertEqual(r['action'],'LOCK');self.assertIn('BTC',self.bot.snapshot()['state']['positions'])
 def test_invalid_prefunding_window_rejected(self):
  self.buy()
  for value in (True,-1,601):
   with self.subTest(value=value),self.assertRaises(ValueError):self.bot.process_book('invalid',symbol='BTC',book_id='b2',book=self.book,rules=self.rules,now=10,funding_exit_before=value)
 def test_trailing_is_favorable_and_only_effective_on_next_book(self):
  self.buy();self.bot.configure_exit('exitcfg',symbol='BTC',entry_stop_at_r='1',trailing_distance='1',now=10)
  book={'symbol':'BTC','observed_at':11,'bids':[['101','2']],'asks':[['106','2']]}
  r=self.bot.process_book('move',symbol='BTC',book_id='move-book',book=book,rules=self.rules,now=11)
  self.assertEqual(r['action'],'MONITOR');self.assertEqual(r['stop'],'102.5')
  self.assertIn('BTC',self.bot.snapshot()['state']['positions'])
  book2={'symbol':'BTC','observed_at':12,'bids':[['102.9','2']],'asks':[['103.1','2']]}
  self.assertEqual(self.bot.process_book('no-loosen',symbol='BTC',book_id='b3',book=book2,rules=self.rules,now=12)['stop'],'102.5')
  book3={'symbol':'BTC','observed_at':13,'bids':[['102.3','2']],'asks':[['102.5','2']]}
  r=self.bot.process_book('stop',symbol='BTC',book_id='b4',book=book3,rules=self.rules,now=13)
  self.assertEqual((r['action'],r['order']['reason']),('CLOSE','STOP'))
 def test_entry_price_stop_does_not_claim_fee_breakeven(self):
  self.buy();self.bot.configure_exit('exitcfg',symbol='BTC',entry_stop_at_r='1',trailing_distance='0',now=10)
  book={'symbol':'BTC','observed_at':11,'bids':[['103.4','2']],'asks':[['103.6','2']]}
  out=self.bot.process_book('move',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=11)
  self.assertEqual(out['stop'],self.bot.snapshot()['state']['positions']['BTC']['entry'])
 def test_short_trailing_direction(self):
  self.buy(side='short',stop='103',target='90');self.bot.configure_exit('exitcfg',symbol='BTC',entry_stop_at_r='0',trailing_distance='1',now=10)
  book={'symbol':'BTC','observed_at':11,'bids':[['98.4','2']],'asks':[['98.6','2']]}
  out=self.bot.process_book('move',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=11)
  self.assertEqual(out['stop'],'99.5')
  book2={'symbol':'BTC','observed_at':12,'bids':[['99.4','2']],'asks':[['99.6','2']]}
  self.assertEqual(self.bot.process_book('stop',symbol='BTC',book_id='b3',book=book2,rules=self.rules,now=12)['action'],'CLOSE')
 def test_invalid_exit_config_is_atomic(self):
  self.buy();before=self.bot.snapshot()
  for at,trail in (('-1','1'),('101','1'),('1','NaN')):
   with self.subTest(at=at,trail=trail),self.assertRaises(ValueError):self.bot.configure_exit('exitcfg',symbol='BTC',entry_stop_at_r=at,trailing_distance=trail,now=10)
  self.assertEqual(self.bot.snapshot(),before)
 def test_daily_equity_halt_and_new_utc_day_reset(self):
  self.buy();book={'symbol':'BTC','observed_at':11,'bids':[['70','1']],'asks':[['70.1','1']]}
  outcome=self.bot.process_book('stop',symbol='BTC',book_id='b2',book=book,rules=self.rules,now=11)
  self.assertEqual(outcome['action'],'CLOSE');state=self.bot.snapshot()['state'];self.assertTrue(state['daily_halt'])
  rules=MarketRules('ETH','0.1','0.1','0.1','0');other={'symbol':'ETH','observed_at':12,'bids':[['49.9','2']],'asks':[['50','2']]}
  args=dict(symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=86500,now=12,book_id='e1',book=other,rules=rules)
  self.assertEqual(self.bot.open_position('blocked',**args)['reason'],'DAILY_LOSS_LIMIT')
  args['now']=86400;args['book']=dict(other,observed_at=86400)
  self.assertEqual(self.bot.open_position('tomorrow',**args)['status'],'FILLED');self.assertFalse(self.bot.snapshot()['state']['daily_halt'])
 def test_utc_reset_with_continuous_short_monitoring(self):
  start=86390;book={'symbol':'BTC','observed_at':start,'bids':[['99.9','10']],'asks':[['100','10']]}
  self.bot.open_position('midnight',symbol='BTC',side='long',quantity='1',leverage='2',stop='98',target='105',next_funding=100000,book_id='midnight-book',book=book,rules=self.rules,now=start)
  self.bot.mark('cross-day','BTC','100',86400)
  s=self.bot.snapshot()['state'];self.assertEqual(s['day'],'1970-01-02');self.assertFalse(s['entry_locked']);self.assertFalse(s['positions']['BTC']['execution_uncertain'])
 def test_funding_settlement_after_monitor_gap_stays_uncertain(self):
  self.buy(next_funding=40)
  self.bot.settle_funding('late-settlement',symbol='BTC',rate='0.001',mark_price='100',settlement_ts=40,finalized_at=41,next_funding=1000,now=41)
  s=self.bot.snapshot()['state'];self.assertTrue(s['positions']['BTC']['execution_uncertain']);self.assertTrue(s['entry_locked'])
 def test_changed_rules_do_not_fabricate_execution(self):
  self.buy(next_funding=1000);changed=MarketRules(symbol='BTC',qty_step='0.01',price_tick='0.2',min_qty='0.01',min_notional='5')
  before=self.bot.snapshot()
  with self.assertRaisesRegex(ValueError,'market rules changed'):self.bot.process_book('bad-rules',symbol='BTC',book_id='b2',book=dict(self.book,observed_at=11),rules=changed,now=11)
  self.assertEqual(before,self.bot.snapshot())
 def test_daily_reset_does_not_assume_gapped_monitoring_is_valid(self):
  self.buy(next_funding=200000);rules=MarketRules('ETH','0.1','0.1','0.1','0');book={'symbol':'ETH','observed_at':11,'bids':[['49.9','2']],'asks':[['50','2']]}
  self.bot.open_position('eth',symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=200000,now=11,book_id='e1',book=book,rules=rules)
  self.bot.mark('btc-mark','BTC','101.05',86400)
  self.assertEqual(self.bot.snapshot()['state']['day'],'1970-01-01')
  self.bot.mark('eth-mark','ETH','49.95',86400)
  self.assertEqual(self.bot.snapshot()['state']['day'],'1970-01-01');self.assertTrue(self.bot.snapshot()['state']['entry_locked'])
 def test_correlation_guard_portfolio_race_refused(self):
  old_hash=sha256(pack({}).encode()).hexdigest();self.buy()
  rules=MarketRules('ETH','0.1','0.1','0.1','0');book={'symbol':'ETH','observed_at':11,'bids':[['49.9','2']],'asks':[['50','2']]}
  before=self.bot.snapshot()
  with self.assertRaisesRegex(ValueError,'changed since correlation'):self.bot.open_position('eth',symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=100,now=11,book_id='e1',book=book,rules=rules,expected_positions_hash=old_hash)
  self.assertEqual(before,self.bot.snapshot())
 def test_two_markets_common_wallet_and_no_lookahead(self):
  self.buy();rules=MarketRules('ETH','0.1','0.1','0.1','0');book={'symbol':'ETH','observed_at':11,'bids':[['49.9','2']],'asks':[['50','2']]}
  r=self.bot.open_position('eth-open',symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=100,now=11,book_id='e1',book=book,rules=rules)
  s=self.bot.snapshot();self.assertEqual(r['position']['side'],'short');self.assertEqual(len(s['state']['positions']),2)
  self.assertLess(float(s['state']['cash']),1000);self.assertEqual(len(s['ledger']),2)
 def test_risk_capped_adding_updates_same_position(self):
  self.buy(quantity='0.5');book={'symbol':'BTC','observed_at':11,'bids':[['100.5','2']],'asks':[['100.6','0.2']]}
  r=self.bot.add_position('dca',symbol='BTC',quantity='0.3',now=11,book_id='b2',book=book,rules=self.rules)
  self.assertEqual(r['status'],'PARTIAL_IOC');self.assertEqual(r['new_qty'],'0.7')
  s=self.bot.snapshot();self.assertEqual(s['state']['positions']['BTC']['qty'],'0.7');self.assertEqual([x['kind'] for x in s['ledger']],['OPEN','ADD'])
  self.assertEqual(self.bot.add_position('dca',symbol='BTC',quantity='0.3',now=11,book_id='b2',book=book,rules=self.rules),r)
 def test_adding_cannot_evade_total_position_risk(self):
  self.buy(quantity='1');book={'symbol':'BTC','observed_at':11,'bids':[['100.5','10']],'asks':[['100.6','10']]}
  before=self.bot.snapshot()
  with self.assertRaisesRegex(ValueError,'risk limit'):self.bot.add_position('dca',symbol='BTC',quantity='2',now=11,book_id='b2',book=book,rules=self.rules)
  self.assertEqual(self.bot.snapshot(),before)
 def test_spread_risk_and_low_equity_gate(self):
  wide=dict(self.book,bids=[['90','2']])
  with self.assertRaisesRegex(ValueError,'spread too wide'):self.buy(book=wide)
  self.assertEqual(self.buy()['status'],'FILLED')
 def test_leverage_and_risk_limit_rollback(self):
  for kw in ({'leverage':'4'},{'stop':'1'}):
   with self.subTest(kw=kw),self.assertRaises(ValueError):self.buy(**kw)
  self.assertFalse(self.bot.snapshot()['state']['positions'])
 def test_outstanding_protection_blocks_other_entry(self):
  self.buy();self.bot.mark('mark1','BTC','98',11)
  rules=MarketRules('ETH','0.1','0.1','0.1','0');book={'symbol':'ETH','observed_at':11,'bids':[['49.9','2']],'asks':[['50','2']]}
  with self.assertRaisesRegex(ValueError,'protective exit'):self.bot.open_position('eth',symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=100,now=11,book_id='e1',book=book,rules=rules)
 def test_short_funding_positive_is_credit(self):
  self.buy(side='short',stop='103',target='90')
  result=self.bot.settle_funding('fund',symbol='BTC',settlement_ts=100,finalized_at=100,rate='0.001',mark_price='100',next_funding=200,now=100)
  self.assertEqual(result['funding_delta'],'0.1')
 def test_quote_age_is_measured_from_observation_not_processing_time(self):
  book=dict(self.book,observed_at=0)
  self.buy(book=book,now=30)
  self.assertEqual(self.bot.snapshot()['state']['positions']['BTC']['mark_at'],0)
  rules=MarketRules('ETH','0.1','0.1','0.1','0');other={'symbol':'ETH','observed_at':31,'bids':[['49.9','2']],'asks':[['50','2']]}
  with self.assertRaisesRegex(ValueError,'stale'):self.bot.open_position('eth',symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=100,now=31,book_id='e1',book=other,rules=rules)
 def test_observation_time_cannot_go_backwards(self):
  self.buy();self.bot.mark('m1','BTC','100',12,observed_at=12)
  with self.assertRaisesRegex(ValueError,'backwards'):self.bot.mark('m2','BTC','100',13,observed_at=11)
 def test_open_rejects_stale_mark_of_other_position(self):
  self.buy();rules=MarketRules('ETH','0.1','0.1','0.1','0');book={'symbol':'ETH','observed_at':50,'bids':[['49.9','2']],'asks':[['50','2']]}
  with self.assertRaisesRegex(ValueError,'stale'):self.bot.open_position('eth',symbol='ETH',side='short',quantity='1',stop='51',target='45',leverage='2',next_funding=100,now=50,book_id='e1',book=book,rules=rules)
 def test_funding_once_updates_margin_and_shared_equity(self):
  self.buy();before=self.bot.snapshot();r=self.bot.settle_funding('fund1',symbol='BTC',settlement_ts=100,finalized_at=101,rate='0.001',mark_price='100',next_funding=200,now=101)
  self.assertEqual(r['funding_delta'],'-0.1');after=self.bot.snapshot();self.assertAlmostEqual(float(before['equity_at_last_marks'])-.1,float(after['equity_at_last_marks']))
  self.assertEqual(self.bot.settle_funding('fund2',symbol='BTC',settlement_ts=100,finalized_at=101,rate='0.001',mark_price='100',next_funding=200,now=101)['status'],'DUPLICATE')
  with self.assertRaises(ValueError):self.bot.settle_funding('fund3',symbol='BTC',settlement_ts=100,finalized_at=101,rate='0.002',mark_price='100',next_funding=200,now=101)
 def test_close_partial_then_final_and_financial_balance(self):
  self.buy();book={'symbol':'BTC','observed_at':11,'bids':[['105','0.4']],'asks':[['106','1']]}
  r=self.bot.close_position('close1',symbol='BTC',quantity='1',now=11,book_id='b2',book=book,rules=self.rules)
  self.assertEqual((r['status'],r['filled'],r['remaining_position']),('PARTIAL_IOC','0.4','0.6'))
  book2={'symbol':'BTC','observed_at':12,'bids':[['104','1']],'asks':[['105','1']]}
  self.bot.close_position('close2',symbol='BTC',quantity='0.6',now=12,book_id='b3',book=book2,rules=self.rules)
  s=self.bot.snapshot();self.assertFalse(s['state']['positions']);self.assertAlmostEqual(float(s['state']['cash']),1003.147225,places=8)
 def test_protective_partial_exit_locks_entries(self):
  self.buy();book={'symbol':'BTC','observed_at':11,'bids':[['98','0.4']],'asks':[['99','1']]}
  self.assertEqual(self.bot.protection_status('BTC','98',11)['status'],'STOP')
  self.bot.close_position('stop1',symbol='BTC',quantity='1',now=11,book_id='b2',book=book,rules=self.rules,reason='STOP')
  self.assertTrue(self.bot.snapshot()['state']['entry_locked'])
 def test_liquidation_threshold_and_funding_due_fail_closed(self):
  self.buy();self.assertEqual(self.bot.protection_status('BTC','60',11)['status'],'LIQUIDATION_MODEL');self.assertEqual(self.bot.protection_status('BTC','60',100)['status'],'FUNDING_DUE_UNKNOWN')
  book={'symbol':'BTC','observed_at':100,'bids':[['98','1']],'asks':[['99','1']]}
  with self.assertRaisesRegex(ValueError,'funding'):self.bot.close_position('x',symbol='BTC',quantity='1',now=100,book_id='b2',book=book,rules=self.rules)
 def test_consumed_snapshot_rejected(self):
  self.buy();before=self.bot.snapshot()
  with self.assertRaisesRegex(ValueError,'snapshot already consumed'):self.bot.close_position('close1',symbol='BTC',quantity='1',now=10,book_id='b1',book=self.book,rules=self.rules)
  self.assertEqual(self.bot.snapshot(),before)
 def test_time_and_book_future_rejected(self):
  for kw in ({'now':9},{'next_funding':10},{'book':dict(self.book,observed_at=11)}):
   with self.subTest(kw=kw),self.assertRaises(ValueError):self.buy(**kw)
 def test_old_schema_requires_explicit_migration(self):
  with closing(sqlite3.connect(self.path)) as c:
   with c:c.execute('PRAGMA user_version=3')
  before=self.path.read_bytes()
  with self.assertRaisesRegex(ValueError,'no automatic migration'):UnifiedSimulator(self.path)
  self.assertEqual(self.path.read_bytes(),before)
 def test_existing_db_never_overwritten(self):
  p=Path(self.temp.name)/'paper.sqlite';p.write_bytes(b'do not touch')
  with self.assertRaises(FileExistsError):UnifiedSimulator.create(p)
  self.assertEqual(p.read_bytes(),b'do not touch')
 def test_tampered_risk_configuration_is_refused(self):
  self.buy()
  with closing(sqlite3.connect(self.path)) as c:
   with c:
    state=json.loads(c.execute('SELECT value FROM state').fetchone()[0]);state['settings']['per_trade_risk']='0.9';c.execute('UPDATE state SET value=?',(json.dumps(state),))
  with self.assertRaisesRegex(ValueError,'risk configuration'):self.bot.snapshot()
 def test_cash_plus_forged_ledger_delta_still_detected(self):
  self.buy()
  with closing(sqlite3.connect(self.path)) as c:
   with c:
    state=json.loads(c.execute('SELECT value FROM state').fetchone()[0]);state['cash']=str(float(state['cash'])+1);c.execute('UPDATE state SET value=?',(json.dumps(state),))
    c.execute("UPDATE ledger SET delta='0.949425' WHERE kind='OPEN'")
  with self.assertRaisesRegex(ValueError,'ledger event mismatch'):self.bot.snapshot()
 def test_invalid_position_level_or_mark_rejected(self):
  self.buy()
  with closing(sqlite3.connect(self.path)) as c:
   with c:
    state=json.loads(c.execute('SELECT value FROM state').fetchone()[0]);state['positions']['BTC']['mark']='NaN';c.execute('UPDATE state SET value=?',(json.dumps(state),))
  with self.assertRaises(ValueError):self.bot.snapshot()
 def test_tampering_detected_blocks_write(self):
  self.buy()
  with closing(sqlite3.connect(self.path)) as c:
   with c:
    s=json.loads(c.execute('SELECT value FROM state').fetchone()[0]);s['cash']='9999';c.execute('UPDATE state SET value=?',(json.dumps(s),))
  with self.assertRaisesRegex(ValueError,'ledger mismatch'):self.bot.mark('m','BTC',100,11)
 def test_concurrent_order_retry_only_one_fill(self):
  barrier=threading.Barrier(2);out=[];errors=[]
  def run():
   try:barrier.wait();out.append(self.buy())
   except Exception as e:errors.append(str(e))
  threads=[threading.Thread(target=run) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertFalse(errors);self.assertEqual(len(out),2);self.assertEqual(out[0],out[1]);self.assertEqual(len(self.bot.snapshot()['ledger']),1)
if __name__=='__main__':unittest.main()
