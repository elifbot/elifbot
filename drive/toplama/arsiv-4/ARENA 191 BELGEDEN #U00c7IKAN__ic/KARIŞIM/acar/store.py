"""Tek süreçli PAPER checkpoint, OHLC arşivi ve atomik SQLite transaction."""
import json,sqlite3,threading
from contextlib import closing
from pathlib import Path
from .engine import initial_state
from .ledger import audit_ledger

def dumps(x):return json.dumps(x,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def _trade_rows(c):return [json.loads(row[0]) for row in c.execute('SELECT data FROM trades ORDER BY id')]
class Store:
 def __init__(self,path,now):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock()
  with closing(sqlite3.connect(self.path)) as c:
   if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SQLite bütünlük hatası')
   with c:
    c.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, time REAL NOT NULL, data TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS candles (timestamp INTEGER PRIMARY KEY, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL, origin TEXT NOT NULL, captured_at REAL NOT NULL)')
    c.execute('INSERT OR IGNORE INTO state VALUES (1,?)',(dumps(initial_state(now)),))
  x=self.load()
  if x.get('version')!=1 or not isinstance(x.get('cash'),(float,int)):raise RuntimeError('uyumsuz kayıt; paper bot kilitli')
 def load(self):
  with self.lock,closing(sqlite3.connect(self.path)) as c:return json.loads(c.execute('SELECT data FROM state WHERE id=1').fetchone()[0])
 def audit(self):
  try:
   with self.lock,closing(sqlite3.connect(self.path)) as c:
    c.execute('BEGIN')
    state=json.loads(c.execute('SELECT data FROM state WHERE id=1').fetchone()[0]);trades=_trade_rows(c)
    return audit_ledger(state,trades)
  except (sqlite3.Error,ValueError,TypeError,KeyError):return {'ok':False,'issues':['LEDGER_READ_ERROR'],'warnings':[],'scope':'paper_arithmetic_only'}
 def commit(self,state,events,trades,*,expected_state=None,candles=None,captured_at=None):
  payload=dumps(state); ev=[(e['time'],e['type'],e['detail']) for e in events]; tr=[(t['exit_time'],dumps(t)) for t in trades]
  with self.lock,closing(sqlite3.connect(self.path,timeout=5)) as c:
   with c:
    c.execute('BEGIN IMMEDIATE')
    prior=c.execute('SELECT data FROM state WHERE id=1').fetchone()
    if prior is None:raise RuntimeError('paper state missing')
    current=json.loads(prior[0])
    if expected_state is not None and current!=expected_state:raise RuntimeError('paper state changed since read')
    existing=_trade_rows(c)
    before=audit_ledger(current,existing)
    if not before['ok']:raise RuntimeError('existing paper ledger invalid: '+','.join(before['issues']))
    after=audit_ledger(state,existing+trades)
    if not after['ok']:raise RuntimeError('new paper ledger invalid: '+','.join(after['issues']))
    if candles is not None:
     if captured_at is None:raise ValueError('captured_at required')
     existing_last=c.execute('SELECT MAX(timestamp) FROM candles').fetchone()[0]
     for b in candles:
      old=c.execute('SELECT open,high,low,close,volume FROM candles WHERE timestamp=?',(b.timestamp,)).fetchone()
      values=(b.open,b.high,b.low,b.close,b.volume)
      if old is not None:
       if old!=values:raise RuntimeError('confirmed candle changed; do not overwrite')
       continue
      origin=('warmup' if existing_last is None else
              'observed' if current.get('last_bar') is not None and b.timestamp==current['last_bar']+60 else 'backfill')
      c.execute('INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)',(b.timestamp,*values,origin,captured_at))
    c.execute('UPDATE state SET data=? WHERE id=1',(payload,))
    c.executemany('INSERT INTO events (time,kind,detail) VALUES (?,?,?)',ev)
    c.executemany('INSERT INTO trades (time,data) VALUES (?,?)',tr)
 def latest(self):
  with self.lock,closing(sqlite3.connect(self.path)) as c:
   events=[{'id':r[0],'time':r[1],'type':r[2],'detail':r[3]} for r in c.execute('SELECT id,time,kind,detail FROM events ORDER BY id DESC LIMIT 30')]
   trades=[json.loads(r[0]) for r in c.execute('SELECT data FROM trades ORDER BY id DESC LIMIT 30')]
   return events,trades
 def candle_summary(self):
  with self.lock,closing(sqlite3.connect(self.path)) as c:
   n,first,last=c.execute('SELECT COUNT(*),MIN(timestamp),MAX(timestamp) FROM candles').fetchone()
   return {'count':n,'first_open':first,'last_open':last,'source':'OKX BTC-USDT-SWAP 1m','note':'seed/backfill/observed etiketleri CSV dışa aktarmada korunur'}
