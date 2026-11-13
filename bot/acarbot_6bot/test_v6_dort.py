# -*- coding: utf-8 -*-
"""test_v6_dort.py — "DÖRT" (v6) ve "ÜÇ-R" (v5.1) deterministik kanıt testi.

DÖRT = 4 seans / 71 kapanan işlemden çıkarılan KAZANAN indikatör listesi +
zayıf-LONG (2,5-3,5x = -45,72 $) yasağı + tek motor sinyaliyle giriş.

T1  kara listedeki indikatör (HACIM_COKUSU_LONG)      -> RED (KARA_LISTE)
T2  beyaz listede olmayan indikatör                    -> RED (BEYAZ_LISTE_DISI)
T3  beyaz listede LONG ama hacim 3,0x (zayıf)          -> RED (ZAYIF_LONG_PATLAMASI)
T4  beyaz listede LONG 4,0x                            -> GİRİŞ
T5  beyaz listede SHORT 2,5x                           -> GİRİŞ (SHORT serbest)
T6  SHORT 1,5x (çok zayıf)                             -> RED (COK_ZAYIF_SHORT)
T7  TEK motor sinyali yeter (2/2 anlaşma aranmaz)      -> GİRİŞ
T8  -10 $ net stop                                     -> ZARAR_KES_-10$
T9  zombi çıkışı 20 dk (19 dk hayır / 21 dk evet)      -> ZOMBI_CIKIS
T10 ÜÇ-R (v5.1) sabitleri: 3,5x eşiği + 20 dk zombi    -> 3,7x LONG girer, 3,2x girmez
"""
from __future__ import annotations

from v3 import ortak
from v5.birlesik import UcPoz
from v6.dort import DortBot
from v51.birlesik_v51 import UcR
import v51.birlesik_v51 as m51

SIMDI = 1760000000.0
SEMBOL = "AKE-USDT-SWAP"
BAZ = ortak.baz(SEMBOL)
DOGRU, HATA = 0, 0


def sonuc(ad: str, kosul: bool, ek: str = "") -> None:
    global DOGRU, HATA
    if kosul:
        DOGRU += 1
        print(f"  -> DOĞRU {ek}")
    else:
        HATA += 1
        print(f"  -> HATA   {ek}")


def bot(sinif=DortBot):
    b = sinif()
    b.fiyat[SEMBOL] = 100.0
    b.sembol[BAZ] = SEMBOL
    return b


def oy(b, ad, yon, vol, akis, ivme=0.40, burst=20000.0, tetik="HACIM_PATLAMASI_LONG (4.3x Hacim | +1.04%)"):
    b.oylar[(BAZ, yon)].append({"ts": SIMDI, "ad": ad, "sembol": SEMBOL, "tetik": tetik,
                                "vol": vol, "akis": akis, "ivme": ivme, "burst": burst})


def gir(b, simdi=SIMDI):
    b._girisleri_dene(simdi)
    return len(b.pozisyonlar)


print("=" * 84)
print("T1 — kara liste: HACIM_COKUSU_LONG (4 seansta -2,15 $)")
b = bot(); oy(b, "TURBO", 1, 6.0, 0.30, tetik="HACIM_COKUSU_LONG (Satış Hacmi Çöktü 9.5x->1.5x)")
n = gir(b)
sonuc("T1", n == 0 and b.veto.get("KARA_LISTE"), f"giriş {n} · veto {dict(b.veto)}")

print("\nT2 — kara liste: OMEGA_HACIM_PATLAMASI_LONG (-4,74 $)")
b = bot(); oy(b, "OMEGA", 1, 5.0, 0.30, tetik="OMEGA_HACIM_PATLAMASI_LONG (5.0x | -0.33%)")
n = gir(b)
sonuc("T2", n == 0 and b.veto.get("KARA_LISTE"), f"giriş {n} · veto {dict(b.veto)}")

print("\nT3 — beyaz liste dışı indikatör (HACIM_COKUSU_LONG dışında kalan 'HACIM_DONUSU_LONG')")
b = bot(); oy(b, "TURBO", 1, 5.0, 0.30, tetik="HACIM_DONUSU_LONG (5.0x Hacim)")
n = gir(b)
sonuc("T3", n == 0 and b.veto.get("BEYAZ_LISTE_DISI"), f"giriş {n} · veto {dict(b.veto)}")

print("\nT4 — beyaz liste LONG ama zayıf hacim 3,0x (2,5-3,5x kovası = -45,72 $)")
b = bot(); oy(b, "TURBO", 1, 3.0, 0.30)
n = gir(b)
sonuc("T4", n == 0 and b.veto.get("ZAYIF_LONG_PATLAMASI"), f"giriş {n} · veto {dict(b.veto)}")

print("\nT5 — beyaz liste LONG 4,0x (3,5-4,5x kovası = +31,55 $)")
b = bot(); oy(b, "TURBO", 1, 4.0, 0.30)
n = gir(b)
sonuc("T5", n == 1, f"giriş {n} · tetik {list(b.pozisyonlar.values())[0].tetik if n else '—'}")

print("\nT6 — SHORT 2,5x, kazanandır (COKUS_PATLAMASI_SHORT)")
b = bot(); oy(b, "OMEGA", -1, 2.5, -0.30, tetik="OMEGA_COKUS_PATLAMASI_SHORT (2.5x | -0.63%)")
n = gir(b)
sonuc("T6", n == 1, f"giriş {n}")

print("\nT7 — SHORT 1,5x çok zayıf")
b = bot(); oy(b, "TURBO", -1, 1.5, -0.30, tetik="HACIM_COKUSU_SHORT (Tepe Hacmi Çöktü)")
n = gir(b)
sonuc("T7", n == 0 and b.veto.get("COK_ZAYIF_SHORT"), f"giriş {n} · veto {dict(b.veto)}")

print("\nT8 — TEK motor sinyali yeterli (ÜÇ'ün 2/2 şartı yok)")
b = bot(); oy(b, "TURBO", 1, 4.6, 0.40)
n = gir(b)
sonuc("T8", n == 1, f"giriş {n} · oylar {list(b.pozisyonlar.values())[0].oylar if n else '—'}")

print("\nT9 — -10 $ stop")
b = bot(); oy(b, "TURBO", 1, 4.6, 0.40); gir(b)
pid = list(b.pozisyonlar)[0]
b.fiyat[SEMBOL] = 100.0 * (1 - 0.021)   # ~-10,5 $ (500 $ nominal)
b._yonet(SIMDI + 30)
sonuc("T9", not b.pozisyonlar and b.kapanan and b.kapanan[-1]["exit_reason"] == "ZARAR_KES_-10$",
      f"kapanan {b.kapanan[-1]['exit_reason'] if b.kapanan else '—'} · net {b.kapanan[-1]['net_pnl_usd'] if b.kapanan else 0}")

print("\nT10 — zombi: 19 dk hayır, 21 dk evet (v5'te 8 dk idi)")
b = bot(); oy(b, "TURBO", 1, 4.6, 0.40); gir(b)
b._yonet(SIMDI + 19 * 60)
erken = len(b.pozisyonlar)
b._yonet(SIMDI + 21 * 60)
sonuc("T10", erken == 1 and not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "ZOMBI_CIKIS",
      f"19 dk açık {erken} · 21 dk kapanan {b.kapanan[-1]['exit_reason'] if b.kapanan else '—'}")

print("\nT11 — ÜÇ-R (v5.1) sabitleri ve davranışı")
print(f"  ZAYIF_LONG_HACIM = {m51.ZAYIF_LONG_HACIM} · ZOMBI_SEC = {m51.ZOMBI_SEC}")
b = bot(UcR); oy(b, "TURBO", 1, 3.7, 0.30); oy(b, "OMEGA", 1, 3.7, 0.30); n1 = gir(b)
b2 = bot(UcR); oy(b2, "TURBO", 1, 3.2, 0.30); oy(b2, "OMEGA", 1, 3.2, 0.30); n2 = gir(b2)
sonuc("T11", m51.ZAYIF_LONG_HACIM == 3.5 and m51.ZOMBI_SEC == 1200.0 and n1 == 1 and n2 == 0,
      f"3,7x giriş {n1} · 3,2x giriş {n2}")

print("\n" + "=" * 84)
print(f"SONUÇ: {DOGRU} DOĞRU · {HATA} HATA")
