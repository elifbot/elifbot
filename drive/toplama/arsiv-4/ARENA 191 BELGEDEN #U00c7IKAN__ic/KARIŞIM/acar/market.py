"""OKX herkese açık salt-okunur verisi. Anahtar ve emir uçları yoktur."""
import json, math, time, urllib.request
from .data import Bar,validate_bars
from .market_safety import funding_gate

BASE='https://www.okx.com'
INSTRUMENT='BTC-USDT-SWAP'

def _get(path):
    req=urllib.request.Request(BASE+path,headers={'User-Agent':'AcarPaper/1.0','Accept':'application/json','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=8) as r:
        raw=r.read(800_001)
        if len(raw)>800_000:raise ValueError('market yanıtı çok büyük')
    data=json.loads(raw)
    if data.get('code')!='0' or not isinstance(data.get('data'),list):raise ValueError('borsa yanıtı geçersiz')
    return data['data']

def candles():
    rows=_get('/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1m&limit=300')
    out=[]
    for row in rows:
        if not isinstance(row,list) or len(row)<9:raise ValueError('mum yanıtı eksik')
        if row[8]!='1':continue
        ts_ms=int(row[0]);
        if ts_ms%60_000:raise ValueError('mum zamanı yanlış')
        out.append(Bar(ts_ms//1000,float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5])))
    out.sort(key=lambda b:b.timestamp)
    validate_bars(out,60)
    if len(out)<60:raise ValueError('yetersiz kapalı mum')
    return out

def quote(now=None):
    row=_get('/api/v5/market/ticker?instId=BTC-USDT-SWAP')[0]
    if row.get('instId')!=INSTRUMENT:raise ValueError('yanlış enstrüman')
    q={'bid':float(row['bidPx']),'ask':float(row['askPx']),'time':int(row['ts'])/1000}
    now=time.time() if now is None else now
    if not all(math.isfinite(v) for v in q.values()) or not (0<q['bid']<=q['ask']) or now-q['time']>20 or q['time']-now>5:
        raise ValueError('geçersiz veya bayat kotasyon')
    q['spread_bps']=(q['ask']-q['bid'])/((q['ask']+q['bid'])/2)*10000
    return q

def funding(now=None):
    row=_get('/api/v5/public/funding-rate?instId=BTC-USDT-SWAP')[0]
    if row.get('instId')!=INSTRUMENT:raise ValueError('yanlış funding enstrümanı')
    if not row.get('fundingRate') or not row.get('fundingTime') or not row.get('ts'):raise ValueError('funding bilinmiyor')
    result={'rate':float(row['fundingRate']),'settlement':int(row['fundingTime'])/1000,'observed':int(row['ts'])/1000}
    if not all(math.isfinite(v) for v in result.values()):raise ValueError('funding sonlu değil')
    now=time.time() if now is None else now
    check=funding_gate('long',result['rate'],result['settlement'],result['observed'],now)
    if check['reason'] not in ('FUNDING_OK','FUNDING_ADVERSE'):raise ValueError('funding bayat veya belirsiz')
    return result
