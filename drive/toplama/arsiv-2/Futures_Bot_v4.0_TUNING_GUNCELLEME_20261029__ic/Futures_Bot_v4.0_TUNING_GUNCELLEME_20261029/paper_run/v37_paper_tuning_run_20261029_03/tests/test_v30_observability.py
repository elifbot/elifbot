"""Veri kaynağı: sentetik/çevrimdışı. Gerçek piyasa veya emir içermez."""
import concurrent.futures
import csv
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
import ws_bot
from reports.process_health import process_identity,durum_canli_mi

FIELDS=['ts_utc','exchange','symbol','yon','etiket','fiyat','ret_pct','rvol','hacim_usd','pencere_ms','gecikme_ms','durum','baglam_ret','baglam_vratio','baglam_vratio3']

def hazirla(monkeypatch,path):
    monkeypatch.setattr(ws_bot,'OLAY_CSV',str(path))
    b=ws_bot.Bot.__new__(ws_bot.Bot);b._olay_dosyasi_hazirla();return b

@pytest.mark.parametrize('exists',[True,False])
def test_yok_veya_bos_baslik(monkeypatch,tmp_path,exists):
    p=tmp_path/'event.csv'
    if exists:p.write_bytes(b'')
    b=hazirla(monkeypatch,p);b.olay_yazici.close()
    with p.open(newline='',encoding='utf-8') as f:assert next(csv.reader(f))==FIELDS

def test_dolu_dokunulmaz_ve_bom(monkeypatch,tmp_path):
    p=tmp_path/'event.csv';p.write_bytes(b'\xef\xbb\xbf'+(','.join(FIELDS)+'\r\na,b,c\r\n').encode());before=p.read_bytes()
    b=hazirla(monkeypatch,p);b.olay_yazici.close();assert p.read_bytes()==before

def test_yanlis_baslik_korunur(monkeypatch,tmp_path):
    p=tmp_path/'event.csv';p.write_text('yanlis,baslik\n');before=p.read_bytes()
    with pytest.raises(RuntimeError,match='başlığı'):hazirla(monkeypatch,p)
    assert p.read_bytes()==before

def test_es_zamanli_ortak_protokol_baslatmalari(monkeypatch,tmp_path):
    p=tmp_path/'event.csv';monkeypatch.setattr(ws_bot,'OLAY_CSV',str(p))
    def worker(_):
        b=ws_bot.Bot.__new__(ws_bot.Bot);b._olay_dosyasi_hazirla();b.olay_yazici.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(worker,range(30)))
    with p.open(newline='',encoding='utf-8') as f:assert list(csv.reader(f))==[FIELDS]

def state(now):return {'calisiyor':True,'pid':os.getpid(),'process_identity':process_identity(os.getpid()),'son_heartbeat_utc':now.isoformat()}

def test_heartbeat_kimlik_kontrolu():
    now=datetime.now(timezone.utc);d=state(now)
    assert durum_canli_mi(d,now)=='CANLI'
    assert durum_canli_mi({**d,'son_heartbeat_utc':(now-timedelta(seconds=31)).isoformat()},now)=='BAYAT'
    assert durum_canli_mi({**d,'son_heartbeat_utc':(now-timedelta(seconds=20)).isoformat()},now)=='SÜREÇ_DOĞRULANAMADI'
    assert durum_canli_mi({**d,'process_identity':{'boot_id':'wrong','start_ticks':1}},now)=='SÜREÇ_DOĞRULANAMADI'
    assert durum_canli_mi({**d,'pid':99999999},now)=='SÜREÇ_DOĞRULANAMADI'
    assert durum_canli_mi({**d,'calisiyor':False,'kapanis_nedeni':'normal'},now)=='KAPANDI'
    assert durum_canli_mi({},now)=='BİLİNMİYOR'
    assert durum_canli_mi({**d,'son_heartbeat_utc':(now+timedelta(seconds=60)).isoformat()},now)=='BİLİNMİYOR'

def test_panel_bayat_dosyayi_canli_gostermez(monkeypatch,tmp_path):
    import panel
    now=datetime.now(timezone.utc);d=state(now-timedelta(seconds=100))
    p=tmp_path/'durum.json';p.write_text(json.dumps(d))
    monkeypatch.setattr(panel,'DURUM',str(p)); result=panel.veri()
    assert result['kayit_calisiyor'] is True and result['calisiyor'] is False and result['canlilik']=='BAYAT'

@pytest.mark.parametrize('sig,kod,neden',[(signal.SIGTERM,143,'sinyal_15'),(signal.SIGINT,130,'kullanici_iptal'),(signal.SIGHUP,129,'sinyal_1')])
def test_sinyal_ve_heartbeat_izole_surecte(tmp_path,sig,kod,neden):
    root=Path(ws_bot.__file__).parent
    # bot taraması sahte: dış ağ/emir yok; gerçek signal ve process lifecycle.
    script='''import asyncio,sys,os\nimport ws_bot\nbase=sys.argv[1];ws_bot.TABAN=base;ws_bot.OLAY_CSV=os.path.join(base,"logs/olay.csv");ws_bot.DURUM_JSON=os.path.join(base,"logs/ws_durum.json")\nasync def fake(self):\n while True:\n  try: await asyncio.sleep(0.5)\n  except Exception: continue\nws_bot.Bot.calistir=fake\nraise SystemExit(ws_bot.main(["--sure-dk","5"]))\n'''
    env={**os.environ,'PYTHONPATH':str(root)}
    p=subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        path=tmp_path/'logs/ws_durum.json'; deadline=time.monotonic()+15
        while not path.exists() and p.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        assert path.exists(),p.communicate(timeout=2)
        first=json.loads(path.read_text());assert first['calisiyor'] and first['pid']==p.pid
        # heartbeat ön-dolgu aşamasında da ilerlemeli.
        deadline=time.monotonic()+9
        while time.monotonic()<deadline:
            try:later=json.loads(path.read_text())
            except (OSError,ValueError):continue
            if later['son_heartbeat_utc']!=first['son_heartbeat_utc']:break
            time.sleep(.1)
        assert later['son_heartbeat_utc']!=first['son_heartbeat_utc']
        p.send_signal(sig);out,err=p.communicate(timeout=10)
        assert p.returncode==kod,(out,err)
        close=json.loads((tmp_path/'logs/ws_kapanis.json').read_text());assert close['cikis_kodu']==kod and close['kapanis_nedeni']==neden
        last=json.loads(path.read_text());assert not last['calisiyor'] and last['kapanis_nedeni']==neden
        events=[json.loads(x) for x in (tmp_path/'logs/process_diagnostics.jsonl').read_text().splitlines()]
        assert any(x['event']=='signal' and x['signal']==sig.name for x in events)
        assert any(x['event']=='process_exit' and x['exit_code']==kod for x in events)
        assert (tmp_path/'logs/faulthandler.log').exists()
    finally:
        if p.poll() is None:p.kill();p.communicate()


def test_sigkill_sonucu_sebep_uydurmaz(tmp_path):
    root=Path(ws_bot.__file__).parent
    script="""import asyncio,sys,os
import ws_bot
base=sys.argv[1];ws_bot.TABAN=base;ws_bot.OLAY_CSV=os.path.join(base,'logs/olay.csv');ws_bot.DURUM_JSON=os.path.join(base,'logs/ws_durum.json')
async def fake(self): await asyncio.sleep(60)
ws_bot.Bot.calistir=fake
raise SystemExit(ws_bot.main(['--sure-dk','5']))
"""
    p=subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],cwd=root,env={**os.environ,'PYTHONPATH':str(root)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        status=tmp_path/'logs/ws_durum.json';deadline=time.monotonic()+15
        while not status.exists() and p.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        assert status.exists(),p.communicate(timeout=2)
        p.kill();p.communicate(timeout=5)
        d=json.loads(status.read_text());close=json.loads((tmp_path/'logs/ws_kapanis.json').read_text())
        assert close['kapanis_nedeni']=='bilinmiyor' and close['cikis_kodu'] is None
        assert durum_canli_mi(d)=='SÜREÇ_DOĞRULANAMADI'
    finally:
        if p.poll() is None:p.kill();p.communicate()

def test_tani_metrikleri_bilinmeyeni_none_raporlar(tmp_path):
    from reports.process_diagnostics import Diagnostics
    d=Diagnostics(str(tmp_path));d.sample()
    row=json.loads((tmp_path/'logs/process_diagnostics.jsonl').read_text())
    assert row['event']=='resource_sample' and row['ws_ping_pong_ms'] is None
    assert isinstance(row['threads'],list) and row['threads']
