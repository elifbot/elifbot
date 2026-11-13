"""Sinyal katmanı: 10 filtreli confluence oylaması + rejim/maliyet/bütünlük kapıları."""
from __future__ import annotations

import math
from typing import Optional, Protocol, Sequence

from .indicators import Indicators, _ok, ema
from .models import Bar, Config, Signal

VOTE_NAMES = ("ema", "macd", "rsi", "adx", "stoch", "obv", "cci", "supertrend", "vwap", "boll")
WARMUP = 220


def votes_at(ind: Indicators, i: int) -> dict[str, int]:
    """i. mum kapanışında 10 oy (+1 long, -1 short, 0 nötr). Yalnız ≤ i verisi."""
    c = ind.close[i]
    v: dict[str, int] = {}
    up = ind.e20[i] > ind.e50[i] > ind.e200[i]
    dn = ind.e20[i] < ind.e50[i] < ind.e200[i]
    v["ema"] = 1 if up else -1 if dn else 0

    m0, s0, m1, s1 = ind.macd[i - 1], ind.macd_sig[i - 1], ind.macd[i], ind.macd_sig[i]
    v["macd"] = 1 if (m0 <= s0 and m1 > s1) else -1 if (m0 >= s0 and m1 < s1) else 0

    r = ind.rsi[i]
    v["rsi"] = 1 if _ok(r) and r > 55 else -1 if _ok(r) and r < 45 else 0  # type: ignore[operator]

    a = ind.adx[i]
    v["adx"] = (1 if _ok(a) and a > 25 and ind.e20[i] > ind.e50[i]            # type: ignore[operator]
                else -1 if _ok(a) and a > 25 and ind.e20[i] < ind.e50[i] else 0)  # type: ignore[operator]

    k0, d0, k1, d1 = ind.k[i - 1], ind.d[i - 1], ind.k[i], ind.d[i]
    if all(_ok(x) for x in (k0, d0, k1, d1)):
        v["stoch"] = (1 if k0 <= d0 and k1 > d1 and k1 < 80           # type: ignore[operator]
                      else -1 if k0 >= d0 and k1 < d1 and k1 > 20 else 0)  # type: ignore[operator]
    else:
        v["stoch"] = 0

    o, os_, op = ind.obv[i], ind.obv_sma[i], ind.obv[i - 1]
    if _ok(os_):
        v["obv"] = (1 if o > os_ and o > op else -1 if o < os_ and o < op else 0)  # type: ignore[operator]
    else:
        v["obv"] = 0

    cc = ind.cci[i]
    v["cci"] = 1 if _ok(cc) and 0 < cc < 100 else -1 if _ok(cc) and -100 < cc < 0 else 0  # type: ignore[operator]

    st = ind.st[i]
    v["supertrend"] = 1 if _ok(st) and st > 0 else -1 if _ok(st) and st < 0 else 0  # type: ignore[operator]

    vw = ind.vwap[i]
    v["vwap"] = 1 if _ok(vw) and c > vw else -1 if _ok(vw) and c < vw else 0  # type: ignore[operator]

    bm, bs = ind.bb_mid[i], ind.bb_sd[i]
    if _ok(bm) and _ok(bs):
        v["boll"] = 1 if c > bm + 2 * bs else -1 if c < bm - 2 * bs else 0  # type: ignore[operator]
    else:
        v["boll"] = 0
    return v


def evaluate(ind: Indicators, i: int, cfg: Config) -> tuple[Optional[Signal], str]:
    """Bir mum kapanışında sinyal kararı. Dönüş: (Signal|None, neden)."""
    if i < WARMUP:
        return None, "WARMUP"
    # mum sürekliliği: son 3 mum arasında iki ve fazlası eksik mum = boşluk
    if ind.ts[i] - ind.ts[i - 2] > 3 * cfg.bar_ms:
        return None, "CANDLE_GAP"
    a = ind.atr[i]
    if not _ok(a) or a <= 0:  # type: ignore[operator]
        return None, "ATR_MISSING"
    votes = votes_at(ind, i)
    score = sum(votes.values())
    th = cfg.conf_th
    side = 1 if score >= th else -1 if score <= -th else 0
    if side == 0:
        return None, "THRESHOLD"
    ch = ind.chop[i]
    if _ok(ch) and ch >= cfg.max_chop:  # type: ignore[operator]
        return None, "CHOP"
    return Signal(side, score, votes, float(a), ind.close[i], ind.ts[i]), "SIGNAL"  # type: ignore[arg-type]


class SignalSource(Protocol):
    def signal(self, sym: str, ts: int) -> tuple[Optional[Signal], str]: ...
    def breadth(self, ts: int) -> Optional[float]: ...


def breadth_from(flags: Sequence[bool]) -> Optional[float]:
    """EMA20 üstündeki sembol oranı, -1..+1 ölçeğine çevrilmiş."""
    if not flags:
        return None
    return round(sum(flags) / len(flags) * 2 - 1, 3)


class PrecomputedSource:
    """Backtest: göstergeler bir kez hesaplanır, i. indekste okunur (ileriye bakış yok)."""

    def __init__(self, data: dict[str, Sequence[Bar]], cfg: Config):
        self.cfg = cfg
        self.ind = {s: Indicators.compute(b) for s, b in data.items()}
        self.idx = {s: {t: i for i, t in enumerate(ind.ts)} for s, ind in self.ind.items()}
        self._breadth: dict[int, Optional[float]] = {}

    def timestamps(self) -> list[int]:
        return sorted({t for m in self.idx.values() for t in m})

    def signal(self, sym: str, ts: int) -> tuple[Optional[Signal], str]:
        i = self.idx[sym].get(ts)
        if i is None:
            return None, "NO_BAR"
        return evaluate(self.ind[sym], i, self.cfg)

    def breadth(self, ts: int) -> Optional[float]:
        if ts not in self._breadth:
            flags = []
            for s, m in self.idx.items():
                i = m.get(ts)
                if i is not None and i >= 25:
                    flags.append(self.ind[s].close[i] > self.ind[s].e20[i])
            self._breadth[ts] = breadth_from(flags)
        return self._breadth[ts]


class RollingSource:
    """Canlı paper: her sembolün son N mumundan göstergeleri yeniden hesaplar."""

    def __init__(self, history: dict[str, list[Bar]], cfg: Config, window: int = 600):
        self.history, self.cfg, self.window = history, cfg, window

    def signal(self, sym: str, ts: int) -> tuple[Optional[Signal], str]:
        bars = self.history.get(sym, [])[-self.window:]
        if not bars or bars[-1].ts != ts:
            return None, "NO_BAR"
        ind = Indicators.compute(bars)
        return evaluate(ind, len(bars) - 1, self.cfg)

    def breadth(self, ts: int) -> Optional[float]:
        flags = []
        for bars in self.history.values():
            if len(bars) >= 25 and bars[-1].ts == ts:
                closes = [b.close for b in bars[-120:]]
                flags.append(closes[-1] > ema(closes, 20)[-1])
        return breadth_from(flags)
