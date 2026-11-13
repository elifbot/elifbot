import sqlite3,tempfile,threading,unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from acar.funding_research import Settlement
from acar.funding_store_research import FundingResearchStore

class FundingStoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'funding.sqlite';self.store=FundingResearchStore.create(self.path,1000)
  self.e=Settlement('OKX','BTC-USDT-SWAP',100,101,.001,50000,True)
  self.p={'id':'p1','venue':'OKX','instrument':'BTC-USDT-SWAP','side':'long','qty_base':.02,'opened_at':50,'closed_at':None}
 def tearDown(self):self.tmp.cleanup()
 def test_atomic_settlement_restart_and_idempotency(self):
  r=self.store.settle(self.e,self.p);self.assertTrue(r['applied']);self.assertAlmostEqual(r['cash_delta'],-1)
  again=FundingResearchStore(self.path);self.assertFalse(again.settle(self.e,self.p)['applied']);self.assertEqual(again.snapshot()['cash'],999);self.assertEqual(again.snapshot()['settlement_count'],1)
 def test_multiple_positions_and_directions(self):
  self.store.settle(self.e,self.p)
  self.store.settle(self.e,dict(self.p,id='p2',side='short'))
  self.assertEqual(self.store.snapshot()['cash'],1000)
  self.assertEqual(self.store.snapshot()['settlement_count'],2)
 def test_conflicting_replay_rolls_back(self):
  self.store.settle(self.e,self.p);before=self.store.snapshot()
  with self.assertRaises(ValueError):self.store.settle(replace(self.e,rate=.002),self.p)
  self.assertEqual(before,self.store.snapshot())
 def test_missing_or_wrong_market_does_not_write(self):
  for e,p in [(replace(self.e,confirmed=False),self.p),(self.e,dict(self.p,instrument='ETH-USDT-SWAP'))]:
   with self.assertRaises(ValueError):self.store.settle(e,p)
  self.assertEqual(self.store.snapshot()['settlement_count'],0)
 def test_concurrent_duplicate_once(self):
  barrier=threading.Barrier(2);out=[];errors=[]
  def worker():
   try:barrier.wait();out.append(self.store.settle(self.e,self.p)['applied'])
   except Exception as e:errors.append(str(e))
  threads=[threading.Thread(target=worker) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertFalse(errors);self.assertEqual(sorted(out),[False,True]);self.assertEqual(self.store.snapshot()['cash'],999)
 def test_tampered_cash_rejected_for_next_write(self):
  with closing(sqlite3.connect(self.path)) as c:
   with c:c.execute('UPDATE account SET cash=123 WHERE id=1')
  with self.assertRaises(ValueError):self.store.settle(self.e,self.p)
  with closing(sqlite3.connect(self.path)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM settlements').fetchone()[0],0)
 def test_tampered_event_detected_after_restart(self):
  self.store.settle(self.e,self.p)
  with closing(sqlite3.connect(self.path)) as c:
   with c:c.execute("UPDATE settlements SET data='{}'")
  with self.assertRaises(ValueError):FundingResearchStore(self.path)
 def test_cannot_overwrite_existing_paper_file(self):
  p=Path(self.tmp.name)/'paper.sqlite';p.write_bytes(b'untouched')
  with self.assertRaises(FileExistsError):FundingResearchStore.create(p,1000)
  self.assertEqual(p.read_bytes(),b'untouched')
 def test_wrong_store_id_rejected(self):
  p=Path(self.tmp.name)/'other.sqlite'
  with closing(sqlite3.connect(p)):pass
  with self.assertRaises(ValueError):FundingResearchStore(p)
if __name__=='__main__':unittest.main()
