"""Read-only experimental measurements; no orders and no strategy changes."""
from collections import deque
from dataclasses import asdict
import math
from scanner.money_flow import AkisDefteri, YuvarlananAkis
from scanner.signal_intel import flow_confirmation

def vwap_shadow(price, side, indicators):
    """v37 strict gate and 0.1/0.2%-band hypotheses, retaining ATR >= 0.10%."""
    try:
        price=float(price);vwap=float(indicators['vwap']);atr=float(indicators['atr_pct'])
        if side not in ('LONG','SHORT') or not all(math.isfinite(x) for x in (price,vwap,atr)) or min(price,vwap)<=0: raise ValueError('invalid values')
        signed=(1 if side=='LONG' else -1)*(price/vwap-1)*100
        return {'available':True,'directional_distance_pct':signed,
                'distance_in_atr':signed/atr if atr>0 else None,
                'atr_pass':atr>=.10,'strict_pass':atr>=.10 and signed>0,
                'band_0_10_pass':atr>=.10 and signed>=-.10,
                'band_0_20_pass':atr>=.10 and signed>=-.20}
    except (KeyError,TypeError,ValueError,OverflowError):
        return {'available':False,'reason':'indicator_unavailable'}

def flow_shadow(book, exchange, symbol, ts_ms, side):
    """Copy only the past 60s to avoid mutating the shared feed or future leakage."""
    if book is None or not hasattr(book,'_kayitlar'):
        return {'available':False,'reason':'orderflow_unavailable'}
    src=book._kayitlar.get((exchange,symbol))
    if src is None:return {'available':False,'reason':'orderflow_unavailable'}
    valid=sorted((x for x in src.olaylar if ts_ms-60_000<=x[0]<=ts_ms),key=lambda x:x[0])
    copied=YuvarlananAkis(max_ms=60_000)
    copied.olaylar=deque(valid);copied.son_ts=valid[-1][0] if valid else 0
    tmp=AkisDefteri();tmp._kayitlar[(exchange,symbol)]=copied
    result=flow_confirmation(tmp,exchange,symbol,ts_ms,side)
    return {'available':bool(valid),**asdict(result),'mode':'diagnostic_only','snapshot_ts_ms':ts_ms}
