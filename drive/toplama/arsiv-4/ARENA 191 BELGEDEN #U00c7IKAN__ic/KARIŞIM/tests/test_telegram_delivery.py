import json,tempfile,threading,unittest,subprocess,sys,sqlite3
from contextlib import closing
from pathlib import Path
from acar.unified_simulator import UnifiedSimulator
from acar.telegram_delivery import deliver_telegram,notification_status,resolve_delivery

TOKEN='12345678'+':'+('A'*35)
CHAT='-123456'
class TelegramTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite';self.bot=UnifiedSimulator.create(self.path)
  self.bot.lock_entries('lock','OPERATOR_HALT',1);self.calls=[]
 def tearDown(self):self.tmp.cleanup()
 def sender(self,req,timeout):self.calls.append((req.method,timeout));return json.dumps({'ok':True}).encode()
 def send(self,attempt='try1',transport=None):return deliver_telegram(self.path,1,token=TOKEN,chat_id=CHAT,attempt_id=attempt,transport=transport or self.sender)
 def test_explicit_delivery_and_duplicate(self):
  self.assertEqual(self.send()['state'],'SENT');self.assertEqual(self.send('try2')['state'],'SENT');self.assertEqual(len(self.calls),1)
  self.assertNotIn(TOKEN,str(notification_status(self.path,1)))
  data=self.path.read_bytes();self.assertNotIn(TOKEN.encode(),data);self.assertNotIn(CHAT.encode(),data)
  with closing(sqlite3.connect(self.path)) as c:self.assertEqual([r[0] for r in c.execute('SELECT action FROM delivery_events ORDER BY id')],['CLAIMED','SENT'])
 def test_timeout_is_uncertain_and_never_auto_retried(self):
  def timeout(*a):raise TimeoutError('contains private transport details')
  r=self.send(transport=timeout);self.assertEqual(r['state'],'UNCERTAIN');self.assertNotIn('private',str(r))
  self.assertFalse(self.send('try2')['sent_now']);self.assertFalse(self.calls)
 def test_process_death_during_send_never_auto_resends(self):
  script="""import os,sys
from acar.telegram_delivery import deliver_telegram
value='12345678'+':'+('A'*35)
def crash(*args):os._exit(79)
deliver_telegram(sys.argv[1],1,token=value,chat_id='-123456',attempt_id='attempt',transport=crash)
"""
  p=subprocess.run([sys.executable,'-c',script,str(self.path)],capture_output=True,text=True,timeout=10)
  self.assertEqual(p.returncode,79,p.stderr);self.assertEqual(notification_status(self.path,1)['state'],'IN_FLIGHT')
  self.assertFalse(self.send('second')['sent_now']);self.assertEqual(self.calls,[])
 def test_credentials_cannot_be_used_as_attempt_id(self):
  with self.assertRaises(ValueError):self.send(TOKEN)
  self.assertEqual(notification_status(self.path,1)['state'],'READY')
 def test_operator_retry_after_uncertainty_is_explicit(self):
  self.send(transport=lambda *_: b'invalid');self.assertEqual(resolve_delivery(self.path,1,'RETRY_APPROVED')['state'],'READY')
  self.assertEqual(self.send('try2')['state'],'SENT');self.assertEqual(len(self.calls),1)
 def test_operator_confirms_without_resending(self):
  self.send(transport=lambda *_: b'{"ok":false}');self.assertEqual(resolve_delivery(self.path,1,'CONFIRMED_SENT')['state'],'SENT')
  self.assertFalse(self.send('try2')['sent_now']);self.assertFalse(self.calls)
 def test_no_credentials_means_no_claim(self):
  with self.assertRaises(ValueError):deliver_telegram(self.path,1,token='',chat_id=CHAT,attempt_id='a',transport=self.sender)
  self.assertEqual(notification_status(self.path,1)['state'],'READY')
 def test_concurrent_claims_deliver_once(self):
  barrier=threading.Barrier(2);out=[];errors=[]
  def run(i):
   try:barrier.wait();out.append(self.send('try'+str(i)))
   except Exception as e:errors.append(str(e))
  ts=[threading.Thread(target=run,args=(i,)) for i in range(2)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertFalse(errors);self.assertEqual(len(self.calls),1);self.assertEqual(sum(r['sent_now'] for r in out),1)
 def test_invalid_seq_and_no_unauthorized_resolve(self):
  for seq in (True,0,99):
   with self.subTest(seq=seq),self.assertRaises(ValueError):notification_status(self.path,seq)
  with self.assertRaises(ValueError):resolve_delivery(self.path,1,'RETRY_APPROVED')
 def test_rejection_is_not_success_and_does_not_retry(self):
  self.assertEqual(self.send(transport=lambda *_:b'{"ok":false}')['state'],'REJECTED')
  self.assertFalse(self.send('other')['sent_now']);self.assertEqual(self.calls,[])
if __name__=='__main__':unittest.main()
