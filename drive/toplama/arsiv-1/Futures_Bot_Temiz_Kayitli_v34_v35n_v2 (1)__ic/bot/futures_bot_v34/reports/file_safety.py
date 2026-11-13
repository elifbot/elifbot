"""Ortak protokol kilitleri ve JSON yazımı; çoklu yazar = çoklu bot güvenliği değildir."""
from __future__ import annotations
from contextlib import contextmanager
import json
import logging
import os
import sys
import tempfile

class InstanceBusy(RuntimeError):
    pass

@contextmanager
def file_lock(path, blocking=True):
    """Aynı kilit yolunu kullanan süreçleri serileştir. Kilit hatası saklanmaz."""
    os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True)
    with open(path,'a+b') as f:
        if sys.platform == 'win32':
            import msvcrt
            f.seek(0,os.SEEK_END)
            if f.tell()==0:
                f.write(b'\0');f.flush()
            f.seek(0)
            mode=msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(f.fileno(),mode,1)
            try:yield
            finally:
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            mode=fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(f.fileno(),mode)
            try:yield
            finally:fcntl.flock(f.fileno(),fcntl.LOCK_UN)

@contextmanager
def instance_lock(path):
    """Aynı çalışma dizininde ikinci bot örneğini kesin başlatma."""
    try:
        guard=file_lock(path,blocking=False)
        guard.__enter__()
    except (BlockingIOError,PermissionError) as e:
        raise InstanceBusy('Bu çalışma dizininde başka bir bot çalışıyor') from e
    try:yield
    finally:guard.__exit__(None,None,None)

def atomic_json(path,data):
    """İşbirlikçi yazarları kilitle; dosya + POSIX dizin fsync; tek dosya düzeyi."""
    path=os.path.abspath(path);directory=os.path.dirname(path)
    os.makedirs(directory,exist_ok=True)
    with file_lock(path+'.lock'):
        fd,tmp=tempfile.mkstemp(dir=directory,prefix='.durum.',suffix='.tmp')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump(data,f,ensure_ascii=False,allow_nan=False)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
            # Windows'ta dizin fsync doğrulanmadı; POSIX'te hata saklanmaz.
            if sys.platform != 'win32':
                # replace gerçekleştiyse geri alma mümkün değildir. Bu noktadaki
                # fsync hatasını istisna ile rollback yapılmış gibi sunma:
                # state görünürdür, kalıcılığı belirsizdir ve uyarı yazılır.
                try:
                    dfd=os.open(directory,os.O_RDONLY | getattr(os,'O_DIRECTORY',0))
                    try:os.fsync(dfd)
                    finally:os.close(dfd)
                except OSError as exc:
                    logging.getLogger(__name__).error('Dizin fsync başarısız; commit kalıcılığı BELİRSİZ: %s',exc)
                    return False
            else:
                logging.getLogger(__name__).warning('Windows dizin fsync doğrulanmadı')
                return False
            return True
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
