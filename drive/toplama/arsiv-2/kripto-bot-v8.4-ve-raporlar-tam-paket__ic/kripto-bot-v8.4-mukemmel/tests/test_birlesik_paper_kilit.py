"""Yeni adayın dar kapsamlı paper kayıt testleri, gerçek emir/ağ içermez."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
from src.birlesik_spike import SpikeShadow
from src.state_store import StateStore
from src.risk import Position

HERE=Path(__file__).resolve().parent

def run_child(tmp_path, scenario):
    return subprocess.run([sys.executable,str(HERE/'_birlesik_senaryo_child.py'),str(tmp_path),scenario],
                          cwd=HERE.parent,env=os.environ.copy(),capture_output=True,text=True,timeout=15)

def read_db(tmp_path):
    return sqlite3.connect(tmp_path/'v78.db')

def test_gercek_surec_fill_sonrasi_cokunce_pending_ve_restart_kilidi(tmp_path):
    run=run_child(tmp_path,'crash')
    assert run.returncode==73,run.stderr
    with read_db(tmp_path) as c:
        assert c.execute('select symbol,status from paper_intents').fetchall()==[('BTC/USDT','PENDING')]
        assert c.execute('select count(*) from open_positions').fetchone()[0]==0
        assert c.execute('pragma quick_check').fetchone()[0]=='ok'
    again=run_child(tmp_path,'restart')
    assert again.returncode==0,again.stderr
    assert 'RESULT positions= [] breaker= False guard= True' in again.stdout

def test_commit_sonrasi_yanit_kaybi_yeni_girisi_ve_restarti_kilitler(tmp_path):
    run=run_child(tmp_path,'lost_ack')
    assert run.returncode==0,run.stderr
    assert "RESULT positions= ['BTC/USDT'] breaker= False guard= True" in run.stdout
    with read_db(tmp_path) as c:
        assert c.execute('select symbol,status from paper_intents').fetchall()==[('BTC/USDT','OPEN')]
        assert c.execute('select symbol from open_positions').fetchall()==[('BTC/USDT',)]
        account=json.loads(c.execute("select value from bot_meta where key='paper_account'").fetchone()[0])
        assert account['balance']==pytest.approx(999.74995)
    again=run_child(tmp_path,'restart')
    assert again.returncode==0,again.stderr
    assert "RESULT positions= ['BTC/USDT'] breaker= False guard= True" in again.stdout

def test_pending_yanit_kaybi_dolumu_engeller_ve_restart_kilitli(tmp_path):
    run=run_child(tmp_path,'pending_lost_ack')
    assert run.returncode==0,run.stderr
    assert 'RESULT positions= [] breaker= False guard= True' in run.stdout
    with read_db(tmp_path) as c:
        assert c.execute('select symbol,status from paper_intents').fetchall()==[('BTC/USDT','PENDING')]
        assert c.execute('select count(*) from open_positions').fetchone()[0]==0
    again=run_child(tmp_path,'restart')
    assert again.returncode==0,again.stderr
    assert 'RESULT positions= [] breaker= False guard= True' in again.stdout

def test_normal_acilis_tek_islem_ve_restart_kilitli(tmp_path):
    run=run_child(tmp_path,'normal')
    assert run.returncode==0,run.stderr
    assert "RESULT positions= ['BTC/USDT', 'ETH/USDT'] breaker= False guard= False" in run.stdout
    with read_db(tmp_path) as c:
        assert c.execute('select count(*) from open_positions').fetchone()[0]==2
        assert c.execute("select count(*) from paper_intents where status='OPEN'").fetchone()[0]==2
        data=json.loads(c.execute("select value from bot_meta where key='paper_account'").fetchone()[0])
        assert data['balance']==pytest.approx(999.4999)
    again=run_child(tmp_path,'restart')
    assert again.returncode==0,again.stderr
    assert 'guard= True' in again.stdout

def test_acilis_finansal_meta_yazimi_hatasi_atomik_rollback(tmp_path):
    store=StateStore(tmp_path/'db.sqlite')
    store.prepare_paper_open('op-1',{'symbol':'BTC/USDT','side':'LONG'})
    with store._conn() as c:
        c.execute("""CREATE TRIGGER injected_failure BEFORE INSERT ON bot_meta
          WHEN NEW.key='paper_account' BEGIN SELECT RAISE(ABORT,'injected'); END""")
    p=Position(symbol='BTC/USDT',side='LONG',entry=100.,qty=1.,stop=90.)
    with pytest.raises(sqlite3.IntegrityError):
        store.commit_paper_open('op-1',p,{'balance':999}, {},{}, {})
    with store._conn() as c:
        assert c.execute('select count(*) from open_positions').fetchone()[0]==0
        assert c.execute("select status from paper_intents where operation_id='op-1'").fetchone()[0]=='PENDING'
        assert c.execute("select count(*) from bot_meta where key='paper_account'").fetchone()[0]==0
    assert StateStore(tmp_path/'db.sqlite').paper_requires_recovery() is True

def test_iki_es_zamanli_pending_reddedilir(tmp_path):
    store=StateStore(tmp_path/'db.sqlite')
    store.prepare_paper_open('a',{'symbol':'BTC/USDT'})
    with pytest.raises(RuntimeError, match='unresolved'):
        store.prepare_paper_open('b',{'symbol':'ETH/USDT'})

def test_birlesik_ana_program_paper_disi_modlarda_kilitli(monkeypatch):
    # Contract changed intentionally: paper entry is no longer always blocked.
    # Test actual config mode, not an unrelated MODE environment variable.
    from src import main
    for mode in ('testnet','live'):
        monkeypatch.setattr(main, 'load_config', lambda mode=mode: {'genel': {'mod': mode}})
        with pytest.raises(RuntimeError,match='YALNIZ PAPER'):
            asyncio.run(main.main())

def test_spike_shadow_girise_baglanmaz_girdi_dogrular():
    class Fake:
        def __init__(self): self.calls=[]
        def besle_hacim(self,*a):self.calls.append(('hacim',a)); return None
        def besle_fiyat(self,*a):self.calls.append(('fiyat',a)); return None
    d=Fake(); shadow=SpikeShadow(d)
    assert shadow.observe_trade('binance','BTC/USDT',100,2,received_ms=120000) is None
    assert shadow.observe_trade('binance','BTC/USDT',101,1,received_ms=121000) is None
    assert d.calls[0][1][2]==200 and d.calls[2][1][2]==301
    shadow.observe_trade('binance','BTC/USDT',100,1,received_ms=119000)
    shadow.observe_trade('binance','BTC/USDT',float('nan'),1,received_ms=122000)
    assert shadow.status()['rejected']==2
    assert shadow.status()['trade_route'] is False

def test_gercek_eski_spike_dedektoru_sadece_shadow_olayi_uretir():
    from scanner.ws_scanner import SpikeDetector
    detector=SpikeDetector(baglam_aktif=False,isinma_ms=1000,ret_min_pct=.2,
        rvol_min=.5,min_hacim_usd=10,kisa_ms=1000,uzun_ms=10000,soguma_ms=30000)
    shadow=SpikeShadow(detector)
    signals=[]
    for i in range(14):
        signal=shadow.observe_trade('binance','BTC/USDT',100 if i<10 else 101,2,
                                   received_ms=60000+i*1000)
        if signal: signals.append(signal)
    assert len(signals)==1 and signals[0].etiket=='ANI_YUKSELIS'
    assert shadow.status()['mode']=='shadow_only' and not shadow.status()['trade_route']
