"""Fetch unseen disjoint historical prices without inspecting returns/results.
Only metadata is printed. Price payload is gzip sealed until freeze manifest exists.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import gzip,hashlib,json,time,urllib.request

ROOT=Path(__file__).resolve().parent.parent
SEALED=ROOT/'reports/v94_sealed_historical_holdout.json.gz'


def request(url):
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'kripto-bot-v9.4-research'})
            with urllib.request.urlopen(req,timeout=35) as r:return json.load(r)
        except Exception:
            if attempt==2:raise
            time.sleep(1+attempt)


def main():
    if SEALED.exists():raise RuntimeError('Holdout already sealed. Do not silently replace.')
    dev=json.loads((ROOT/'reports/development_v93_snapshot.json').read_text())
    symbols=sorted(dev['frames'])
    end_ms=min(rows[0]['open_time'] for rows in dev['frames'].values())-86400000-1
    count=4800;start_ms=end_ms+1-count*300000
    def fetch(sym):
        remaining=count;cursor=end_ms;parts=[]
        while remaining:
            limit=min(1500,remaining)
            rows=request(f'https://www.binance.com/fapi/v1/klines?symbol={sym}&interval=5m&limit={limit}&endTime={cursor}')
            if not isinstance(rows,list) or len(rows)!=limit:raise RuntimeError(f'Incomplete {sym}')
            parts=rows+parts;remaining-=len(rows);cursor=int(rows[0][0])-1
        parsed=[dict(open_time=int(r[0]),open=float(r[1]),high=float(r[2]),low=float(r[3]),close=float(r[4]),volume=float(r[7]),taker_buy_quote=float(r[10])) for r in parts]
        if len({r['open_time'] for r in parsed})!=count:raise RuntimeError('Duplicate timestamps')
        try:
            funding=request(f'https://www.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={start_ms}&endTime={end_ms}&limit=1000')
            funding=[{'fundingTime':int(x['fundingTime']),'fundingRate':float(x['fundingRate'])} for x in funding]
            funding_status='FETCHED' if funding else 'EMPTY'
        except Exception:funding=[];funding_status='UNAVAILABLE'
        return sym,parsed,funding,funding_status
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(fetch,symbols))
    payload={'start_ms':start_ms,'end_ms':end_ms,'bars_per_symbol':count,
             'design':'Retrospective unseen non-overlapping historical block; NOT prospective chronological OOS.',
             'frames':{s:p for s,p,_,_ in rows},'funding':{s:f for s,_,f,_ in rows},'funding_status':{s:st for s,_,_,st in rows}}
    blob=gzip.compress(json.dumps(payload,separators=(',',':')).encode(),mtime=0)
    SEALED.write_bytes(blob)
    metadata={'sealed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),'symbols':symbols,'bars_per_symbol':count,
              'start_ms':start_ms,'end_ms':end_ms,'embargo_before_development_ms':86400000}
    (ROOT/'reports/v94_sealed_data_metadata.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata,indent=2))
if __name__=='__main__':main()
