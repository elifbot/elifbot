"""Saf Python göstergeler (pandas/numpy yok). Hepsi nedensel: i. değer yalnız ≤ i verisini kullanır."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from .models import Bar

Num = Optional[float]


def _ok(x: Num) -> bool:
    return x is not None and math.isfinite(x)


def ewm(values: Sequence[Num], alpha: float) -> list[Num]:
    """EWM(adjust=False): ilk geçerli değer tohum; None değerler önceki değeri taşır."""
    out: list[Num] = [None] * len(values)
    prev: Num = None
    for i, v in enumerate(values):
        if not _ok(v):
            out[i] = prev
            continue
        prev = v if prev is None else v * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def ema(values: Sequence[float], period: int) -> list[float]:
    a = 2.0 / (period + 1)
    out: list[float] = []
    for i, v in enumerate(values):
        out.append(v if i == 0 else v * a + out[-1] * (1 - a))
    return out


def true_range(bars: Sequence[Bar]) -> list[Num]:
    out: list[Num] = [None] * len(bars)
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        out[i] = max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))
    return out


def atr_series(bars: Sequence[Bar], period: int = 14) -> list[Num]:
    sm = ewm(true_range(bars), 1.0 / period)
    return [v if i >= period else None for i, v in enumerate(sm)]


def rsi_series(closes: Sequence[float], period: int = 14) -> list[Num]:
    n = len(closes)
    gains: list[Num] = [None] * n
    losses: list[Num] = [None] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    g, l = ewm(gains, 1.0 / period), ewm(losses, 1.0 / period)
    out: list[Num] = [None] * n
    for i in range(period, n):
        if g[i] is None or l[i] is None:
            continue
        out[i] = 100.0 if l[i] == 0 else 100.0 - 100.0 / (1.0 + g[i] / l[i])
    return out


def adx_series(bars: Sequence[Bar], period: int = 14) -> list[Num]:
    a = 1.0 / period
    n = len(bars)
    pdm: list[Num] = [None] * n
    mdm: list[Num] = [None] * n
    for i in range(1, n):
        up = bars[i].high - bars[i - 1].high
        dn = bars[i - 1].low - bars[i].low
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
    tr_e = ewm(true_range(bars), a)
    p_e, m_e = ewm(pdm, a), ewm(mdm, a)
    dx: list[Num] = []
    for i in range(n):
        if not tr_e[i] or p_e[i] is None or m_e[i] is None:
            dx.append(None)
            continue
        pdi = 100 * p_e[i] / tr_e[i]
        mdi = 100 * m_e[i] / tr_e[i]
        dx.append(100 * abs(pdi - mdi) / max(pdi + mdi, 1e-9))
    out = ewm(dx, a)
    return [v if i >= 2 * period else None for i, v in enumerate(out)]


def stochastic(bars: Sequence[Bar], period: int = 14, k_smooth: int = 3,
               d_smooth: int = 3) -> tuple[list[Num], list[Num]]:
    n = len(bars)
    raw: list[Num] = [None] * n
    for i in range(period - 1, n):
        win = bars[i - period + 1:i + 1]
        hh, ll = max(b.high for b in win), min(b.low for b in win)
        raw[i] = 100 * (bars[i].close - ll) / (hh - ll) if hh > ll else None

    def sma(seq: list[Num], w: int) -> list[Num]:
        out: list[Num] = [None] * len(seq)
        for i in range(len(seq)):
            win = seq[max(0, i - w + 1):i + 1]
            if len(win) == w and all(x is not None for x in win):
                out[i] = sum(win) / w  # type: ignore[arg-type]
        return out

    k = sma(raw, k_smooth)
    return k, sma(k, d_smooth)


def obv_series(bars: Sequence[Bar], sma_len: int = 10) -> tuple[list[float], list[Num]]:
    obv = [0.0]
    for i in range(1, len(bars)):
        if bars[i].close > bars[i - 1].close:
            obv.append(obv[-1] + bars[i].volume)
        elif bars[i].close < bars[i - 1].close:
            obv.append(obv[-1] - bars[i].volume)
        else:
            obv.append(obv[-1])
    sma: list[Num] = [None] * len(obv)
    for i in range(sma_len - 1, len(obv)):
        sma[i] = sum(obv[i - sma_len + 1:i + 1]) / sma_len
    return obv, sma


def vwap_series(bars: Sequence[Bar]) -> list[Num]:
    """Günlük VWAP; UTC gün sınırında sıfırlanır."""
    out: list[Num] = [None] * len(bars)
    day, pv, vol = None, 0.0, 0.0
    for i, b in enumerate(bars):
        d = b.ts // 86_400_000
        if d != day:
            day, pv, vol = d, 0.0, 0.0
        pv += (b.high + b.low + b.close) / 3 * b.volume
        vol += b.volume
        out[i] = pv / vol if vol > 0 else None
    return out


def cci_series(bars: Sequence[Bar], period: int = 20) -> list[Num]:
    out: list[Num] = [None] * len(bars)
    tp = [(b.high + b.low + b.close) / 3 for b in bars]
    for i in range(period - 1, len(bars)):
        w = tp[i - period + 1:i + 1]
        mean = sum(w) / period
        dev = sum(abs(x - mean) for x in w) / period
        out[i] = (tp[i] - mean) / (0.015 * dev) if dev > 0 else None
    return out


def supertrend_series(bars: Sequence[Bar], period: int = 10, mult: float = 3.0) -> list[Num]:
    """Yön dizisi: +1 yukarı, -1 aşağı."""
    n = len(bars)
    out: list[Num] = [None] * n
    atr = atr_series(bars, period)
    fu: Num = None
    fl: Num = None
    trend = 1
    started = False
    for i in range(n):
        a = atr[i]
        if a is None:
            continue
        mid = (bars[i].high + bars[i].low) / 2
        bu, bl = mid + mult * a, mid - mult * a
        if not started:
            fu, fl, trend, started = bu, bl, 1, True
        else:
            pc = bars[i - 1].close
            fu = bu if (bu < fu or pc > fu) else fu      # type: ignore[operator]
            fl = bl if (bl > fl or pc < fl) else fl      # type: ignore[operator]
            if bars[i].close > fu:                        # type: ignore[operator]
                trend = 1
            elif bars[i].close < fl:                      # type: ignore[operator]
                trend = -1
        out[i] = float(trend)
    return out


def bollinger(closes: Sequence[float], period: int = 20) -> tuple[list[Num], list[Num]]:
    mid: list[Num] = [None] * len(closes)
    sd: list[Num] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        w = closes[i - period + 1:i + 1]
        m = sum(w) / period
        mid[i] = m
        sd[i] = math.sqrt(sum((x - m) ** 2 for x in w) / period)
    return mid, sd


def choppiness(bars: Sequence[Bar], period: int = 14) -> list[Num]:
    """0..100; yüksek = yatay/testere piyasa."""
    tr = true_range(bars)
    out: list[Num] = [None] * len(bars)
    for i in range(period, len(bars)):
        s = sum(t for t in tr[i - period + 1:i + 1] if t is not None)
        win = bars[i - period + 1:i + 1]
        rng = max(b.high for b in win) - min(b.low for b in win)
        if rng > 0 and s > 0:
            out[i] = 100 * math.log10(s / rng) / math.log10(period)
    return out


@dataclass
class Indicators:
    """Bir sembolün tüm gösterge serileri (bir kez hesaplanır, i. indekste okunur)."""
    ts: list[int]
    close: list[float]
    e20: list[float]
    e50: list[float]
    e200: list[float]
    macd: list[float]
    macd_sig: list[float]
    rsi: list[Num]
    atr: list[Num]
    adx: list[Num]
    k: list[Num]
    d: list[Num]
    obv: list[float]
    obv_sma: list[Num]
    vwap: list[Num]
    cci: list[Num]
    st: list[Num]
    bb_mid: list[Num]
    bb_sd: list[Num]
    chop: list[Num]

    @classmethod
    def compute(cls, bars: Sequence[Bar]) -> "Indicators":
        closes = [b.close for b in bars]
        macd = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
        obv, obv_sma = obv_series(bars)
        k, d = stochastic(bars)
        bm, bs = bollinger(closes)
        return cls(
            ts=[b.ts for b in bars], close=closes,
            e20=ema(closes, 20), e50=ema(closes, 50), e200=ema(closes, 200),
            macd=macd, macd_sig=ema(macd, 9), rsi=rsi_series(closes),
            atr=atr_series(bars), adx=adx_series(bars), k=k, d=d,
            obv=obv, obv_sma=obv_sma, vwap=vwap_series(bars), cci=cci_series(bars),
            st=supertrend_series(bars), bb_mid=bm, bb_sd=bs, chop=choppiness(bars),
        )
