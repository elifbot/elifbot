#!/usr/bin/env python3
"""
maker_testi.py — MAKER (limit) GİRİŞİN GERÇEK FİLL ORANINI ÖLÇER

SORU: Limit emri koyup 30 saniye beklemek mantıklı mı?

Canlıda ilk sinyalde emir dolmadı ve kaçan işlem +1,77 USDT kazanan bir
işlemdi. Yani maker'ın iki etkisi var:
    (+) daha düşük komisyon + %0,05 daha iyi giriş
    (−) dolmayan emirler yüzünden kaçan işlemler

Bu betik ikisini de 7 günlük 1 dakikalık veride ölçer.

SINIRLAMA: Elde 1 dakikalık mumlar var, 30 saniyelik veri yok. Bu yüzden
dolumu ÜST SINIR olarak ölçüyorum: sinyal dakikasının VE sonraki dakikanın
high/low'u limit fiyata değiyorsa "dolardı" sayılır. Yani gerçek fill oranı
buradaki sayıdan KÜÇÜK veya eşittir.

Kullanım:
    python3 maker_testi.py [--bekle-dk 5] [--pay 0.05] [--bekle-sn 30]
"""
from __future__ import annotations

import argparse
import datetime
import glob
import os
import statistics

import numpy as np

PARCA = "/home/user/.veri_parca"
ONBELLEK = "/home/user/okx_onbellek.npz"


def veri_yukle() -> dict[str, np.ndarray]:
    if os.path.exists(ONBELLEK):
        z = np.load(ONBELLEK, allow_pickle=True)
        return {k: z[k] for k in z.files}
    out = {}
    for p in glob.glob(f"{PARCA}/*.npy"):
        out[os.path.basename(p)[:-4]] = np.load(p)
    return out


def sinyaller(veri: dict, esik=1.2, maks=2.0, vr3_min=10.0,
              geri=3, medyan=30) -> list[dict]:
    """3 dk getiri + 3 dk ortalama hacim oranı ile sinyal üretir."""
    out = []
    for sym, a in veri.items():
        if a.shape[0] < 200:
            continue
        a = a[np.argsort(a[:, 0])]
        ts, o, h, l, c, v = a.T
        n = len(c)
        ret = np.full(n, np.nan)
        ret[geri:] = (c[geri:] - c[:-geri]) / c[:-geri] * 100.0
        vsum = np.convolve(v, np.ones(geri), mode="full")[:n]
        vr3 = np.full(n, np.nan)
        for t in range(geri + medyan, n):
            m = np.median(v[t - geri - medyan:t - geri])
            if m > 0:
                vr3[t] = vsum[t - geri + 1] / (m * geri)
        uy = ((np.abs(ret) >= esik) & (np.abs(ret) <= maks)
              & (vr3 >= vr3_min))
        for t in np.flatnonzero(uy):
            if t + 1 >= n:
                continue
            out.append({"sym": sym, "t": int(t), "ts": int(ts[t]),
                        "a": a, "ret": float(ret[t]),
                        "yon": -1.0 if ret[t] > 0 else 1.0})
    return out


def degerlendir(sn: list[dict], pay: float, bekle_sn: float,
                sl: float, tut: int) -> dict:
    """
    Her sinyal için iki senaryo:
      MARKET — sonraki dakika açılışından gir, sl/tut ile çık
      MAKER  — limit emri, `bekle_sn` içinde değerse limit fiyattan gir;
               değmezse işlem YOK (kaçan fırsat)
    """
    m_net, k_net, dolan, kacan = [], [], 0, 0
    kacan_kazanc = []

    for x in sn:
        a = x["a"]
        t = x["t"]
        n = len(a)
        yon = x["yon"]
        giris_m = a[t + 1, 1]                  # sonraki dakika AÇILIŞI
        if giris_m <= 0 or t + 1 >= n:
            continue

        # --- MARKET senaryosu ---
        r_m = cikis_getirisi(a, t + 1, giris_m, yon, sl, tut)
        # --- MAKER senaryosu ---
        limit = giris_m * (1 - yon * pay / 100)
        # dolum penceresi: sinyal dakikasının kalanı + bekle_sn
        # muhafazakâr: sadece sonraki 1 dakikanın high/low'una bak
        # (30 sn'lik çözünürlük yok → üst sınır)
        dk_sinir = max(1, int(round(bekle_sn / 60.0)))
        doldu, d_t = False, None
        for k in range(t + 1, min(t + 1 + dk_sinir, n)):
            if (yon > 0 and a[k, 3] <= limit) or (yon < 0 and a[k, 2] >= limit):
                doldu, d_t = True, k
                break
        if doldu:
            dolan += 1
            r_k = cikis_getirisi(a, d_t, limit, yon, sl, tut)
            k_net.append(r_k - 2 * 0.02)       # maker ücreti %0,02 × 2
        else:
            kacan += 1
            kacan_kazanc.append(r_m)
        m_net.append(r_m - 2 * 0.05)           # taker ücreti %0,05 × 2

    return {"market": m_net, "maker": k_net, "dolan": dolan,
            "kacan": kacan, "kacan_kazanc": kacan_kazanc}


def cikis_getirisi(a, bas: int, giris: float, yon: float,
                   sl: float, tut: int) -> float:
    """SL'ye değerse -sl, tut süresi dolunca kapanıştan; yön düzeltilmiş %."""
    n = len(a)
    if giris <= 0:
        return 0.0
    zarar = giris * (1 - yon * sl / 100)
    for k in range(bas, min(bas + tut, n)):
        if (yon > 0 and a[k, 3] <= zarar) or (yon < 0 and a[k, 2] >= zarar):
            return -sl
    k = min(bas + tut - 1, n - 1)
    return (a[k, 4] - giris) / giris * 100.0 * yon


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pay", type=float, default=0.05)
    ap.add_argument("--bekle-sn", type=float, default=30.0)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--tut", type=int, default=5)
    a = ap.parse_args()

    veri = veri_yukle()
    print(f"{len(veri)} sembol yüklendi")
    sn = sinyaller(veri)
    print(f"{len(sn)} sinyal\n")

    for pay in (0.02, 0.05, 0.10):
       for bsn in (15, 30, 60):
            r = degerlendir(sn, pay, bsn, a.sl, a.tut)
            m, k = r["market"], r["maker"]
            if not m or not k:
                print(f"  pay={pay}% bekle={bsn}sn → yeterli veri yok")
                continue
            print(f"  pay=%{pay:.2f}  bekle={bsn:>2}sn | "
                  f"dolan {r['dolan']:>5}/{len(m)} (%{r['dolan']/len(m)*100:>4.1f}) | "
                  f"MARKET net {statistics.mean(m):>+7.3f}% | "
                  f"MAKER net {statistics.mean(k):>+7.3f}% | "
                  f"toplam M {sum(m):>+7.0f} K {sum(k):>+7.0f}")
       print()

    # kaçan işlemler kazanan mıydı?
    r = degerlendir(sn, 0.05, 30, a.sl, a.tut)
    kk = r["kacan_kazanc"]
    if kk:
        print(f"KAÇAN İŞLEMLER (n={len(kk)}): ortalama {statistics.mean(kk):+.3f}%")
        print(f"  kazanan oranı: %{sum(1 for q in kk if q > 0)/len(kk)*100:.1f}")
        print(f"  → kaçanlar {'İYİ' if statistics.mean(kk) > 0 else 'KÖTÜ'} işlemlermiş")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
