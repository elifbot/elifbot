#!/usr/bin/env python3
"""Verilen test_tek.py için 60 günlük cache doğrula, eksikleri hız limitli tamamla.
Kullanıcının test_tek.py dosyasını değiştirmez. Yalnız araştırma verisi indirir.
"""
import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path
import aiohttp
import numpy as np
import sweep_v2 as s

SYMS='BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,ATOMUSDT,LTCUSDT,UNIUSDT,ARBUSDT,OPUSDT,APTUSDT,SUIUSDT,INJUSDT,NEARUSDT'.split(',')
out=Path('reports/oos_test'); work=out/'kontrollu'; work.mkdir(parents=True,exist_ok=True)
start=int(datetime(2026,5,31,tzinfo=timezone.utc).timestamp()*1000)
end=int(datetime(2026,7,30,tzinfo=timezone.utc).timestamp()*1000)-1
count=86400; last=end+1-s.MINUTE
assert start==end+1-count*s.MINUTE

def name(sym):return out/f'oos_{sym}_2026-05-31_2026-07-30.json'

def check_json(sym):
    data=json.loads(name(sym).read_text())
    # Ham Binance verisiyse kapanış zamanlarını da doğrula.
    if any(len(row)<6 for row in data):raise ValueError(f'{sym}: JSON şeması geçersiz')
    if all(len(row)>=7 for row in data):
        if any(int(row[6])!=int(row[0])+s.MINUTE-1 for row in data):raise ValueError(f'{sym}: kapanış zamanı hatalı')
    arr=np.asarray([[int(x[0])]+[float(v) for v in x[1:6]] for x in data],dtype=np.float64)
    s.validate_data(arr,start,last,count)
    return arr

async def run():
    missing=[]
    for sym in SYMS:
        if name(sym).exists():
            arr=check_json(sym);s.atomic_npz(work/'veriler'/f'{sym}.npz',arr)
            print(f'{sym}: mevcut JSON {count}/{count} mum bağımsız doğrulandı',flush=True)
        else:missing.append(sym)
    print('Kontrollü tamamlanacak: '+', '.join(missing),flush=True)
    async with aiohttp.ClientSession() as session:
        gate=s.RateGate()
        for sym in missing:
            npz=await s.download_symbol(session,gate,work,sym,60,end)
            arr=s.load_npz(npz,start,last,count)
            # test_tek.py yalnız ilk 6 sütunu okur; öteki sütunları uydurmuyoruz.
            tmp=name(sym).with_suffix('.tmp')
            with tmp.open('w') as fh:
                json.dump([[int(row[0]),*[float(v) for v in row[1:]]] for row in arr],fh,separators=(',',':'))
            tmp.replace(name(sym));check_json(sym)
            print(f'{sym}: test_tek uyumlu 6 sütunlu JSON hazır',flush=True)
    for sym in SYMS:check_json(sym)
    print('TÜM 19 SEMBOL: 86400/86400, zaman ve OHLCV doğrulandı',flush=True)

if __name__=='__main__':
    try:asyncio.run(run())
    except Exception as e:print(f'KONTROL HATASI: {type(e).__name__}: {e}',file=sys.stderr,flush=True);sys.exit(1)
