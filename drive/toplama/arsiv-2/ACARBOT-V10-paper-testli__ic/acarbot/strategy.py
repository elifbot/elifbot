"""Kapanmış 5dk mumlarla HTML stratejileri; eksik veri işlem açmaz."""
from dataclasses import dataclass
from math import sqrt, isfinite
from typing import Sequence
from omnistudio.core.types import Candle, Side
from omnistudio.strategy.indicators import rsi

STRATEGIES = ('trend', 'rsirev', 'kombin', 'macd', 'bollkir', 'bolldon')

@dataclass(frozen=True)
class Result:
    side: Side | None
    reason: str
    bar_open_ms: int = 0
    volume_ratio: float = 0.0


def ema_series(v, period):
    if not v or period < 1: return []
    result = [v[0]]
    k = 2 / (period + 1)
    for x in v[1:]: result.append(x*k + result[-1]*(1-k))
    return result


def bollinger(v, period=20, mult=2):
    if len(v) < period: return None
    w = v[-period:]; mean = sum(w)/period
    sd = sqrt(sum((x-mean)**2 for x in w)/period)
    return mean + mult*sd, mean - mult*sd


def closed_candles(candles: Sequence[Candle], now_ms: int, interval_ms=300000):
    # Kaynak adaptörü closed=True işaretini tüm mumlara verir; saatle ayrıca doğrula.
    return [c for c in candles if c.closed and c.open_ms + interval_ms <= now_ms]


def decide(candles: Sequence[Candle], now_ms: int, strategy='trend', confirm=2) -> Result:
    if strategy not in STRATEGIES: raise ValueError('Bilinmeyen strateji')
    c = sorted(closed_candles(candles, now_ms), key=lambda x:x.open_ms)
    if len(c) < 250: return Result(None, 'INSUFFICIENT_CLOSED_BARS')
    if any(c[i].open_ms - c[i-1].open_ms != 300000 for i in range(1,len(c))):
        return Result(None, 'CANDLE_GAP', c[-1].open_ms)
    if any(not all(isfinite(x) for x in (k.open,k.high,k.low,k.close,k.quote_volume)) or k.close <= 0 or k.quote_volume < 0 for k in c):
        return Result(None,'BAD_CANDLE',c[-1].open_ms)
    if now_ms - (c[-1].open_ms + 300000) > 90000:
        return Result(None, 'STALE_CANDLE', c[-1].open_ms)
    v = [x.close for x in c]; f=ema_series(v,20); m=ema_series(v,50); slow=ema_series(v,200)
    fast=ema_series(v,12); macdslow=ema_series(v,26)
    mac=[a-b for a,b in zip(fast,macdslow)]; sig=ema_series(mac,9)
    def one(i):
        x=v[i]; up=x>f[i]>m[i]>slow[i]; down=x<f[i]<m[i]<slow[i]
        if strategy=='trend': return Side.LONG if up else Side.SHORT if down else None
        r=rsi(v[:i+1]); prev=rsi(v[:i])
        if strategy=='rsirev': return Side.LONG if prev is not None and prev<35<=r else Side.SHORT if prev is not None and prev>65>=r else None
        if strategy=='kombin': return Side.LONG if up and r is not None and 50<=r<72 else Side.SHORT if down and r is not None and 28<r<=50 else None
        if strategy=='macd': return Side.LONG if mac[i]>sig[i] and x>slow[i] else Side.SHORT if mac[i]<sig[i] and x<slow[i] else None
        upper,lower=bollinger(v[:i+1]);
        if strategy=='bollkir': return Side.LONG if x>upper and x>slow[i] else Side.SHORT if x<lower and x<slow[i] else None
        pu,pl=bollinger(v[:i]); px=v[i-1]
        return Side.LONG if px<pl and x>lower else Side.SHORT if px>pu and x<upper else None
    i=len(c)-1; side=one(i)
    if not side: return Result(None, 'NO_SIGNAL', c[-1].open_ms)
    n=1 if strategy in ('rsirev','bolldon') else confirm
    if any(one(i-j)!=side for j in range(n)): return Result(None, 'CONFIRMATION', c[-1].open_ms)
    mean=sum(x.quote_volume for x in c[-21:-1])/20
    if mean <= 0: return Result(None,'VOLUME_UNAVAILABLE',c[-1].open_ms)
    vr=c[-1].quote_volume/mean
    if vr < 1: return Result(None,'VOLUME_CONFIRMATION',c[-1].open_ms,vr)
    return Result(side,'SIGNAL',c[-1].open_ms,vr)
