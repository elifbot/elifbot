"""Offline regression; synthetic clocks/feeds, no live API, wallet or orders."""
import asyncio
import time
from unittest.mock import AsyncMock
import pytest
import ws_bot
import scanner.v78_flow_adapter as legacy
from scanner.ws_scanner import SpikeDetector


def bot_factory(tmp_path, monkeypatch, enabled=True):
    monkeypatch.setattr(ws_bot, 'TABAN', str(tmp_path))
    monkeypatch.setattr(ws_bot.Bot, '_olay_dosyasi_hazirla', lambda self: None)
    detector=SpikeDetector(); detector.ind_aktif=True
    bot=ws_bot.Bot(detector, strateji='momentum', sinyal_zenginlestirme=True,
        risk_limitleri=True, binance_hacim_kaynagi='aggtrade', teyit_aktif=True,
        eski_v78_paper=enabled, sadece_kayit=True, defter_golge=False)
    bot.indikator_hazir=True
    return bot


def bootstrap_candidate(b, monkeypatch, ex='binance'):
    now=int(time.time()*1000); sym='TESTUSDT' if ex=='binance' else 'TEST-USDT-SWAP';key=(ex,sym)
    if ex=='binance':
        b._v78_binance_connection([sym],True)
    else:
        b.eski_v78_motor.okx_connection_change(sym,True)
    b.detektor.durum(*key)._flow_start_ms=now-40_000  # synthetic elapsed time
    for i in range(40):b.akis.ekle(*key,100,100,'buy',now-39_000+i*1_000)
    d=b.detektor.durum(*key);d.son_fiyat=100.;d.son_fiyat_ts=now;d.hiz_uzun=1.;d.son_hacim_ts=now;d.ret_2s=0.;d.rvol=2.
    b._sinyal_dispatch=AsyncMock()
    monkeypatch.setattr(legacy,'giris_karari',lambda *a:(True,'synthetic_gate',{}))
    b.eski_v78_motor.record=lambda row:None
    return key,d


def test_old_trade_rejected_not_written(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);sym='TESTUSDT';b._v78_binance_connection([sym],True)
    b._binance_akis_trade('binance',sym,100,1,'buy',int(time.time()*1000)-10_000)
    assert b._real_volume.stale==1 and b._real_volume.accepted==0
    assert ('binance',sym) not in b.akis._kayitlar
    assert b.eski_v78_motor.stats['book_rejected']==1


def test_disabled_original_v4_data_path_is_unchanged(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch,False); sym='TESTUSDT'; b._real_volume.connection([sym],True)
    b._binance_akis_trade('binance',sym,100,1,'buy',int(time.time()*1000)-10_000)
    assert b._real_volume.stale==1
    assert len(b.akis._kayitlar[('binance',sym)].olaylar)==1
    assert b.eski_v78_motor is None


def test_valid_trade_written_in_new_generation(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);sym='TESTUSDT';b._v78_binance_connection([sym],True)
    b._binance_akis_trade('binance',sym,100,1,'buy',int(time.time()*1000))
    assert b._real_volume.accepted==1 and b.eski_v78_motor.stats['book_accepted']==1
    assert len(b.akis._kayitlar[('binance',sym)].olaylar)==1


def test_out_of_order_or_future_does_not_enter_book(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);sym='TESTUSDT';b._v78_binance_connection([sym],True)
    n=int(time.time()*1000)
    b._binance_akis_trade('binance',sym,100,1,'buy',n)
    b._binance_akis_trade('binance',sym,100,1,'buy',n-1)
    b._binance_akis_trade('binance',sym,100,1,'buy',n+3_000)
    assert b._real_volume.stale==2
    assert len(b.akis._kayitlar[('binance',sym)].olaylar)==1


def test_generation_cutoff_rejects_even_volume_accepted(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);sym='TESTUSDT';b._v78_binance_connection([sym],True)
    n=int(time.time()*1000)
    b._binance_akis_trade('binance',sym,100,1,'buy',n-1_000)
    assert b._real_volume.accepted==1
    assert b.eski_v78_motor.stats['before_generation_rejected']==1
    assert ('binance',sym) not in b.akis._kayitlar


def test_reconnect_clears_old_events_and_counts(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch); sym=key[1]
    other=('okx','OTHER');b.akis.ekle(*other,100,1,'buy',int(time.time()*1000))
    b._v78_binance_connection([sym],False)
    assert d._flow_start_ms==0 and not b.akis._kayitlar[key].olaylar
    assert len(b.akis._kayitlar[other].olaylar)==1
    assert d.hiz_uzun==0
    b._v78_binance_connection([sym],True)
    assert d._flow_start_ms>0 and not b.akis._kayitlar[key].olaylar
    assert b.eski_v78_motor.stats['binance_reconnect_symbols']==1
    assert b.eski_v78_motor.stats['book_events_cleared']==40


def test_id_gap_clears_and_restarts_generation(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch)
    old_epoch=b.eski_v78_motor._epochs[key[1]]
    b._v78_binance_gap(key[1])
    assert d._flow_start_ms>0 and d.hiz_uzun==0 and not b.akis._kayitlar[key].olaylar
    assert b.eski_v78_motor._epochs[key[1]]==old_epoch+1
    assert b.eski_v78_motor.stats['binance_gap_reset_symbols']==1


def test_invalid_reset_clears_flow(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch)
    b._binance_akis_trade('binance',key[1],-1,1,'buy',int(time.time()*1000))
    assert not b.akis._kayitlar[key].olaylar and b._real_volume.invalid==1
    assert d.hiz_uzun==0 and b.eski_v78_motor.stats['binance_gap_reset_symbols']==1


@pytest.mark.parametrize('change',['down','reconnect','warmup','continuity'])
def test_after_await_disconnect_generation_warmup_and_continuity(tmp_path,monkeypatch,change):
    b=bot_factory(tmp_path,monkeypatch);key,d=bootstrap_candidate(b,monkeypatch);m=b.eski_v78_motor
    async def candle(*args):
        if change=='down': b._v78_binance_connection([key[1]],False)
        elif change=='reconnect':
            b._v78_binance_connection([key[1]],False);b._v78_binance_connection([key[1]],True)
            d.hiz_uzun=1.;d.son_hacim_ts=int(time.time()*1000)  # forged warmup still cannot pass changed generation
        elif change=='warmup':d.hiz_uzun=0
        else:b.akis._kayitlar[key].olaylar.clear()
        return {'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}}
    m.candles=candle
    asyncio.run(m.cycle())
    b._sinyal_dispatch.assert_not_awaited()
    assert m.stats[('v4_volume_changed' if change in ('down','warmup') else 'connection_or_warmup_changed') if change!='continuity' else 'continuity_changed']==1


def test_after_await_happy_path_dispatches(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);bootstrap_candidate(b,monkeypatch)
    b.eski_v78_motor.candles=AsyncMock(return_value={'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}})
    asyncio.run(b.eski_v78_motor.cycle())
    assert b._sinyal_dispatch.await_count==1 and b.eski_v78_motor.stats['dispatched']==1


def test_okx_does_not_reuse_binance_epoch(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);bootstrap_candidate(b,monkeypatch,'okx')
    b.eski_v78_motor.candles=AsyncMock(return_value={'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}})
    asyncio.run(b.eski_v78_motor.cycle())
    assert b._sinyal_dispatch.await_count==1


def test_watchdog_real_5_second_only_new_source_stops(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);bootstrap_candidate(b,monkeypatch)
    m=b.eski_v78_motor
    async def slow(*a):await asyncio.sleep(20)
    m.candles=slow
    async def go():
        ticks=[]
        async def v4_dummy():
            for i in range(7):await asyncio.sleep(1);ticks.append(i)
        other=asyncio.create_task(v4_dummy()); start=time.monotonic()
        source=asyncio.create_task(m.run(),name='eski-v78-paper-sinyal')
        assert await asyncio.to_thread(m.watchdog_stopped.wait,6.5)
        elapsed=time.monotonic()-start
        await asyncio.sleep(.1)
        assert not source.done()  # V4 treats a finished task as bot-fatal
        assert not other.cancelled() and not other.done()
        await other
        source.cancel();await asyncio.gather(source,return_exceptions=True)
        return elapsed,ticks
    elapsed,ticks=asyncio.run(go())
    assert 4.9<=elapsed<6.5 and len(ticks)==7
    assert m.watchdog_stopped.is_set() and m.stats['watchdog_stops']==1
    assert not m.status()['active'] and not b.durdu
    b._sinyal_dispatch.assert_not_awaited()


def test_blocking_candle_cannot_dispatch_after_deadline(tmp_path,monkeypatch):
    b=bot_factory(tmp_path,monkeypatch);bootstrap_candidate(b,monkeypatch);m=b.eski_v78_motor
    m.watchdog_seconds=.05
    async def blocked(*a):
        time.sleep(.15)  # deliberately blocks only this synthetic event loop
        return {'score':20.,'_closed_5m_end_ms':int(time.time()*1000)-300000,'snapshot':{'entry_allowed':True}}
    m.candles=blocked
    async def go():
        task=asyncio.create_task(m.run())
        await asyncio.sleep(.25)
        assert not task.done()
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(go())
    assert m.watchdog_stopped.is_set() and m.stats['watchdog_stops']==1
    assert m.stats['deadline_reject']==1
    b._sinyal_dispatch.assert_not_awaited()


def test_per_source_candidate_and_rejection_counters(tmp_path,monkeypatch):
    from unittest.mock import Mock
    from scanner.ws_scanner import Sinyal
    b=bot_factory(tmp_path,monkeypatch)
    b.olay_csv=Mock();b.olay_yazici=Mock()
    monkeypatch.setattr(b,'_akis_sinyal_yaz',lambda *a:None)
    monkeypatch.setattr(b,'_zengin_sinyal_say',lambda *a:None)
    monkeypatch.setattr(b,'_zengin_sinyal_yaz',lambda *a:None)
    b._zengin_sinyali_degerlendir=AsyncMock(return_value={
        'accepted':False,'reasons':['mtf_opposes_entry','signal_stale_at_confirmation']})
    now=int(time.time()*1000)
    v4=Sinyal(ts_ms=now,exchange='binance',symbol='TESTUSDT',yon='LONG',etiket='ANI_YUKSELIS',fiyat=100,ret_pct=1,rvol=2,hacim_usd=1000,gecen_ms=2000)
    v78=Sinyal(ts_ms=now,exchange='binance',symbol='TESTUSDT',yon='LONG',etiket='V78_AKIS_ADAY',fiyat=100,ret_pct=1,rvol=2,hacim_usd=1000,gecen_ms=300000)
    async def go():
        await b._sinyal_dispatch(v4);await b._sinyal_dispatch(v78)
        await asyncio.gather(*list(b._akis_gorevler))
    asyncio.run(go())
    c=b.eski_v78_motor.stats
    for source in ('v4','v78'):
        assert c[f'source_{source}_candidate_dispatch_attempt']==1
        assert c[f'source_{source}_dispatch_queued']==1
        assert c[f'source_{source}_enrichment_rejected']==1
        assert c[f'source_{source}_enrichment_reason_mtf_opposes_entry']==1
        assert c[f'source_{source}_enrichment_reason_signal_stale_at_confirmation']==1
    assert b.sinyal_sayisi==2  # no event-level deduplication


def test_confirmation_counter_keeps_source_on_timeout(tmp_path,monkeypatch):
    from scanner.ws_scanner import Sinyal
    b=bot_factory(tmp_path,monkeypatch);now=int(time.time()*1000)
    s=Sinyal(ts_ms=now,exchange='binance',symbol='TESTUSDT',yon='LONG',etiket='V78_AKIS_ADAY',fiyat=100,ret_pct=1,rvol=2,hacim_usd=1000,gecen_ms=300000)
    b.teyit_bekleyen[(s.exchange,s.symbol)]=(now-1,100,s)
    b._teyit_isle(s.exchange,s.symbol,100,now)
    assert b.eski_v78_motor.stats['source_v78_confirmation_expired']==1
    assert b.teyit_iptal==1
