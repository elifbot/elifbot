#!/usr/bin/env python3
"""
izole_test.py — İZOLE MARJ + TREND TAKİBİ ÇIKIŞI

Kullanıcının istediği yapı:
  • Sabit stop YOK. 50$ marj girildiyse, marj BİTENE kadar (yani fiyat
    1/kaldıraç kadar ters gidene kadar) pozisyon açık kalır.
  • Üst limitte TP var.
  • Yön sürdüğü sürece pozisyonda kal (long sürüyorsa long, short sürüyorsa short).
  • En iyi noktada çık.

Bu, klasik "trend takip / iz süren çıkış" problemidir. 6 farklı çıkış
yöntemini 7 günlük veride kıyaslıyorum:

  0) MEVCUT   : TP %2 / SL %3 / 5 dk
  1) SAF SÜRE : stop yok, marj bitmezse T dk sonra çık
  2) TASFİYE  : stop yok, sadece marj bitince (1/kaldıraç düşüş) çık
  3) İZ SÜREN : zirveden X% geri çekilirse çık (trailing)
  4) MOMENTUM : 1 dakikalık yön tersine dönerse çık
  5) MELEZ    : iz süren + momentum birlikte

Kullanım: python3 izole_test.py
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

import numpy as np

NPZ = "/home/user/okx_onbellek.npz"
GERI, MEDYAN = 3, 30


# ----------------------------------------------------------------------
def veri_yukle():
    z = np.load(NPZ, allow_pickle=True)
    return {k: z[k][np.argsort(z[k][:, 0])] for k in z.files}


def genislik_haritasi(veri):
    """Her dakikada |3dk|>=0.5% olan sembol sayısı."""
    h = {}
    for sym, a in veri.items():
        n = a.shape[0]
        if n < MEDYAN + GERI + 10:
            continue
        c = a[:, 4]
        ret = np.zeros(n)
        ret[GERI:] = (c[GERI:] - c[:-GERI]) / c[:-GERI] * 100
        for t in range(GERI + MEDYAN, n):
            if abs(ret[t]) >= 0.5:
                h.setdefault(int(a[t, 0]) // 60000, set()).add(sym)
    return h


def sinyaller(veri):
    out = []
    for sym, a in veri.items():
        n = a.shape[0]
        if n < MEDYAN + GERI + 10:
            continue
        c, v = a[:, 4], a[:, 5]
        ret = np.full(n, np.nan)
        ret[GERI:] = (c[GERI:] - c[:-GERI]) / c[:-GERI] * 100
        vs = np.convolve(v, np.ones(GERI), mode="full")[:n]
        vr3 = np.full(n, np.nan)
        for t in range(GERI + MEDYAN, n):
            m = np.median(v[t - GERI - MEDYAN:t - GERI])
            if m > 0:
                vr3[t] = vs[t - GERI + 1] / (m * GERI)
        uy = (np.abs(ret) >= 1.2) & (np.abs(ret) <= 2.0) & (vr3 >= 10)
        for t in np.flatnonzero(uy):
            if t + 1 >= n:
                continue
            out.append({"sym": sym, "t": int(t), "ts": int(a[t, 0]),
                        "r3": float(ret[t]), "a": a})
    out.sort(key=lambda x: x["ts"])
    return out


def gun(x):
    return dt.datetime.fromtimestamp(x["ts"] / 1000, dt.UTC).strftime("%d.%m")


# ----------------------------------------------------------------------
# ÇIKIŞ YÖNTEMLERİ — hepsi tek bir "getiri %" döndürür
# ----------------------------------------------------------------------
def c_mevcut(a, t, g, yon, tp=2.0, sl=3.0, tut=5):
    n = a.shape[0]
    zz = g * (1 - yon * sl / 100)
    hh = g * (1 + yon * tp / 100)
    for k in range(t, min(t + tut, n)):
        if (yon > 0 and a[k, 3] <= zz) or (yon < 0 and a[k, 2] >= zz):
            return -sl
        if (yon > 0 and a[k, 2] >= hh) or (yon < 0 and a[k, 3] <= hh):
            return tp
    k = min(t + tut - 1, n - 1)
    return (a[k, 4] - g) / g * 100 * yon


def c_sure(a, t, g, yon, tut=30):
    """Stop yok — sadece süre."""
    n = a.shape[0]
    k = min(t + tut - 1, n - 1)
    return (a[k, 4] - g) / g * 100 * yon


def c_tasfiye(a, t, g, yon, kaldirac=10, tut=240, tp=None):
    """
    İZOLE MARJ: marj 1/kaldıraç kadar ters harekette biter.
    10x → %10 ters hareket = marj sıfır. 20x → %5.
    """
    n = a.shape[0]
    ifiy = 100.0 / kaldirac
    zz = g * (1 - yon * ifiy / 100)
    hh = g * (1 + yon * tp / 100) if tp else None
    for k in range(t, min(t + tut, n)):
        if (yon > 0 and a[k, 3] <= zz) or (yon < 0 and a[k, 2] >= zz):
            return -ifiy
        if hh is not None and ((yon > 0 and a[k, 2] >= hh) or (yon < 0 and a[k, 3] <= hh)):
            return tp
    k = min(t + tut - 1, n - 1)
    return (a[k, 4] - g) / g * 100 * yon


def c_izsuren(a, t, g, yon, geri=0.5, tut=120, kaldirac=10):
    """
    İZ SÜREN (trailing): zirveden `geri`% geri çekilirse çık.
    Marj bitene kadar beklenir (tasfiye sınırı).
    """
    n = a.shape[0]
    ifiy = 100.0 / kaldirac
    zz = g * (1 - yon * ifiy / 100)
    zirve = g
    for k in range(t, min(t + tut, n)):
        if (yon > 0 and a[k, 3] <= zz) or (yon < 0 and a[k, 2] >= zz):
            return -ifiy
        hi, lo = a[k, 2], a[k, 3]
        zirve = max(zirve, hi) if yon > 0 else min(zirve, lo)
        # iz süren eşiği zirveden geri
        esik = zirve * (1 - yon * geri / 100)
        if (yon > 0 and lo <= esik) or (yon < 0 and hi >= esik):
            return (esik - g) / g * 100 * yon
    k = min(t + tut - 1, n - 1)
    return (a[k, 4] - g) / g * 100 * yon


def c_momentum(a, t, g, yon, kaldirac=10, tut=120, geri=1, esik_pct=0.3):
    """
    Momentum tersine dönerse çık: son `geri` dakikada fiyat bizim yönümüzün
    TERSİNE `esik_pct` kadar giderse kapat.
    """
    n = a.shape[0]
    ifiy = 100.0 / kaldirac
    zz = g * (1 - yon * ifiy / 100)
    for k in range(t, min(t + tut, n)):
        if (yon > 0 and a[k, 3] <= zz) or (yon < 0 and a[k, 2] >= zz):
            return -ifiy
        if k - geri >= t - 1:
            onceki = a[k - geri, 4]
            degisim = (a[k, 4] - onceki) / onceki * 100 * yon
            if degisim <= -esik_pct:
                return (a[k, 4] - g) / g * 100 * yon
    k = min(t + tut - 1, n - 1)
    return (a[k, 4] - g) / g * 100 * yon


def c_melez(a, t, g, yon, geri=0.8, esik_pct=0.4, tut=120, kaldirac=10):
    """İz süren + momentum: hangisi önce tetiklerse."""
    n = a.shape[0]
    ifiy = 100.0 / kaldirac
    zz = g * (1 - yon * ifiy / 100)
    zirve = g
    for k in range(t, min(t + tut, n)):
        if (yon > 0 and a[k, 3] <= zz) or (yon < 0 and a[k, 2] >= zz):
            return -ifiy
        hi, lo = a[k, 2], a[k, 3]
        zirve = max(zirve, hi) if yon > 0 else min(zirve, lo)
        esik = zirve * (1 - yon * geri / 100)
        if (yon > 0 and lo <= esik) or (yon < 0 and hi >= esik):
            return (esik - g) / g * 100 * yon
        if k - 1 >= t:
            degisim = (a[k, 4] - a[k - 1, 4]) / a[k - 1, 4] * 100 * yon
            if degisim <= -esik_pct:
                return (a[k, 4] - g) / g * 100 * yon
    k = min(t + tut - 1, n - 1)
    return (a[k, 4] - g) / g * 100 * yon


# ----------------------------------------------------------------------
def degerlendir(sn, fn, ad, ucret=0.10, **kw):
    r = []
    for x in sn:
        a = x["a"]
        g = a[x["t"] + 1, 1]
        if g <= 0:
            continue
        yon = -1.0 if x["r3"] > 0 else 1.0
        r.append(fn(a, x["t"] + 1, g, yon, **kw) - ucret)
    if not r:
        return
    isa = sum(1 for q in r if q > 0) / len(r) * 100
    eq = np.cumsum(np.array(r))
    mdd = float(np.max(np.maximum.accumulate(eq) - eq))
    # en kötü tek işlem
    print(f"  {ad:<32}{len(r):>6}{statistics.mean(r):>+9.3f}%{isa:>7.1f}%"
          f"{sum(r):>+10.1f}%{mdd:>7.0f}{min(r):>9.1f}%")


def main():
    veri = veri_yukle()
    gh = genislik_haritasi(veri)
    sn = sinyaller(veri)
    # genişlik >= %45 (289 sembolde 130+)
    sn = [x for x in sn if len(gh.get(x["ts"] // 60000, ())) / 289 >= 0.45]
    print(f"{len(veri)} sembol · {len(sn)} sinyal (genişlik>=%45)\n")

    print("=" * 94)
    print(" İZOLE MARJ / TREND TAKİBİ — ÇIKIŞ YÖNTEMİ KIYASLAMASI")
    print(" (ücret %0,10 gidiş-dönüş · 'en kötü' = tek işlemde en büyük kayıp)")
    print("=" * 94)
    print(f"  {'yöntem':<32}{'n':>6}{'ort':>10}{'isabet':>8}{'toplam':>11}{'MDD':>7}{'en kötü':>9}")
    print("-" * 94)

    degerlendir(sn, c_mevcut, "0 MEVCUT TP2/SL3/5dk")
    print()
    for tut in (10, 30, 60, 240):
        degerlendir(sn, c_sure, f"1 saf süre {tut} dk (stop yok)", tut=tut)
    print()
    for L in (10, 20):
        degerlendir(sn, c_tasfiye, f"2 tasfiye {L}x (marj biter)", kaldirac=L, tut=240)
    print()
    for geri in (0.3, 0.5, 1.0, 2.0):
        degerlendir(sn, c_izsuren, f"3 iz süren {geri}% (10x)", geri=geri, tut=240)
    print()
    for esik in (0.3, 0.5, 1.0):
        degerlendir(sn, c_momentum, f"4 momentum ters {esik}% (10x)",
                    esik_pct=esik, tut=240)
    print()
    for geri, esik in ((0.8, 0.4), (1.0, 0.5), (0.5, 0.3)):
        degerlendir(sn, c_melez, f"5 melez iz {geri}% + mom {esik}%",
                    geri=geri, esik_pct=esik, tut=240)

    # ---- kazananı gün gün göster ----
    print()
    print("=" * 94)
    print(" EN İYİ 3 YÖNTEM — GÜN GÜN")
    print("=" * 94)
    adaylar = [
        ("iz süren 0,5% (10x)", c_izsuren, dict(geri=0.5, tut=240)),
        ("iz süren 1,0% (10x)", c_izsuren, dict(geri=1.0, tut=240)),
        ("melez 0,8/0,4", c_melez, dict(geri=0.8, esik_pct=0.4, tut=240)),
        ("saf süre 60 dk", c_sure, dict(tut=60)),
        ("MEVCUT TP2/SL3/5dk", c_mevcut, dict()),
    ]
    for ad, fn, kw in adaylar:
        gd = defaultdict(list)
        for x in sn:
            a = x["a"]
            g = a[x["t"] + 1, 1]
            if g <= 0:
                continue
            yon = -1.0 if x["r3"] > 0 else 1.0
            gd[gun(x)].append(fn(a, x["t"] + 1, g, yon, **kw) - 0.10)
        satir = "  ".join(f"{k[-5:]}:{statistics.mean(v):+.2f}" for k, v in sorted(gd.items()))
        poz = sum(1 for v in gd.values() if statistics.mean(v) > 0)
        print(f"  {ad:<22} {poz}/{len(gd)} gün+ · {satir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
