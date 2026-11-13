"""Sistem tasarımından bağımsız veri kapıları. PAPER motoruna bağlı değildir.
Gerçek borsa protokol uyumluluğu iddia edilmez.
"""
import math

def _finite_num(x):
    try: return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
    except OverflowError: return False

def funding_gate(side, rate, next_settlement, observed_at, now, *, max_age=600, window=180, adverse_bps=0):
    """Eksik, gelecekten veya bayat funding girdisini reddet; belirsizlik sıfır değildir."""
    if side not in ('long','short'): return {'allowed':False,'reason':'INVALID_SIDE'}
    if any(not _finite_num(x) for x in (rate,next_settlement,observed_at,now,max_age,window,adverse_bps)):
        return {'allowed':False,'reason':'FUNDING_UNKNOWN'}
    if min(now,next_settlement,observed_at,max_age,window,adverse_bps)<0:
        return {'allowed':False,'reason':'FUNDING_INVALID'}
    if observed_at>now or now-observed_at>max_age or next_settlement<now:
        return {'allowed':False,'reason':'FUNDING_STALE'}
    payment_bps=(rate if side=='long' else -rate)*10000
    if next_settlement-now<=window and payment_bps>adverse_bps:
        return {'allowed':False,'reason':'FUNDING_ADVERSE','adverse_bps':payment_bps}
    return {'allowed':True,'reason':'FUNDING_OK','adverse_bps':max(0,payment_bps)}

class BookSyncError(ValueError): pass

class SequenceBook:
    """Genel snapshot/artımlı sıra kontrolü; borsaya özel checksum değildir."""
    def __init__(self):self.bids={};self.asks={};self.seq=None;self.valid=False
    @staticmethod
    def _apply(book, levels):
        for pair in levels:
            if not isinstance(pair,(tuple,list)) or len(pair)!=2: raise BookSyncError('invalid level')
            price,qty=pair
            if not _finite_num(price) or not _finite_num(qty) or price<=0 or qty<0: raise BookSyncError('invalid price or quantity')
            if qty==0:book.pop(price,None)
            else:book[price]=qty
    def apply(self,action,seq,bids,asks,prev_seq=None):
        try:
            if isinstance(seq,bool) or not isinstance(seq,int) or seq<0:raise BookSyncError('invalid sequence')
            if action=='snapshot':new_bids={};new_asks={}
            elif action=='update':
                if not self.valid or self.seq is None:raise BookSyncError('snapshot required')
                if isinstance(prev_seq,bool) or not isinstance(prev_seq,int) or prev_seq!=self.seq or seq<=self.seq:raise BookSyncError('sequence mismatch')
                new_bids=dict(self.bids);new_asks=dict(self.asks)
            else: raise BookSyncError('invalid action')
            self._apply(new_bids,bids);self._apply(new_asks,asks)
            if not new_bids or not new_asks or max(new_bids)>=min(new_asks):raise BookSyncError('empty or crossed book')
        except (BookSyncError,TypeError):
            self.valid=False
            raise BookSyncError('invalid or out-of-sequence book; snapshot required') from None
        self.bids,self.asks,self.seq,self.valid=new_bids,new_asks,seq,True
    def top(self):
        if not self.valid: raise BookSyncError('book unavailable')
        return max(self.bids),min(self.asks)
