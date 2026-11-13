#!/usr/bin/env python3
"""
matematik_lab.py — ÇOK STRATEJİLİ KIYASLAMA

Sorulan soru: "Bazı pozisyonlar zararda iken tam tersi durumda kârda olan
bir strateji vardı." Bu, iki farklı şey olabilir ve ikisini de ölçüyorum:

  A) STOP-AND-REVERSE — stop yerine TERS pozisyon aç.
     Fiyat aleyhine gidip stopu vuruyorsa, demek ki sinyal yanlıştı;
     o zaman ters yönde girmek kâr getirir mi?

  B) NÖTR STRADDLE — aynı anda HEM long HEM short aç.
     Kaybeden stopla erken kapanır, kazanan sonuna kadar koşar.
     Konveksite (asimetri) kâr üretir mi?

  C) YÖN SEÇİCİ — sabit fade/momentum yerine, özelliklerden yönü ÖĞRENEN
     lojistik regresyon. Walk-forward (ileriye dönük) sınav.

  D) TEMEL — mevcut fade (kıyas tabanı).

Hepsi aynı veride, aynı ücret/varsayımlarda. Kazanan tek strateji raporlanır.

Kullanım:
    python3 matematik_lab.py [--sembol 289] [--ucret 0.10]
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import statistics
from collections import defaultdict

import numpy as np

NPZ = "/home/user/okx_onbellek.npz"


# ======================================================================
# 1) VERİ
# ======================================================================
def veri_yukle(sinir: int | None = None) -> dict[str, np.ndarray]:
    z = np.load(NPZ, allow_pickle=True)
    adlar = sorted(z.files)
    if sinir:
        adlar = adlar[:sinir]
    return {k: z[k][np.argsort(z[k][:, 0])] for k in adlar}


# ======================================================================
# 2) SİNYAL ÜRETİMİ (canlı botla aynı tanım)
# ======================================================================
GERI, MEDYAN = 3, 30
LO, HI, VR3_MIN = 1.2, 2.0, 10.0


def sinyalleri_bul(veri: dict) -> list[dict]:
    out = []
    for sym, a in veri.items():
        n = a.shape[0]
        if n < MEDYAN + GERI + 10:
            continue
        c, v = a[:, 4], a[:, 5]
        ret = np.full(n, np.nan)
        ret[GERI:] = (c[GERI:] - c[:-GERI]) / c[:-GERI] * 100.0
        vs = np.convolve(v, np.ones(GERI), mode="full")[:n]
        vr3 = np.full(n, np.nan)
        for t in range(GERI + MEDYAN, n):
            m = np.median(v[t - GERI - MEDYAN:t - GERI])
            if m > 0:
                vr3[t] = vs[t - GERI + 1] / (m * GERI)
        uy = (np.abs(ret) >= LO) & (np.abs(ret) <= HI) & (vr3 >= VR3_MIN)
        for t in np.flatnonzero(uy):
            if t + 1 >= n:
                continue
            out.append({"sym": sym, "t": int(t), "ts": int(a[t, 0]),
                        "r3": float(ret[t]), "vr3": float(vr3[t])})
    out.sort(key=lambda x: x["ts"])
    return out


def dizi_ekle(sn: list[dict], veri: dict) -> list[dict]:
    """Her sinyale ait fiyat dizisini bağlar (tekrar aramayı önler)."""
    for x in sn:
        x["a"] = veri[x["sym"]]
    return sn


def cascade_ekle(sn: list[dict], pencere_ms=60_000, esik=3) -> list[dict]:
    """Son `pencere_ms` içindeki sinyal sayısını ekler (nedensel)."""
    gecmis: list[int] = []
    for x in sn:
        gecmis = [t for t in gecmis if x["ts"] - t <= pencere_ms]
        gecmis.append(x["ts"])
        x["cascade"] = len(gecmis)
    return [x for x in sn if x["cascade"] >= esik]


# ======================================================================
# 3) YARDIMCI: tek pozisyon simülasyonu (SL / tut)
# ======================================================================
def pozisyon(a, giris_t: int, giris: float, yon: float,
             sl_pct: float, tut: int) -> tuple[float, int, bool]:
    """
    yon = +1 LONG, -1 SHORT.
    Dönen: (getiri %, çıkış indeksi, stopa_değdi_mi)
    """
    n = a.shape[0]
    if giris <= 0 or giris_t >= n:
        return 0.0, giris_t, False
    if sl_pct:
        zarar = giris * (1 - yon * sl_pct / 100.0)
        for k in range(giris_t, min(giris_t + tut, n)):
            if (yon > 0 and a[k, 3] <= zarar) or (yon < 0 and a[k, 2] >= zarar):
                return -sl_pct, k, True
    k = min(giris_t + tut - 1, n - 1)
    return (a[k, 4] - giris) / giris * 100.0 * yon, k, False


# ======================================================================
# 4) STRATEJİLER
# ======================================================================
def s_temel(sn, ucret, sl=2.0, tut=5) -> list[float]:
    """D) Mevcut: fade, sabit SL."""
    r = []
    for x in sn:
        a = x["a"]
        g = a[x["t"] + 1, 1]
        yon = -1.0 if x["r3"] > 0 else 1.0
        pnl, _, _ = pozisyon(a, x["t"] + 1, g, yon, sl, tut)
        r.append(pnl - 2 * ucret / 2)
    return r


def s_stop_reverse(sn, ucret, sl=2.0, tut=5, maks_donus=2) -> list[float]:
    """
    A) STOP-AND-REVERSE: stopu yiyince kapat ve TERS yönde yeniden gir.
    Dönüş sayısı `maks_donus` ile sınırlı (sonsuz flip = komisyon yakar).
    """
    r = []
    for x in sn:
        a = x["a"]
        kalan = tut
        bas = x["t"] + 1
        g = a[bas, 1]
        yon = -1.0 if x["r3"] > 0 else 1.0
        toplam = 0.0
        islem = 0
        for _ in range(maks_donus + 1):
            if kalan <= 0 or bas >= a.shape[0]:
                break
            pnl, cikis, stop = pozisyon(a, bas, g, yon, sl, kalan)
            toplam += pnl
            islem += 1
            kalan -= max(1, cikis - bas + 1)
            if not stop:
                break
            # ters yönde yeniden gir, çıkış fiyatından
            yon = -yon
            bas = cikis + 1
            if bas >= a.shape[0]:
                break
            g = a[cikis, 4]
        r.append(toplam - islem * ucret)
    return r


def s_straddle(sn, ucret, sl=1.0, tut=5) -> list[float]:
    """
    B) NÖTR STRADDLE: aynı anda HEM long HEM short.
    Her bacak ayrı stoplu. Kaybeden erken kapanır, kazanan koşar.
    Net = long + short - 2× komisyon (iki bacak).
    """
    r = []
    for x in sn:
        a = x["a"]
        g = a[x["t"] + 1, 1]
        if g <= 0:
            continue
        p_long, _, _ = pozisyon(a, x["t"] + 1, g, 1.0, sl, tut)
        p_short, _, _ = pozisyon(a, x["t"] + 1, g, -1.0, sl, tut)
        r.append(p_long + p_short - 2 * ucret)
    return r


def s_cift_stop(sn, ucret, sl=1.0, tut=5, kaldirac_bol=2) -> list[float]:
    """Straddle'ın yarı boyutlu hâli (aynı sermaye, iki bacak)."""
    return [v / 2 for v in s_straddle(sn, ucret, sl, tut)]


# ======================================================================
# 5) ÖZELLİK MÜHENDİSLİĞİ (yön seçici için)
# ======================================================================
def ozellikler(sn: list[dict], veri: dict) -> np.ndarray:
    """
    Her sinyal için yön seçiciye girecek özellikler.
    ÖNEMLİ: hepsi sinyal ANINDA bilinebilir (geleceğe bakış yok).
    """
    # sembol bazında geçmiş istatistik için: geçmiş 3 dk getirilerin
    # otokorelasyonu — sembol geri mi dönüyor, trend mi yapıyor?
    sembol_ist = {}
    for sym, a in veri.items():
        c = a[:, 4]
        n = len(c)
        if n < 200:
            continue
        r = np.diff(np.log(np.maximum(c, 1e-12))) * 100
        # 3 dakikalık getiri ile sonraki 5 dakikalık getiri korelasyonu
        L = 3
        x1 = np.convolve(r, np.ones(L), mode="full")[:n - 1]
        fwd = np.full(n - 1, np.nan)
        for t in range(0, n - 1 - 5):
            fwd[t] = np.sum(r[t + 1:t + 6])
        gecerli = ~np.isnan(fwd) & (np.abs(x1) > 0)
        if gecerli.sum() > 100:
            k = np.corrcoef(x1[gecerli], fwd[gecerli])[0, 1]
            sembol_ist[sym] = float(k) if math.isfinite(k) else 0.0
        else:
            sembol_ist[sym] = 0.0

    X = []
    for x in sn:
        h = dt.datetime.fromtimestamp(x["ts"] / 1000, dt.UTC).hour
        X.append([
            x["r3"] / 2.0,                         # yön + büyüklük
            abs(x["r3"]) / 2.0,
            math.log1p(x["vr3"]) / 4.0,
            math.log1p(x["cascade"]) / 3.0,
            1.0 if x["r3"] > 0 else -1.0,          # taraf
            sembol_ist.get(x["sym"], 0.0),
            math.sin(2 * math.pi * h / 24),
            math.cos(2 * math.pi * h / 24),
        ])
    return np.array(X, dtype=float)


def s_ogrenen(sn, veri, ucret, egitim_oran=0.6, sl=2.0, tut=5) -> dict:
    """
    C) YÖN SEÇİCİ — lojistik regresyon (numpy ile, sıfır bağımlılık).

    Hedef: ileriye dönük getirinin işareti (+1 yukarı / -1 aşağı).
    Eğitim: zaman sırasına göre ilk %60. Test: son %40. (walk-forward)

    Model çıktısı > 0.5 ise LONG, değilse SHORT açılır.
    """
    X = ozellikler(sn, veri)
    # hedef: giriş = sonraki dakika açılışı, çıkış = tut sonrası kapanış
    y, rlar = [], []
    for x in sn:
        a = x["a"]
        g = a[x["t"] + 1, 1]
        if g <= 0:
            y.append(0.0); rlar.append(0.0); continue
        k = min(x["t"] + tut, a.shape[0] - 1)
        fwd = (a[k, 4] - g) / g * 100.0
        y.append(1.0 if fwd > 0 else 0.0)
        rlar.append(fwd)
    y = np.array(y); rlar = np.array(rlar)

    kes = int(len(sn) * egitim_oran)
    # standardize (yalnızca EĞİTİM istatistikleriyle — sızıntı yok)
    mu = X[:kes].mean(axis=0)
    sd = X[:kes].std(axis=0) + 1e-9
    Xs = (X - mu) / sd

    # lojistik regresyon: gradyan inişi
    w = np.zeros(Xs.shape[1]); b = 0.0
    lr = 0.5
    Xe, ye = Xs[:kes], y[:kes]
    for _ in range(3000):
        z = Xe @ w + b
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        gw = Xe.T @ (p - ye) / len(ye) + 1e-4 * w
        gb = float(np.mean(p - ye))
        w -= lr * gw
        b -= lr * gb

    # test dönemi
    Xt = Xs[kes:]
    pt = 1 / (1 + np.exp(-np.clip(Xt @ w + b, -30, 30)))
    yon = np.where(pt > 0.5, 1.0, -1.0)

    pnl = []
    dogru = 0
    for i in range(kes, len(sn)):
        x = sn[i]
        a = x["a"]
        g = a[x["t"] + 1, 1]
        if g <= 0:
            continue
        yon_i = yon[i - kes]
        p, _, _ = pozisyon(a, x["t"] + 1, g, yon_i, sl, tut)
        pnl.append(p - ucret)
        if (rlar[i] > 0 and yon_i > 0) or (rlar[i] < 0 and yon_i < 0):
            dogru += 1

    # eğitim dönemi referansı
    pe = 1 / (1 + np.exp(-np.clip(Xs[:kes] @ w + b, -30, 30)))
    yone = np.where(pe > 0.5, 1.0, -1.0)
    pnl_e = []
    for i in range(kes):
        x = sn[i]
        a = x["a"]
        g = a[x["t"] + 1, 1]
        if g <= 0:
            continue
        p, _, _ = pozisyon(a, x["t"] + 1, g, yone[i], sl, tut)
        pnl_e.append(p - ucret)

    return {"test": pnl, "egitim": pnl_e,
            "yön_isabet": dogru / max(1, len(pnl)),
            "w": w}


# ======================================================================
# 6) RAPOR
# ======================================================================
def ozet(ad: str, r: list[float], ek: str = "") -> None:
    if not r:
        print(f"  {ad:<34} VERİ YOK")
        return
    ort = statistics.mean(r)
    isa = sum(1 for q in r if q > 0) / len(r) * 100
    eq = np.cumsum(np.array(r))
    mdd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0.0
    print(f"  {ad:<34}{len(r):>6}{ort:>+9.3f}%{isa:>7.1f}%{sum(r):>+10.1f}%{mdd:>8.0f}{ek}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ucret", type=float, default=0.10)
    ap.add_argument("--sembol", type=int, default=0)
    a = ap.parse_args()

    veri = veri_yukle(a.sembol or None)
    print(f"{len(veri)} sembol")
    sn = dizi_ekle(sinyalleri_bul(veri), veri)
    print(f"{len(sn)} ham sinyal")
    sn = cascade_ekle(sn, esik=3)
    print(f"{len(sn)} cascade sinyali (eşik 3)\n")
    if len(sn) < 30:
        print("yetersiz veri")
        return 1

    print("=" * 92)
    print(f" STRATEJİ KIYASLAMASI — ücret %{a.ucret} gidiş-dönüş")
    print("=" * 92)
    print(f"  {'strateji':<34}{'n':>6}{'ort':>10}{'isabet':>8}{'toplam':>11}{'MDD':>8}")
    print("-" * 92)

    ozet("D  temel fade (SL2/tut5)", s_temel(sn, a.ucret, 2.0, 5))
    ozet("A  stop-and-reverse (1 dönüş)", s_stop_reverse(sn, a.ucret, 2.0, 5, 1))
    ozet("A  stop-and-reverse (2 dönüş)", s_stop_reverse(sn, a.ucret, 2.0, 5, 2))
    ozet("B  straddle SL1 (tam boyut)", s_straddle(sn, a.ucret, 1.0, 5))
    ozet("B  straddle SL2 (tam boyut)", s_straddle(sn, a.ucret, 2.0, 5))
    print()

    og = s_ogrenen(sn, veri, a.ucret, 0.6, 2.0, 5)
    print("=" * 92)
    print(" C  YÖN SEÇİCİ (lojistik regresyon · walk-forward)")
    print("=" * 92)
    print(f"  yön isabeti (test): %{og['yön_isabet']*100:.1f}   "
          f"→ rastgele %50, sabit fade ~%50")
    ozet("C  eğitim dönemi (ilk %60)", og["egitim"])
    ozet("C  TEST dönemi (son %40)", og["test"])
    print()
    print("  katsayılar (standartlaştırılmış):")
    adlar = ["r3 yön", "|r3|", "log vr3", "log cascade",
             "taraf(+yukarı)", "sembol reversion", "saat sin", "saat cos"]
    for ad, w in zip(adlar, og["w"]):
        print(f"    {ad:<20}{w:>+8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
