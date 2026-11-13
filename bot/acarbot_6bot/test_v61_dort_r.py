# -*- coding: utf-8 -*-
"""test_v61_dort_r.py — "DÖRT-R" (v6.1) kanıt testi.

T1  hüsran çıkışı: 60 sn (henüz değil)        -> pozisyon durur
T2  hüsran çıkışı: 95 sn, tepe < 1 $         -> HUSRAN_CIKIS
T3  hüsran çıkışı: 95 sn, tepe 1,8 $         -> çıkmaz
T4  LONG 2,5-3,5x bandı (v6.1'de serbest)    -> 3,0x LONG GİRİŞ
T5  LONG 2,0x (bandın altı)                  -> RED
T6  -10 $ stop                                -> ZARAR_KES_-10$
T7  zombi 20 dk                               -> ZOMBI_CIKIS
T8  kara liste (OMEGA_HACIM_PATLAMASI_LONG)   -> RED
T9  karşılaştırma: v6'da 3,0x LONG girmez, v6.1'de girer
"""
from v3 import ortak
from v6.dort import DortBot
from v61.dort_v61 import DortR

SIMDI = 1760000000.0
SEMBOL = "AKE-USDT-SWAP"
BAZ = ortak.baz(SEMBOL)
D = H = 0


def sonuc(ad, kosul, ek=""):
    global D, H
    if kosul:
        D += 1; print("  -> DOĞRU", ek)
    else:
        H += 1; print("  -> HATA  ", ek)


def bot(sinif=DortR):
    b = sinif(); b.fiyat[SEMBOL] = 100.0; b.sembol[BAZ] = SEMBOL
    return b


def oy(b, ad, yon, vol, akis, tetik="HACIM_PATLAMASI_LONG (3.0x Hacim | +1.04%)"):
    b.oylar[(BAZ, yon)].append({"ts": SIMDI, "ad": ad, "sembol": SEMBOL, "tetik": tetik,
                                "vol": vol, "akis": akis, "ivme": 0.4, "burst": 20000.0})


def gir(b, simdi=SIMDI):
    b._girisleri_dene(simdi)
    return len(b.pozisyonlar)

print("=" * 80)
print("T1 — 60 sn sonra: hüsran süresi dolmadı")
b = bot(); oy(b, "TURBO", 1, 3.0, 0.3); gir(b)
b.fiyat[SEMBOL] = 100.20      # net ~+0,50 $
b._yonet(SIMDI + 60)
sonuc("T1", len(b.pozisyonlar) == 1, f"açık {len(b.pozisyonlar)}")

print("\nT2 — 95 sn, tepe < 1 $ -> HÜSRAN ÇIKIŞI")
b = bot(); oy(b, "TURBO", 1, 3.0, 0.3); gir(b)
b.fiyat[SEMBOL] = 100.10      # net ~0,00 $
b._yonet(SIMDI + 95)
sonuc("T2", not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "HUSRAN_CIKIS",
      f"{b.kapanan[-1]['exit_reason'] if b.kapanan else '—'} net {b.kapanan[-1]['net_pnl_usd'] if b.kapanan else 0}")

print("\nT3 — 95 sn ama tepe 1,8 $ (işlem canlı) -> çıkmaz")
b = bot(); oy(b, "TURBO", 1, 3.0, 0.3); gir(b)
b.fiyat[SEMBOL] = 100.45           # net ~+1,75 $
b._yonet(SIMDI + 30)
b.fiyat[SEMBOL] = 100.40
b._yonet(SIMDI + 95)
sonuc("T3", len(b.pozisyonlar) == 1, f"açık {len(b.pozisyonlar)} tepe {list(b.pozisyonlar.values())[0].zirve_net:.2f}")

print("\nT4 — LONG 3,0x: v6.1'de serbest (2,5x eşiği)")
b = bot(); oy(b, "TURBO", 1, 3.0, 0.3); n = gir(b)
sonuc("T4", n == 1, f"giriş {n}")

print("\nT5 — LONG 2,0x: bandın altı -> RED")
b = bot(); oy(b, "TURBO", 1, 2.0, 0.3); n = gir(b)
sonuc("T5", n == 0 and b.veto.get("ZAYIF_LONG_PATLAMASI"), f"giriş {n} veto {dict(b.veto)}")

print("\nT6 — -10 $ stop")
b = bot(); oy(b, "TURBO", 1, 4.0, 0.3); gir(b)
b.fiyat[SEMBOL] = 98.10       # -1,9% -> ~-10 $
b._yonet(SIMDI + 20)
sonuc("T6", not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "ZARAR_KES_-10$",
      f"{b.kapanan[-1]['exit_reason'] if b.kapanan else '—'}")

print("\nT7 — zombi 20 dk (tepe >= 1 $ olduğu için hüsran devreye girmez)")
b = bot(); oy(b, "TURBO", 1, 4.0, 0.3); gir(b)
b.fiyat[SEMBOL] = 100.45
b._yonet(SIMDI + 30)
b.fiyat[SEMBOL] = 100.10
b._yonet(SIMDI + 21 * 60)
sonuc("T7", not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "ZOMBI_CIKIS",
      f"{b.kapanan[-1]['exit_reason'] if b.kapanan else '—'}")

print("\nT8 — kara liste")
b = bot(); oy(b, "OMEGA", 1, 5.0, 0.3, tetik="OMEGA_HACIM_PATLAMASI_LONG (5.0x | -0.33%)"); n = gir(b)
sonuc("T8", n == 0 and b.veto.get("KARA_LISTE"), f"giriş {n} veto {dict(b.veto)}")

print("\nT9 — v6 vs v6.1: aynı 3,0x LONG sinyali")
b6 = bot(DortBot); oy(b6, "TURBO", 1, 3.0, 0.3); n6 = gir(b6)
b61 = bot(DortR); oy(b61, "TURBO", 1, 3.0, 0.3); n61 = gir(b61)
sonuc("T9", n6 == 0 and n61 == 1, f"v6 giriş {n6} · v6.1 giriş {n61}")

print("\n" + "=" * 80)
print(f"SONUÇ: {D} DOĞRU · {H} HATA")
