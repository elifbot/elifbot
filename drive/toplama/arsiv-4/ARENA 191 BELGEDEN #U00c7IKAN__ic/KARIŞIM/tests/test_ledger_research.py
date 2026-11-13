import json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from contextlib import closing
from acar.data import Bar,load_csv
from acar.engine import initial_state,process
from acar.ledger import audit_ledger
from acar.store import Store
from export_history import export
from acar.replay import PaperEngine,Config
from acar.strategy import Confluence
from acar.research import walk_forward

def bar(ts,close=100):return Bar(ts,100,101,99,close,10)
class LedgerTest(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'test.sqlite';self.store=Store(self.db,1000)
 def tearDown(self):self.temp.cleanup()
 def test_cash_mismatch_rejects_atomically(self):
  old=self.store.load();bad=dict(old,cash=old['cash']+1)
  with self.assertRaises(RuntimeError):self.store.commit(bad,[{'time':1,'type':'X','detail':'test'}],[],expected_state=old)
  self.assertEqual(self.store.load(),old);self.assertEqual(self.store.latest()[0],[])
 def test_detect_existing_tampered_state(self):
  with closing(sqlite3.connect(self.db)) as c:
   with c:
    s=self.store.load();s['cash']+=1;c.execute('UPDATE state SET data=? WHERE id=1',(json.dumps(s),))
  report=self.store.audit();self.assertFalse(report['ok']);self.assertIn('CASH_MISMATCH',report['issues'])
  with self.assertRaises(RuntimeError):self.store.commit(s,[],[])
 def test_net_and_gross_trade_mismatch(self):
  s=initial_state(1);s['trade_count']=1
  t={'side':'long','entry':100,'exit':110,'qty':1,'gross':10,'fees':1,'net':100}
  a=audit_ledger(s,[t]);self.assertIn('TRADE_NET_MISMATCH_0',a['issues'])
 def test_optimistic_state_mismatch_rejects(self):
  a=self.store.load();b=dict(a,last_bar=60);self.store.commit(b,[],[],expected_state=a)
  with self.assertRaises(RuntimeError):self.store.commit(dict(a,last_bar=120),[],[],expected_state=a)
  self.assertEqual(self.store.load()['last_bar'],60)
 def test_concurrent_writers_cannot_both_commit_same_state(self):
  old=self.store.load();barrier=threading.Barrier(2);out=[]
  def writer(t):
   barrier.wait()
   try:self.store.commit(dict(old,last_bar=t),[],[],expected_state=old);out.append('ok')
   except RuntimeError:out.append('stale')
  a=threading.Thread(target=writer,args=(60,));b=threading.Thread(target=writer,args=(120,));a.start();b.start();a.join();b.join()
  self.assertEqual(sorted(out),['ok','stale'])
 def test_candles_provenance_and_no_overwrite(self):
  a=self.store.load();b=dict(a,last_bar=60)
  self.store.commit(b,[],[],expected_state=a,candles=[bar(0),bar(60)],captured_at=125)
  self.store.commit(dict(b,last_bar=120),[],[],expected_state=b,candles=[bar(60),bar(120)],captured_at=185)
  with closing(sqlite3.connect(self.db)) as c:
   self.assertEqual([r[0] for r in c.execute('SELECT origin FROM candles ORDER BY timestamp')],['warmup','warmup','observed'])
  current=self.store.load()
  with self.assertRaises(RuntimeError):self.store.commit(dict(current,last_bar=180),[],[],expected_state=current,candles=[bar(60,100.5)],captured_at=200)
  self.assertEqual(self.store.load(),current)
 def test_export_no_overwrite_and_closed_bars_valid(self):
  old=self.store.load();self.store.commit(old,[],[],expected_state=old,candles=[bar(0),bar(60)],captured_at=125)
  p=Path(self.temp.name)/'bars.csv';self.assertEqual(export(self.db,p),2);self.assertEqual(len(load_csv(p,60)),2)
  with self.assertRaises(FileExistsError):export(self.db,p)
  with self.assertRaises(ValueError):export(self.db,self.db)
 def test_record_uncertain_closure_after_outage(self):
  now=1704068000;s=initial_state(now);s['last_bar']=now-60;s['last_quote_time']=now-100;s['position']={'side':'long','entry':100,'qty':1,'entry_time':now-200,'entry_fee':.05,'stop':95,'target':110,'signal_bar':now-100};s['cash']-=.05
  q={'time':now,'bid':94.,'ask':94.01,'spread_bps':1.06};f={'rate':0.,'settlement':now+2000,'observed':now}
  new,events,trades=process(s,[],q,f,now)
  self.assertTrue(trades[0]['execution_uncertain']);self.assertTrue(new['halt']);self.assertIn('MONITORING_GAP',audit_ledger(new,trades)['warnings'])
class ResearchTest(unittest.TestCase):
 def test_replay_no_future_and_audit(self):
  bars=[Bar(1704067200+i*60,100+i*.1,101+i*.1,99+i*.1,100.1+i*.1,1000+i%9) for i in range(120)]
  cfg=Config(initial_cash=1000,max_notional=250)
  r=PaperEngine(cfg,Confluence()).run(bars)
  self.assertAlmostEqual(r['net_pnl'],sum(t['net_pnl'] for t in r['trades']),places=8)
  wf=walk_forward(bars,cfg,train_bars=60,test_bars=30)
  for w in wf['windows']:
   for t in w['test_trade_details']:self.assertGreaterEqual(t['entry_time'],w['test_start']+60)
if __name__=='__main__':unittest.main()

class TechnicalSummaryTest(unittest.TestCase):
 def test_partial_utc_day_not_labeled_full_vwap(self):
  from acar.indicators import technical_snapshot
  bars=[bar(1704067200+i*60) for i in range(40)]
  self.assertEqual(technical_snapshot(bars)['vwap_status'],'COMPLETE')
  partial=technical_snapshot(bars[1:]);self.assertEqual(partial['vwap_status'],'PARTIAL_DAY');self.assertIsNone(partial['vwap_utc'])
 def test_snapshot_uses_only_given_prefix(self):
  from acar.indicators import technical_snapshot
  bars=[bar(1704067200+i*60) for i in range(40)];a=technical_snapshot(bars[:30]);bars[-1]=bar(bars[-1].timestamp,100.5)
  self.assertEqual(a,technical_snapshot(bars[:30]));self.assertIsNone(technical_snapshot([]).get('rsi14'))
