"""OKX genel (API anahtarsız) verisini birleşik simülatör şemasına çevirir.
Bu modül otomatik ağ çağırmaz, emir yolu içermez ve sonuçların borsa paritesini
kanıtlamaz. İleri PAPER çalıştırıcısına kendiliğinden bağlanmaz.
"""
from dataclasses import dataclass,asdict
from hashlib import sha256
from decimal import Decimal,localcontext
import json,re,urllib.parse,urllib.request,time,threading
from .data import Bar,validate_bars
from .depth_research import MarketRules,dec,fmt,estimate_depth

BASE='https://www.okx.com'
ALLOWED={'/api/v5/public/instruments','/api/v5/market/books','/api/v5/market/candles','/api/v5/market/history-candles','/api/v5/public/funding-rate','/api/v5/public/funding-rate-history','/api/v5/market/history-mark-price-candles'}

def symbol_ok(symbol):
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z0-9]{2,15}-USDT-SWAP',symbol):raise ValueError('unsupported symbol')
    return symbol

def _data(payload):
    if not isinstance(payload,dict) or payload.get('code')!='0' or not isinstance(payload.get('data'),list):raise ValueError('invalid OKX response')
    return payload['data']

def _ms(value,label):
    if not isinstance(value,str) or not value.isdigit() or len(value)>15:raise ValueError('invalid '+label)
    return int(value)

def _clock(now_ms):
    if type(now_ms) is not int or not 0<=now_ms<=253402300799999:raise ValueError('invalid clock')

@dataclass(frozen=True)
class Instrument:
    symbol:str
    contract_base:str
    lot_contracts:str
    min_contracts:str
    rules:MarketRules

def parse_instrument(payload,symbol,*,min_notional):
    symbol_ok(symbol);base=symbol.split('-')[0];data=_data(payload)
    if len(data)!=1 or not isinstance(data[0],dict):raise ValueError('instrument response ambiguous')
    r=data[0]
    if (r.get('instId')!=symbol or r.get('instType')!='SWAP' or r.get('ctType')!='linear'
        or r.get('state')!='live' or r.get('settleCcy')!='USDT' or r.get('ctValCcy')!=base
        or r.get('instCategory')!='1' or r.get('ruleType')!='normal'):raise ValueError('unsupported instrument specification')
    with localcontext() as ctx:
        ctx.prec=80
        value=dec(r.get('ctVal'),'ctVal',positive=True);mult=dec(r.get('ctMult'),'ctMult',positive=True)
        # Kaynak dokümanında ctMult anlamı ürün türüne göre değişebilir;
        # çarpanı 1 dışındaki ürünler burada bilinçli olarak desteklenmez.
        if mult!=1:raise ValueError('unsupported contract multiplier')
        lot=dec(r.get('lotSz'),'lotSz',positive=True);minsz=dec(r.get('minSz'),'minSz',positive=True);tick=dec(r.get('tickSz'),'tickSz',positive=True)
        min_usdt=dec(min_notional,'min_notional',nonnegative=True)
        if minsz%lot!=0:raise ValueError('minimum size not aligned')
        step=value*lot;minimum=value*minsz
        # Çekirdeğin Decimal sınırını önceden denetle.
        for v in (step,minimum,tick,min_usdt):dec(fmt(v),'normalized rule',nonnegative=True)
        rules=MarketRules(symbol,fmt(step),fmt(tick),fmt(minimum),fmt(min_usdt))
        return Instrument(symbol,fmt(value),fmt(lot),fmt(minsz),rules)

def parse_book(payload,instrument,*,now_ms,max_age=20):
    if not isinstance(instrument,Instrument):raise ValueError('instrument unknown')
    _clock(now_ms)
    if type(max_age) is not int or max_age<0:raise ValueError('invalid max_age')
    data=_data(payload)
    if len(data)!=1 or not isinstance(data[0],dict):raise ValueError('book response ambiguous')
    row=data[0];ts=_ms(row.get('ts'),'book timestamp')
    if ts>now_ms or now_ms-ts>max_age*1000:raise ValueError('stale or future book')
    with localcontext() as ctx:
        ctx.prec=80;ct=D(instrument.contract_base);lot=D(instrument.lot_contracts)
        def levels(key):
            x=row.get(key)
            if not isinstance(x,list) or not x:raise ValueError('empty book')
            out=[]
            for r in x:
                if not isinstance(r,list) or len(r)<2:raise ValueError('invalid level')
                p=dec(r[0],'book price',positive=True);contracts=dec(r[1],'book contracts',positive=True)
                if contracts%lot:raise ValueError('book contract size not lot-aligned')
                out.append([fmt(p),fmt(contracts*ct)])
            return out
        book={'symbol':instrument.symbol,'observed_at':ts//1000,'bids':levels('bids'),'asks':levels('asks')}
        # Geçerli sıralama, fiyat adımı, boş/crossed defter için merkezi denetim.
        estimate_depth(book=book,rules=MarketRules(instrument.symbol,instrument.rules.qty_step,instrument.rules.price_tick,'0','0'),side='buy',quantity=instrument.rules.qty_step,now=now_ms//1000,max_age=max_age+1,fee_rate='0')
        # Aynı simge ve ms timestamp için tek snapshot ID'si (içerik değişse de).
        return {'book':book,'book_id':'OKX:'+instrument.symbol+':'+str(ts),'source_ts_ms':ts}
D=Decimal

def parse_candles(payload,*,now_ms):
    _clock(now_ms);rows=_data(payload);bars=[]
    for r in rows:
        if not isinstance(r,list) or len(r)<9:raise ValueError('invalid candle row')
        if r[8] not in ('0','1'):raise ValueError('invalid confirmation')
        if r[8]=='0':continue
        ts=_ms(r[0],'candle timestamp')
        if ts%60000 or ts+60000>now_ms:raise ValueError('future or unaligned candle')
        try:
            # volCcy = taban para hacmi; vol = türev kontrat adedi.
            b=Bar(ts//1000,float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[6]))
        except (TypeError,ValueError,OverflowError) as e:raise ValueError('invalid OHLCV') from e
        bars.append(b)
    if not bars:raise ValueError('no closed candles')
    bars.sort(key=lambda b:b.timestamp);validate_bars(bars,60)
    return bars

def parse_upcoming_funding(payload,symbol,*,now_ms,max_age=600):
    symbol_ok(symbol);_clock(now_ms)
    if type(max_age) is not int or max_age<0:raise ValueError('invalid max_age')
    data=_data(payload)
    if len(data)!=1 or not isinstance(data[0],dict) or data[0].get('instId')!=symbol:raise ValueError('funding symbol unknown')
    row=data[0];ts=_ms(row.get('ts'),'funding observation');settle=_ms(row.get('fundingTime'),'funding time')
    rate=dec(row.get('fundingRate'),'fundingRate')
    if abs(rate)>1 or ts>now_ms or now_ms-ts>max_age*1000 or settle<=now_ms or settle%1000:raise ValueError('invalid or stale funding')
    return {'rate':fmt(rate),'observed_at':ts//1000,'next_funding':settle//1000,'kind':'PREDICTED_NOT_SETTLED'}

def parse_realized_funding(payload,symbol,*,settlement_ts,now_ms):
    """Only explicit realizedRate at exact time; never fall back to forecast."""
    symbol_ok(symbol);_clock(now_ms)
    if type(settlement_ts) is not int or settlement_ts<=0 or settlement_ts%60 or now_ms<(settlement_ts+120)*1000:raise ValueError('funding not final or not aligned')
    rows=_data(payload);matches=[]
    for row in rows:
        if not isinstance(row,dict):raise ValueError('invalid history row')
        if row.get('instId')!=symbol or row.get('instType')!='SWAP':raise ValueError('funding symbol mismatch')
        t=_ms(row.get('fundingTime'),'funding time')
        if t>settlement_ts*1000 and t<=now_ms:raise ValueError('multiple funding periods need reconciliation')
        if t==settlement_ts*1000:matches.append(row)
    if len(matches)!=1:raise ValueError('funding event missing or duplicate')
    rate=dec(matches[0].get('realizedRate'),'realizedRate')
    if abs(rate)>1:raise ValueError('invalid realized rate')
    return {'symbol':symbol,'settlement_ts':settlement_ts,'rate':fmt(rate),'rate_kind':'OKX_REALIZED_RATE'}

def parse_funding_mark_proxy(payload,*,settlement_ts,now_ms):
    """Candle open at funding minute is a proxy, NOT an exact settlement mark."""
    _clock(now_ms)
    if type(settlement_ts) is not int or settlement_ts<=0 or settlement_ts%60 or now_ms<(settlement_ts+120)*1000:raise ValueError('mark candle not final')
    matches=[]
    for row in _data(payload):
        if not isinstance(row,list) or len(row)!=6:raise ValueError('invalid mark candle')
        t=_ms(row[0],'mark candle time')
        if t==settlement_ts*1000:matches.append(row)
    if len(matches)!=1:raise ValueError('mark candle missing or duplicate')
    r=matches[0]
    if r[5]!='1':raise ValueError('mark candle not closed')
    o,h,l,c=(dec(x,'mark price',positive=True) for x in r[1:5])
    if h<max(o,c,l) or l>min(o,c,h):raise ValueError('invalid mark OHLC')
    return {'mark_price_proxy':fmt(o),'mark_kind':'ONE_MINUTE_MARK_OPEN_PROXY_NOT_EXACT'}

def make_entry_event(*,event_id,instrument,bars,book_snapshot,funding,quantity,leverage,now_ms,correlation_histories=None):
    """İleri simülasyon için veri olayı üretir; hiçbir işlem başlatmaz."""
    from .order_journal_research import ident
    ident(event_id,'event_id');_clock(now_ms)
    if not isinstance(instrument,Instrument) or not isinstance(book_snapshot,dict) or not isinstance(funding,dict):raise ValueError('data unknown')
    now=now_ms//1000
    if funding.get('kind')!='PREDICTED_NOT_SETTLED':raise ValueError('funding forecast required')
    # Tahmin settlement değildir; yalnız giriş-zamanı kapısıdır.
    rate=dec(funding.get('rate'),'rate');nxt=funding.get('next_funding');observed=funding.get('observed_at')
    if abs(rate)>1 or type(nxt) is not int or type(observed) is not int or now-observed>600 or observed>now or nxt-now<600:raise ValueError('funding stale or too close')
    if not isinstance(bars,list) or len(bars)<220:raise ValueError('insufficient bars')
    validate_bars(bars,60)
    if bars[-1].timestamp+60>now or now-(bars[-1].timestamp+60)>30:raise ValueError('stale candle')
    if book_snapshot.get('book',{}).get('symbol')!=instrument.symbol:raise ValueError('book mismatch')
    data={'symbol':instrument.symbol,'bars':[asdict(b) for b in bars],'quantity':fmt(dec(quantity,'quantity',positive=True)),
          'leverage':fmt(dec(leverage,'leverage',positive=True)),'next_funding':nxt,'now':now,'book_id':book_snapshot['book_id'],
          'book':book_snapshot['book'],'rules':asdict(instrument.rules),'market_spec_fingerprint':sha256(json.dumps(asdict(instrument),sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    if correlation_histories is not None:data['correlation_histories']={k:[asdict(b) for b in v] for k,v in correlation_histories.items()}
    return {'type':'candles','id':event_id,'data':data,'source':'OKX_PUBLIC_UNVERIFIED','warning':'Forecast funding, no settlement proof; offline event only.'}

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

class PublicClient:
    """Açıkça çağrıldığında yalnız izinli halka açık GET uçları kullanır."""
    def __init__(self,transport=None):
        self.transport=transport or self._request;self._throttle=(transport is None);self._last=0.0;self._lock=threading.Lock()
    @staticmethod
    def _request(url):
        request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'ACAR-Paper-ReadOnly/1'})
        with urllib.request.build_opener(_NoRedirect()).open(request,timeout=8) as r:
            raw=r.read(800001)
            if len(raw)>800000:raise ValueError('response too large')
            return json.loads(raw.decode('utf-8'))
    def get(self,path,params):
        if path not in ALLOWED:raise ValueError('endpoint not permitted')
        allowed={'/api/v5/public/instruments':{'instType','instId'},'/api/v5/market/books':{'instId','sz'},'/api/v5/market/candles':{'instId','bar','limit'},'/api/v5/market/history-candles':{'instId','bar','limit','after'},'/api/v5/public/funding-rate':{'instId'},'/api/v5/public/funding-rate-history':{'instId','limit'},'/api/v5/market/history-mark-price-candles':{'instId','bar','limit','before','after'}}
        if not isinstance(params,dict) or not set(params).issubset(allowed[path]):raise ValueError('parameters invalid')
        if 'instId' in params:symbol_ok(params['instId'])
        query=urllib.parse.urlencode(params)
        with self._lock:
            if self._throttle:
                delay=.15-(time.monotonic()-self._last)
                if delay>0:time.sleep(delay)
            try:return self.transport(BASE+path+'?'+query)
            finally:self._last=time.monotonic()
    def _observation_clock(self,requested_ms):
        _clock(requested_ms)
        # Real server timestamps can advance during HTTP transit. Validate
        # against the local wall clock AFTER the response, not before request.
        return time.time_ns()//1_000_000 if self._throttle else requested_ms
    def instrument(self,symbol,*,min_notional):
        symbol_ok(symbol)
        return parse_instrument(self.get('/api/v5/public/instruments',{'instType':'SWAP','instId':symbol}),symbol,min_notional=min_notional)
    def book(self,instrument,*,now_ms,depth=20,max_age=20):
        if not isinstance(instrument,Instrument) or type(depth) is not int or not 1<=depth<=400:raise ValueError('invalid book request')
        response=self.get('/api/v5/market/books',{'instId':instrument.symbol,'sz':depth})
        return parse_book(response,instrument,now_ms=self._observation_clock(now_ms),max_age=max_age)
    def candles(self,symbol,*,now_ms,limit=300):
        symbol_ok(symbol)
        if type(limit) is not int or not 1<=limit<=300:raise ValueError('invalid limit')
        response=self.get('/api/v5/market/candles',{'instId':symbol,'bar':'1m','limit':limit})
        return parse_candles(response,now_ms=self._observation_clock(now_ms))
    def complete_history(self,symbol,*,now_ms,minimum=220,max_pages=20):
        """UTC gün başlangıcı + ısınma mumu için sayfalı, kesintisiz kapalı seri.
        Eksik, tekrar veya değişmiş barlarda reddeder; ağa kendiliğinden başlamaz.
        """
        symbol_ok(symbol);_clock(now_ms)
        if type(minimum) is not int or minimum<220 or minimum>2000 or type(max_pages) is not int or not 0<=max_pages<=30:raise ValueError('invalid history bounds')
        bars=self.candles(symbol,now_ms=now_ms,limit=300)
        last_open=bars[-1].timestamp
        day_start=(last_open//86400)*86400
        need=min(day_start,last_open-(minimum-1)*60)
        merged={b.timestamp:b for b in bars};cursor=bars[0].timestamp
        for _ in range(max_pages):
            if cursor<=need:break
            raw=self.get('/api/v5/market/history-candles',{'instId':symbol,'bar':'1m','limit':100,'after':cursor*1000})
            page=parse_candles(raw,now_ms=now_ms)
            if page[0].timestamp>=cursor or page[-1].timestamp>=cursor:raise ValueError('history pagination did not move strictly backward')
            for b in page:
                if b.timestamp in merged and merged[b.timestamp]!=b:raise ValueError('conflicting historical candle')
                merged[b.timestamp]=b
            cursor=page[0].timestamp
        if cursor>need:raise ValueError('incomplete UTC history')
        result=[merged[t] for t in sorted(merged) if t>=need]
        validate_bars(result,60)
        if len(result)<minimum or result[0].timestamp!=need:raise ValueError('insufficient or gapped history')
        return result
    def realized_settlement(self,symbol,*,settlement_ts,now_ms):
        """Actual published rate plus a clearly labelled mark-price proxy."""
        symbol_ok(symbol);_clock(now_ms)
        if type(settlement_ts) is not int or settlement_ts<=0 or settlement_ts%60 or now_ms<(settlement_ts+120)*1000:raise ValueError('funding not final')
        h=self.get('/api/v5/public/funding-rate-history',{'instId':symbol,'limit':100})
        rate=parse_realized_funding(h,symbol,settlement_ts=settlement_ts,now_ms=self._observation_clock(now_ms))
        t=settlement_ts*1000
        marks=self.get('/api/v5/market/history-mark-price-candles',{'instId':symbol,'bar':'1m','limit':4,'before':t-60000,'after':t+60000})
        price=parse_funding_mark_proxy(marks,settlement_ts=settlement_ts,now_ms=self._observation_clock(now_ms))
        upcoming=self.funding(symbol,now_ms=self._observation_clock(now_ms))
        return {**rate,**price,'next_funding':upcoming['next_funding']}

    def funding(self,symbol,*,now_ms):
        symbol_ok(symbol)
        response=self.get('/api/v5/public/funding-rate',{'instId':symbol})
        return parse_upcoming_funding(response,symbol,now_ms=self._observation_clock(now_ms))
