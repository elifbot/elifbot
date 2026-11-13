# -*- coding: utf-8 -*-
"""sizing.py — pozisyon boyutu, stop fiyatı ve tasfiye matematiği.

Tek kural: **notional her zaman 500 $** (50 $ teminat × 10x). Bot "iyi hissettiğinde"
büyütmez, küçültmez. Kasa büyüse de küçülse de pozisyon başına risk sabittir; bu,
kullanıcı kuralının doğal sonucudur ve testlerin karşılaştırılabilir olmasını sağlar.

Borsa gerçekleri (adım yuvarlaması, min notional, kontrat çarpanı) burada uygulanır;
motor "500 $ açtım" sanıp 380 $ açmaz.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import KasaKurallari
from .types import Enstruman, Yon


@dataclass(frozen=True)
class Boyut:
    adet: float
    notional_usd: float
    teminat_usd: float
    giris_fiyati: float
    stop_fiyati: float
    gecerli: bool = True
    neden: str = ""


def birim_fiyat(enstruman: Enstruman, fiyat: float) -> float:
    """1 adet kontratın USD değeri (OKX'te ctVal, Binance'te 1.0)."""
    return fiyat * max(1e-12, enstruman.kontrat_carpani)


def boyut_hesapla(
    enstruman: Enstruman,
    fiyat: float,
    yon: Yon,
    kurallar: KasaKurallari,
    kayma_tamponu: float = 0.0005,
) -> Boyut:
    """500 $ notional'a en yakın, borsa adımlarına uygun miktarı üretir.

    kayma_tamponu: stop emri *market* tetiklenir; tetik ile dolum arasındaki kaymayı
    -10 $ bütçesinin içinde tutmak için stop fiyatı bu kadar daha yakına çekilir.
    """
    if fiyat <= 0:
        return Boyut(0, 0, 0, fiyat, 0, False, "fiyat sıfır/negatif")

    hedef = kurallar.notional_per_pozisyon_usd
    birim = birim_fiyat(enstruman, fiyat)
    ham_adet = hedef / birim
    adet = enstruman.miktar_yuvarla(ham_adet, asagi=True)

    if adet < enstruman.min_miktar or adet <= 0:
        return Boyut(0, 0, 0, fiyat, 0, False,
                     f"adım çok kaba (min {enstruman.min_miktar}, hedef {ham_adet:.8f})")

    notional = adet * birim
    if notional < max(enstruman.min_notional_usd, 5.0):
        return Boyut(0, 0, 0, fiyat, 0, False, f"notional {notional:.2f}$ < min")

    # 500 $ hedefinden %10'dan fazla sapma kabul edilmez: adım yuvarlaması
    # riski bozuyorsa o sembolde işlem yapılmaz.
    if notional < hedef * 0.90:
        return Boyut(0, 0, 0, fiyat, 0, False,
                     f"yuvarlama sonrası notional {notional:.0f}$ (hedef {hedef:.0f}$) — sapma >%10")

    stop_px = stop_fiyati(enstruman, fiyat, yon, kurallar, notional, kayma_tamponu)
    return Boyut(adet=adet, notional_usd=round(notional, 4),
                 teminat_usd=round(notional / kurallar.kaldirac, 4),
                 giris_fiyati=fiyat, stop_fiyati=stop_px)


def stop_fiyati(
    enstruman: Enstruman,
    giris: float,
    yon: Yon,
    kurallar: KasaKurallari,
    notional: float | None = None,
    kayma_tamponu: float = 0.0005,
) -> float:
    """Net -10 $ (komisyon + kayma dahil) verecek stop tetik fiyatı."""
    n = notional if notional and notional > 0 else kurallar.notional_per_pozisyon_usd
    # bütçe: 10 $ - (giriş taker + çıkış taker)
    komisyon = n * 2.0 * kurallar.taker_fee_orani
    butce = max(0.01, kurallar.stop_net_usd - komisyon)
    mesafe = butce / n + kayma_tamponu           # + kayma payı
    if yon is Yon.LONG:
        px = giris * (1.0 - mesafe)
    else:
        px = giris * (1.0 + mesafe)
    return enstruman.fiyat_yuvarla(px)


def stop_mesafesi_pct(kurallar: KasaKurallari, kayma_tamponu: float = 0.0005) -> float:
    return (kurallar.stop_net_usd - kurallar.gidis_donus_komisyon_usd) / \
        kurallar.notional_per_pozisyon_usd + kayma_tamponu


# --------------------------------------------------------------- tasfiye
def tasfiye_mesafesi_pct(kasa_usd: float, pozisyon_sayisi: int, kurallar: KasaKurallari,
                         bakim_marj_orani: float = 0.005) -> float:
    """CROSS marjinde, tüm pozisyonlar aynı yönde hareket ederse tasfiye mesafesi.

    Kasa 1.000 $, pozisyon başına 500 $ notional, bakım marjı %0.5 varsayımıyla:
      n=1  -> %199      (tek pozisyon asla tasfiye etmez)
      n=10 -> %19.5
      n=20 -> %9.5
      n=40 -> %4.5
      n=100-> %1.5
      n=170-> %0.68
    Yani "sınırsız pozisyon" pratikte 20'den sonra kasanın tamamını tek bir
    piyasa hareketine rehin verir. Bu bir görüş değil, bölme işlemidir.
    """
    if pozisyon_sayisi <= 0:
        return float("inf")
    n = pozisyon_sayisi
    notional = n * kurallar.notional_per_pozisyon_usd
    bakim = notional * bakim_marj_orani
    kalan = kasa_usd - bakim
    return max(0.0, kalan / notional)


def guvenli_max_pozisyon(kasa_usd: float, kurallar: KasaKurallari,
                         kabul_edilen_tasfiye_mesafesi: float = 0.10) -> int:
    """Verilen tasfiye mesafesini koruyan en yüksek eşzamanlı pozisyon sayısı.

    %10 kabul -> kasa 1.000 $ iken 18 pozisyon (√ 500$ * 18 = 9.000$ notional).
    Bu, kullanıcı kuralındaki "sınırsız" ifadesini değiştirmez; yalnızca
    türetilmiş risk raporunda uyarı eşiği olarak kullanılır.
    """
    en_iyi = 0
    for n in range(1, 200):
        if tasfiye_mesafesi_pct(kasa_usd, n, kurallar) >= kabul_edilen_tasfiye_mesafesi:
            en_iyi = n
        else:
            break
    return en_iyi
