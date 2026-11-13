import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from acar.data import Bar
from dataclasses import asdict
class UnifiedCliTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name);self.db=self.dir/'db.sqlite';self.events=self.dir/'events.jsonl';self.out=self.dir/'out.jsonl'
 def tearDown(self):self.tmp.cleanup()
 def cmd(self,*args):return subprocess.run([sys.executable,'unified_cli.py',*map(str,args)],capture_output=True,text=True,timeout=10)
 def test_offline_workflow_and_exclusive_output(self):
  self.assertEqual(self.cmd('init','--db',self.db).returncode,0)
  bars=[asdict(Bar(1704067200+i*60,100+i,101+i,99+i,100.5+i,10)) for i in range(220)];now=bars[-1]['timestamp']+60
  rules={'symbol':'BTC','qty_step':'0.1','price_tick':'0.1','min_qty':'0.1','min_notional':'0'}
  event={'id':'one','type':'candles','data':{'symbol':'BTC','bars':bars,'quantity':'0.2','leverage':'2','next_funding':now+100,'now':now,'book_id':'b1','book':{'symbol':'BTC','observed_at':now,'bids':[['319.4','1']],'asks':[['319.6','1']]},'rules':rules}}
  self.events.write_text(json.dumps(event)+'\n',encoding='utf-8')
  p=self.cmd('run','--db',self.db,'--events',self.events,'--out',self.out);self.assertEqual(p.returncode,0,p.stderr)
  self.assertEqual(json.loads(self.out.read_text())['result']['action'],'OPEN')
  state=json.loads(self.cmd('status','--db',self.db).stdout);self.assertIn('BTC',state['state']['positions'])
  omni=json.loads(self.cmd('status','--db',self.db,'--format','omni').stdout);self.assertEqual(omni['integrationState'],'DEPLOYMENT_NOT_VERIFIED');self.assertEqual(omni['positions'][0]['symbol'],'BTC');self.assertNotIn('ledger',omni)
  self.assertEqual(self.cmd('run','--db',self.db,'--events',self.events,'--out',self.out).returncode,2)
 def test_risk_status_and_wrong_asof_format(self):
  self.assertEqual(self.cmd('init','--db',self.db).returncode,0)
  output=self.cmd('status','--db',self.db,'--format','risk','--as-of','10');self.assertEqual(output.returncode,0);self.assertEqual(json.loads(output.stdout)['mode'],'OFFLINE_ESTIMATE')
  self.assertEqual(self.cmd('status','--db',self.db,'--format','omni','--as-of','10').returncode,2)
 def test_db_cannot_equal_input_or_output(self):
  self.assertEqual(self.cmd('init','--db',self.db).returncode,0);before=self.db.read_bytes()
  self.assertEqual(self.cmd('run','--db',self.db,'--events',self.db,'--out',self.out).returncode,2)
  self.assertEqual(before,self.db.read_bytes())
 def test_notification_status_requires_explicit_send_and_attempt(self):
  self.assertEqual(self.cmd('init','--db',self.db).returncode,0)
  self.events.write_text(json.dumps({'id':'lock','type':'lock','data':{'reason':'OPERATOR_HALT','now':1}})+'\n')
  self.assertEqual(self.cmd('run','--db',self.db,'--events',self.events,'--out',self.out).returncode,0)
  p=self.cmd('telegram','--db',self.db,'--seq','1');self.assertEqual(p.returncode,0);self.assertEqual(json.loads(p.stdout)['state'],'READY')
  self.assertEqual(self.cmd('telegram','--db',self.db,'--seq','1','--send').returncode,2)
 def test_partial_file_results_retained_after_bad_event(self):
  self.assertEqual(self.cmd('init','--db',self.db).returncode,0)
  self.events.write_text(json.dumps({'id':'lock','type':'lock','data':{'reason':'OPERATOR_HALT','now':1}})+'\n'+json.dumps({'id':'bad','type':'bad','data':{}})+'\n')
  p=self.cmd('run','--db',self.db,'--events',self.events,'--out',self.out);self.assertEqual(p.returncode,2);self.assertEqual(len(self.out.read_text().splitlines()),1)
  state=json.loads(self.cmd('status','--db',self.db).stdout);self.assertTrue(state['state']['entry_locked'])
if __name__=='__main__':unittest.main()
