import http.client,json,tempfile,threading,unittest
from pathlib import Path
from acar.unified_simulator import UnifiedSimulator
from status_gateway import ReadOnlyStatusServer

class GatewayTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db.sqlite';sim=UnifiedSimulator.create(self.path);sim.lock_entries('l','OPERATOR_HALT',1)
  self.token='A'*40;self.server=ReadOnlyStatusServer(0,self.path,self.token)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.thread.join();self.server.server_close();self.temp.cleanup()
 def call(self,method,path,headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
  try:c.request(method,path,headers=headers or {});r=c.getresponse();return r.status,json.loads(r.read())
  finally:c.close()
 def test_auth_read_only_and_minimal_view(self):
  self.assertEqual(self.call('GET','/v1/status')[0],401)
  self.assertEqual(self.call('GET','/v1/status',{'Authorization':'Bearer wrong'})[0],401)
  status,body=self.call('GET','/v1/status',{'Authorization':'Bearer '+self.token});self.assertEqual(status,200)
  self.assertEqual(body['mode'],'PAPER_SIMULATION');self.assertNotIn('ledger',body);self.assertTrue(body['account']['entriesLocked'])
  self.assertEqual(self.call('POST','/v1/status',{'Authorization':'Bearer '+self.token})[0],405)
  self.assertEqual(self.call('GET','/api/state',{'Authorization':'Bearer '+self.token})[0],404)
 def test_gateway_wall_clock_shows_stopped_worker_stale(self):
  from acar.depth_research import MarketRules
  sim=UnifiedSimulator(self.path);sim.clear_entry_lock('unlock',2)
  rules=MarketRules('BTC','0.1','0.1','0.1','0');book={'symbol':'BTC','observed_at':2,'bids':[['99.9','1']],'asks':[['100','1']]}
  sim.open_position('o',symbol='BTC',side='long',quantity='1',stop='98',target='105',leverage='2',next_funding=1000000000,book_id='b',book=book,rules=rules,now=2)
  _,body=self.call('GET','/v1/status',{'Authorization':'Bearer '+self.token})
  self.assertEqual(body['clockBasis'],'WALL_CLOCK');self.assertTrue(body['positions'][0]['markStale']);self.assertTrue(body['positions'][0]['fundingDue']);self.assertFalse(body['account']['equityReliable']);self.assertEqual(body['workerStatus'],'NOT_OBSERVED')
 def test_local_panel_is_static_and_never_contains_credentials(self):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
  try:
   c.request('GET','/');r=c.getresponse();body=r.read().decode('utf-8')
   self.assertEqual(r.status,200);self.assertIn('Birleşik bot durumu',body);self.assertNotIn(self.token,body)
   self.assertIn("default-src 'none'",r.getheader('Content-Security-Policy'));self.assertEqual(r.getheader('Cache-Control'),'no-store')
  finally:c.close()
 def test_panel_has_no_external_urls_or_persisted_tokens(self):
  html=self.server.panel.decode('utf-8')
  self.assertNotIn('localStorage',html);self.assertNotIn('sessionStorage',html);self.assertNotIn('https://',html);self.assertNotIn('innerHTML',html)
 def test_bind_only_loopback(self):self.assertEqual(self.server.server_address[0],'127.0.0.1')
 def test_no_db_mutation(self):
  before=self.path.read_bytes();self.call('GET','/v1/status',{'Authorization':'Bearer '+self.token});self.assertEqual(self.path.read_bytes(),before)
 def test_token_and_nonexistent_db_rejected(self):
  with self.assertRaises(ValueError):ReadOnlyStatusServer(0,self.path,'short')
  with self.assertRaises(Exception):ReadOnlyStatusServer(0,Path(self.temp.name)/'missing.sqlite',self.token)
if __name__=='__main__':unittest.main()
