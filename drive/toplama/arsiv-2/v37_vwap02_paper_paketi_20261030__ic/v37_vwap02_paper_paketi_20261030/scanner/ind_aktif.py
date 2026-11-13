"""Paper-only aktif gösterge kapısı. Yalnız tamamlanmış 1m mumlar kullanılır.

VWAP son 60 TAM dakika quote/base; ATR Wilder(14) aynı kapalı mumlarda.
Cari dakika dışlanır; bu nedenle en son dakika sınırına hizalanmış yaklaşımdır,
tick-seviyesinde kayan VWAP değildir. Eksik/kopuk/bayat veri kapıyı kapatır.
"""
from __future__ import annotations
import math


def kapali_mum_ekle(d, mid, high, low, close, base, quote):
    try:
        mid=int(mid); high=float(high); low=float(low); close=float(close)
        base=float(base); quote=float(quote)
    except (ValueError,TypeError,OverflowError):return False
    if mid<0 or not all(math.isfinite(x) for x in (high,low,close,base,quote)):
        return False
    if low<=0 or close<=0 or high<max(low,close) or close<low or base<0 or quote<0:
        return False
    if (base==0)!=(quote==0):return False
    if base>0 and not (low*(1-1e-8) <= quote/base <= high*(1+1e-8)):return False
    # Borsa tarafından doğrulanmış aynı dakikanın son versiyonu. Sonraki
    # revizyonların olay anında bilinebilirliği ayrıca kanıtlanmamıştır.
    d.ind_mum[mid]=(high,low,close,base,quote)
    for old in sorted(d.ind_mum)[:-65]:del d.ind_mum[old]
    return True


def metrik(d, simdi_ms, fiyat):
    try:
        fiyat=float(fiyat);simdi_ms=int(simdi_ms)
    except (ValueError,TypeError,OverflowError):return None
    if not math.isfinite(fiyat) or fiyat<=0:return None
    end=simdi_ms//60_000-1
    keys=range(end-59,end+1)
    if any(k not in d.ind_mum for k in keys):return None
    rows=[d.ind_mum[k] for k in keys]
    total_base=sum(x[3] for x in rows);total_quote=sum(x[4] for x in rows)
    if total_base<=0 or total_quote<=0:return None
    vwap=total_quote/total_base
    if not math.isfinite(vwap) or vwap<=0:return None
    atr=None;prev=None
    for high,low,close,_,_ in rows:
        tr=high-low if prev is None else max(high-low,abs(high-prev),abs(low-prev))
        atr=tr if atr is None else (13*atr+tr)/14
        prev=close
    pct=atr/fiyat*100
    if not math.isfinite(pct):return None
    return {'vwap':vwap,'atr_pct':pct,'kapanis_dk':end}


def kapsam(detektor, simdi_ms, evrenler=None):
    """Anlık indikatör + taze fiyat kapsamı.

    ``evrenler`` verilirse payda, yalnızca gözlemlenmiş durumları değil,
    borsadan beklenen tüm sembolleri içerir. Böylece hiç veri gelmeyen bir
    sembol kapsam yüzdesinden sessizce düşmez.
    """
    sonuc={'toplam':0, 'mum_hazir':0, 'mum_ve_fiyat_hazir':0,
           'hazir_oran':0.0, 'hazir_yuzde':0.0, 'borsalar':{}}
    if not getattr(detektor, 'ind_aktif', False):return sonuc

    if evrenler is None:
        adaylar=((d.exchange,d.symbol,d) for d in detektor.durumlar.values())
    else:
        adaylar=(
            (exchange,symbol,detektor.durumlar.get((exchange,symbol)))
            for exchange,symbols in evrenler.items()
            for symbol in set(symbols)
        )

    for exchange,symbol,d in adaylar:
        b=sonuc['borsalar'].setdefault(exchange, {'toplam':0,'mum_hazir':0,'mum_ve_fiyat_hazir':0})
        sonuc['toplam']+=1;b['toplam']+=1
        if d is None or metrik(d,simdi_ms,d.son_fiyat) is None:continue
        sonuc['mum_hazir']+=1;b['mum_hazir']+=1
        age=simdi_ms-d.son_fiyat_ts
        if 0<=age<=detektor.tazelik_ms:
            sonuc['mum_ve_fiyat_hazir']+=1;b['mum_ve_fiyat_hazir']+=1

    for b in sonuc['borsalar'].values():
        b['hazir_oran']=(b['mum_ve_fiyat_hazir']/b['toplam']) if b['toplam'] else 0.0
        b['hazir_yuzde']=round(100*b['hazir_oran'],2)
    sonuc['hazir_oran']=(sonuc['mum_ve_fiyat_hazir']/sonuc['toplam']) if sonuc['toplam'] else 0.0
    sonuc['hazir_yuzde']=round(100*sonuc['hazir_oran'],2)
    return sonuc


def giris_karari(d, simdi_ms, fiyat, yon, *, vwap_tolerans_pct=0.0):
    # Opt-in isolated paper experiment; strict 0.0 preserves prior behavior.
    try: tolerance=float(vwap_tolerans_pct)
    except (ValueError, TypeError, OverflowError): return False,'indikator_tolerans_gecersiz',None
    if not math.isfinite(tolerance) or not 0<=tolerance<=0.2:
        return False,'indikator_tolerans_gecersiz',None
    m=metrik(d,simdi_ms,fiyat)
    if m is None:return False,'indikator_veri_yok',None
    if m['atr_pct'] < 0.10:return False,'indikator_atr_dusuk',m
    if tolerance==0.0:
        if yon=='LONG' and fiyat>m['vwap']:return True,'onay',m
        if yon=='SHORT' and fiyat<m['vwap']:return True,'onay',m
    else:
        if yon=='LONG' and fiyat>=m['vwap']*(1-tolerance/100):return True,'onay',m
        if yon=='SHORT' and fiyat<=m['vwap']*(1+tolerance/100):return True,'onay',m
    return False,'indikator_vwap_yon',m


def aggtrade_ekle(d, ts_ms, price, base):
    """Onaylanmış Binance trade'lerinden dakika OHLC/quote/base biriktir.

    Bağlantının ilk (kısmi) dakikası tam sayılmaz; boş dakika uydurulmaz.
    Sıra/kopma kontrolü çağıran akışın sorumluluğudur.
    """
    mid=ts_ms//60_000; qv=price*base
    b=d.ind_acik_mum
    if b is None:
        d.ind_acik_mum={'mid':mid,'high':price,'low':price,'close':price,'base':base,'quote':qv,'tam':False}
        return
    if mid < b['mid']:return
    if mid>b['mid']:
        if b['tam']:kapali_mum_ekle(d,b['mid'],b['high'],b['low'],b['close'],b['base'],b['quote'])
        d.ind_acik_mum={'mid':mid,'high':price,'low':price,'close':price,'base':base,'quote':qv,'tam':True}
        return
    b['high']=max(b['high'],price);b['low']=min(b['low'],price)
    b['close']=price;b['base']+=base;b['quote']+=qv
