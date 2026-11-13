"""Girişteki kapalı mumlardan yalnız gözlem: asla emir/sinyal kapısı değildir.

Sinyalden sonra indirilen geçmiş, olay saatinde bilinmiş olmayı kanıtlamaz:
sonradan düzeltilmiş mumlar bulunabilir. Geleceğe açılan mumlar dışlanır;
sonuç 'retrospektif shadow' olarak etiketlenir. Eksik/stale veri = bilinmiyor.
"""
from __future__ import annotations
import math
import aiohttp
import pandas as pd
from data.feed_utils import ensure_url_allowed
from indicators.core import atr_wilder, bollinger, adx

BINANCE = 'https://www.binance.com/fapi/v1/klines'
OKX = 'https://www.okx.com/api/v5/market/candles'
GATES = ('vwap_yakin', 'bb_dar', 'atr_alti', 'trend_rejimi', 'hacimsiz')


def _frame(rows, exchange, duration, asof):
    """Kapalı ve doğru biçimli mumları doğrula, boşlukları uydurma."""
    parsed = {}
    for x in rows:
        try:
            if exchange == 'okx' and (len(x) < 9 or str(x[8]) != '1'):
                continue
            ts = int(x[0]); o,h,l,c = (float(x[i]) for i in (1,2,3,4))
            base,quote = (float(x[6]),float(x[7])) if exchange == 'okx' else (float(x[5]),float(x[7]))
            if ts < 0 or ts % duration or ts + duration > asof:
                continue
            if not all(math.isfinite(v) for v in (o,h,l,c,base,quote)):
                continue
            if min(o,h,l,c) <= 0 or h < max(o,c,l) or l > min(o,c,h) or min(base,quote) < 0:
                continue
            row = (ts,o,h,l,c,base,quote)
            if ts in parsed and parsed[ts] != row:
                raise ValueError('ayni mum zamani icin cakisan veriler')
            parsed[ts] = row
        except (TypeError, IndexError, OverflowError):
            continue
    data=sorted(parsed.values())
    # Sadece en son kesintisiz dizi kullanilir. Mum eklenmez veya doldurulmaz.
    suffix=[]
    for row in reversed(data):
        if suffix and suffix[-1][0]-row[0] != duration: break
        suffix.append(row)
    suffix.reverse()
    return pd.DataFrame(suffix, columns=['open_time','open','high','low','close','base','quote'])


def _finite(v):
    try:
        val=float(v)
        return val if math.isfinite(val) else None
    except (ValueError,TypeError): return None


def evaluate(rows1, rows15, exchange, asof, price, ret_pct):
    """Bağımsız karar: True=engellerdi, False=geçerdi, None=bilinmiyor.

    1m BB 20/2 ddof=1; p30 önceki 60 width; ATR14/price 1m;
    15m ADX14 + ATR14 yüzdesi p80 önceki 60 kapalı 15m; 1m z-score
    son kapalı mum vs önceki 20. Eşikler yalnız hipotezdir.
    """
    if exchange not in ('binance','okx') or not math.isfinite(price) or price<=0 or not math.isfinite(ret_pct):
        raise ValueError('gecersiz sinyal')
    a=_frame(rows1,exchange,60_000,asof); b=_frame(rows15,exchange,900_000,asof)
    gates={name:None for name in GATES}
    metrics={'bar_count_1m':len(a),'bar_count_15m':len(b)}
    fresh1=len(a)>0 and int(a.iloc[-1]['open_time']) == (asof//60_000)*60_000-60_000
    fresh15=len(b)>0 and int(b.iloc[-1]['open_time']) == (asof//900_000)*900_000-900_000
    metrics.update(fresh_1m=bool(fresh1),fresh_15m=bool(fresh15))
    if fresh1:
        # UTC gun basi itibariyle tum tamamlanmis mumlar bulunmali.
        start=(asof//86_400_000)*86_400_000
        day=a[a.open_time>=start]
        expected=(asof//60_000)*60_000-start
        if expected and len(day)==expected//60_000 and int(day.iloc[0].open_time)==start:
            vol=float(day.base.sum()); quote=float(day.quote.sum())
            vwap=quote/vol if vol>0 and quote>0 else None
            if vwap and math.isfinite(vwap):
                # base/quote birim hatasini fiyat araligi disinda yakala.
                if float(day.low.min()) <= vwap <= float(day.high.max()):
                    distance=(price/vwap-1)*100
                    metrics.update(vwap=vwap, vwap_distance_pct=distance)
                    gates['vwap_yakin']=abs(distance)<0.5
        bb=bollinger(a.close)['bb_width']
        if len(bb)>=80 and bb.iloc[-61:-1].notna().all() and pd.notna(bb.iloc[-1]):
            width=float(bb.iloc[-1]);p30=float(bb.iloc[-61:-1].quantile(.3))
            metrics.update(bb_width=width,bb_p30=p30);gates['bb_dar']=width<p30
        atr=_finite(atr_wilder(a).iloc[-1]) if len(a)>=14 else None
        if atr is not None and atr>0:
            atrpct=atr/price*100; ratio=abs(ret_pct)/atrpct
            metrics.update(atr_1m_pct=atrpct,ret_atr_ratio=ratio)
            gates['atr_alti']=ratio<1.5
        if len(a)>=21:
            prev=a.quote.iloc[-21:-1]; mean=float(prev.mean()); sd=float(prev.std(ddof=1))
            if math.isfinite(sd) and sd>0:
                z=(float(a.quote.iloc[-1])-mean)/sd
                metrics['volume_z_1m_closed']=z;gates['hacimsiz']=z<2.0
    if fresh15 and len(b)>=75:
        adx_value=_finite(adx(b)['adx'].iloc[-1])
        atr15=atr_wilder(b)/b.close*100
        prev=atr15.iloc[-61:-1]
        nowatr=_finite(atr15.iloc[-1])
        if adx_value is not None and nowatr is not None and len(prev)==60 and prev.notna().all():
            p80=float(prev.quantile(.8));metrics.update(adx_15m=adx_value,atr_15m_pct=nowatr,atr_15m_p80=p80)
            gates['trend_rejimi']=adx_value>35 and nowatr>p80
    return {'gates':gates,'metrics':metrics,'type':'retrospektif_kapali_mum_shadow',
            'asof_ms':asof,'volume_z_basis':'son_kapali_1m_quote_vs_onceki_20',
            'vwap_basis':'utc_oturum_kapali_1m_quote_base; cari mum haric'}


async def fetch_candles(session, exchange, symbol, asof, interval):
    duration={'1m':60_000,'15m':900_000}[interval]
    if exchange=='binance':
        url=BINANCE;params={'symbol':symbol,'interval':interval,'limit':1500 if interval=='1m' else 100,'endTime':asof-1}
    elif exchange=='okx':
        url=OKX;params={'instId':symbol,'bar':interval,'limit':'300' if interval=='1m' else '100'}
    else: raise ValueError('desteklenmeyen borsa')
    ensure_url_allowed(url)
    async with session.get(url,params=params,timeout=aiohttp.ClientTimeout(total=15),allow_redirects=False) as response:
        response.raise_for_status();data=await response.json()
    if exchange=='okx':
        if not isinstance(data,dict) or data.get('code')!='0' or not isinstance(data.get('data'),list):
            raise ValueError('OKX mum yaniti gecersiz')
        return data['data']
    if not isinstance(data,list):raise ValueError('Binance mum yaniti gecersiz')
    return data
