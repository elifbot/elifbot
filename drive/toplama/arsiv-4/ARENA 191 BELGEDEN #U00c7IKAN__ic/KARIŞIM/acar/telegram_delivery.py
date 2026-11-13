"""İsteğe bağlı Telegram teslimi; kimlik bilgileri yalnız çağırandan gelir.
Gerçek gönderim yalnız açıkça çağrıldığında yapılır. Bilinmeyen sonuç tekrar edilmez.
"""
import json,re,sqlite3,urllib.parse,urllib.request
from contextlib import closing
from .unified_simulator import connect,_state,APP_ID,VERSION
from .order_journal_research import ident

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def _transport(req,timeout):
    opener=urllib.request.build_opener(_NoRedirect())
    with opener.open(req,timeout=timeout) as response:
        if response.status!=200:raise ValueError('provider error')
        body=response.read(100_001)
        if len(body)>100_000:raise ValueError('response too large')
        return body

def _credentials(token,chat_id):
    if not isinstance(token,str) or not re.fullmatch(r'\d{7,12}:[A-Za-z0-9_-]{30,}',token):raise ValueError('missing or invalid Telegram token')
    if not isinstance(chat_id,str) or not re.fullmatch(r'-?\d{1,20}',chat_id):raise ValueError('missing or invalid Telegram chat id')

def _sequence(seq):
    if type(seq) is not int or seq<1:raise ValueError('invalid notification id')

def _transaction(path,fn):
    with closing(connect(path)) as c:
        c.execute('PRAGMA foreign_keys=ON')
        with c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID or c.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise ValueError('unsupported database')
            _state(c)
            return fn(c)

def _message(kind,detail):
    # Keyfi alanlar/secretlar mesajlara taşınmaz; kesin bir alan listesi.
    fields=('symbol','side','reason','requested','filled','remaining_position','gross_pnl','fee','funding_delta','new','day')
    if not isinstance(kind,str) or not re.fullmatch(r'[A-Z_]{1,40}',kind) or not isinstance(detail,dict):raise ValueError('invalid notification')
    lines=['ACAR OFFLINE SIMULATION',kind]
    for key in fields:
        value=detail.get(key)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',value):lines.append(key+': '+value)
    return '\n'.join(lines)

def notification_status(path,seq):
    _sequence(seq)
    with closing(connect(path,True)) as c:
        c.execute('BEGIN');_state(c)
        if not c.execute('SELECT 1 FROM notifications WHERE seq=?',(seq,)).fetchone():raise ValueError('notification not found')
        row=c.execute('SELECT state,attempt_id FROM notification_delivery WHERE seq=?',(seq,)).fetchone()
        return {'seq':seq,'state':row[0] if row else 'READY','attempt_id':row[1] if row else None}

def deliver_telegram(path,seq,*,token,chat_id,attempt_id,transport=None):
    """Claim atomik; ağ dış transaction. Kesintide tekrar kesinlikle otomatik değil.
    İstek sonucu belirsizse UNCERTAIN; işlem yarıda kalırsa IN_FLIGHT olarak kalır.
    Bu şema dış serviste exactly-once garantisi sunmaz.
    """
    _sequence(seq);_credentials(token,chat_id);ident(attempt_id,'attempt_id')
    if re.fullmatch(r'\d{7,12}:[A-Za-z0-9_-]{30,}',attempt_id):raise ValueError('attempt id must not be a credential')
    def claim(c):
        row=c.execute('SELECT kind,detail FROM notifications WHERE seq=?',(seq,)).fetchone()
        if not row:raise ValueError('notification not found')
        message=_message(row[0],json.loads(row[1]))
        prior=c.execute('SELECT state FROM notification_delivery WHERE seq=?',(seq,)).fetchone()
        if prior and prior[0]!='READY':return {'state':prior[0],'message':None}
        c.execute('INSERT INTO notification_delivery(seq,state,attempt_id) VALUES(?,?,?) ON CONFLICT(seq) DO UPDATE SET state=excluded.state,attempt_id=excluded.attempt_id',(seq,'IN_FLIGHT',attempt_id))
        c.execute('INSERT INTO delivery_events(notification_seq,action,attempt_id) VALUES(?,?,?)',(seq,'CLAIMED',attempt_id))
        return {'state':'CLAIMED','message':message}
    claimed=_transaction(path,claim)
    if claimed['state']!='CLAIMED':return {'seq':seq,'state':claimed['state'],'sent_now':False}
    # API token sadece lokal request'tedir; istek/URL/istisna asla rapora yazılmaz.
    body=urllib.parse.urlencode({'chat_id':chat_id,'text':claimed['message']}).encode()
    req=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=body,method='POST')
    try:
        raw=(transport or _transport)(req,8)
        if not isinstance(raw,bytes) or len(raw)>100_000:raise ValueError('invalid response')
        result=json.loads(raw.decode('utf-8'))
        state='SENT' if isinstance(result,dict) and result.get('ok') is True else 'REJECTED' if isinstance(result,dict) and result.get('ok') is False else 'UNCERTAIN'
    except Exception:
        state='UNCERTAIN'
    def finish(c):
        row=c.execute('SELECT state,attempt_id FROM notification_delivery WHERE seq=?',(seq,)).fetchone()
        if row!=('IN_FLIGHT',attempt_id):raise ValueError('delivery state changed')
        c.execute('UPDATE notification_delivery SET state=? WHERE seq=?',(state,seq))
        c.execute('INSERT INTO delivery_events(notification_seq,action,attempt_id) VALUES(?,?,?)',(seq,state,attempt_id))
    _transaction(path,finish)
    return {'seq':seq,'state':state,'sent_now':state=='SENT'}

def resolve_delivery(path,seq,decision):
    """Operatör haricen doğrular; RETRY yeni gönderime ve olası çift mesaja izin verir."""
    _sequence(seq)
    if decision not in ('CONFIRMED_SENT','RETRY_APPROVED'):raise ValueError('invalid decision')
    def run(c):
        row=c.execute('SELECT state FROM notification_delivery WHERE seq=?',(seq,)).fetchone()
        if not row or row[0] not in ('IN_FLIGHT','UNCERTAIN','REJECTED'):raise ValueError('nothing unresolved')
        state='SENT' if decision=='CONFIRMED_SENT' else 'READY'
        c.execute('UPDATE notification_delivery SET state=?,attempt_id=NULL WHERE seq=?',(state,seq))
        c.execute('INSERT INTO delivery_events(notification_seq,action,attempt_id) VALUES(?,?,NULL)',(seq,decision))
        return {'seq':seq,'state':state,'warning':'RETRY_APPROVED yinelenen mesaj riski taşır.' if state=='READY' else 'Operatör beyanı; otomatik doğrulama değildir.'}
    return _transaction(path,run)
