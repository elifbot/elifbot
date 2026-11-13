# -*- coding: utf-8 -*-
"""test_v7_bes.py — "BEŞ" (v7) kanıt testi: DÖRT-R + kovalama filtresi."""
from v3 import ortak
from v7.bes import BesBot

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


def bot():
    b = BesBot(); b.fiyat[SEMBOL] = 100.0; b.sembol[BAZ] = SEMBOL
    return b


def gecmis(b, son_fiyat, onceki=100.0, saniye=60.0):
    b.gecmis[SEMBOL] = [(SIMDI - saniye, onceki), (SIMDI, son_fiyat)]


def oy(b, yon, vol, akis=0.3, tetik="HACIM_PATLAMASI_LONG (4.0x Hacim | +1.04%)"):
    b.oylar[(BAZ, yon)].append({"ts": SIMDI, "ad": "TURBO", "sembol": SEMBOL, "tetik": tetik,
                                "vol": vol, "akis": akis, "ivme": 0.4, "burst": 20000.0})


print("=" * 76)
print("T1 — sakin piyasa (%0,3 hareket) + 4,0x LONG -> GİRİŞ")
b = bot(); gecmis(b, 100.3); oy(b, 1, 4.0); b._girisleri_dene(SIMDI)
sonuc("T1", len(b.pozisyonlar) == 1, f"giriş {len(b.pozisyonlar)}")

print("\nT2 — tepe kovalama: son 30 sn'de %1,8 yükselmiş, 4,0x LONG -> RED")
b = bot(); gecmis(b, 101.8); oy(b, 1, 4.0); b._girisleri_dene(SIMDI)
sonuc("T2", len(b.pozisyonlar) == 0 and b.veto.get("KOVALAMA"), f"giriş {len(b.pozisyonlar)} veto {dict(b.veto)}")

print("\nT3 — aşağı yönde de aynı: son 30 sn'de %2,0 düşmüş, 2,6x SHORT -> RED")
b = bot(); gecmis(b, 98.0); oy(b, -1, 2.6, -0.3, tetik="OMEGA_COKUS_PATLAMASI_SHORT (2.6x | -0.73%)")
b._girisleri_dene(SIMDI)
sonuc("T3", len(b.pozisyonlar) == 0 and b.veto.get("KOVALAMA"), f"giriş {len(b.pozisyonlar)} veto {dict(b.veto)}")

print("\nT4 — %1,0 düşüş (tavanın altı), 2,6x SHORT -> GİRİŞ")
b = bot(); gecmis(b, 99.0); oy(b, -1, 2.6, -0.3, tetik="OMEGA_COKUS_PATLAMASI_SHORT (2.6x | -0.73%)")
b._girisleri_dene(SIMDI)
sonuc("T4", len(b.pozisyonlar) == 1, f"giriş {len(b.pozisyonlar)}")

print("\nT5 — zayıf LONG 3,0x (eşik 3,5x) -> RED")
b = bot(); gecmis(b, 100.2); oy(b, 1, 3.0); b._girisleri_dene(SIMDI)
sonuc("T5", len(b.pozisyonlar) == 0 and b.veto.get("ZAYIF_LONG_PATLAMASI"), f"veto {dict(b.veto)}")

print("\nT6 — hüsran çıkışı 90 sn (tepe < 1 $)")
b = bot(); gecmis(b, 100.2); oy(b, 1, 4.0); b._girisleri_dene(SIMDI)
b.fiyat[SEMBOL] = 100.10
b._yonet(SIMDI + 95)
sonuc("T6", not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "HUSRAN_CIKIS",
      f"{b.kapanan[-1]['exit_reason'] if b.kapanan else '—'}")

print("\nT7 — -10 $ stop")
b = bot(); gecmis(b, 100.2); oy(b, 1, 4.0); b._girisleri_dene(SIMDI)
b.fiyat[SEMBOL] = 98.10
b._yonet(SIMDI + 20)
sonuc("T7", not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "ZARAR_KES_-10$",
      f"{b.kapanan[-1]['exit_reason'] if b.kapanan else '—'}")

print("\nT8 — kara liste (OMEGA_HACIM_PATLAMASI_LONG)")
b = bot(); gecmis(b, 100.2); oy(b, 1, 5.0, tetik="OMEGA_HACIM_PATLAMASI_LONG (5.0x | -0.33%)")
b._girisleri_dene(SIMDI)
sonuc("T8", len(b.pozisyonlar) == 0 and b.veto.get("KARA_LISTE"), f"veto {dict(b.veto)}")

print("\nT9 — zombi 20 dk (tepe >= 1 $)")
b = bot(); gecmis(b, 100.2); oy(b, 1, 4.0); b._girisleri_dene(SIMDI)
b.fiyat[SEMBOL] = 100.45; b._yonet(SIMDI + 30)
b.fiyat[SEMBOL] = 100.10; b._yonet(SIMDI + 21 * 60)
sonuc("T9", not b.pozisyonlar and b.kapanan[-1]["exit_reason"] == "ZOMBI_CIKIS",
      f"{b.kapanan[-1]['exit_reason'] if b.kapanan else '—'}")

print("\n" + "=" * 76)
print(f"SONUÇ: {D} DOĞRU · {H} HATA")
