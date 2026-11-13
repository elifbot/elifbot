import json
from threading import RLock

class Journal:
    def __init__(self,path): self.path=path; self.lock=RLock()
    def append(self,obj):
        with self.lock:
            with open(self.path,'a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')
