"""Risk matematigi (saf fonksiyonlar, borsa baglantisi yok).

Kullanici kararlari: sabit marj (ornek 50$), kaldirac (ornek 10x) ve
islem basina azami zarar (ornek 25$). Burada stop fiyati, komisyon dahil
zarar tam max_loss_usd olacak sekilde hesaplanir; stop likidasyondan once olmali.
"""

MMR = 0.005  # kabaca bakim marji orani (gercek deger borsa/kademe bazli, sonra degistirilecek)


def pozisyon_boyutu(giris, marj_usd=50.0, kaldirac=10.0):
    """Nominal buyukluk ve adet. nominal = marj * kaldirac."""
    if giris <= 0 or marj_usd <= 0 or kaldirac < 1:
        raise ValueError("gecersiz giris/marj/kaldirac")
    nominal = marj_usd * kaldirac
    return {"nominal": nominal, "adet": nominal / giris}


def stop_mesafesi_sabit_zarar(giris, adet, max_zarar_usd=25.0, komisyon_orani=0.0005):
    """Giris+cikis komisyonu dahil toplam zarar max_zarar_usd olacak stop mesafesi (fiyat farki)."""
    if giris <= 0 or adet <= 0 or max_zarar_usd <= 0:
        raise ValueError("gecersiz parametre")
    # zarar = mesafe*adet + komisyon(giris) + komisyon(cikis)  ~  mesafe*adet + 2*k*giris*adet
    mesafe = (max_zarar_usd - 2 * komisyon_orani * giris * adet) / adet
    if mesafe <= 0:
        raise ValueError("komisyon max zarari asiyor, boyutu kucultun")
    return mesafe


def stop_fiyati(taraf, giris, mesafe):
    if taraf not in ("LONG", "SHORT"):
        raise ValueError("taraf LONG veya SHORT olmali")
    return giris - mesafe if taraf == "LONG" else giris + mesafe


def likidasyon_fiyati(taraf, giris, kaldirac, mmr=MMR):
    """Kaba likidasyon tahmini (izole marj)."""
    oran = max(0.0005, 1.0 / kaldirac - mmr)
    return giris * (1 - oran) if taraf == "LONG" else giris * (1 + oran)


def atr_stop_icin_adet(giris, atr, atr_carpani=2.5, max_zarar_usd=25.0,
                       marj_usd=50.0, kaldirac=10.0):
    """ATR stop'unda zarar max_zarar_usd'yi ASMASIN diye adedi kisitla.

    Eski HTML surumundeki eksik buydu: ATR stop'ta zarar sinirsizdi.
    Donen adet = min(marj*kaldirac/giris, max_zarar/stop_mesafesi).
    """
    if giris <= 0 or atr <= 0:
        raise ValueError("gecersiz giris/atr")
    mesafe = atr * atr_carpani
    adet_marj = marj_usd * kaldirac / giris
    adet_risk = max_zarar_usd / mesafe
    return {"adet": min(adet_marj, adet_risk), "mesafe": mesafe,
            "risk_ile_kisitlandi": adet_risk < adet_marj}
