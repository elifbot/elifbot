"""UnifiedSimulator için çevrimdışı veriyle çalışan strateji/koruma orkestrasyonu.
Ağ yoktur, çağıran kapanmış mumları ve yeni orderbook snapshot'ı sağlar.
"""
from dataclasses import replace,asdict
from decimal import Decimal,localcontext
from .confluence10 import confluence_snapshot
from .strategy import Breakout
from .depth_research import estimate_depth,fmt
from .correlation_research import correlation_gate
from .unified_simulator import pack
from hashlib import sha256

class OfflineUnifiedBot:
    def __init__(self,simulator):self.sim=simulator
    def on_candles(self,command_id,*,symbol,bars,quantity,leverage,next_funding,now,book_id,book,rules,require_breakout=False,correlation_histories=None,market_spec_fingerprint=None):
        if type(now) is not int:raise ValueError('invalid current time')
        def fingerprint():
            try:
                hist=None if correlation_histories is None else {k:[asdict(b) for b in v] for k,v in correlation_histories.items()}
                raw={'symbol':symbol,'bars':[asdict(b) for b in bars],'quantity':quantity,'leverage':leverage,'next_funding':next_funding,'now':now,'book_id':book_id,'book':book,'rules':asdict(rules),'require_breakout':require_breakout,'correlation_histories':hist,'market_spec_fingerprint':market_spec_fingerprint}
                return sha256(pack(raw).encode()).hexdigest()
            except (TypeError,AttributeError,ValueError):raise ValueError('invalid signal input') from None
        def skip(reason,extra=None):
            return self.sim.record_signal_skip(command_id,symbol=symbol,now=now,reason=reason,request_fingerprint=fingerprint(),extra=extra)
        if not bars:return skip('NO_BARS')
        snapshot=confluence_snapshot(bars)
        if not snapshot['ready']:return skip(snapshot['reason'])
        if snapshot['bar_close']>now or now-snapshot['bar_close']>self.sim.snapshot()['state']['max_age']:
            return skip('BAR_NOT_CLOSED_OR_STALE')
        side=snapshot['side']
        if side not in ('long','short'):return skip('NO_DIRECTION',{'score':snapshot['score']})
        if require_breakout:
            other=Breakout()(bars)
            if not other or other.side!=side:return skip('BREAKOUT_DISAGREEMENT',{'score':snapshot['score']})
        expected_hash=None;correlation={'reason':'NOT_REQUESTED'}
        if correlation_histories is not None:
            portfolio=self.sim.snapshot()['state']['positions']
            if not isinstance(correlation_histories,dict) or any(sym not in correlation_histories for sym in portfolio):
                return skip('CORRELATION_UNKNOWN')
            existing={sym:{'side':p['side'],'bars':correlation_histories[sym]} for sym,p in portfolio.items()}
            correlation=correlation_gate(bars,side,existing,now,max_age=self.sim.snapshot()['state']['max_age'])
            if not correlation['allowed']:return skip(correlation['reason'],{'correlation':correlation})
            expected_hash=sha256(pack(portfolio).encode()).hexdigest()
        # Doğrulama ve kotasyon kontrolü orijinal kitap üzerinde yapılır.
        estimate_depth(book=book,rules=replace(rules,min_qty='0',min_notional='0'),side='buy' if side=='long' else 'sell',quantity=rules.qty_step,now=now,max_age=self.sim.snapshot()['state']['max_age'],fee_rate='0')
        with localcontext() as ctx:
            ctx.prec=80
            reference=Decimal(str(book['asks'][0][0] if side=='long' else book['bids'][0][0]))
            atr=Decimal(str(snapshot['indicators']['atr']));sign=Decimal(1 if side=='long' else -1)
            stop=reference-sign*atr*Decimal('1.5');target=reference+sign*atr*Decimal('3')
        if stop<=0 or target<=0:return skip('INVALID_LEVELS')
        result=self.sim.open_position(command_id,symbol=symbol,side=side,quantity=quantity,stop=fmt(stop),target=fmt(target),leverage=leverage,next_funding=next_funding,now=now,book_id=book_id,book=book,rules=rules,expected_positions_hash=expected_hash,signal_fingerprint=fingerprint(),market_spec_fingerprint=market_spec_fingerprint)
        return {'correlation':correlation,'action':'BLOCKED' if result.get('status')=='BLOCKED' else 'OPEN','signal':snapshot,'order':result}
    def on_book(self,command_id,*,symbol,book_id,book,rules,now,funding_exit_before=0):
        # Mark ve koruyucu çıkış aynı SQLite transaction içinde hesaplanır.
        return self.sim.process_book(command_id,symbol=symbol,book_id=book_id,book=book,rules=rules,now=now,funding_exit_before=funding_exit_before)
