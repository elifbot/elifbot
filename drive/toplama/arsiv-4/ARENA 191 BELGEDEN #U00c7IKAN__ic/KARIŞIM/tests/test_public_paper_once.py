import copy,subprocess,sys,tempfile,unittest
from pathlib import Path
from acar.okx_public_adapter import parse_instrument,parse_book,parse_candles,parse_upcoming_funding
from acar.public_paper_once import public_paper_once
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator

class PublicOnceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.sim=UnifiedSimulator.create(Path(self.tmp.name)/'db.sqlite')
  self.now=1704080400000;self.symbol='BTC-USDT-SWAP'
  payload={'code':'0','data':[{'instId':self.symbol,'instType':'SWAP','ctType':'linear','state':'live','settleCcy':'USDT','ctValCcy':'BTC','instCategory':'1','ruleType':'normal','ctVal':'0.01','ctMult':'1','lotSz':'1','minSz':'2','tickSz':'0.1'}]}
  self.inst=parse_instrument(payload,self.symbol,min_notional='5')
  rows=[]
  for i in range(220):
   p=100+i;rows.append([str((1704067200+i*60)*1000),str(p),str(p+1),str(p-1),str(p+.5),'500','10','1000','1'])
  self.bars=parse_candles({'code':'0','data':rows},now_ms=self.now)
  self.book=parse_book({'code':'0','data':[{'ts':str(self.now),'bids':[['319.4','10']],'asks':[['319.6','10']]}]},self.inst,now_ms=self.now)
  self.funding=parse_upcoming_funding({'code':'0','data':[{'instId':self.symbol,'ts':str(self.now),'fundingTime':str(self.now+1000000),'fundingRate':'0.001'}]},self.symbol,now_ms=self.now)
 def tearDown(self):self.tmp.cleanup()
 def client(self):
  parent=self
  class Fake:
   def instrument(self,*a,**kw):return parent.inst
   def complete_history(self,*a,**kw):return parent.bars
   def funding(self,*a,**kw):return parent.funding
   def book(self,*a,**kw):return parent.book
  return Fake()
 def test_public_pipeline_fake_data_and_monitor(self):
  c=self.client();kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  r=public_paper_once(self.sim,**kw);self.assertEqual(r['action'],'OPEN');self.assertIn(self.symbol,self.sim.snapshot()['state']['positions'])
  monitor=public_paper_once(self.sim,**kw);self.assertEqual(monitor['action'],'MONITOR')
  before=self.sim.snapshot();again=public_paper_once(self.sim,**kw);self.assertEqual(again['action'],'ALREADY_PROCESSED_BOOK');self.assertEqual(before,self.sim.snapshot())
 def test_expected_stale_closed_candle_is_safe_wait_not_data_error(self):
  c=self.client();later=self.now+31000
  old=copy.deepcopy(self.book);old['book']['observed_at']=later//1000;old['source_ts_ms']=later;old['book_id']='OKX:'+self.symbol+':'+str(later)
  c.book=lambda *a,**k:old
  out=public_paper_once(self.sim,symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:later)
  self.assertEqual((out['action'],out['reason']),('SKIP','WAIT_FOR_FRESH_CLOSED_CANDLE'));self.assertFalse(self.sim.snapshot()['state']['entry_locked'])
 def test_risk_rejection_is_not_mislabeled_as_data_error(self):
  c=self.client();deep=copy.deepcopy(self.book);deep['book']['asks']=[['319.6','10']];c.book=lambda *a,**k:deep
  r=public_paper_once(self.sim,symbol=self.symbol,quantity='10',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(r['action'],'BLOCKED');self.assertEqual(r['reason'],'portfolio risk limit');self.assertFalse(self.sim.snapshot()['state']['entry_locked'])
 def test_changed_instrument_spec_locks_open_position(self):
  c=self.client();kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'OPEN')
  kw['min_notional']='6'
  # Fake provider must faithfully reflect the changed metadata/config value.
  from dataclasses import replace
  from acar.depth_research import MarketRules
  old=self.inst.rules;changed=replace(self.inst,rules=MarketRules(symbol=old.symbol,qty_step=old.qty_step,price_tick=old.price_tick,min_qty=old.min_qty,min_notional='6'))
  c.instrument=lambda *a,**k:changed
  r=public_paper_once(self.sim,**kw);self.assertEqual(r['action'],'DATA_ERROR');self.assertTrue(self.sim.snapshot()['state']['entry_locked']);self.assertIn(self.symbol,self.sim.snapshot()['state']['positions'])
 def test_due_funding_never_automatically_invented(self):
  c=self.client();kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'OPEN')
  # Test-only book reflecting the funding due moment.
  due=self.funding['next_funding']*1000;newbook=copy.deepcopy(self.book);newbook['book']['observed_at']=due//1000;newbook['book_id']='OKX:'+self.symbol+':'+str(due);newbook['source_ts_ms']=due
  c.book=lambda *a,**k:newbook;kw['clock_ms']=lambda:due
  out=public_paper_once(self.sim,**kw);self.assertEqual(out['action'],'LOCK');self.assertEqual(out['protection']['status'],'FUNDING_DUE_UNKNOWN')
  self.assertIn(self.symbol,self.sim.snapshot()['state']['positions']);self.assertTrue(self.sim.snapshot()['state']['entry_locked'])
 def test_bridge_pre_funding_close_with_continuous_monitoring(self):
  c=self.client();kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'OPEN');start=self.now//1000
  for elapsed in range(25,801,25):self.sim.mark('mark-'+str(elapsed),self.symbol,'319.5',start+elapsed)
  timestamp=self.now+820000;book=copy.deepcopy(self.book);book['book']['observed_at']=timestamp//1000;book['source_ts_ms']=timestamp;book['book_id']='OKX:'+self.symbol+':'+str(timestamp)
  c.book=lambda *a,**k:book;kw['clock_ms']=lambda:timestamp
  r=public_paper_once(self.sim,**kw);self.assertEqual((r['action'],r['order']['reason']),('CLOSE','FUNDING_PREEMPT'));self.assertFalse(r['order']['execution_uncertain'])
 def test_market_error_locks_existing_position_no_fake_close(self):
  c=self.client();kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'OPEN')
  def bad(*a,**k):raise OSError('bad')
  c.instrument=bad;r=public_paper_once(self.sim,**kw)
  state=self.sim.snapshot()['state'];self.assertEqual(r['action'],'DATA_ERROR');self.assertTrue(state['entry_locked']);self.assertIn(self.symbol,state['positions'])
 def test_cli_requires_explicit_opt_in_before_db_or_network(self):
  path=Path(self.tmp.name)/'not-existing.sqlite'
  p=subprocess.run([sys.executable,'public_paper_once.py','--db',str(path),'--symbol',self.symbol,'--quantity','.02','--leverage','2','--min-notional','5'],capture_output=True,text=True,timeout=10)
  self.assertEqual(p.returncode,2);self.assertFalse(path.exists());self.assertIn('Ağ veya PAPER başlatılmadı',p.stderr)
 def test_auto_realized_rate_uses_proxy_and_persistent_uncertainty(self):
  c=self.client();self.funding['next_funding']=1704081420
  kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'OPEN')
  t=self.funding['next_funding'];kw['clock_ms']=lambda:(t+120)*1000
  c.realized_settlement=lambda *a,**k:{'symbol':self.symbol,'settlement_ts':t,'rate':'-0.002','rate_kind':'OKX_REALIZED_RATE','mark_price_proxy':'320','mark_kind':'ONE_MINUTE_MARK_OPEN_PROXY_NOT_EXACT','next_funding':t+28800}
  out=public_paper_once(self.sim,**kw);self.assertEqual(out['action'],'FUNDING_APPLIED_ESTIMATED')
  snap=self.sim.snapshot();p=snap['state']['positions'][self.symbol]
  self.assertTrue(p['execution_uncertain']);self.assertTrue(p['funding_price_uncertain']);self.assertTrue(snap['state']['entry_locked']);self.assertEqual(snap['state']['lock_reason'],'FUNDING_PRICE_ESTIMATED')
  funding=[x for x in snap['ledger'] if x['kind']=='FUNDING'];self.assertEqual(len(funding),1);self.assertEqual(funding[0]['delta'],'0.0128');self.assertTrue(funding[0]['detail']['funding_amount_uncertain'])
  duplicate=self.sim.settle_funding('another-id',symbol=self.symbol,settlement_ts=t,finalized_at=t+120,rate='-0.002',mark_price='320',next_funding=t+28800,now=t+120,estimated_price=True)
  self.assertEqual(duplicate['status'],'DUPLICATE');self.assertEqual(len([x for x in self.sim.snapshot()['ledger'] if x['kind']=='FUNDING']),1)
  with self.assertRaises(ValueError):self.sim.clear_entry_lock('no-unlock',now=t+120)
  from acar.risk_report import risk_report
  from acar.omnistudio_contract import build_omni_status
  self.assertIn(self.symbol+':FUNDING_PRICE_PROXY',risk_report(self.sim.snapshot())['warnings'])
  self.assertFalse(build_omni_status(self.sim.snapshot())['account']['equityReliable'])
  at=t+121;book=copy.deepcopy(self.book['book']);book['observed_at']=at
  self.sim.close_position('close-estimated',symbol=self.symbol,quantity='0.02',now=at,book_id='proxy-close',book=book,rules=self.inst.rules)
  final=self.sim.snapshot();self.assertFalse(final['state']['positions']);self.assertTrue(final['state']['entry_locked'])
  self.assertIn('EXECUTION_HISTORY_UNCERTAIN',risk_report(final)['warnings'])
  self.assertFalse(build_omni_status(final)['account']['equityReliable'])
  self.assertTrue(build_omni_status(final)['account']['uncertainExecutionHistory'])
 def test_failed_realized_evidence_fails_closed_no_funding(self):
  c=self.client();self.funding['next_funding']=1704081420
  kw=dict(symbol=self.symbol,quantity='0.02',leverage='2',min_notional='5',client=c,clock_ms=lambda:self.now)
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'OPEN');t=self.funding['next_funding'];kw['clock_ms']=lambda:(t+120)*1000
  def bad(*a,**k):raise ValueError('missing realized')
  c.realized_settlement=bad
  self.assertEqual(public_paper_once(self.sim,**kw)['action'],'DATA_ERROR')
  s=self.sim.snapshot();self.assertTrue(s['state']['entry_locked']);self.assertIn(self.symbol,s['state']['positions']);self.assertFalse(any(x['kind']=='FUNDING' for x in s['ledger']))
if __name__=='__main__':unittest.main()
