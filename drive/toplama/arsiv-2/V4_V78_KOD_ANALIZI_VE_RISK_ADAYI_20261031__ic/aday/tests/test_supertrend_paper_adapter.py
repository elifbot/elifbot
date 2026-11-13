"""Paper-source contract, no network; no real orders or return claims."""
import asyncio,time
from unittest.mock import AsyncMock,Mock
import pytest
import ws_bot
from scanner.trend_paper_adapter import filtered_universe,closed_1m
from scanner.ws_scanner import SpikeDetector


def test_crypto_allowlist_both_venues_excludes_equity_and_unknown():
    bn,ok=filtered_universe({'BTCUSDT','AAPLUSDT','TSLAUSDT','UNKNOWNUSDT'},
        {'BTC-USDT-SWAP','AAPL-USDT-SWAP','TSLA-USDT-SWAP','XAU-USDT-SWAP'})
    assert bn=={'BTCUSDT'} and ok=={'BTC-USDT-SWAP'}


def candle_rows(now,ex='binance'):
    last=((now-2000)//60000)*60000-60000;rows=[]
    for i in range(260):
        ts=last-(259-i)*60000;close=400.-i;op=close+.5;high=close+1;low=close-1
        if ex=='binance':rows.append([ts,str(op),str(high),str(low),str(close),'100',ts+59999])
        else:rows.append([str(ts),str(op),str(high),str(low),str(close),'100','1','1','1'])
    return rows

@pytest.mark.parametrize('ex',['binance','okx'])
def test_closed_input_detects_downtrend_both_venues(ex):
    from strategies.trend_follower import TrendFollowerStrategy
    now=int(time.time()*1000);df=closed_1m(ex,candle_rows(now,ex),now)
    assert TrendFollowerStrategy().evaluate(df).signal=='SHORT'
    assert df.iloc[-1].open_time+60000<=now-2000

def test_conflicting_or_insufficient_data_fail_closed():
    now=int(time.time()*1000);rows=candle_rows(now)
    duplicate=rows[-1].copy();duplicate[4]='141.25';rows.append(duplicate)
    with pytest.raises(ValueError):closed_1m('binance',rows,now)
    with pytest.raises(ValueError):closed_1m('binance',rows[:50],now)


def make_bot(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
    (tmp_path/'logs').mkdir(exist_ok=True)
    detector=SpikeDetector();detector.ind_aktif=True
    b=ws_bot.Bot(detector,strateji='momentum',sinyal_zenginlestirme=True,risk_limitleri=True,
        binance_hacim_kaynagi='aggtrade',teyit_aktif=True,eski_v78_paper=True,trend_paper=True,
        sadece_kayit=True,defter_golge=False)
    b.indikator_hazir=True;b.asama='tarama';ex='binance';sym='BTCUSDT';key=(ex,sym);now=int(time.time()*1000)
    b._v78_binance_connection([sym],True);d=detector.durum(*key);d._flow_start_ms=now-40000
    for i in range(40):b.akis.ekle(*key,141,100,'sell',now-39000+i*1000)
    d.son_fiyat=141.;d.son_fiyat_ts=now;d.hiz_uzun=1.;d.son_hacim_ts=now;d.ret_2s=0.;d.rvol=2.
    class Response:
        def __init__(self,disconnect=False):self.disconnect=disconnect
        async def __aenter__(self):return self
        async def __aexit__(self,*_):return None
        def raise_for_status(self):pass
        async def json(self):
            if self.disconnect:b._v78_binance_connection([sym],False)
            return candle_rows(now)
    b._oturum=Mock();b._oturum.get=Mock(return_value=Response())
    import scanner.trend_paper_adapter as adapter
    monkeypatch.setattr(adapter,'giris_karari',lambda *a:(True,'synthetic',{}))
    return b,Response,now


def test_corrected_source_dispatches_only_after_fresh_checks(tmp_path,monkeypatch):
    b,Response,now=make_bot(tmp_path,monkeypatch);b._sinyal_dispatch=AsyncMock()
    asyncio.run(b.trend_paper_motor.evaluate_one('binance','BTCUSDT'))
    assert b.trend_paper_motor.stats['evaluated']==1 and b._sinyal_dispatch.await_count==1
    sig=b._sinyal_dispatch.await_args.args[0]
    assert (sig.yon,sig.etiket)==('SHORT','SUPERTREND_PAPER_ADAY')


def test_connection_lost_during_await_fails_closed(tmp_path,monkeypatch):
    b,Response,now=make_bot(tmp_path,monkeypatch);b._oturum.get=Mock(return_value=Response(True));b._sinyal_dispatch=AsyncMock()
    asyncio.run(b.trend_paper_motor.evaluate_one('binance','BTCUSDT'))
    assert b._sinyal_dispatch.await_count==0
    assert b.trend_paper_motor.stats['post_await_not_ready']==1


def test_strategy_candidate_cannot_bypass_mtf_reject(tmp_path,monkeypatch):
    b,Response,now=make_bot(tmp_path,monkeypatch)
    b.olay_csv=Mock();b.olay_yazici=Mock()
    monkeypatch.setattr(b,'_akis_sinyal_yaz',lambda *a:None)
    monkeypatch.setattr(b,'_zengin_sinyal_say',lambda *a:None)
    monkeypatch.setattr(b,'_zengin_sinyal_yaz',lambda *a:None)
    b._pozisyon_ac=Mock()
    b._zengin_sinyali_degerlendir=AsyncMock(return_value={'accepted':False,'reasons':['mtf_opposes_entry']})
    async def run():
        await b.trend_paper_motor.evaluate_one('binance','BTCUSDT')
        await asyncio.gather(*list(b._akis_gorevler))
    asyncio.run(run())
    b._pozisyon_ac.assert_not_called()
    assert b.eski_v78_motor.stats['source_supertrend_enrichment_reason_mtf_opposes_entry']==1


def test_option_is_off_by_default_and_requires_paper_source(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path));monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
    assert ws_bot.Bot(SpikeDetector()).trend_paper_motor is None
    with pytest.raises(ValueError):ws_bot.Bot(SpikeDetector(),trend_paper=True)


def test_audit_failure_stops_only_new_source(tmp_path,monkeypatch):
    b,_,_=make_bot(tmp_path,monkeypatch);m=b.trend_paper_motor
    m.path=str(tmp_path/'missing'/'audit.jsonl')
    with pytest.raises(OSError):m.record({'x':1})
    assert m.stop.is_set() and not b.durdu and not b.eski_v78_motor.watchdog_stopped.is_set()


def test_real_five_second_watchdog_stops_only_trend_source(tmp_path,monkeypatch):
    b,_,_=make_bot(tmp_path,monkeypatch);m=b.trend_paper_motor
    b.indikator_evrenleri={'binance':{'BTCUSDT'}}
    async def slow(*args):await asyncio.sleep(20)
    m.evaluate_one=slow
    async def main():
        ticks=[]
        async def v4_dummy():
            for i in range(7):await asyncio.sleep(1);ticks.append(i)
        other=asyncio.create_task(v4_dummy());src=asyncio.create_task(m.run())
        assert await asyncio.to_thread(m.stop.wait,6.5)
        await asyncio.sleep(.15)
        assert not other.cancelled() and not other.done() and not b.durdu
        await other
        src.cancel();await asyncio.gather(src,return_exceptions=True)
        return ticks
    assert len(asyncio.run(main()))==7 and m.stats['watchdog_stops']==1
    assert not b.eski_v78_motor.watchdog_stopped.is_set()
