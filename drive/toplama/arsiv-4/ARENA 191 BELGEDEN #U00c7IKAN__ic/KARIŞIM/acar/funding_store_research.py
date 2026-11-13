"""İzole funding araştırma defteri. PAPER SQLite defterinin migrasyonu değildir.
Dış funding geçmişi yoktur; olaylar çağıran tarafından sağlanır ve kanıtlanmaz.
"""
import json,math,os,sqlite3
from contextlib import closing
from pathlib import Path
from .funding_research import Settlement,apply_settlement,_finite

APP_ID=0x4143464A
VERSION=1

def _connect(path,read_only=False):
    return sqlite3.connect(Path(path).resolve().as_uri()+('?mode=ro' if read_only else '?mode=rw'),uri=True,timeout=5)

def _pack(x):return json.dumps(x,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)

def _read(c):
    row=c.execute('SELECT initial_cash,cash FROM account WHERE id=1').fetchone()
    if not row or not all(_finite(x) for x in row) or row[0]<=0:raise ValueError('account invalid')
    initial,cash=row;applied={};deltas=[]
    for key,raw in c.execute('SELECT key,data FROM settlements ORDER BY rowid'):
        try:
            data=json.loads(raw);payload=data['payload'];event=Settlement(**payload['event']);position=payload['position']
            _, outcome=apply_settlement({'cash':0.0,'applied':{}},event,position)
            delta=data['cash_delta']
            if outcome['key']!=key or not _finite(delta) or delta!=outcome['cash_delta']:raise ValueError('event mismatch')
            if not isinstance(data,dict) or set(data)!={'payload','cash_delta'}:raise ValueError('invalid event')
            applied[key]=data;deltas.append(delta)
        except (KeyError,TypeError,ValueError,OverflowError) as e:raise ValueError('invalid funding record') from e
    try:expected=math.fsum([initial]+deltas)
    except (OverflowError,ValueError):raise ValueError('nonfinite ledger') from None
    if not math.isfinite(expected) or not math.isclose(cash,expected,rel_tol=1e-12,abs_tol=1e-8):raise ValueError('funding cash mismatch')
    return {'initial_cash':initial,'cash':cash,'applied':applied}

class FundingResearchStore:
    def __init__(self,path):
        self.path=Path(path).resolve()
        with closing(_connect(self.path,True)) as c:
            if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or c.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise ValueError('not funding research store')
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('SQLite corrupt')
            _read(c)
    @classmethod
    def create(cls,path,initial_cash):
        if not _finite(initial_cash) or initial_cash<=0:raise ValueError('invalid initial cash')
        path=Path(path).resolve();fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        try:
            with closing(_connect(path)) as c:
                with c:
                    c.execute(f'PRAGMA application_id={APP_ID}');c.execute(f'PRAGMA user_version={VERSION}')
                    c.execute('CREATE TABLE account(id INTEGER PRIMARY KEY CHECK(id=1),initial_cash REAL NOT NULL,cash REAL NOT NULL)')
                    c.execute('CREATE TABLE settlements(key TEXT PRIMARY KEY,data TEXT NOT NULL)')
                    c.execute('INSERT INTO account VALUES(1,?,?)',(initial_cash,initial_cash))
            return cls(path)
        except Exception:
            path.unlink(missing_ok=True);raise
    def snapshot(self):
        with closing(_connect(self.path,True)) as c:
            c.execute('BEGIN');a=_read(c)
            return {'initial_cash':a['initial_cash'],'cash':a['cash'],'settlement_count':len(a['applied']),
                    'scope':'isolated_funding_research','notice':'Girdi verilerinin dış kaynağı veya borsa paritesi doğrulanmaz.'}
    def settle(self,event,position):
        with closing(_connect(self.path)) as c:
            with c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or c.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise ValueError('store identity changed')
                before=_read(c)
                after,result=apply_settlement({'cash':before['cash'],'applied':before['applied']},event,position)
                if not result['applied']:return result
                c.execute('INSERT INTO settlements VALUES(?,?)',(result['key'],_pack(after['applied'][result['key']])))
                c.execute('UPDATE account SET cash=? WHERE id=1',(after['cash'],))
                _read(c)  # hatalı defter tek transaction içinde geri alınır
                return result
