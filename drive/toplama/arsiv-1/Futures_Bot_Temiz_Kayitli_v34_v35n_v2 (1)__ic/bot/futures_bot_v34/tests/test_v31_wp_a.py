"""Sentetik yerel WP-A testleri; gerçek güç kesintisi veya Windows testi değil."""
import json,multiprocessing as mp,os,sys,types
import pytest
from reports import file_safety as s

def writer(path,pid):
    for i in range(100):s.atomic_json(path,{'pid':pid,'i':i})

def test_linux_multiyazar_atomik_json(tmp_path):
    path=str(tmp_path/'state.json')
    ps=[mp.Process(target=writer,args=(path,i)) for i in (1,2)]
    for p in ps:p.start()
    for p in ps:p.join(15);assert p.exitcode==0
    d=json.loads(open(path,encoding='utf-8').read());assert d['pid'] in (1,2) and d['i']==99
    assert not list(tmp_path.glob('.durum.*.tmp'))

def test_fsync_dosya_ve_dizin(tmp_path,monkeypatch):
    fsync=os.fsync;seen=[]
    def tracked(fd):seen.append(os.fstat(fd).st_mode);return fsync(fd)
    monkeypatch.setattr(os,'fsync',tracked)
    assert s.atomic_json(str(tmp_path/'s.json'),{'a':1}) is True
    assert len(seen)==2
    import stat
    assert stat.S_ISREG(seen[0]) and stat.S_ISDIR(seen[1])

def test_fsync_sonrasi_belirsiz_commit_gizlenmez(tmp_path,monkeypatch,caplog):
    real=os.fsync;calls=[]
    def fsync(fd):
        calls.append(1)
        if len(calls)==2:raise OSError('sentetik dizin hatası')
        return real(fd)
    monkeypatch.setattr(os,'fsync',fsync);p=tmp_path/'state.json'
    assert s.atomic_json(str(p),{'x':1}) is False
    assert json.loads(p.read_text())=={'x':1} and 'BELİRSİZ' in caplog.text

def test_bagimsiz_iki_instance_ikinciyi_reddeder(tmp_path):
    path=tmp_path/'instance.lock'
    with s.instance_lock(path):
        with pytest.raises(s.InstanceBusy):
            with s.instance_lock(path):pass
    with s.instance_lock(path):pass

def test_platform_secimi_mock(monkeypatch,tmp_path):
    calls=[]
    fake=types.SimpleNamespace(LK_LOCK=1,LK_NBLCK=2,LK_UNLCK=3,locking=lambda fd,mode,n:calls.append((mode,n)))
    monkeypatch.setitem(sys.modules,'msvcrt',fake);monkeypatch.setattr(sys,'platform','win32')
    with s.file_lock(str(tmp_path/'win.lock'),blocking=False):pass
    assert calls==[(2,1),(3,1)]
