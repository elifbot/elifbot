"""Mum verisi okuma ve yeniden örnekleme.

CSV başlığı: ts,open,high,low,close,volume[,funding,oi]
ts: saniye veya milisaniye epoch. Yalnızca dosya okunur; ağ çağrısı yapılmaz.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Bar:
    ts: float
    o: float
    h: float
    l: float
    c: float
    v: float
    funding: float | None = None
    oi: float | None = None


@dataclass
class Seri:
    sembol: str
    bars: list[Bar] = field(default_factory=list)


def _ts(x: float) -> float:
    return x / 1000.0 if x > 1e12 else x


def oku_csv(yol: str | Path, sembol: str) -> Seri:
    s = Seri(sembol=sembol)
    with open(yol, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            fund = r.get("funding")
            oi = r.get("oi")
            s.bars.append(Bar(
                ts=_ts(float(r["ts"])), o=float(r["open"]), h=float(r["high"]),
                l=float(r["low"]), c=float(r["close"]), v=float(r.get("volume") or 0),
                funding=float(fund) if fund not in (None, "") else None,
                oi=float(oi) if oi not in (None, "") else None,
            ))
    s.bars.sort(key=lambda b: b.ts)
    return s


def yeniden_ornekle(s: Seri, dakika: int) -> Seri:
    """1 dk barları N dk'lık barlara toplar. Son eksik grup atılır."""
    if dakika <= 1:
        return s
    out = Seri(sembol=s.sembol)
    grup: list[Bar] = []
    anahtar = None
    for b in s.bars:
        k = int(b.ts // (dakika * 60))
        if anahtar is None or k != anahtar:
            if grup and len(grup) == dakika:
                out.bars.append(_birlestir(grup))
            grup = []
            anahtar = k
        grup.append(b)
    if grup and len(grup) == dakika:
        out.bars.append(_birlestir(grup))
    return out


def _birlestir(g: list[Bar]) -> Bar:
    return Bar(
        ts=g[0].ts, o=g[0].o, h=max(b.h for b in g), l=min(b.l for b in g),
        c=g[-1].c, v=sum(b.v for b in g),
        funding=g[-1].funding, oi=g[-1].oi,
    )
