"""Gelecekte açık talimatla çalıştırılacak tek tur public-veri PAPER uyarlayıcı.
Gerçek emir/özel API yoktur. Modül importu ağ çağrısı veya işlem başlatmaz.
Gerçekleşmiş public funding oranını alır; tarihsel mark mum açılışı yalnız yaklaşık vekildir ve belirsizlik kilidi doğurur.
"""
import time,json
from hashlib import sha256
from dataclasses import asdict
from .okx_public_adapter import PublicClient,make_entry_event,symbol_ok
from .unified_bot import OfflineUnifiedBot
from .order_journal_research import ident
from unified_cli import event_execute

def public_paper_once(sim,*,symbol,quantity,leverage,min_notional,client=None,clock_ms=None):
    """Tek kez veri al, mevcut pozisyonu izle veya tek kapanmış mumda karar ver.
    Gerçek fiyat kaynakları ve borsa paritesi ayrıca test edilmeyi gerektirir.
    """
    symbol_ok(symbol);client=client or PublicClient();clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)
    bot=OfflineUnifiedBot(sim)
    try:
        instrument=client.instrument(symbol,min_notional=min_notional)
        state=sim.snapshot()['state'];existing=state['positions'].get(symbol)
        if existing is not None:
            current_spec=sha256(json.dumps(asdict(instrument),sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if existing.get('market_spec_fingerprint')!=current_spec:raise ValueError('market specification changed or provenance unknown')
            # Matured funding is verified from public history. A 1-minute mark
            # open is ONLY a model proxy, so this never claims exact settlement.
            now_s=clock_ms()//1000
            if now_s>=existing['next_funding']+120:
                t=existing['next_funding'];evidence=client.realized_settlement(symbol,settlement_ts=t,now_ms=clock_ms())
                if evidence.get('rate_kind')!='OKX_REALIZED_RATE' or evidence.get('mark_kind')!='ONE_MINUTE_MARK_OPEN_PROXY_NOT_EXACT' or evidence.get('symbol')!=symbol or evidence.get('settlement_ts')!=t:raise ValueError('funding evidence invalid')
                now_s=clock_ms()//1000
                settled=sim.settle_funding('AUTO_FUNDING:'+symbol+':'+str(t),symbol=symbol,settlement_ts=t,finalized_at=now_s,
                    rate=evidence['rate'],mark_price=evidence['mark_price_proxy'],next_funding=evidence['next_funding'],now=now_s,estimated_price=True)
                return {'action':'FUNDING_APPLIED_ESTIMATED','result':settled,'warning':'Realized rate; one-minute mark open is an approximate price, entry lock requires review.'}
            snap=client.book(instrument,now_ms=clock_ms());now=clock_ms()//1000
            # Piyasa snapshot id'si aynıysa tek olay olarak kalır.
            cid='BOOK:'+symbol+':'+str(snap['source_ts_ms']);ident(cid,'event id')
            if sim.command_result(cid) is not None:return {'action':'ALREADY_PROCESSED_BOOK','book_id':snap['book_id']}
            return bot.on_book(cid,symbol=symbol,book_id=snap['book_id'],book=snap['book'],rules=instrument.rules,now=now,funding_exit_before=180)
        if state['entry_locked']:return {'action':'BLOCKED','reason':'ACCOUNT_LOCKED'}
        bars=client.complete_history(symbol,now_ms=clock_ms())
        funding=client.funding(symbol,now_ms=clock_ms())
        book=client.book(instrument,now_ms=clock_ms());now_ms=clock_ms()
        bar_close=bars[-1].timestamp+60
        # Between 30 and 60 seconds after close, the last confirmed candle is
        # intentionally too old for entry; this is a normal wait, not a feed failure.
        if now_ms//1000-bar_close>30:return {'action':'SKIP','reason':'WAIT_FOR_FRESH_CLOSED_CANDLE'}
        cid='BAR:'+symbol+':'+str(bar_close);ident(cid,'event id')
        if sim.command_result(cid) is not None:return {'action':'ALREADY_EVALUATED_BAR','bar_close':bar_close}
        event=make_entry_event(event_id=cid,instrument=instrument,bars=bars,book_snapshot=book,funding=funding,quantity=quantity,leverage=leverage,now_ms=now_ms)
        try:
            return event_execute(sim,event)
        except ValueError as e:
            safe_blocks={'portfolio risk limit','position/equity/leverage limit','insufficient free cash','one position per symbol','invalid stop/target','spread too wide','entries locked','position mark stale or future','position monitoring uncertain','protective exit requires attention','unsettled funding; settle before trading','position mark stale or future'}
            if str(e) in safe_blocks:return {'action':'BLOCKED','reason':str(e)}
            raise
    except (ValueError,TypeError,KeyError,OSError,TimeoutError) as e:
        # Aktif pozisyon varken veri/işleme hatası yeni girişleri kilitler;
        # geçersiz veya bilinmeyen fiyatla sahte koruyucu kapanış yazılmaz.
        state=sim.snapshot()['state']
        if state['positions']:
            now=max(state['last_time'],clock_ms()//1000)
            lock_id='FEED_ERROR:'+symbol+':'+str(now)
            sim.lock_entries(lock_id,'MARKET_DATA_UNKNOWN',now)
        return {'action':'DATA_ERROR','reason':type(e).__name__,'entry_locked':bool(sim.snapshot()['state']['entry_locked'])}
