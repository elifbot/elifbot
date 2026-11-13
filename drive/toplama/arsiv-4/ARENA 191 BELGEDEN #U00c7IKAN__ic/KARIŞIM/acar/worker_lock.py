"""Mutual exclusion among the supported CLI market workers (Linux/Unix)."""
import fcntl,os,stat
from pathlib import Path
class WorkerLock:
 def __init__(self,db):self.path=Path(str(Path(db).resolve())+'.worker.lock');self.fd=None
 def __enter__(self):
  flags=os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
  fd=os.open(self.path,flags,0o600)
  try:
   if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('worker lock is not a regular file')
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BaseException:
   os.close(fd);raise
  self.fd=fd;return self
 def __exit__(self,*args):
  try:fcntl.flock(self.fd,fcntl.LOCK_UN)
  finally:os.close(self.fd);self.fd=None
