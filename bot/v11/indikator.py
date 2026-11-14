"""İndikatörler. Yalnızca kapanmış barlar üzerinde; geleceğe bakmaz."""
from __future__ import annotations

from math import sqrt


def ema(deger: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(deger)
    if len(deger) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(deger[:n]) / n
    out[n - 1] = e
    for i in range(n, len(deger)):
        e = deger[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi(kapanis: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(kapanis)
    if len(kapanis) <= n:
        return out
    kazan = kayip = 0.0
    for i in range(1, n + 1):
        d = kapanis[i] - kapanis[i - 1]
        kazan += max(d, 0)
        kayip += max(-d, 0)
    kazan /= n
    kayip /= n
    out[n] = 100.0 if kayip == 0 else 100 - 100 / (1 + kazan / kayip)
    for i in range(n + 1, len(kapanis)):
        d = kapanis[i] - kapanis[i - 1]
        kazan = (kazan * (n - 1) + max(d, 0)) / n
        kayip = (kayip * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if kayip == 0 else 100 - 100 / (1 + kazan / kayip)
    return out


def atr(h: list[float], l: list[float], c: list[float], n: int = 14) -> list[float | None]:
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
                          for i in range(1, len(c))]
    out: list[float | None] = [None] * len(c)
    if len(c) < n:
        return out
    a = sum(tr[:n]) / n
    out[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def adx(h: list[float], l: list[float], c: list[float], n: int = 14) -> list[float | None]:
    m = len(c)
    out: list[float | None] = [None] * m
    if m < 2 * n:
        return out
    pdm = [0.0] * m
    mdm = [0.0] * m
    tr = [0.0] * m
    for i in range(1, m):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    s_tr = sum(tr[1:n + 1])
    s_p = sum(pdm[1:n + 1])
    s_m = sum(mdm[1:n + 1])
    dx: list[float] = []
    for i in range(n, m):
        if i > n:
            s_tr = s_tr - s_tr / n + tr[i]
            s_p = s_p - s_p / n + pdm[i]
            s_m = s_m - s_m / n + mdm[i]
        pdi = 100 * s_p / s_tr if s_tr else 0.0
        mdi = 100 * s_m / s_tr if s_tr else 0.0
        den = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / den if den else 0.0)
    if len(dx) < n:
        return out
    a = sum(dx[:n]) / n
    out[2 * n - 1] = a
    for j in range(n, len(dx)):
        a = (a * (n - 1) + dx[j]) / n
        out[n + j] = a
    return out


def bb_genislik(kapanis: list[float], n: int = 20, k: float = 2.0) -> list[float | None]:
    """(üst − alt) / orta, oran olarak (0.005 = %0.5)."""
    out: list[float | None] = [None] * len(kapanis)
    for i in range(n - 1, len(kapanis)):
        pen = kapanis[i - n + 1:i + 1]
        mu = sum(pen) / n
        sd = sqrt(sum((x - mu) ** 2 for x in pen) / n)
        out[i] = (2 * k * sd) / mu if mu else None
    return out
