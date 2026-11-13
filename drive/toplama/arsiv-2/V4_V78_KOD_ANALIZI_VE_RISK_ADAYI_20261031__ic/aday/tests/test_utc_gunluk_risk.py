"""UTC daily equity risk in the WS paper integration. Offline synthetic clocks."""
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import pytest
import ws_bot
from scanner.ws_scanner import Sinyal

DAY1=int(datetime(2026,10,30,23,59,55,tzinfo=timezone.utc).timestamp()*1000)
DAY2=int(datetime(2026,10,31,0,0,2,tzinfo=timezone.utc).timestamp()*1000)

def make_bot(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
    b=ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0.,durumlar={}),
                 strateji='momentum',giris_modu='market',teyit_aktif=False,risk_limitleri=True)
    b.durum_dosya=str(tmp_path/'state.json')
    return b

def sig(ms,sym='TESTUSDT'):
    return Sinyal(ts_ms=ms,exchange='binance',symbol=sym,yon='LONG',etiket='T',fiyat=100,
                  ret_pct=0.6,rvol=6.,hacim_usd=10000.,gecen_ms=60000)

def test_new_utc_day_allows_entry_when_only_yesterdays_loss_blocked(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    b.portfoy.day_start_balance=1000.;b.portfoy.balance=940.
    b._risk_son_gozlem_ms=DAY1  # explicit near-boundary observation
    assert b.portfoy.daily_loss_limit_hit()
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY2/1000)
    assert b._pozisyon_ac(sig(DAY2))=='acildi'
    assert b.portfoy.day_start_balance==pytest.approx(940.)
    assert b._risk_gun_utc=='2026-10-31'


def test_same_day_restart_preserves_loss_limit(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    b.portfoy.day_start_balance=1000.;b.portfoy.balance=940.;b._durum_kaydet(strict=True)
    b2=make_bot(tmp_path,monkeypatch);assert b2._durum_yukle()==0
    assert b2._risk_gun_utc=='2026-10-30' and not b2._risk_gun_belirsiz
    assert b2._pozisyon_ac(sig(DAY1))=='engel:günlük zarar limiti'
    assert b2.portfoy.day_start_balance==1000.


def test_old_state_without_risk_date_recovers_but_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    b=make_bot(tmp_path,monkeypatch);b._durum_kaydet(strict=True)
    data=json.loads((tmp_path/'state.json').read_text());data.pop('utc_risk_version')
    (tmp_path/'state.json').write_text(json.dumps(data))
    b2=make_bot(tmp_path,monkeypatch);assert b2._durum_yukle()==0
    assert b2._risk_gun_belirsiz
    assert b2._pozisyon_ac(sig(DAY1))=='engel:gunluk_risk_bilinmiyor'
    b2._durum_kaydet(strict=True)
    b3=make_bot(tmp_path,monkeypatch);b3._durum_yukle()
    assert b3._risk_gun_belirsiz


def test_state_write_failure_rolls_back_rollover_and_blocks(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    b.portfoy.day_start_balance=1000.;b.portfoy.balance=940.
    b._risk_son_gozlem_ms=DAY1
    def fail(**kw):raise OSError('synthetic state failure')
    monkeypatch.setattr(b,'_durum_kaydet',fail)
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_state_yazilamadi')
    assert b._risk_gun_utc=='2026-10-30' and b.portfoy.day_start_balance==1000.


def test_manual_safety_block_is_never_cleared_by_utc_rollover(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30';b.portfoy.blocked_new_positions=True
    b._risk_son_gozlem_ms=DAY1
    assert b._gunluk_risk_guncelle(DAY2)==(True,'')
    assert b.portfoy.blocked_new_positions
    b2=make_bot(tmp_path,monkeypatch);b2._durum_yukle()
    assert b2.portfoy.blocked_new_positions


def test_backward_utc_day_fails_closed(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-31'
    assert b._gunluk_risk_guncelle(DAY1)==(False,'gunluk_risk_saat_geri')


def test_open_position_at_midnight_blocks_new_entries_but_not_exit(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    res=b.portfoy.open_position('binance','BTCUSDT','LONG',100.,100.,now_ms=DAY1)
    assert res.ok
    p=b.portfoy.positions[('binance','BTCUSDT')];p.last_price=99.;p.last_price_ts=DAY2
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_bilinmiyor')
    assert b._risk_gun_utc=='2026-10-30' and b._risk_gun_belirsiz
    # The risk guard is only for entries; existing paper positions remain closable.
    rec=b.portfoy.close_position('binance','BTCUSDT',99.,now_ms=DAY2,reason='synthetic')
    assert rec is not None and not b.portfoy.positions
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_bilinmiyor')
    b._durum_kaydet(strict=True)
    b2=make_bot(tmp_path,monkeypatch);b2._durum_yukle();assert b2._risk_gun_belirsiz


def test_invalid_risk_equity_fails_closed(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    b.portfoy.day_start_balance=float('nan')
    assert b._gunluk_risk_guncelle(DAY1)==(False,'gunluk_risk_equity_gecersiz')


def test_auto_restart_without_durum_devam_keeps_loss_history(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot,'TABAN',str(tmp_path))
    monkeypatch.setattr(ws_bot.Bot,'_olay_dosyasi_hazirla',lambda self:None)
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    def new():return ws_bot.Bot(SimpleNamespace(genislik=0,genislik_oran=0.,durumlar={}),
                 strateji='momentum',giris_modu='market',teyit_aktif=False,risk_limitleri=True)
    a=new();a.portfoy.day_start_balance=1000.;a.portfoy.balance=940.;a._durum_kaydet(strict=True)
    b=new()  # no durum_devam flag
    assert b.portfoy.balance==940. and b.portfoy.day_start_balance==1000.
    assert b._pozisyon_ac(sig(DAY1))=='engel:günlük zarar limiti'


def test_entry_is_rolled_back_on_precommit_state_error(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30';balance=b.portfoy.balance
    b._risk_son_gozlem_ms=DAY1
    def fail(**kw):raise OSError('synthetic precommit failure')
    monkeypatch.setattr(b,'_durum_kaydet',fail)
    assert b._pozisyon_ac(sig(DAY1))=='engel:pozisyon_state_yazilamadi'
    assert not b.portfoy.positions and b.portfoy.balance==balance and b.acilan==0


def test_shutdown_exit_at_day_boundary_flags_unknown_before_close(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    assert b.portfoy.open_position('binance','BTCUSDT','LONG',100.,100.,now_ms=DAY1).ok
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY2/1000)
    assert b._kapat_ve_kaydet('binance','BTCUSDT',99.,DAY2,'synthetic') is not None
    assert not b.portfoy.positions and b._risk_gun_belirsiz
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_bilinmiyor')


def test_ambiguous_fsync_at_rollover_never_allows_entry(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    b._risk_son_gozlem_ms=DAY1
    monkeypatch.setattr(b,'_durum_kaydet',lambda **kw:False)
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_state_kalicilik_belirsiz')
    assert b._risk_gun_belirsiz and b._risk_gun_utc=='2026-10-31'
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_bilinmiyor')


def test_ambiguous_fsync_at_entry_keeps_position_and_blocks_later_entries(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30'
    b._risk_son_gozlem_ms=DAY1
    monkeypatch.setattr(b,'_durum_kaydet',lambda **kw:False)
    assert b._pozisyon_ac(sig(DAY1))=='acildi'
    assert ('binance','TESTUSDT') in b.portfoy.positions and b._risk_gun_belirsiz
    assert b._pozisyon_ac(sig(DAY1,'OTHERUSDT'))=='engel:gunluk_risk_bilinmiyor'


def test_long_unobserved_flat_overnight_gap_does_not_reset_risk(tmp_path,monkeypatch):
    noon1=int(datetime(2026,10,30,12,0,tzinfo=timezone.utc).timestamp()*1000)
    noon2=int(datetime(2026,10,31,12,0,tzinfo=timezone.utc).timestamp()*1000)
    monkeypatch.setattr(ws_bot.time,'time',lambda:noon1/1000)
    b=make_bot(tmp_path,monkeypatch)
    assert b._gunluk_risk_guncelle(noon1)==(True,'')
    b.portfoy.balance=940.;b.portfoy.day_start_balance=1000.
    monkeypatch.setattr(ws_bot.time,'time',lambda:noon2/1000)
    ok,reason=b._gunluk_risk_guncelle(noon2)
    assert not ok and reason=='gunluk_risk_bilinmiyor'
    assert b.portfoy.day_start_balance==1000. and b._risk_gun_belirsiz


def test_near_midnight_checkpoint_survives_restart_and_flat_rollover(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    first=make_bot(tmp_path,monkeypatch)
    assert first._gunluk_risk_guncelle(DAY1)==(True,'')
    first.portfoy.balance=940.;first.portfoy.day_start_balance=1000.;first._durum_kaydet(strict=True)
    second=make_bot(tmp_path,monkeypatch);second._durum_yukle()
    assert second._risk_son_gozlem_ms==DAY1
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY2/1000)
    assert second._gunluk_risk_guncelle(DAY2)==(True,'')
    assert second.portfoy.day_start_balance==940.


def test_old_state_without_checkpoint_stays_blocked_after_overnight_restart(tmp_path,monkeypatch):
    monkeypatch.setattr(ws_bot.time,'time',lambda:DAY1/1000)
    first=make_bot(tmp_path,monkeypatch);first._durum_kaydet(strict=True)
    data=json.loads((tmp_path/'state.json').read_text());data.pop('utc_risk_checkpoint_ms')
    (tmp_path/'state.json').write_text(json.dumps(data))
    second=make_bot(tmp_path,monkeypatch);second._durum_yukle()
    assert second._risk_son_gozlem_ms is None
    assert second._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_bilinmiyor')


def test_near_midnight_pending_funding_blocks_rollover(tmp_path,monkeypatch):
    b=make_bot(tmp_path,monkeypatch);b._risk_gun_utc='2026-10-30';b._risk_son_gozlem_ms=DAY1
    b.portfoy.funding_outbox=[{'pending':True}]
    assert b._gunluk_risk_guncelle(DAY2)==(False,'gunluk_risk_bilinmiyor')
