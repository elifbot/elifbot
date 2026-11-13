import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from acar.worker_lock import WorkerLock
from public_paper_loop import load_config,run_cycle

class LoopTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'config.json';self.db=Path(self.tmp.name)/'db'
  self.config={'poll_seconds':10,'instruments':[{'symbol':'BTC-USDT-SWAP','quantity':'0.01','leverage':'2','min_notional':'5'}]};self.path.write_text(json.dumps(self.config))
 def tearDown(self):self.tmp.cleanup()
 def test_config_strict(self):
  self.assertEqual(load_config(self.path),self.config)
  for change in ({'poll_seconds':True},{'poll_seconds':4},{'instruments':self.config['instruments']*2},{'instruments':[dict(self.config['instruments'][0],leverage='NaN')]}):
   bad=dict(self.config,**change);self.path.write_text(json.dumps(bad))
   with self.assertRaises(ValueError):load_config(self.path)
 def test_run_cycle_calls_only_configured_public_once(self):
  out=[]
  sim=type('FakeSim',(),{'snapshot':lambda self:{'state':{'positions':{}}}})()
  with patch('public_paper_loop.public_paper_once',return_value={'action':'MONITOR'}) as fake:
   result=run_cycle(sim,self.config,object(),clock_ms=lambda:100,emit=lambda x,**kw:out.append(json.loads(x)))
  self.assertEqual(fake.call_count,1);self.assertEqual(result,[{'action':'MONITOR'}]);self.assertEqual(out[0]['symbol'],'BTC-USDT-SWAP')
 def test_unconfigured_open_position_is_never_silently_ignored(self):
  sim=type('FakeSim',(),{'snapshot':lambda self:{'state':{'positions':{'ETH-USDT-SWAP':{}}}}})()
  with patch('public_paper_loop.public_paper_once') as fake:
   with self.assertRaisesRegex(ValueError,'not covered'):run_cycle(sim,self.config,object(),emit=lambda *a,**k:None)
   fake.assert_not_called()
 def test_open_positions_monitored_before_entries_and_entries_skipped(self):
  symbols=['BTC-USDT-SWAP','ETH-USDT-SWAP'];config={'poll_seconds':10,'instruments':[dict(self.config['instruments'][0],symbol=x) for x in symbols]}
  sim=type('FakeSim',(),{'snapshot':lambda self:{'state':{'positions':{'ETH-USDT-SWAP':{}}}}})()
  with patch('public_paper_loop.public_paper_once',return_value={'action':'MONITOR'}) as fake:
   result=run_cycle(sim,config,object(),emit=lambda *a,**k:None)
  self.assertEqual(fake.call_count,1);self.assertEqual(fake.call_args.kwargs['symbol'],'ETH-USDT-SWAP');self.assertEqual(result[1]['reason'],'OPEN_POSITION_MONITOR_PRIORITY')
 def test_new_position_stops_later_entry_scans_in_same_cycle(self):
  config={'poll_seconds':10,'instruments':[dict(self.config['instruments'][0],symbol=x) for x in ['BTC-USDT-SWAP','ETH-USDT-SWAP']]}
  class FakeSim:
   positions={}
   def snapshot(self):return {'state':{'positions':self.positions}}
  sim=FakeSim()
  def opening(sim,**kw):sim.positions[kw['symbol']]={};return {'action':'OPEN'}
  with patch('public_paper_loop.public_paper_once',side_effect=opening) as fake:
   result=run_cycle(sim,config,object(),emit=lambda *a,**k:None)
  self.assertEqual(fake.call_count,1);self.assertEqual(result[1]['reason'],'OPEN_POSITION_MONITOR_PRIORITY')
 def test_worker_lock_is_shared_and_released(self):
  with WorkerLock(self.db):
   with self.assertRaises(BlockingIOError):
    with WorkerLock(self.db):pass
  with WorkerLock(self.db):pass
 def test_confirmed_loop_loads_existing_db_and_stops_on_unexpected_error(self):
  from acar.unified_simulator import UnifiedSimulator
  from public_paper_loop import main
  UnifiedSimulator.create(self.db)
  with patch('public_paper_loop.run_cycle',side_effect=RuntimeError('synthetic')),patch('public_paper_loop.PublicClient') as client:
   rc=main(['--db',str(self.db),'--config',str(self.path),'--confirm-public-paper'])
  self.assertEqual(rc,1);client.assert_called_once()
  with WorkerLock(self.db):pass
 def test_unexpected_worker_error_attempts_account_lock_with_open_position(self):
  from acar.unified_simulator import UnifiedSimulator
  from acar.depth_research import MarketRules
  from public_paper_loop import main
  sim=UnifiedSimulator.create(self.db);rules=MarketRules('BTC','0.1','0.1','0.1','0')
  book={'symbol':'BTC','observed_at':10,'bids':[['99.9','1']],'asks':[['100','1']]}
  sim.open_position('test-open',symbol='BTC',side='long',quantity='1',stop='98',target='105',leverage='2',next_funding=10000000000,now=10,book_id='book',book=book,rules=rules)
  with patch('public_paper_loop.run_cycle',side_effect=RuntimeError('synthetic')),patch('public_paper_loop.PublicClient'):
   self.assertEqual(main(['--db',str(self.db),'--config',str(self.path),'--confirm-public-paper']),1)
  self.assertTrue(sim.snapshot()['state']['entry_locked']);self.assertIn('BTC',sim.snapshot()['state']['positions'])
 def test_confirmed_once_uses_existing_db_and_worker_lock_without_network(self):
  from acar.unified_simulator import UnifiedSimulator
  from public_paper_once import main
  UnifiedSimulator.create(self.db)
  args=['public_paper_once.py','--db',str(self.db),'--symbol','BTC-USDT-SWAP','--quantity','.01','--leverage','2','--min-notional','5','--confirm-public-paper']
  with patch('sys.argv',args),patch('public_paper_once.public_paper_once',return_value={'action':'MONITOR'}) as fake:
   self.assertEqual(main(),0)
  fake.assert_called_once()
  with WorkerLock(self.db):pass
 def test_no_confirm_does_not_read_config_or_create_lock_or_db(self):
  missing=self.path.parent/'does-not-exist';p=subprocess.run([sys.executable,'public_paper_loop.py','--db',str(self.db),'--config',str(missing)],capture_output=True,text=True,timeout=10)
  self.assertEqual(p.returncode,2);self.assertFalse(self.db.exists());self.assertFalse(Path(str(self.db)+'.worker.lock').exists());self.assertIn('Ağ veya PAPER başlatılmadı',p.stderr)
if __name__=='__main__':unittest.main()
