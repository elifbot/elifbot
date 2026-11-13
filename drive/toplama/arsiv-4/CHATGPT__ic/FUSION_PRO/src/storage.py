import sqlite3, json, time
class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(path,check_same_thread=False); self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('CREATE TABLE IF NOT EXISTS events(ts INTEGER, kind TEXT, payload TEXT)'); self.db.commit()
    def log(self,kind,payload): self.db.execute('INSERT INTO events VALUES(?,?,?)',(int(time.time()*1000),kind,json.dumps(payload,ensure_ascii=False,default=str))); self.db.commit()
