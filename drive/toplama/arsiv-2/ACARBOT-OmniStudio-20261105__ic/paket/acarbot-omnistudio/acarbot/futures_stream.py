"""PAPER için değil gözlem: borsa WebSocket 5dk mumlarını anlık topla.

Kapanmış mumlar SQLite'a yazılır; açık mumlar güncel bellek gözlemidir.
Boşluk/yeniden bağlanma güvenlik olayları izlenir, otomatik geriye dönük
onarım veya strateji/emir yürütmesi yapılmaz. Gerçek/özel API emri yok.
"""
from __future__ import annotations
import argparse, asyncio, json, math, random, sqlite3, time
from collections import Counter, defaultdict
from datetime import datetime,timezone
from pathlib import Path
import aiohttp
from .futures_market import MARKETS,instruments

INTERVAL=300000

def ms():return int(time.time()*1000)
def iso():return datetime.now(timezone.utc).isoformat()

def parse_binance(inst, data):
    if data.get('e')!='kline':return None
    k=data.get('k') or {}
    if k.get('s')!=inst.symbol or k.get('i')!='5m':return None
    # COIN-M v=contract volume, contractSize=USD face value; q is BASE.
    vol=float(k['v'])*float(inst.contract_value) if inst.market=='binance_coinm' else float(k['q'])
    return (int(k['t']),float(k['o']),float(k['h']),float(k['l']),float(k['c']),vol,k.get('x') is True)

def parse_okx(inst,data):
    arg=data.get('arg') or {}
    if arg.get('channel')!='candle5m' or arg.get('instId')!=inst.symbol:return []
    rows=[]
    for r in data.get('data',[]):
        if len(r)>=9:rows.append((int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[7]),r[8]=='1'))
    return rows

def valid(row):
    ts,o,h,l,c,v,closed=row
    return (ts>0 and ts%INTERVAL==0 and all(math.isfinite(x) for x in (o,h,l,c,v))
            and min(o,h,l,c)>0 and v>=0 and l<=min(o,c) and h>=max(o,c))

class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS candles(market TEXT NOT NULL,symbol TEXT NOT NULL,open_ms INTEGER NOT NULL,o REAL NOT NULL,h REAL NOT NULL,l REAL NOT NULL,c REAL NOT NULL,quote_volume REAL NOT NULL,observed_ms INTEGER NOT NULL,PRIMARY KEY(market,symbol,open_ms))')
        self.db.execute('CREATE TABLE IF NOT EXISTS incidents(market TEXT NOT NULL,symbol TEXT NOT NULL,at_ms INTEGER NOT NULL,kind TEXT NOT NULL,details TEXT NOT NULL)')
        self.db.commit();self.pending=0
        self.last={(m,s):t for m,s,t in self.db.execute('SELECT market,symbol,MAX(open_ms) FROM candles GROUP BY market,symbol')}
    def insert(self,inst,row,observed):
        ts,o,h,l,c,v,_=row;key=(inst.market,inst.symbol);prev=self.last.get(key)
        cur=self.db.execute('INSERT OR IGNORE INTO candles VALUES(?,?,?,?,?,?,?,?,?)',(inst.market,inst.symbol,ts,o,h,l,c,v,observed))
        if not cur.rowcount:return 'duplicate'
        if prev is not None and ts>prev+INTERVAL:
            self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?)',(inst.market,inst.symbol,observed,'GAP',json.dumps({'previous':prev,'current':ts})))
            status='gap'
        else:status='inserted'
        self.last[key]=max(ts,prev or ts);self.pending+=1
        if self.pending>=100:self.commit()
        return status
    def commit(self):self.db.commit();self.pending=0
    def close(self):self.commit();self.db.close()

def chunks(seq,n):return [seq[i:i+n] for i in range(0,len(seq),n)]

async def run(out,duration=600,per_market=0,db_path=None):
    if duration<=0 or per_market<0:raise ValueError('geçersiz süre/limit')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    store=Store(db_path or (out/'candles.sqlite3')); began=iso(); start=time.monotonic();counts=Counter();sets=defaultdict(set); markets={}; logs=[]
    timeouts=aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeouts,trust_env=True,headers={'User-Agent':'Mozilla/5.0 ACARBOT research'}) as session:
      async def discover(market,base,path):
        try:
          async with session.get(base+path) as res:
            if res.status!=200:raise RuntimeError('HTTP '+str(res.status))
            data=await res.json(content_type=None)
          li=instruments(market,data);total=len(li)
          if not total:raise RuntimeError('empty universe')
          if per_market:li=li[:per_market]
          markets[market]={'discovered':total,'selected':len(li),'status':'AVAILABLE'}
          return li
        except Exception as e:
          markets[market]={'status':'ERROR','error':f'{type(e).__name__}: {str(e)[:160]}'};return []
      arrays=await asyncio.gather(*(discover(m,*p) for m,p in MARKETS.items()))
      bymarket=dict(zip(MARKETS,arrays)); deadline=time.monotonic()+duration
      allins=[i for arr in arrays for i in arr];bykey={(i.market,i.symbol):i for i in allins}
      for market,arr in bymarket.items():
        for i in arr:sets[market+':selected'].add(i.symbol)
      def onrow(inst,row):
        if not valid(row):counts['invalid_rows']+=1;return
        sets[inst.market+':data'].add(inst.symbol);counts['updates']+=1
        ts,o,h,l,c,v,closed=row
        if not closed:return
        observed=ms();age=observed-(ts+INTERVAL)
        if age < -5000:counts['future_closed']+=1;return
        status=store.insert(inst,row,observed);counts[status]+=1
        if status=='duplicate':return
        sets[inst.market+':closed'].add(inst.symbol);counts['closed_fresh_90s' if 0<=age<=90000 else 'closed_other_age']+=1
        counts['latency_ms_sum']+=max(0,age);counts['latency_ms_max']=max(counts['latency_ms_max'],max(0,age))
        if 0<=age<=5000:counts['closed_5s']+=1
      async def shard(market, group, delay):
        await asyncio.sleep(delay); lookup={x.symbol:x for x in group}; backoff=1;number=0
        if market.startswith('okx'):
          url='wss://ws.okx.com/ws/v5/business';request={'op':'subscribe','args':[{'channel':'candle5m','instId':x.symbol} for x in group]}
        else:
          url='wss://fstream.binance.com/market/ws' if market=='binance_usdm' else 'wss://dstream.binance.com/market/ws'
          request={'method':'SUBSCRIBE','params':[x.symbol.lower()+'@kline_5m' for x in group],'id':1}
        while time.monotonic()<deadline:
          try:
            async with session.ws_connect(url,heartbeat=20,timeout=15,max_msg_size=8*1024*1024) as ws:
              number+=1;counts['connections']+=1
              if number>1:counts['reconnects']+=1
              await ws.send_json(request);backoff=1
              while time.monotonic()<deadline:
                try:msg=await asyncio.wait_for(ws.receive(),min(25,max(.01,deadline-time.monotonic())))
                except asyncio.TimeoutError:
                  if time.monotonic()>=deadline:break
                  # OKX expects a text ping on quiet channels.
                  if market.startswith('okx'):await ws.send_str('ping')
                  continue
                if msg.type in (aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.ERROR):raise RuntimeError('websocket closed')
                if msg.type!=aiohttp.WSMsgType.TEXT or msg.data=='pong':continue
                try:
                  d=json.loads(msg.data)
                  if market.startswith('okx'):
                    arg=d.get('arg') or {};symbol=arg.get('instId'); inst=lookup.get(symbol)
                    if d.get('event')=='subscribe' and inst:sets[market+':ack'].add(symbol);continue
                    if d.get('event')=='error':counts['subscribe_errors']+=1;logs.append(str(d)[:400]);continue
                    if inst:
                      for row in parse_okx(inst,d):onrow(inst,row)
                  else:
                    if 'result' in d and d.get('id')==1:
                      if d['result'] is None:sets[market+':ack'].update(lookup)
                      continue
                    if 'code' in d:counts['subscribe_errors']+=1;logs.append(str(d)[:400]);continue
                    payload=d.get('data',d); symbol=payload.get('s');inst=lookup.get(symbol)
                    if inst:
                      row=parse_binance(inst,payload)
                      if row:onrow(inst,row)
                except (ValueError,TypeError,KeyError,IndexError,OverflowError,json.JSONDecodeError):counts['parse_errors']+=1
          except asyncio.CancelledError:raise
          except Exception as e:
            counts['connection_errors']+=1
            if len(logs)<40:logs.append(market+': '+type(e).__name__+': '+str(e)[:180])
            await asyncio.sleep(min(backoff+random.random()*.3,max(0,deadline-time.monotonic())))
            backoff=min(backoff*2,30)
      jobs=[];index=0
      for market,arr in bymarket.items():
        for group in chunks(arr,75):
          jobs.append(asyncio.create_task(shard(market,group,index*.38)));index+=1
      print(f'ACTIVE {duration}s: {len(allins)} instruments, {len(jobs)} shards',flush=True)
      async def commit_loop():
        while time.monotonic()<deadline:
          await asyncio.sleep(min(2,max(0,deadline-time.monotonic())));store.commit()
      commit_task=asyncio.create_task(commit_loop())
      try:await asyncio.sleep(max(0,deadline-time.monotonic()))
      finally:
        for job in jobs:job.cancel()
        commit_task.cancel();await asyncio.gather(*jobs,commit_task,return_exceptions=True)
    for market,info in markets.items():
      for name in ('ack','data','closed'):info[name+'_symbols']=len(sets[market+':'+name])
    dbcounts=dict(store.db.execute('SELECT market,COUNT(*) FROM candles GROUP BY market').fetchall());incident_count=store.db.execute('SELECT count(*) FROM incidents').fetchone()[0];store.close()
    result={'status':'OBSERVATION_ONLY','started_utc':began,'finished_utc':iso(),'duration_target':duration,'total_sec':round(time.monotonic()-start,3),'markets':markets,'counts':dict(counts),'database_candles':dbcounts,'database_gap_incidents':incident_count,'errors':logs[:40],'real_orders':0,'paper_orders':0,'limits':['No execution or PAPER strategy in this collector','Reconnection and gaps are flagged; no REST backfill implemented','No health proof for symbols without updates','Only confirmed exchange close flags are recorded','Universe refresh requires restart']}
    (out/'SONUC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('SONUÇ',json.dumps(result,ensure_ascii=False),flush=True);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--duration',type=float,default=600);p.add_argument('--limit-per-market',type=int,default=0);p.add_argument('--db');a=p.parse_args();asyncio.run(run(a.out,a.duration,a.limit_per_market,a.db))
if __name__=='__main__':main()
