import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
from acar.unified_simulator import UnifiedSimulator
from acar.depth_research import MarketRules
from acar.worker_lock import WorkerLock
from paper_operator import main

class OperatorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'db.sqlite';self.sim=UnifiedSimulator.create(self.db)
  rules=MarketRules('BTC','0.1','0.1','0.1','0');book={'symbol':'BTC','observed_at':10,'bids':[['99.9','1']],'asks':[['100','1']]}
  self.sim.open_position('open',symbol='BTC',side='long',quantity='1',stop='98',target='105',leverage='2',next_funding=20,now=10,book_id='book',book=book,rules=rules)
 def tearDown(self):self.tmp.cleanup()
 def args(self):return ['funding','--db',str(self.db),'--symbol','BTC','--settlement-ts','20','--finalized-at','20','--rate','0.001','--mark-price','100','--next-funding','100']
 def invoke(self,args,now=20):
  with patch('paper_operator.time.time',return_value=now),redirect_stdout(StringIO()) as output,redirect_stderr(StringIO()) as error:
   rc=main(args)
  return rc,output.getvalue(),error.getvalue()
 def test_without_confirmation_no_mutation_and_no_lockfile(self):
  before=self.sim.snapshot();rc,_,_=self.invoke(self.args());self.assertEqual(rc,2);self.assertEqual(before,self.sim.snapshot());self.assertFalse(Path(str(self.db)+'.worker.lock').exists())
 def test_funding_duplicate_does_not_double_charge(self):
  a=self.args()+['--confirm-manual-funding'];rc,out,_=self.invoke(a);self.assertEqual(rc,0);self.assertEqual(json.loads(out)['result']['status'],'APPLIED');before=self.sim.snapshot()
  rc,out,_=self.invoke(a,21);self.assertEqual(rc,0);self.assertEqual(json.loads(out)['result']['status'],'DUPLICATE');self.assertEqual(len(before['ledger']),len(self.sim.snapshot()['ledger']))
 def test_running_worker_blocks_manual_changes(self):
  before=self.sim.snapshot()
  with WorkerLock(self.db):rc,_,_=self.invoke(self.args()+['--confirm-manual-funding'])
  self.assertEqual(rc,2);self.assertEqual(before,self.sim.snapshot())
 def test_unlock_does_not_override_unknown_funding_or_gap(self):
  self.sim.lock_entries('test-lock','FUNDING_UNKNOWN',19)
  rc,_,_=self.invoke(['unlock','--db',str(self.db),'--confirm-unlock'],20);self.assertEqual(rc,2);self.assertTrue(self.sim.snapshot()['state']['entry_locked'])
 def test_confirmed_settlement_then_operator_unlock_can_recover_when_fresh(self):
  self.sim.lock_entries('funding-lock','FUNDING_UNKNOWN',19)
  rc,_,_=self.invoke(self.args()+['--confirm-manual-funding'],20);self.assertEqual(rc,0)
  rc,_,_=self.invoke(['unlock','--db',str(self.db),'--confirm-unlock'],20);self.assertEqual(rc,0);self.assertFalse(self.sim.snapshot()['state']['entry_locked'])
 def test_invented_settlement_time_is_rejected(self):
  args=self.args();args[args.index('--settlement-ts')+1]='21';rc,_,_=self.invoke(args+['--confirm-manual-funding'],21)
  self.assertEqual(rc,2);self.assertEqual(len(self.sim.snapshot()['ledger']),1)
if __name__=='__main__':unittest.main()
