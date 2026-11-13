#!/usr/bin/env python3
"""90 günlük fade taraması. Bağımsız araştırma; gerçek emir veya strateji değişikliği yok.

Örnek kullanıcı taslağından farklar: sabit ortak 90 günlük kapanmış mum
penceresi, parça başına disk checkpoint, sıralı/eksiksiz veri doğrulaması,
kontrollü ağırlık limiti, yönlendirme reddi, önceki tamamlanmış sembolleri
sonraki gruba ekleme ve vektörlü ön hesaplama. 5×4×4×4 = 320 kombinasyon.
"""
from __future__ import annotations
import argparse
import asyncio
import csv
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path
import aiohttp
import numpy as np
from data.feed_utils import ensure_url_allowed
from reports.file_safety import file_lock

HOSTLAR=('https://www.binance.com/fapi/v1/klines','https://fapi.binance.com/fapi/v1/klines')
MINUTE=60_000
PAGE=1500
HOLD=240
BAG=(0.,.3,.5,.8,1.2)
RET=(.3,.5,1.,2.)
RVOL=(2.,3.,5.,10.)
TPSL=((.5,1.),(1.,2.),(2.,3.),(1.25,2.))
ROOT=Path(__file__).resolve().parent

class RateGate:
    """Tüm coroutine'ler için dakikalık 2400 ağırlığa ihtiyatlı hız sınırı."""
    def __init__(self):self.lock=asyncio.Lock();self.next=0.;self.until=0.
    async def wait(self):
        async with self.lock:
            now=time.monotonic();delay=max(0.,self.next-now,self.until-now)
            if delay:await asyncio.sleep(delay)
            self.next=time.monotonic()+.36
    def defer(self,seconds):self.until=max(self.until,time.monotonic()+max(0.,seconds))

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.tmp_',suffix='.json')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def atomic_npz(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.tmp_',suffix='.npz')
    try:
        with os.fdopen(fd,'wb') as f:np.savez_compressed(f,data=data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def validate_data(arr,first,last,count):
    if not isinstance(arr,np.ndarray) or arr.shape!=(count,6):raise ValueError('mum sayısı/şekli eksik')
    if not np.isfinite(arr).all():raise ValueError('sonlu olmayan mum')
    ts=arr[:,0]
    if ts[0]!=first or ts[-1]!=last or np.any(np.diff(ts)!=MINUTE):raise ValueError('mumlarda boşluk, tekrar veya zaman uyuşmazlığı')
    o,h,l,c,v=(arr[:,i] for i in (1,2,3,4,5))
    if np.any(o<=0) or np.any(h<=0) or np.any(l<=0) or np.any(c<=0) or np.any(v<0):raise ValueError('geçersiz OHLCV')
    if np.any(h<np.maximum.reduce((o,c,l))) or np.any(l>np.minimum.reduce((o,c,h))):raise ValueError('tutarsız OHLC')
    return arr

def decode_page(payload,end_ms,limit):
    if not isinstance(payload,list) or len(payload)!=limit:raise ValueError(f'API sayfası eksik: {len(payload) if isinstance(payload,list) else "geçersiz"}/{limit}')
    last=end_ms+1-MINUTE
    first=last-(limit-1)*MINUTE
    try:
        closes=np.asarray([int(row[6]) for row in payload],dtype=np.int64)
        arr=np.asarray([[int(row[0]),float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5])] for row in payload],dtype=np.float64)
    except (IndexError,ValueError,TypeError) as exc:raise ValueError('geçersiz API mum verisi') from exc
    if np.any(closes != arr[:,0].astype(np.int64)+MINUTE-1):raise ValueError('kapanmamış/yanlış süreli mum')
    return validate_data(arr,first,last,limit)

async def get_page(session,gate,sym,limit,end_ms):
    params={'symbol':sym,'interval':'1m','limit':str(limit),'endTime':str(end_ms)}
    for host in HOSTLAR:
        url=host
        ensure_url_allowed(url)
        for attempt in range(5):
            await gate.wait()
            try:
                async with session.get(url,params=params,timeout=aiohttp.ClientTimeout(total=25),allow_redirects=False) as r:
                    if 300<=r.status<400:raise RuntimeError('API yönlendirmesi reddedildi')
                    if r.status in (403,451):print(f'{sym}: HTTP {r.status}, alternatif host deneniyor',flush=True);break
                    if r.status==418:raise RuntimeError('HTTP 418: IP engeli, istekler durduruldu')
                    if r.status==429:
                        raw=r.headers.get('Retry-After','60')
                        try:delay=max(1.,float(raw))
                        except ValueError:delay=60.
                        gate.defer(delay);print(f'{sym}: HTTP 429, {delay:g} sn bekleniyor',flush=True)
                        if attempt==4:raise RuntimeError('HTTP 429 tekrarlı; veri eksik')
                        continue
                    if r.status>=500:
                        if attempt==4:raise RuntimeError(f'API HTTP {r.status}')
                        gate.defer(2**attempt);continue
                    if r.status!=200:raise RuntimeError(f'API HTTP {r.status}: {(await r.text())[:160]}')
                    weight=r.headers.get('x-mbx-used-weight-1m')
                    if weight and weight.isdigit() and int(weight)>=1700:
                        gate.defer(62-(time.time()%60));print(f'İstek ağırlığı {weight}: sonraki dakika bekleniyor',flush=True)
                    payload=await r.json(content_type=None)
                    return decode_page(payload,end_ms,limit)
            except (asyncio.TimeoutError,aiohttp.ClientError) as exc:
                if attempt==4:raise RuntimeError(f'API bağlantı hatası: {type(exc).__name__}') from exc
                gate.defer(2**attempt)
        else:continue
    raise RuntimeError(f'{sym}: hiçbir host veri vermedi')

def load_npz(path,first,last,count):
    with np.load(path,allow_pickle=False) as f:
        if set(f.files)!={'data'}:raise ValueError(f'{path}: yanlış dosya şeması')
        data=f['data']
    return validate_data(data,first,last,count)

async def download_symbol(session,gate,out,symbol,days,end_ms):
    total=days*1440; first=end_ms+1-total*MINUTE;last=end_ms+1-MINUTE
    dest=out/'veriler'/f'{symbol}.npz'
    if dest.exists():
        load_npz(dest,first,last,total)
        print(f'{symbol}: cache {total} doğrulanmış mum',flush=True);return dest
    parts=out/'parcalar'/symbol;parts.mkdir(parents=True,exist_ok=True)
    pages=math.ceil(total/PAGE)
    for no in range(pages):
        already=no*PAGE;limit=min(PAGE,total-already);cursor=end_ms-already*MINUTE
        page_last=cursor+1-MINUTE;page_first=page_last-(limit-1)*MINUTE
        path=parts/f'{no:04d}.npz'
        if path.exists():load_npz(path,page_first,page_last,limit)
        else:
            arr=await get_page(session,gate,symbol,limit,cursor)
            atomic_npz(path,arr)
        if (no+1)%10==0 or no+1==pages:print(f'{symbol}: {no+1}/{pages} sayfa kaydedildi',flush=True)
    arrays=[]
    for no in range(pages-1,-1,-1):
        already=no*PAGE;limit=min(PAGE,total-already);cursor=end_ms-already*MINUTE
        last0=cursor+1-MINUTE;first0=last0-(limit-1)*MINUTE
        arrays.append(load_npz(parts/f'{no:04d}.npz',first0,last0,limit))
    data=validate_data(np.concatenate(arrays,axis=0),first,last,total)
    atomic_npz(dest,data);load_npz(dest,first,last,total)
    for p in parts.glob('*.npz'):p.unlink()
    parts.rmdir()
    print(f'{symbol}: {total}/{total} kesintisiz kapanmış mum doğrulandı',flush=True)
    return dest

def features(a,split):
    n=len(a);i=np.arange(120,n-HOLD,dtype=np.int64)
    cum=np.r_[0.,np.cumsum(a[:,5])]
    previous=cum[i-60]-cum[i-120];recent=cum[i]-cum[i-60]
    rv=np.divide(recent,previous,out=np.zeros_like(recent),where=previous>0)
    ret=(a[i,4]/a[i,1]-1)*100
    bg=(a[i,4]/a[i-3,1]-1)*100
    mask=((i+HOLD<split)|(i>=split))&(np.abs(ret)>=min(RET))&(rv>=min(RVOL))
    return [(int(ix),float(re),float(v),float(b),'egitim' if ix<split else 'test') for ix,re,v,b in zip(i[mask],ret[mask],rv[mask],bg[mask])]

def simule(a,i,yon,tp,sl,uc,ky):
    direction=1 if yon=='long' else -1;entry_i=i+1
    g=a[entry_i,1]*(1+direction*ky/100);target=g*(1+direction*tp/100);stop=g*(1-direction*sl/100)
    end_i=entry_i+HOLD-1;reason='timeout';raw=a[end_i,4]
    for j in range(entry_i,end_i+1):
        o,h,l=a[j,1],a[j,2],a[j,3]
        if direction==1:
            if j>entry_i and o<=stop:raw=o;reason='sl_acilis';break
            if l<=stop:raw=stop;reason='sl';break
            if h>=target:raw=target;reason='tp';break
        else:
            if j>entry_i and o>=stop:raw=o;reason='sl_acilis';break
            if h>=stop:raw=stop;reason='sl';break
            if l<=target:raw=target;reason='tp';break
    exit_price=raw*(1-direction*ky/100)
    return (direction*(exit_price/g-1)*100-2*uc,reason)

def aggregate(items,prefix):
    n=len(items);values=[x[0] for x in items]
    return {prefix+'_adet':n,prefix+'_ort':sum(values)/n if n else '',
            prefix+'_kaz':sum(x>0 for x in values)/n if n else '',
            prefix+'_timeout':sum(x[1]=='timeout' for x in items),
            prefix+'_tp':sum(x[1]=='tp' for x in items),
            prefix+'_sl':sum(x[1] in ('sl','sl_acilis') for x in items),
            prefix+'_timeout_orani':sum(x[1]=='timeout' for x in items)/n if n else ''}

def sweep(arrays,uc,ky):
    first=next(iter(arrays.values()));n=len(first);split=int(n*.70);signals=[];series={}
    for sym,a in arrays.items():
        if not np.array_equal(a[:,0],first[:,0]):raise ValueError('semboller ortak zaman ızgarasında değil')
        series[sym]=a
        signals.extend((sym,*x) for x in features(a,split))
    print(f'Ön aday: {len(signals)} sembol-zaman; eğitim/test kesimi: {datetime.fromtimestamp(first[split,0]/1000,timezone.utc).isoformat()}',flush=True)
    cached={}
    for sym,i,r,v,b,phase in signals:
        yon='short' if r>0 else 'long'
        for tp,sl in TPSL:cached[(sym,i,tp,sl)]=simule(series[sym],i,yon,tp,sl,uc,ky)
    results=[]
    for b in BAG:
        for r in RET:
            for v in RVOL:
                subset=[s for s in signals if abs(s[2])>=r and s[3]>=v and abs(s[4])>=b]
                for tp,sl in TPSL:
                    train=[cached[(s[0],s[1],tp,sl)] for s in subset if s[5]=='egitim']
                    test=[cached[(s[0],s[1],tp,sl)] for s in subset if s[5]=='test']
                    results.append({'baglam':b,'ret':r,'rvol':v,'tp':tp,'sl':sl,**aggregate(train,'eg'),**aggregate(test,'te')})
    return results,split,len(signals)

def write_results(out,results,split,signals,symbols,start_ms,end_ms,uc,ky):
    path=out/'kombinasyonlar.csv'
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(results[0]));writer.writeheader();writer.writerows(results)
    both30=[r for r in results if r['eg_adet']>=30 and r['te_adet']>=30]
    train30=sorted((r for r in results if r['eg_adet']>=30),key=lambda x:x['eg_ort'],reverse=True)
    yt=[r for r in results if r['te_adet'] and r['te_timeout']/r['te_adet']>.8]
    meta={'veri_kaynagi':'canli_public_tarihsel','semboller':symbols,'mum_sembol':len(symbols),
          'baslangic_utc':datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat(),
          'bitis_haric_utc':datetime.fromtimestamp((end_ms+1)/1000,timezone.utc).isoformat(),
          'kesim_utc':datetime.fromtimestamp((start_ms+split*MINUTE)/1000,timezone.utc).isoformat(),
          'kombinasyon':len(results),'yalniz_fade':True,'aday':signals,'egitim_ve_test_30':len(both30),
          'test_timeout_yuzde80_ustu':len(yt),'ucret_pct_tarafta':uc,'kayma_pct_tarafta':ky,
          'uyarilar':['tarihsel OHLC; canlı bot değil','test dönemi model seçiminde kullanılmaz','portföy/funding yok; sonuç kârlılık kanıtı değil','RVOL base hacim 60dk/önceki60dk','bağlam i-3 açık ile i kapanış arası yaklaşık 4 dk','her dönemin son 240 dakikasındaki sinyaller dışlanır']}
    atomic_json(out/'ozet.json',meta)
    print(f'CSV: {path}\nKombinasyon: {len(results)} (sadece fade)',flush=True)
    print(f'Her iki dönemde ≥30 işlem: {len(both30)}',flush=True)
    print(f'Test işlemlerinin >%80’i timeout: {len(yt)}/{len(results)} kombinasyon',flush=True)
    print('Eğitim ortalamasına göre ilk 10 (eğitim ≥30; test sayıları ayrıca gösterilir):',flush=True)
    for x in train30[:10]:
        test_value=f"{x['te_ort']:+.4f}%" if x['te_adet'] else 'hesaplanamaz'
        print(f"bag={x['baglam']} ret={x['ret']} rvol={x['rvol']} tp/sl={x['tp']}/{x['sl']} eğt={x['eg_adet']}({x['eg_ort']:+.4f}%) test={x['te_adet']}({test_value})",flush=True)
    print('UYARI: Sadece tarihsel araştırma; finansman/portföy yok, canlı kârlılık sonucu değil.',flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--gun',type=int,default=90);ap.add_argument('--semboller',default='BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT')
    ap.add_argument('--kayma',type=float,default=.05);ap.add_argument('--ucret',type=float,default=.04)
    ap.add_argument('--cikti',default='reports/sweep_v2_90gun')
    args=ap.parse_args()
    requested=[x.strip().upper() for x in args.semboller.split(',') if x.strip()]
    if not requested or len(requested)!=len(set(requested)) or any(not s.isalnum() or len(s)>25 for s in requested):ap.error('geçersiz veya tekrarlı sembol')
    if not 1<=args.gun<=365 or any(not math.isfinite(x) or x<0 or x>=100 for x in (args.ucret,args.kayma)):ap.error('parametre geçersiz')
    out=Path(args.cikti);out=out if out.is_absolute() else ROOT/out;out.mkdir(parents=True,exist_ok=True)
    manifest=out/'pencere.json'
    with file_lock(str(out/'sweep.instance.lock'),blocking=False):
        if manifest.exists():
            window=json.loads(manifest.read_text(encoding='utf-8'))
            if window.get('gun')!=args.gun:raise ValueError('önceden sabitlenmiş pencere farklı: yeni çıktı dizini kullanın')
            end_ms=int(window['end_ms'])
        else:
            end_ms=(int(time.time()*1000)//MINUTE)*MINUTE-1
            atomic_json(manifest,{'gun':args.gun,'end_ms':end_ms,'expected':args.gun*1440,'source':'Binance USD-M public klines'})
        first=end_ms+1-args.gun*1440*MINUTE
        print(f'=== sweep_v2 | {args.gun} gün | {len(requested)} yeni/istenen sembol | sadece fade | 320 kombinasyon ===',flush=True)
        print(f'Ortak pencere: {datetime.fromtimestamp(first/1000,timezone.utc).isoformat()} — {datetime.fromtimestamp((end_ms+1)/1000,timezone.utc).isoformat()} (bitiş hariç)',flush=True)
        print('Eksik/geçersiz sayfalar tamamlanmadan cache ve sweep başarı sayılmaz.',flush=True)
        async def run():
            gate=RateGate();connector=aiohttp.TCPConnector(limit=4)
            async with aiohttp.ClientSession(connector=connector) as session:
                return await asyncio.gather(*(download_symbol(session,gate,out,s,args.gun,end_ms) for s in requested))
        asyncio.run(run())
        # Önceki komutlarda tamamlanan cache'ler kullanıcı isteğindeki gibi eklenir.
        symbols=sorted(set(requested)|{p.stem for p in (out/'veriler').glob('*.npz')})
        arrays={s:load_npz(out/'veriler'/f'{s}.npz',first,end_ms+1-MINUTE,args.gun*1440) for s in symbols}
        print(f'Analize alınan toplam sembol ({len(symbols)}): {", ".join(symbols)}',flush=True)
        results,split,signals=sweep(arrays,args.ucret,args.kayma)
        write_results(out,results,split,signals,symbols,first,end_ms,args.ucret,args.kayma)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'HATA: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
        sys.exit(1)
