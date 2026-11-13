import sqlite3,tempfile,threading,unittest
from pathlib import Path
from contextlib import closing
from acar.order_journal_research import ResearchJournal

class JournalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'research.sqlite';self.j=ResearchJournal.create(self.path)
 def tearDown(self):self.tmp.cleanup()
 def submit(self):return self.j.submit('order-1','BTC-USDT-SWAP','buy','1')
 def test_create_does_not_touch_existing_db(self):
  p=Path(self.tmp.name)/'paper.sqlite';p.write_bytes(b'untouched')
  with self.assertRaises(FileExistsError):ResearchJournal.create(p)
  self.assertEqual(p.read_bytes(),b'untouched')
 def test_reopen_and_reject_other_database(self):
  self.submit();self.assertEqual(ResearchJournal(self.path).snapshot('order-1')['order']['status'],'PENDING')
  p=Path(self.tmp.name)/'other.sqlite'
  with closing(sqlite3.connect(p)):pass
  with self.assertRaises(ValueError):ResearchJournal(p)
 def test_order_idempotency_and_conflict(self):
  self.submit();self.j.submit('order-1','BTC-USDT-SWAP','buy','1.0')
  with self.assertRaises(ValueError):self.j.submit('order-1','BTC-USDT-SWAP','buy','2')
  self.assertEqual(len(self.j.snapshot('order-1')['events']),1)
 def test_partial_cancellation_only_after_final_match(self):
  self.submit();self.j.acknowledge('order-1');self.j.record_fill('order-1','f1','0.4','100','0.02');self.j.request_cancel('order-1')
  self.j.record_fill('order-1','f2','0.1','101','0.005')
  self.assertEqual(self.j.snapshot('order-1')['order']['status'],'CANCEL_PENDING')
  result=self.j.reconcile_final('order-1','CANCELED','0.5');self.assertEqual(result['status'],'CANCELED')
  a=self.j.snapshot('order-1');self.assertTrue(a['integrity_ok']);self.assertEqual(a['filled_notional'],'50.1');self.assertEqual(a['fees'],'0.025')
  with self.assertRaises(ValueError):self.j.record_fill('order-1','f3','0.1','100','0')
 def test_wrong_final_status_does_not_clear_uncertainty(self):
  self.submit();self.j.request_cancel('order-1');self.j.record_fill('order-1','f','0.5','100','0')
  self.assertEqual(self.j.reconcile_final('order-1','FILLED','0.5')['status'],'UNCERTAIN')
  with self.assertRaises(ValueError):self.j.request_cancel('order-1')
  self.assertEqual(self.j.reconcile_final('order-1','CANCELED','0.5')['status'],'CANCELED')
 def test_unknown_final_fill_mismatch_locks_then_resolve(self):
  self.submit();self.j.request_cancel('order-1')
  self.assertEqual(self.j.reconcile_final('order-1','CANCELED','0.2')['status'],'UNCERTAIN')
  self.j.record_fill('order-1','f1','0.2','100','0')
  self.assertEqual(self.j.snapshot('order-1')['order']['status'],'UNCERTAIN')
  self.assertEqual(self.j.reconcile_final('order-1','CANCELED','0.2')['status'],'CANCELED')
 def test_duplicate_fill_is_idempotent_conflict_rolls_back(self):
  self.submit();self.j.record_fill('order-1','f','0.2','100','0.01')
  self.assertTrue(self.j.record_fill('order-1','f','0.20','100.0','0.010')['duplicate'])
  before=self.j.snapshot('order-1')
  with self.assertRaises(ValueError):self.j.record_fill('order-1','f','0.3','100','0.01')
  self.assertEqual(before,self.j.snapshot('order-1'))
 def test_overfill_rejected_atomically(self):
  self.submit();self.j.record_fill('order-1','f1','0.8','100','0');before=self.j.snapshot('order-1')
  with self.assertRaises(ValueError):self.j.record_fill('order-1','f2','0.3','100','0')
  self.assertEqual(before,self.j.snapshot('order-1'))
 def test_full_fill_while_cancel_pending(self):
  self.submit();self.j.request_cancel('order-1');self.j.record_fill('order-1','f','1','100','0')
  self.assertEqual(self.j.snapshot('order-1')['order']['status'],'FILLED')
  with self.assertRaises(ValueError):self.j.reconcile_final('order-1','CANCELED','1')
 def test_uncertainty_cannot_be_cleared_by_fill_alone(self):
  self.submit();self.j.mark_uncertain('order-1');self.j.record_fill('order-1','f','1','100','0')
  self.assertEqual(self.j.snapshot('order-1')['order']['status'],'UNCERTAIN')
  self.assertEqual(self.j.reconcile_final('order-1','FILLED','1')['status'],'FILLED')
 def test_concurrent_replayed_fill_applied_once(self):
  self.submit();barrier=threading.Barrier(2);result=[];errors=[]
  def run():
   try:barrier.wait();result.append(self.j.record_fill('order-1','f','0.3','100','0')['duplicate'])
   except Exception as e:errors.append(str(e))
  ts=[threading.Thread(target=run) for _ in range(2)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertFalse(errors);self.assertEqual(sorted(result),[False,True]);self.assertEqual(self.j.snapshot('order-1')['order']['filled'],'0.3')
 def test_tampered_filled_total_is_detected(self):
  self.submit()
  with closing(sqlite3.connect(self.path)) as c:
   with c:c.execute("UPDATE orders SET filled='0.5' WHERE order_id='order-1'")
  self.assertFalse(self.j.snapshot('order-1')['integrity_ok'])
  with self.assertRaises(ValueError):self.j.record_fill('order-1','f','0.1','100','0')
 def test_no_conflicting_fill_id_across_orders(self):
  self.submit();self.j.submit('other','ETH-USDT-SWAP','buy','1');self.j.record_fill('order-1','f','0.2','100','0')
  with self.assertRaises(ValueError):self.j.record_fill('other','f','0.2','100','0')
 def test_decimal_precision_not_rounded_to_default_context(self):
  q='0.123456789123456789'
  self.j.submit('precise','BTC','buy','1')
  self.j.record_fill('precise','f',q,'999999999999.999999','0')
  r=self.j.snapshot('precise');self.assertTrue(r['integrity_ok']);self.assertEqual(r['order']['filled'],q)
 def test_invalid_numbers_and_final_states(self):
  self.submit()
  for q in ('NaN','-1',True,'1e99'):
   with self.subTest(q=q),self.assertRaises(ValueError):self.j.record_fill('order-1','f',q,'100','0')
  with self.assertRaises(ValueError):self.j.reconcile_final('order-1','OPEN','0')
if __name__=='__main__':unittest.main()
