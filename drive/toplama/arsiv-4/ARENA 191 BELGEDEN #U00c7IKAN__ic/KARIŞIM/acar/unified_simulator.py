"""ÇOKLU PİYASA ÇEVRİMDIŞI PAPER SİMÜLATÖRÜ — gerçek emir içermez.
Ayrı bir defter kullanır; eski PAPER defterine ve ağ kaynağına bağlı değildir.
Tüm fiyatlar/sözleşme kuralları/settlement verileri çağıran tarafından verilir.
İzole teminat ve likidasyon eşiği basit bir MODELdir, borsa formülü değildir.
"""
from contextlib import closing
from decimal import Decimal,localcontext
from hashlib import sha256
from pathlib import Path
import json,os,sqlite3,copy
from dataclasses import replace
from datetime import datetime,timezone
from .depth_research import MarketRules,estimate_depth,dec,fmt
from .order_journal_research import ident

APP_ID=0x4143554E
VERSION=4
D=Decimal
QUANTUM=D('0.000000000000000001')

def quant(x):return x.quantize(QUANTUM)

def pack(value):return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)
def connect(path,ro=False):return sqlite3.connect(Path(path).resolve().as_uri()+('?mode=ro' if ro else '?mode=rw'),uri=True,timeout=10)
def number(x,name,positive=False,nonnegative=False):return dec(x,name,positive=positive,nonnegative=nonnegative)

def _stored_number(value,name,*,positive=False,nonnegative=False):
    try:
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):raise ValueError('invalid '+name)
        result=D(str(value))
        if not result.is_finite() or len(result.as_tuple().digits)>80 or abs(result.as_tuple().exponent)>80:raise ValueError('invalid '+name)
        if positive and result<=0 or nonnegative and result<0:raise ValueError('invalid '+name)
        return result
    except (ArithmeticError,TypeError):raise ValueError('invalid '+name) from None

def _state(c):
    row=c.execute('SELECT value FROM state WHERE id=1').fetchone()
    if not row:raise ValueError('missing state')
    try:
        s=json.loads(row[0])
        if not isinstance(s,dict) or s.get('version')!=VERSION or not isinstance(s.get('positions'),dict):raise ValueError('invalid state')
        if type(s.get('entry_locked')) is not bool or type(s.get('daily_halt')) is not bool or not isinstance(s.get('lock_reason'),str):raise ValueError('invalid locks')
        if type(s.get('last_time')) is not int or not 0<=s['last_time']<=253402300799 or type(s.get('max_age')) is not int or not 1<=s['max_age']<=3600:raise ValueError('invalid clock')
        settings=s.get('settings')
        expected_settings={'max_positions':4,'max_position_notional':'250','max_gross_notional':'500','per_trade_risk':'0.005','total_risk':'0.02','max_leverage':'3','maintenance_rate':'0.005','fee_rate':'0.0005','max_spread_bps':'30','daily_loss_fraction':'0.02'}
        if settings!=expected_settings:raise ValueError('risk configuration changed unexpectedly')
        if s.get('day') is not None:
            if not isinstance(s['day'],str):raise ValueError('invalid day')
            datetime.strptime(s['day'],'%Y-%m-%d')
        _stored_number(s['day_start_equity'],'day_start_equity')
        cash=_stored_number(s['cash'],'cash');initial=_stored_number(s['initial_cash'],'initial_cash',positive=True)
        with localcontext() as ctx:
            ctx.prec=80
            margins=D(0);ids=set()
            for symbol,p in s['positions'].items():
                ident(symbol,'symbol')
                if not isinstance(p,dict) or symbol!=p.get('symbol') or p.get('side') not in ('long','short') or type(p.get('execution_uncertain')) is not bool:raise ValueError('invalid position')
                if type(p.get('funding_price_uncertain',False)) is not bool or (p.get('funding_price_uncertain',False) and not p['execution_uncertain']):raise ValueError('invalid funding uncertainty flag')
                if not isinstance(p.get('rules'),dict) or set(p['rules'])!={'symbol','qty_step','price_tick','min_qty','min_notional'} or p['rules']['symbol']!=symbol:raise ValueError('invalid saved market rules')
                digest=p.get('market_spec_fingerprint')
                if digest is not None and (not isinstance(digest,str) or len(digest)!=64 or any(x not in '0123456789abcdef' for x in digest)):raise ValueError('invalid market specification hash')
                ident(p['id'],'position id')
                if p['id'] in ids:raise ValueError('duplicate position id')
                ids.add(p['id'])
                qty=_stored_number(p['qty'],'qty',positive=True);entry=_stored_number(p['entry'],'entry',positive=True)
                stop=_stored_number(p['stop'],'stop',positive=True);target=_stored_number(p['target'],'target',positive=True)
                initial_stop=_stored_number(p['initial_stop'],'initial_stop',positive=True);initial_entry=_stored_number(p['initial_entry'],'initial_entry',positive=True)
                initial_r=_stored_number(p['initial_r'],'initial_r',positive=True)
                trigger=_stored_number(p['entry_stop_at_r'],'entry_stop_at_r',nonnegative=True);_stored_number(p['trailing_distance'],'trailing_distance',nonnegative=True)
                if initial_r!=abs(initial_entry-initial_stop) or trigger>D(100):raise ValueError('invalid exit config')
                _stored_number(p['mark'],'mark',positive=True)
                margin=_stored_number(p['margin'],'margin');margins+=margin
                leverage=_stored_number(p['leverage'],'leverage',positive=True)
                if leverage>D(settings['max_leverage']):raise ValueError('invalid leverage')
                sign=D(1 if p['side']=='long' else -1)
                if sign*(initial_entry-initial_stop)<=0 or sign*(target-entry)<=0 or sign*(target-stop)<=0:raise ValueError('invalid position levels')
                if any(type(p.get(k)) is not int for k in ('mark_at','last_change','next_funding')):raise ValueError('invalid position time')
                if not 0<=p['mark_at']<=s['last_time'] or not 0<=p['last_change']<=s['last_time'] or p['next_funding']<=p['last_change']:raise ValueError('invalid position time')
            actual=cash+margins;amounts=[]
            for kind,rawdelta,rawdetail in c.execute('SELECT kind,delta,detail FROM ledger ORDER BY seq'):
                delta=_stored_number(rawdelta,'ledger delta');detail=json.loads(rawdetail)
                if not isinstance(detail,dict):raise ValueError('invalid ledger detail')
                if kind in ('OPEN','ADD'):
                    derived=-_stored_number(detail['fee'],'fee',nonnegative=True)
                elif kind=='CLOSE':
                    derived=_stored_number(detail['gross_pnl'],'gross_pnl')-_stored_number(detail['fee'],'fee',nonnegative=True)
                elif kind=='FUNDING':derived=_stored_number(detail['funding_delta'],'funding_delta')
                elif kind in ('ENTRY_LOCK','ENTRY_UNLOCK','DAILY_HALT','EXIT_CONFIG','STOP_UPDATE','MONITORING_GAP'):derived=D(0)
                else:raise ValueError('unknown ledger event')
                if delta!=derived:raise ValueError('ledger event mismatch')
                amounts.append(delta)
            expected=initial+sum(amounts,D(0))
            if actual!=expected:raise ValueError('unified ledger mismatch')
        return s
    except (KeyError,TypeError,ArithmeticError,json.JSONDecodeError) as e:
        raise ValueError('invalid unified ledger/state') from e

def _event(c,kind,delta,detail):
    c.execute('INSERT INTO ledger(kind,delta,detail) VALUES(?,?,?)',(kind,fmt(delta),pack(detail)))
    # Yerel bildirim kuyruğu, dış servis bağlantısı değildir.
    c.execute('INSERT INTO notifications(kind,detail) VALUES(?,?)',(kind,pack(detail)))

def _condition(s,p,px,now):
    sign=D(1 if p['side']=='long' else -1);qty=D(p['qty'])
    isolated=D(p['margin'])+sign*(px-D(p['entry']))*qty
    maintenance=px*qty*D(s['settings']['maintenance_rate'])
    if now>=p['next_funding']:status='FUNDING_DUE_UNKNOWN'
    elif isolated<=maintenance:status='LIQUIDATION_MODEL'
    elif sign*(px-D(p['stop']))<=0:status='STOP'
    elif sign*(px-D(p['target']))>=0:status='TARGET'
    else:status='NORMAL'
    return status,isolated,maintenance

def _fresh_marks(s,now):
    for p in s['positions'].values():
        if p.get('execution_uncertain'):raise ValueError('position monitoring uncertain')
        if now-int(p['mark_at'])>s['max_age'] or int(p['mark_at'])>now:raise ValueError('position mark stale or future')
        if now>=p['next_funding']:raise ValueError('unsettled funding; settle before trading')
        if _condition(s,p,D(p['mark']),now)[0]!='NORMAL':raise ValueError('protective exit requires attention')

def _equity(s):
    eq=D(s['cash'])
    for p in s['positions'].values():
        sign=D(1 if p['side']=='long' else -1)
        eq+=D(p['margin'])+sign*(D(p['mark'])-D(p['entry']))*D(p['qty'])
    return eq

def _daily_update(c,s,now):
    """UTC günü için ilk taze gözlemde açılış equity; eksik funding/mark'ta bekle."""
    for p in s['positions'].values():
        if p.get('execution_uncertain') or p['mark_at']>now or now-p['mark_at']>s['max_age'] or now>=p['next_funding']:
            return
    day=datetime.fromtimestamp(now,timezone.utc).date().isoformat();equity=_equity(s)
    if s['day']!=day:
        s['day']=day;s['day_start_equity']=fmt(equity);s['daily_halt']=False
    start=D(s['day_start_equity']);limit=D(s['settings']['daily_loss_fraction'])
    if not s['daily_halt'] and (start<=0 or equity<=start*(D(1)-limit)):
        s['daily_halt']=True
        _event(c,'DAILY_HALT',D(0),{'day':day,'start_equity':fmt(start),'equity':fmt(equity)})

def _fill(estimate):
    fills=estimate['levels'];qty=sum((D(x['qty']) for x in fills),D(0));notional=sum((D(x['qty'])*D(x['price']) for x in fills),D(0))
    return qty,notional

def _check_time(s,now):
    if type(now) is not int or now<0 or now>253402300799 or now<s['last_time']:raise ValueError('time must be monotonic integer seconds')
    s['last_time']=now

def _note_gap(c,s,p,now):
    # Kesinti arası stop/fill yolunu uydurma. Pozisyon kapanana kadar belirsizlik kalıcıdır.
    if now-p['mark_at']>s['max_age'] and not p['execution_uncertain']:
        p['execution_uncertain']=True;s['entry_locked']=True;s['lock_reason']='MONITORING_GAP'
        _event(c,'MONITORING_GAP',D(0),{'symbol':p['symbol'],'last_mark_at':p['mark_at'],'detected_at':now})

def _observed(book,now,max_age):
    if not isinstance(book,dict):raise ValueError('book unknown')
    ts=book.get('observed_at')
    if type(ts) is not int or ts<0 or ts>now or now-ts>max_age:raise ValueError('book timestamp stale or future')
    return ts

def _book_identity(c,symbol,book_id):
    ident(book_id,'book_id')
    # Aynı snapshot birden çok kez sınırsız likidite gibi kullanılamaz.
    if c.execute('SELECT 1 FROM used_books WHERE symbol=? AND book_id=?',(symbol,book_id)).fetchone():raise ValueError('book snapshot already consumed')
    c.execute('INSERT INTO used_books VALUES(?,?)',(symbol,book_id))

class UnifiedSimulator:
    """Bir kasada çoklu simge, IOC kısmi dolum, funding ve basit izole marj.
    İşlemler bir SQLite transaction; otoritatif dış borsa durumu söz konusu değil.
    """
    def __init__(self,path):
        self.path=Path(path).resolve()
        with closing(connect(self.path,True)) as c:
            if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID:raise ValueError('not a unified simulator database')
            if c.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise ValueError('unsupported unified schema; no automatic migration')
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('database corrupt')
            c.execute('BEGIN');_state(c)
    @classmethod
    def create(cls,path,initial_cash='1000',max_age=30):
        initial=number(initial_cash,'initial_cash',positive=True)
        if type(max_age) is not int or not 1<=max_age<=3600:raise ValueError('invalid max_age')
        path=Path(path).resolve();fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        try:
            s={'version':VERSION,'initial_cash':fmt(initial),'cash':fmt(initial),'positions':{},'last_time':0,'max_age':max_age,
               'entry_locked':False,'lock_reason':'','day':None,'day_start_equity':fmt(initial),'daily_halt':False,'settings':{'max_positions':4,'max_position_notional':'250','max_gross_notional':'500','per_trade_risk':'0.005','total_risk':'0.02','max_leverage':'3','maintenance_rate':'0.005','fee_rate':'0.0005','max_spread_bps':'30','daily_loss_fraction':'0.02'}}
            with closing(connect(path)) as c:
                with c:
                    c.execute(f'PRAGMA application_id={APP_ID}');c.execute(f'PRAGMA user_version={VERSION}')
                    c.execute('CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
                    c.execute('CREATE TABLE ledger(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,delta TEXT NOT NULL,detail TEXT NOT NULL)')
                    c.execute('CREATE TABLE commands(id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,result TEXT NOT NULL)')
                    c.execute('CREATE TABLE used_books(symbol TEXT NOT NULL,book_id TEXT NOT NULL,PRIMARY KEY(symbol,book_id))')
                    c.execute('CREATE TABLE settlements(symbol TEXT NOT NULL,settlement_ts INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(symbol,settlement_ts))')
                    c.execute('CREATE TABLE notifications(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,detail TEXT NOT NULL)')
                    c.execute('CREATE TABLE notification_delivery(seq INTEGER PRIMARY KEY,state TEXT NOT NULL,attempt_id TEXT,FOREIGN KEY(seq) REFERENCES notifications(seq))')
                    c.execute('CREATE TABLE delivery_events(id INTEGER PRIMARY KEY,notification_seq INTEGER NOT NULL,action TEXT NOT NULL,attempt_id TEXT,FOREIGN KEY(notification_seq) REFERENCES notifications(seq))')
                    c.execute('INSERT INTO state VALUES(1,?)',(pack(s),))
            return cls(path)
        except Exception:
            path.unlink(missing_ok=True);raise
    def _command(self,command_id,payload,fn):
        ident(command_id,'command_id');request_hash=sha256(pack(payload).encode()).hexdigest()
        with closing(connect(self.path)) as c:
            with c,localcontext() as ctx:
                ctx.prec=80;c.execute('BEGIN IMMEDIATE')
                if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or c.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise ValueError('database identity changed')
                s=_state(c)
                prior=c.execute('SELECT request_hash,result FROM commands WHERE id=?',(command_id,)).fetchone()
                if prior:
                    if prior[0]!=request_hash:raise ValueError('command id conflict')
                    return json.loads(prior[1])
                result=fn(c,s);c.execute('UPDATE state SET value=? WHERE id=1',(pack(s),))
                _state(c)  # tüm parasal eşitlikleri commit öncesinde doğrula
                c.execute('INSERT INTO commands VALUES(?,?,?)',(command_id,request_hash,pack(result)))
                return result
    def command_result(self,command_id):
        ident(command_id,'command_id')
        with closing(connect(self.path,True)) as c:
            c.execute('BEGIN');_state(c)
            row=c.execute('SELECT result FROM commands WHERE id=?',(command_id,)).fetchone()
            return json.loads(row[0]) if row else None
    def snapshot(self):
        with closing(connect(self.path,True)) as c,localcontext() as ctx:
            ctx.prec=80;c.execute('BEGIN');s=_state(c)
            return {'state':s,'equity_at_last_marks':fmt(_equity(s)),
                'ledger':[{'kind':k,'delta':d,'detail':json.loads(v)} for k,d,v in c.execute('SELECT kind,delta,detail FROM ledger ORDER BY seq')],
                'notifications':[{'kind':k,'detail':json.loads(v)} for k,v in c.execute('SELECT kind,detail FROM notifications ORDER BY seq')],
                'warning':'Çevrimdışı simülasyon: son marklar bayat olabilir, likidasyon basitleştirilmiştir.'}
    def record_signal_skip(self,command_id,*,symbol,now,reason,request_fingerprint,extra=None):
        """Hiç işlem açılmasa bile alınmış sinyal olayının saati kalıcılaşır."""
        ident(symbol,'symbol')
        if not isinstance(reason,str) or not reason or len(reason)>80:raise ValueError('invalid skip reason')
        if not isinstance(request_fingerprint,str) or len(request_fingerprint)!=64 or any(x not in '0123456789abcdef' for x in request_fingerprint):raise ValueError('invalid fingerprint')
        if extra is None:extra={}
        if not isinstance(extra,dict):raise ValueError('invalid extra')
        payload={'type':'signal_skip','symbol':symbol,'now':now,'reason':reason,'fingerprint':request_fingerprint,'extra':extra}
        def run(c,s):
            _check_time(s,now);_daily_update(c,s,now)
            return {'action':'NO_TRADE','reason':reason,**extra}
        return self._command(command_id,payload,run)
    def mark(self,command_id,symbol,price,now,observed_at=None):
        ident(symbol,'symbol');px=number(price,'mark',positive=True)
        observed_at=now if observed_at is None else observed_at
        payload={'type':'mark','symbol':symbol,'price':fmt(px),'now':now,'observed_at':observed_at}
        def run(c,s):
            _check_time(s,now)
            p=s['positions'].get(symbol)
            if not p:raise ValueError('position missing')
            if type(observed_at) is not int or observed_at<0 or observed_at>now or now-observed_at>s['max_age']:raise ValueError('mark stale or future')
            if observed_at<p['mark_at']:raise ValueError('mark observation moved backwards')
            _note_gap(c,s,p,now)
            p['mark']=fmt(px);p['mark_at']=observed_at
            _daily_update(c,s,now)
            # Liquidation olayının yürütülmesi yalnız monitor() içinde açık defterle yapılır.
            return {'marked':symbol,'price':fmt(px)}
        return self._command(command_id,payload,run)
    def open_position(self,command_id,*,symbol,side,quantity,stop,target,leverage,next_funding,now,book_id,book,rules,expected_positions_hash=None,signal_fingerprint=None,market_spec_fingerprint=None):
        ident(symbol,'symbol')
        if side not in ('long','short'):raise ValueError('invalid side')
        if not isinstance(rules,MarketRules):raise ValueError('rules unknown')
        if signal_fingerprint is not None and (not isinstance(signal_fingerprint,str) or len(signal_fingerprint)!=64 or any(x not in '0123456789abcdef' for x in signal_fingerprint)):raise ValueError('invalid signal fingerprint')
        if market_spec_fingerprint is not None and (not isinstance(market_spec_fingerprint,str) or len(market_spec_fingerprint)!=64 or any(x not in '0123456789abcdef' for x in market_spec_fingerprint)):raise ValueError('invalid market specification hash')
        q=number(quantity,'quantity',positive=True);stop=number(stop,'stop',positive=True);target=number(target,'target',positive=True);lev=number(leverage,'leverage',positive=True)
        payload={'type':'open','symbol':symbol,'side':side,'qty':fmt(q),'stop':fmt(stop),'target':fmt(target),'leverage':fmt(lev),'next_funding':next_funding,'now':now,'book_id':book_id,'book':book,'rules':rules.__dict__,'expected_positions_hash':expected_positions_hash,'signal_fingerprint':signal_fingerprint,'market_spec_fingerprint':market_spec_fingerprint}
        def run(c,s):
            _check_time(s,now)
            if expected_positions_hash is not None and sha256(pack(s['positions']).encode()).hexdigest()!=expected_positions_hash:raise ValueError('portfolio changed since correlation check')
            if s['entry_locked']:raise ValueError('entries locked')
            _fresh_marks(s,now);_daily_update(c,s,now)
            if s['daily_halt']:return {'status':'BLOCKED','reason':'DAILY_LOSS_LIMIT'}
            if symbol in s['positions']:raise ValueError('one position per symbol')
            cfg=s['settings'];equity=_equity(s)
            if equity<=0 or len(s['positions'])>=cfg['max_positions'] or lev> D(cfg['max_leverage']):raise ValueError('position/equity/leverage limit')
            if type(next_funding) is not int or next_funding<=now:raise ValueError('future funding schedule required')
            observed=_observed(book,now,s['max_age'])
            _book_identity(c,symbol,book_id)
            estimate=estimate_depth(book=book,rules=rules,side='buy' if side=='long' else 'sell',quantity=fmt(q),now=now,max_age=s['max_age'],fee_rate=cfg['fee_rate'])
            if rules.symbol!=symbol:raise ValueError('symbol mismatch')
            bid=D(str(book['bids'][0][0]));ask=D(str(book['asks'][0][0]));mid=(bid+ask)/2
            if (ask-bid)*D(10000)/mid>D(cfg['max_spread_bps']):raise ValueError('spread too wide')
            filled,notional=_fill(estimate)
            if not filled:raise ValueError('no executable liquidity')
            entry=quant(notional/filled);sign=D(1 if side=='long' else -1)
            if sign*(entry-stop)<=0 or sign*(target-entry)<=0:raise ValueError('invalid stop/target')
            risk=filled*(abs(entry-stop)+entry*D(cfg['fee_rate'])*2)
            gross=notional+sum((D(p['qty'])*D(p['mark']) for p in s['positions'].values()),D(0))
            oldrisk=sum((D(p['qty'])*(max(D(0),(D(p['entry'])-D(p['stop']))*D(1 if p['side']=='long' else -1))+D(p['entry'])*D(cfg['fee_rate'])*2) for p in s['positions'].values()),D(0))
            if notional>D(cfg['max_position_notional']) or gross>D(cfg['max_gross_notional']) or risk>equity*D(cfg['per_trade_risk']) or oldrisk+risk>equity*D(cfg['total_risk']):raise ValueError('portfolio risk limit')
            margin=quant(notional/lev);fee=notional*D(cfg['fee_rate'])
            if margin+fee>D(s['cash']):raise ValueError('insufficient free cash')
            s['cash']=fmt(D(s['cash'])-margin-fee)
            s['positions'][symbol]={'symbol':symbol,'rules':rules.__dict__,'market_spec_fingerprint':market_spec_fingerprint,'id':command_id,'side':side,'qty':fmt(filled),'entry':fmt(entry),'execution_uncertain':False,'initial_entry':fmt(entry),'initial_stop':fmt(stop),'initial_r':fmt(abs(entry-stop)),'entry_stop_at_r':'0','trailing_distance':'0','margin':fmt(margin),'stop':fmt(stop),'target':fmt(target),'mark':fmt((D(str(book['bids'][0][0]))+D(str(book['asks'][0][0])))/2),'mark_at':observed,'leverage':fmt(lev),'next_funding':next_funding,'last_change':now}
            if _condition(s,s['positions'][symbol],mid,now)[0]!='NORMAL':raise ValueError('entry violates current protective levels')
            detail={'symbol':symbol,'side':side,'requested':fmt(q),'filled':fmt(filled),'remaining_canceled':fmt(q-filled),'notional':fmt(notional),'fee':fmt(fee),'book_id':book_id,'signal_fingerprint':signal_fingerprint}
            _event(c,'OPEN',-fee,detail);_daily_update(c,s,now)
            return {'status':'FILLED' if filled==q else 'PARTIAL_IOC','position':s['positions'][symbol],**detail}
        return self._command(command_id,payload,run)
    def add_position(self,command_id,*,symbol,quantity,now,book_id,book,rules):
        """Aynı yönde, orijinal stop ile sınırlı araştırma DCA/piramitleme.
        Ekleme, ek pozisyonun değil toplam pozisyonun risk sınırına tabidir.
        """
        ident(symbol,'symbol');q=number(quantity,'quantity',positive=True)
        if not isinstance(rules,MarketRules):raise ValueError('rules unknown')
        payload={'type':'add','symbol':symbol,'qty':fmt(q),'now':now,'book_id':book_id,'book':book,'rules':rules.__dict__}
        def run(c,s):
            _check_time(s,now)
            if s['entry_locked']:raise ValueError('entries locked')
            _fresh_marks(s,now);_daily_update(c,s,now)
            if s['daily_halt']:return {'status':'BLOCKED','reason':'DAILY_LOSS_LIMIT'}
            p=s['positions'].get(symbol)
            if not p:raise ValueError('position missing')
            if rules.__dict__!=p['rules']:raise ValueError('market rules changed; reconciliation required')
            cfg=s['settings'];equity=_equity(s)
            if equity<=0:raise ValueError('equity invalid')
            observed=_observed(book,now,s['max_age'])
            if observed<p['mark_at']:raise ValueError('book observation moved backwards')
            _book_identity(c,symbol,book_id)
            estimate=estimate_depth(book=book,rules=rules,side='buy' if p['side']=='long' else 'sell',quantity=fmt(q),now=now,max_age=s['max_age'],fee_rate=cfg['fee_rate'])
            if rules.symbol!=symbol:raise ValueError('symbol mismatch')
            bid=D(str(book['bids'][0][0]));ask=D(str(book['asks'][0][0]));mid=(bid+ask)/2
            if (ask-bid)*D(10000)/mid>D(cfg['max_spread_bps']):raise ValueError('spread too wide')
            filled,notional=_fill(estimate)
            if not filled:raise ValueError('no executable liquidity')
            oldqty=D(p['qty']);totalqty=oldqty+filled
            entry=quant((oldqty*D(p['entry'])+notional)/totalqty);sign=D(1 if p['side']=='long' else -1)
            if sign*(entry-D(p['stop']))<=0 or sign*(D(p['target'])-entry)<=0:raise ValueError('invalid aggregated stop/target')
            new_notional=totalqty*mid
            gross=new_notional+sum((D(other['qty'])*D(other['mark']) for name,other in s['positions'].items() if name!=symbol),D(0))
            newrisk=totalqty*(max(D(0),sign*(entry-D(p['stop'])))+entry*D(cfg['fee_rate'])*2)
            oldrisk=sum((D(other['qty'])*(max(D(0),(D(other['entry'])-D(other['stop']))*D(1 if other['side']=='long' else -1))+D(other['entry'])*D(cfg['fee_rate'])*2) for name,other in s['positions'].items() if name!=symbol),D(0))
            if new_notional>D(cfg['max_position_notional']) or gross>D(cfg['max_gross_notional']) or newrisk>equity*D(cfg['per_trade_risk']) or oldrisk+newrisk>equity*D(cfg['total_risk']):raise ValueError('portfolio risk limit')
            extra_margin=quant(notional/D(p['leverage']));fee=notional*D(cfg['fee_rate'])
            if extra_margin+fee>D(s['cash']):raise ValueError('insufficient free cash')
            s['cash']=fmt(D(s['cash'])-extra_margin-fee);p['qty']=fmt(totalqty);p['entry']=fmt(entry)
            p['margin']=fmt(D(p['margin'])+extra_margin);p['mark']=fmt(mid);p['mark_at']=observed;p['last_change']=now
            if _condition(s,p,mid,now)[0]!='NORMAL':raise ValueError('addition violates protective levels')
            detail={'symbol':symbol,'requested':fmt(q),'filled':fmt(filled),'remaining_canceled':fmt(q-filled),'new_qty':fmt(totalqty),'new_entry':fmt(entry),'fee':fmt(fee),'book_id':book_id}
            _event(c,'ADD',-fee,detail);_daily_update(c,s,now)
            return {'status':'FILLED' if filled==q else 'PARTIAL_IOC',**detail}
        return self._command(command_id,payload,run)
    def configure_exit(self,command_id,*,symbol,entry_stop_at_r,trailing_distance,now):
        """Stop eşik ayarı: giriş-fiyat stopu ücretleri karşılamayabilir.
        Ayarlar yalnız sonraki book olaylarında geçerli olur.
        """
        ident(symbol,'symbol')
        trigger=number(entry_stop_at_r,'entry_stop_at_r',nonnegative=True);trail=number(trailing_distance,'trailing_distance',nonnegative=True)
        if trigger>D(100):raise ValueError('entry stop threshold too high')
        payload={'type':'exit_config','symbol':symbol,'entry_stop_at_r':fmt(trigger),'trailing_distance':fmt(trail),'now':now}
        def run(c,s):
            _check_time(s,now);p=s['positions'].get(symbol)
            if not p:raise ValueError('position missing')
            _fresh_marks(s,now)
            p['entry_stop_at_r']=fmt(trigger);p['trailing_distance']=fmt(trail)
            detail={'symbol':symbol,'entry_stop_at_r':fmt(trigger),'trailing_distance':fmt(trail),'notice':'giriş fiyatı stopu ücretleri karşılamayabilir'}
            _event(c,'EXIT_CONFIG',D(0),detail)
            return {'status':'CONFIGURED',**detail}
        return self._command(command_id,payload,run)
    def settle_funding(self,command_id,*,symbol,settlement_ts,finalized_at,rate,mark_price,next_funding,now,estimated_price=False):
        ident(symbol,'symbol');rate=number(rate,'rate');mark=number(mark_price,'mark_price',positive=True)
        if abs(rate)>1:raise ValueError('invalid funding rate')
        if type(estimated_price) is not bool:raise ValueError('invalid estimated price flag')
        payload={'type':'funding','symbol':symbol,'settlement_ts':settlement_ts,'finalized_at':finalized_at,'rate':fmt(rate),'mark':fmt(mark),'next_funding':next_funding,'now':now}
        if estimated_price:payload['price_source']='OKX_ONE_MINUTE_MARK_OPEN_PROXY'
        def run(c,s):
            _check_time(s,now)
            if any(type(x) is not int for x in (settlement_ts,finalized_at,next_funding)) or not (0<settlement_ts<=finalized_at<=now<next_funding):raise ValueError('invalid settlement time')
            old=c.execute('SELECT payload FROM settlements WHERE symbol=? AND settlement_ts=?',(symbol,settlement_ts)).fetchone()
            event_payload={k:payload[k] for k in ('symbol','settlement_ts','finalized_at','rate','mark','next_funding')}
            if estimated_price:event_payload['price_source']=payload['price_source']
            if old:
                if json.loads(old[0])!=event_payload:raise ValueError('funding event conflict')
                return {'status':'DUPLICATE','symbol':symbol,'settlement_ts':settlement_ts}
            p=s['positions'].get(symbol)
            if not p or settlement_ts!=p['next_funding'] or settlement_ts<=p['last_change']:raise ValueError('position or schedule not provable')
            _note_gap(c,s,p,now)
            if estimated_price:
                p['execution_uncertain']=True;p['funding_price_uncertain']=True;s['entry_locked']=True;s['lock_reason']='FUNDING_PRICE_ESTIMATED'
                _event(c,'ENTRY_LOCK',D(0),{'reason':'FUNDING_PRICE_ESTIMATED','symbol':symbol})
            delta=-D(1 if p['side']=='long' else -1)*rate*D(p['qty'])*mark
            p['margin']=fmt(D(p['margin'])+delta);p['next_funding']=next_funding
            c.execute('INSERT INTO settlements VALUES(?,?,?)',(symbol,settlement_ts,pack(event_payload)))
            detail={'symbol':symbol,'settlement_ts':settlement_ts,'funding_delta':fmt(delta)}
            if estimated_price:detail.update({'rate_source':'OKX_REALIZED_RATE','mark_source':'OKX_ONE_MINUTE_MARK_OPEN_PROXY','funding_amount_uncertain':True})
            _event(c,'FUNDING',delta,detail);_daily_update(c,s,now)
            return {'status':'APPLIED',**detail}
        return self._command(command_id,payload,run)
    def _close_in_tx(self,c,s,*,symbol,qty,now,book_id,book,rules,reason):
        p=s['positions'].get(symbol)
        if not p:raise ValueError('position missing')
        if rules.__dict__!=p['rules']:raise ValueError('market rules changed; reconciliation required')
        if now>=p['next_funding']:raise ValueError('unsettled funding; settle before closing')
        if qty>D(p['qty']):raise ValueError('close quantity exceeds position')
        _note_gap(c,s,p,now)
        observed=_observed(book,now,s['max_age'])
        if observed<p['mark_at']:raise ValueError('book observation moved backwards')
        _book_identity(c,symbol,book_id)
        estimate=estimate_depth(book=book,rules=rules,side='sell' if p['side']=='long' else 'buy',quantity=fmt(qty),now=now,max_age=s['max_age'],fee_rate=s['settings']['fee_rate'])
        if rules.symbol!=symbol:raise ValueError('symbol mismatch')
        filled,notional=_fill(estimate)
        if not filled:raise ValueError('no executable liquidity')
        p['mark']=fmt((D(str(book['bids'][0][0]))+D(str(book['asks'][0][0])))/2);p['mark_at']=observed
        oldqty=D(p['qty']);released=quant(D(p['margin'])*filled/oldqty)
        gross=D(1 if p['side']=='long' else -1)*(notional-D(p['entry'])*filled)
        fee=notional*D(s['settings']['fee_rate']);s['cash']=fmt(D(s['cash'])+released+gross-fee)
        remaining=oldqty-filled
        if remaining:
            p['qty']=fmt(remaining);p['margin']=fmt(D(p['margin'])-released);p['last_change']=now
            if reason in ('STOP','TARGET','LIQUIDATION','FUNDING_PREEMPT'):
                s['entry_locked']=True;s['lock_reason']='PARTIAL_PROTECTIVE_EXIT'
        else:del s['positions'][symbol]
        detail={'symbol':symbol,'reason':reason,'execution_uncertain':p['execution_uncertain'],'requested':fmt(qty),'filled':fmt(filled),'remaining_position':fmt(remaining),'released_margin':fmt(released),'gross_pnl':fmt(gross),'fee':fmt(fee),'book_id':book_id}
        _event(c,'CLOSE',gross-fee,detail);_daily_update(c,s,now)
        return {'status':'FILLED' if filled==qty else 'PARTIAL_IOC',**detail}
    def close_position(self,command_id,*,symbol,quantity,now,book_id,book,rules,reason='MANUAL'):
        ident(symbol,'symbol');qty=number(quantity,'quantity',positive=True)
        if reason not in ('MANUAL','STOP','TARGET','LIQUIDATION'):raise ValueError('invalid reason')
        if not isinstance(rules,MarketRules):raise ValueError('rules unknown')
        payload={'type':'close','symbol':symbol,'quantity':fmt(qty),'now':now,'book_id':book_id,'book':book,'rules':rules.__dict__,'reason':reason}
        def run(c,s):
            _check_time(s,now)
            return self._close_in_tx(c,s,symbol=symbol,qty=qty,now=now,book_id=book_id,book=book,rules=rules,reason=reason)
        return self._command(command_id,payload,run)
    def process_book(self,command_id,*,symbol,book_id,book,rules,now,funding_exit_before=0):
        """Mark, koruma, IOC fill, kilit ve bildirim tek SQLite transaction'ında.
        Bu yalnız verilen sentetik/önceden kaydedilmiş kitap üzerinde modeldir.
        """
        ident(symbol,'symbol');ident(book_id,'book_id')
        if not isinstance(rules,MarketRules):raise ValueError('rules unknown')
        if type(funding_exit_before) is not int or not 0<=funding_exit_before<=600:raise ValueError('invalid pre-funding window')
        payload={'type':'book','symbol':symbol,'book_id':book_id,'book':book,'rules':rules.__dict__,'now':now}
        if funding_exit_before:payload['funding_exit_before']=funding_exit_before
        def run(c,s):
            _check_time(s,now);p=s['positions'].get(symbol)
            if not p:raise ValueError('position missing')
            if rules.__dict__!=p['rules']:raise ValueError('market rules changed; reconciliation required')
            observed=_observed(book,now,s['max_age'])
            if observed<p['mark_at']:raise ValueError('book observation moved backwards')
            estimate_depth(book=book,rules=replace(rules,min_qty='0',min_notional='0'),side='sell',quantity=rules.qty_step,now=now,max_age=s['max_age'],fee_rate='0')
            if book.get('symbol')!=symbol or rules.symbol!=symbol:raise ValueError('symbol mismatch')
            mid=(D(str(book['bids'][0][0]))+D(str(book['asks'][0][0])))/2
            _note_gap(c,s,p,now)
            p['mark']=fmt(mid);p['mark_at']=observed
            _daily_update(c,s,now)
            status,isolated,maintenance=_condition(s,p,mid,now)
            protection={'symbol':symbol,'status':status,'isolated_equity':fmt(isolated),'maintenance_estimate':fmt(maintenance),
                        'warning':'Yalnız eşik tahmini; otomatik borsa likidasyonu veya garantili stop değildir.'}
            mark={'marked':symbol,'price':fmt(mid)}
            if status=='FUNDING_DUE_UNKNOWN':
                s['entry_locked']=True;s['lock_reason']='FUNDING_UNKNOWN'
                _event(c,'ENTRY_LOCK',D(0),{'reason':'FUNDING_UNKNOWN','symbol':symbol})
                return {'action':'LOCK','protection':protection,'mark':mark}
            reason={'STOP':'STOP','TARGET':'TARGET','LIQUIDATION_MODEL':'LIQUIDATION'}.get(status)
            if reason is None and funding_exit_before and p['next_funding']-now<=funding_exit_before:
                reason='FUNDING_PREEMPT'
            if reason is None:
                # Önce eski stop kontrol edildi; yeni stop yalnız bir SONRAKİ
                # snapshot'tan itibaren çalışabilir (geriye dönük dolum yok).
                sign=D(1 if p['side']=='long' else -1);entry=D(p['entry']);old=D(p['stop']);proposed=old
                favorable=sign*(mid-entry);trigger=D(p['entry_stop_at_r']);trail=D(p['trailing_distance'])
                if trigger and favorable>=trigger*D(p['initial_r']):
                    proposed=max(proposed,entry) if sign==1 else min(proposed,entry)
                if trail and favorable>0:
                    candidate=mid-sign*trail
                    proposed=max(proposed,candidate) if sign==1 else min(proposed,candidate)
                if proposed!=old:
                    p['stop']=fmt(proposed)
                    _event(c,'STOP_UPDATE',D(0),{'symbol':symbol,'old':fmt(old),'new':fmt(proposed),'effective_after':now})
                return {'action':'MONITOR','protection':protection,'mark':mark,'stop':p['stop']}
            # Dolum başarısız olursa aynı transaction'da mark + kilit kaydedilir;
            # yarım kalmış fill/kitap tüketimi SAVEPOINT ile geri alınır.
            saved=copy.deepcopy(s);c.execute('SAVEPOINT protective_close')
            try:
                close=self._close_in_tx(c,s,symbol=symbol,qty=D(p['qty']),now=now,book_id=book_id,book=book,rules=rules,reason=reason)
            except ValueError:
                c.execute('ROLLBACK TO protective_close');c.execute('RELEASE protective_close')
                s.clear();s.update(saved);s['entry_locked']=True;s['lock_reason']='PROTECTION_FAILED'
                _event(c,'ENTRY_LOCK',D(0),{'reason':'PROTECTION_FAILED','symbol':symbol})
                return {'action':'LOCK','protection':protection,'mark':mark,'reason':'PROTECTIVE_EXECUTION_FAILED'}
            c.execute('RELEASE protective_close')
            return {'action':'CLOSE','protection':protection,'mark':mark,'order':close}
        return self._command(command_id,payload,run)
    def protection_status(self,symbol,mark,now):
        """Basit izolasyon eşik kontrolü; bağımsız emir yerine yalnız durumu döndürür."""
        px=number(mark,'mark',positive=True);snap=self.snapshot();p=snap['state']['positions'].get(symbol)
        if not p:raise ValueError('position missing')
        if type(now) is not int or now<snap['state']['last_time']:raise ValueError('invalid time')
        with localcontext() as ctx:
            ctx.prec=80
            status,isolated_equity,maintenance=_condition(snap['state'],p,px,now)
            return {'symbol':symbol,'status':status,'isolated_equity':fmt(isolated_equity),'maintenance_estimate':fmt(maintenance),
                    'warning':'Yalnız eşik tahmini; otomatik borsa likidasyonu veya garantili stop değildir.'}

    def lock_entries(self,command_id,reason,now):
        if reason not in ('PROTECTION_FAILED','FUNDING_UNKNOWN','OPERATOR_HALT','MARKET_DATA_UNKNOWN','WORKER_ERROR'):raise ValueError('invalid lock reason')
        payload={'type':'lock','reason':reason,'now':now}
        def run(c,s):
            _check_time(s,now);s['entry_locked']=True;s['lock_reason']=reason
            _event(c,'ENTRY_LOCK',D(0),{'reason':reason})
            return {'locked':True,'reason':reason}
        return self._command(command_id,payload,run)
    def clear_entry_lock(self,command_id,now):
        """Yalnız operatör isteğiyle; koruma, tazelik, funding açık ise reddedilir."""
        payload={'type':'clear_lock','now':now}
        def run(c,s):
            _check_time(s,now);_fresh_marks(s,now)
            if not s['entry_locked']:return {'locked':False,'reason':'ALREADY_CLEAR'}
            s['entry_locked']=False;s['lock_reason']='';_event(c,'ENTRY_UNLOCK',D(0),{'operator_requested':True})
            return {'locked':False,'reason':'OPERATOR_CLEAR'}
        return self._command(command_id,payload,run)
