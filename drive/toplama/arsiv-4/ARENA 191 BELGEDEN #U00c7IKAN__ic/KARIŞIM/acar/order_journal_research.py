"""Yalnız çevrimdışı araştırma emri/dolumu için ayrı SQLite günlüğü.
Borsa bağlantısı, gerçek emir, mevcut PAPER defterine yazma veya otomatik uzlaşma yoktur.
İptal ve rekonsiliasyon onayı burada çağıran tarafından verilen varsayımsal kanıttır.
"""
import json, os, re, sqlite3
from contextlib import closing
from decimal import Decimal, localcontext
from pathlib import Path
from .depth_research import dec, fmt

APP_ID=0x4143524A
SCHEMA_VERSION=1
STATES=('PENDING','OPEN','PARTIAL','CANCEL_PENDING','CANCELED','FILLED','UNCERTAIN')

def ident(x, name):
    if not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',x):
        raise ValueError('invalid '+name)
    return x

def _open(path, readonly=False):
    # mode=rw asla yeni veya eksik bir dosya oluşturmaz.
    return sqlite3.connect(Path(path).resolve().as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=5)

def _event(c,order_id,kind,payload):
    c.execute('INSERT INTO events(order_id,kind,payload) VALUES(?,?,?)',
              (order_id,kind,json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)))

def _order(c,order_id):
    row=c.execute('SELECT order_id,symbol,side,qty,filled,status FROM orders WHERE order_id=?',(order_id,)).fetchone()
    if row is None:raise ValueError('order not found')
    return dict(zip(('order_id','symbol','side','qty','filled','status'),row))

def _integrity(c,o):
    try:
        ident(o['order_id'],'order_id');ident(o['symbol'],'symbol')
        qty=dec(o['qty'],'quantity',positive=True);filled=dec(o['filled'],'filled',nonnegative=True)
        if o['side'] not in ('buy','sell') or o['status'] not in STATES:return False
        with localcontext() as ctx:
            ctx.prec=80
            total=Decimal(0)
            for fill_id,q,p,f in c.execute('SELECT fill_id,qty,price,fee FROM fills WHERE order_id=?',(o['order_id'],)):
                ident(fill_id,'fill_id');total+=dec(q,'fill quantity',positive=True)
                dec(p,'fill price',positive=True);dec(f,'fill fee',nonnegative=True)
            if total!=filled or filled>qty:return False
            if o['status'] in ('PENDING','OPEN') and filled!=0:return False
            if o['status']=='PARTIAL' and not 0<filled<qty:return False
            if o['status']=='FILLED' and filled!=qty:return False
            if o['status']=='CANCELED' and filled>=qty:return False
            return True
    except (ValueError,ArithmeticError):return False

def _guard(c,o):
    if not _integrity(c,o):raise ValueError('local journal integrity error; mutation refused')

class ResearchJournal:
    def __init__(self,path):
        self.path=Path(path).resolve()
        with closing(_open(self.path,True)) as c:
            if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or c.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION:
                raise ValueError('not an ACAR research journal')
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('journal integrity error')
            expected={'orders','fills','events'}
            if not expected.issubset({x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}):raise ValueError('research schema missing')
    @classmethod
    def create(cls,path):
        path=Path(path).resolve()
        # Kasıtlı olarak var olan dosyaya dokunmaz; mevcut paper.sqlite kullanılamaz.
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        try:
            with closing(_open(path)) as c:
                with c:
                    c.execute(f'PRAGMA application_id={APP_ID}')
                    c.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
                    c.execute("CREATE TABLE orders(order_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,side TEXT NOT NULL,qty TEXT NOT NULL,filled TEXT NOT NULL,status TEXT NOT NULL)")
                    c.execute("CREATE TABLE fills(fill_id TEXT PRIMARY KEY,order_id TEXT NOT NULL,qty TEXT NOT NULL,price TEXT NOT NULL,fee TEXT NOT NULL,FOREIGN KEY(order_id) REFERENCES orders(order_id))")
                    c.execute("CREATE TABLE events(id INTEGER PRIMARY KEY,order_id TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL)")
            return cls(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    def _transaction(self,operation):
        with closing(_open(self.path)) as c:
            c.execute('PRAGMA foreign_keys=ON')
            with c:
                c.execute('BEGIN IMMEDIATE')
                # Açılış sonrasında dosya değiştirildiyse başka deftere yazma.
                if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or c.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION:raise ValueError('journal identity changed')
                return operation(c)
    def submit(self,order_id,symbol,side,quantity):
        ident(order_id,'order_id');ident(symbol,'symbol')
        if side not in ('buy','sell'):raise ValueError('invalid side')
        q=fmt(dec(quantity,'quantity',positive=True))
        def op(c):
            old=c.execute('SELECT symbol,side,qty FROM orders WHERE order_id=?',(order_id,)).fetchone()
            if old:
                _guard(c,_order(c,order_id))
                if old!=(symbol,side,q):raise ValueError('conflicting order id')
                return _order(c,order_id)
            c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?)',(order_id,symbol,side,q,'0','PENDING'))
            _event(c,order_id,'SUBMIT',{'symbol':symbol,'side':side,'qty':q})
            return _order(c,order_id)
        return self._transaction(op)
    def acknowledge(self,order_id):
        ident(order_id,'order_id')
        def op(c):
            o=_order(c,order_id);_guard(c,o)
            if o['status'] in ('OPEN','PARTIAL','FILLED'):return o
            if o['status']!='PENDING':raise ValueError('acknowledgement invalid in this state')
            c.execute("UPDATE orders SET status='OPEN' WHERE order_id=?",(order_id,));_event(c,order_id,'ACK',{})
            return _order(c,order_id)
        return self._transaction(op)
    def record_fill(self,order_id,fill_id,quantity,price,fee):
        ident(order_id,'order_id');ident(fill_id,'fill_id')
        q=dec(quantity,'quantity',positive=True);p=dec(price,'price',positive=True);f=dec(fee,'fee',nonnegative=True)
        qstr,pstr,fstr=fmt(q),fmt(p),fmt(f)
        def op(c):
            o=_order(c,order_id);_guard(c,o)
            prior=c.execute('SELECT order_id,qty,price,fee FROM fills WHERE fill_id=?',(fill_id,)).fetchone()
            if prior:
                if prior!=(order_id,qstr,pstr,fstr):raise ValueError('conflicting fill id')
                return {'duplicate':True,'order':o}
            if o['status'] not in ('PENDING','OPEN','PARTIAL','CANCEL_PENDING','UNCERTAIN'):raise ValueError('fill rejected on terminal order')
            with localcontext() as ctx:
                ctx.prec=80
                total=Decimal(o['filled'])+q
                if total>Decimal(o['qty']):raise ValueError('overfill')
                # Bir iptal belirsizliği, dolum geldi diye ortadan kalkmaz.
                if o['status']=='UNCERTAIN':status='UNCERTAIN'
                elif total==Decimal(o['qty']):status='FILLED'
                elif o['status']=='CANCEL_PENDING':status='CANCEL_PENDING'
                else:status='PARTIAL'
                c.execute('INSERT INTO fills VALUES(?,?,?,?,?)',(fill_id,order_id,qstr,pstr,fstr))
                c.execute('UPDATE orders SET filled=?,status=? WHERE order_id=?',(fmt(total),status,order_id))
                _event(c,order_id,'FILL',{'fill_id':fill_id,'qty':qstr,'price':pstr,'fee':fstr})
            return {'duplicate':False,'order':_order(c,order_id)}
        return self._transaction(op)
    def request_cancel(self,order_id):
        ident(order_id,'order_id')
        def op(c):
            o=_order(c,order_id);_guard(c,o)
            if o['status']=='CANCEL_PENDING':return o
            if o['status'] not in ('PENDING','OPEN','PARTIAL'):raise ValueError('cancel request invalid in this state')
            c.execute("UPDATE orders SET status='CANCEL_PENDING' WHERE order_id=?",(order_id,));_event(c,order_id,'CANCEL_REQUEST',{})
            return _order(c,order_id)
        return self._transaction(op)
    def mark_uncertain(self,order_id):
        ident(order_id,'order_id')
        def op(c):
            o=_order(c,order_id);_guard(c,o)
            if o['status']=='UNCERTAIN':return o
            if o['status'] in ('CANCELED','FILLED'):raise ValueError('terminal order')
            c.execute("UPDATE orders SET status='UNCERTAIN' WHERE order_id=?",(order_id,));_event(c,order_id,'UNCERTAIN',{})
            return _order(c,order_id)
        return self._transaction(op)
    def reconcile_final(self,order_id,final_status,observed_total):
        """Yalnız doğrulanmış kabul edilen nihai durumu uzlaştır; fark varsa kilitle.
        Gerçek bir dış kaynaktan veri getirmez veya kanıtın güvenilirliğini doğrulamaz.
        """
        ident(order_id,'order_id')
        if final_status not in ('CANCELED','FILLED'):raise ValueError('invalid final state')
        total=dec(observed_total,'observed_total',nonnegative=True)
        def op(c):
            o=_order(c,order_id);_guard(c,o);local=Decimal(o['filled']);qty=Decimal(o['qty'])
            if o['status'] in ('CANCELED','FILLED'):
                if o['status']==final_status and total==local:return o
                raise ValueError('terminal reconciliation conflict')
            if o['status'] not in ('CANCEL_PENDING','UNCERTAIN'):raise ValueError('final reconciliation requires cancellation or uncertainty')
            if total!=local or total>qty or (final_status=='FILLED' and total!=qty) or (final_status=='CANCELED' and total>=qty):
                c.execute("UPDATE orders SET status='UNCERTAIN' WHERE order_id=?",(order_id,))
                _event(c,order_id,'RECONCILIATION_MISMATCH',{'reported_total':fmt(total),'reported_status':final_status})
            else:
                c.execute('UPDATE orders SET status=? WHERE order_id=?',(final_status,order_id))
                _event(c,order_id,'RECONCILED_FINAL',{'total':fmt(total),'status':final_status})
            return _order(c,order_id)
        return self._transaction(op)
    def snapshot(self,order_id):
        ident(order_id,'order_id')
        with closing(_open(self.path,True)) as c:
            c.execute('BEGIN')
            o=_order(c,order_id)
            fills=[dict(zip(('fill_id','qty','price','fee'),x)) for x in c.execute('SELECT fill_id,qty,price,fee FROM fills WHERE order_id=? ORDER BY rowid',(order_id,))]
            events=[{'kind':k,'payload':json.loads(p)} for k,p in c.execute('SELECT kind,payload FROM events WHERE order_id=? ORDER BY id',(order_id,))]
            with localcontext() as ctx:
                ctx.prec=80
                actual=sum((Decimal(x['qty']) for x in fills),Decimal(0))
                notional=sum((Decimal(x['qty'])*Decimal(x['price']) for x in fills),Decimal(0))
                fees=sum((Decimal(x['fee']) for x in fills),Decimal(0))
                ok=_integrity(c,o)
                return {'order':o,'fills':fills,'events':events,'integrity_ok':ok,'filled_notional':fmt(notional),'fees':fmt(fees),
                        'warning':'Araştırma defteri; harici borsa ile doğrulanmış mutabakat değildir.'}
