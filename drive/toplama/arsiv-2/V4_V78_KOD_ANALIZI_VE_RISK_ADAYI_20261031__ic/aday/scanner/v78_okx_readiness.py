"""Paper opt-in: diagnose and repair only missing, verified OKX 1m candles.

This never creates a candle or modifies ticker/flow/risk thresholds. Existing
candles are never replaced. A repair changes V4's indicator *input* while the
v7.8 flag is on; that can change V4 paper decisions and is explicitly reported.
"""
from __future__ import annotations
import asyncio, math, time
import aiohttp
from data.feed_utils import ensure_url_allowed
from scanner.ind_aktif import kapali_mum_ekle, metrik

URL='https://www.okx.com/api/v5/market/candles'

def diagnose(detektor,symbols,now_ms):
    end=int(now_ms)//60_000-1
    result=[]
    for symbol in sorted(set(symbols)):
        d=detektor.durumlar.get(('okx',symbol));reasons=[]
        if d is None:
            result.append({'symbol':symbol,'reasons':['sembol_durumu_yok'],'missing_count':60});continue
        missing=[x for x in range(end-59,end+1) if x not in d.ind_mum]
        if missing:reasons.append('kapali_mum_eksik')
        price=d.son_fiyat
        if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:reasons.append('fiyat_gecersiz')
        if not missing:
            rows=[d.ind_mum[x] for x in range(end-59,end+1)]
            if sum(x[3] for x in rows)<=0 or sum(x[4] for x in rows)<=0:reasons.append('hacim_yok')
        if metrik(d,now_ms,price) is None and not reasons:reasons.append('metrik_gecersiz')
        age=int(now_ms)-int(d.son_fiyat_ts or 0)
        if age<0:reasons.append('fiyat_gelecek')
        elif age>detektor.tazelik_ms:reasons.append('fiyat_bayat')
        if reasons:
            result.append({'symbol':symbol,'reasons':reasons,'missing_count':len(missing),
                           'missing_first_mid':missing[0] if missing else None,'missing_last_mid':missing[-1] if missing else None,
                           'price_age_ms':age if d.son_fiyat_ts else None})
    return result

async def repair_missing(session,detektor,symbols,*,now_ms=None,pace_sec=.35):
    """Repair target missing 1m closes, serial pacing, fail-closed errors.

    Request a public OKX response; accept only HTTP 200, code 0, confirmed,
    aligned, fully closed, internally valid rows from required missing minutes.
    Never replace an already present row, including data arriving during await.
    No synthetic fill or change to flow/volume deques is allowed.
    """
    now=int(time.time()*1000) if now_ms is None else int(now_ms);end=now//60000-1
    window=set(range(end-59,end+1));targets=[]
    for sym in sorted(set(symbols)):
        d=detektor.durumlar.get(('okx',sym))
        if d is not None:
            missing=window.difference(d.ind_mum)
            if missing:targets.append((sym,d,missing))
    result={'targets':len(targets),'requests':0,'added':0,'completed':0,'errors':0,
            'http_429':0,'bad_rows':0,'conflict_minutes':0,'symbols':[]}
    for index,(sym,d,missing) in enumerate(targets):
        if index and pace_sec:await asyncio.sleep(max(0,float(pace_sec)))
        entry={'symbol':sym,'missing_before':len(missing),'added':0,'error':None}
        result['requests']+=1
        try:
            ensure_url_allowed(URL)
            async with session.get(URL,params={'instId':sym,'bar':'1m','limit':'100'},
                                   timeout=aiohttp.ClientTimeout(total=4)) as r:
                if r.status!=200:
                    result['http_429']+=int(r.status==429);raise ValueError('http_'+str(r.status))
                body=await r.json()
            if not isinstance(body,dict) or body.get('code')!='0' or not isinstance(body.get('data'),list):
                raise ValueError('invalid_okx_response')
            now_after=int(time.time()*1000) if now_ms is None else int(now_ms)
            observed={};conflicts=set()
            for row in body['data']:
                try:
                    ts=int(row[0]);mid=ts//60000
                    if ts%60000 or ts+60000>now_after or str(row[8])!='1' or mid not in missing:continue
                    data=tuple(row[i] for i in (2,3,4,6,7))
                    if mid in observed and observed[mid]!=data:conflicts.add(mid)
                    else:observed[mid]=data
                except (IndexError,TypeError,ValueError,OverflowError):result['bad_rows']+=1
            result['conflict_minutes']+=len(conflicts)
            for mid,data in sorted(observed.items()):
                if mid in conflicts or mid in d.ind_mum:continue
                if kapali_mum_ekle(d,mid,*data):entry['added']+=1
                else:result['bad_rows']+=1
            entry['complete']=all(mid in d.ind_mum for mid in missing)
            result['added']+=entry['added'];result['completed']+=int(entry['complete'])
        except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,TypeError,KeyError) as exc:
            entry['error']=str(exc)[:100] or type(exc).__name__;result['errors']+=1
        result['symbols'].append(entry)
    return result
