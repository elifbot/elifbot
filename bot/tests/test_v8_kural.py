# -*- coding: utf-8 -*-
"""Kullanıcı kuralı ve risk matematiği testleri.

Bu dosya "kural gerçekten uygulanıyor mu" sorusunu kilitler. Bir geliştirici
teminatı 50'den 60'a çıkarır veya stopu -10'dan -20'ye alırsa test kırılır.
"""
from __future__ import annotations

import math

import pytest

from bot.v8.config import KasaKurallari, MotorAyarlari, RiskProfili
from bot.v8.sizing import (boyut_hesapla, guvenli_max_pozisyon, stop_fiyati,
                           tasfiye_mesafesi_pct)
from bot.v8.types import Enstruman, Yon


def enstruman(px_adim=0.01, miktar_adim=0.001, min_miktar=0.001, carpan=1.0):
    return Enstruman("test", "BTCUSDT", "BTC", px_adim, miktar_adim, min_miktar, 5.0, carpan)


# ------------------------------------------------------------------ kural
def test_kural_sabitleri():
    k = KasaKurallari()
    assert k.baslangic_kasa_usd == 1000.0
    assert k.teminat_per_pozisyon_usd == 50.0
    assert k.kaldirac == 10
    assert k.notional_per_pozisyon_usd == 500.0
    assert k.marjin_modu == "cross"
    assert k.max_pozisyon == 0          # sınırsız
    assert k.stop_net_usd == 10.0


def test_izole_marjin_reddedilir():
    with pytest.raises(ValueError):
        KasaKurallari(marjin_modu="isolated").dogrula()


def test_pozisyon_limiti_koymak_reddedilir():
    with pytest.raises(ValueError):
        KasaKurallari(max_pozisyon=10).dogrula()


def test_komisyon_ve_stop_mesafesi():
    k = KasaKurallari()
    assert k.gidis_donus_komisyon_usd == pytest.approx(0.50)
    # (10 - 0.5) / 500 = %1.9
    assert k.stop_fiyat_mesafesi == pytest.approx(0.019)


def test_yetersiz_stop_reddedilir():
    with pytest.raises(ValueError):
        KasaKurallari(stop_net_usd=0.4).dogrula()


# ------------------------------------------------------------ boyutlandırma
def test_boyut_notional_500():
    # adım 0.0001 -> 500 $ notional tam yakalanır
    b = boyut_hesapla(enstruman(0.01, 0.0001), 60000.0, Yon.LONG, KasaKurallari())
    assert b.gecerli
    assert b.notional_usd == pytest.approx(500.0, rel=0.02)
    assert b.teminat_usd == pytest.approx(50.0, rel=0.02)


def test_adim_yuvarlamasi_notional_sapmasi():
    """Adım kaba ise notional 500'ün altına düşer; %10'dan fazla sapma reddedilir."""
    b = boyut_hesapla(enstruman(0.01, 0.001), 60000.0, Yon.LONG, KasaKurallari())
    assert b.gecerli and b.notional_usd == pytest.approx(480.0)
    kaba = boyut_hesapla(enstruman(0.01, 0.5), 60000.0, Yon.LONG, KasaKurallari())
    assert not kaba.gecerli


def test_boyut_kontrat_carpani_dogru():
    # OKX tarzı: 1 kontrat = 0.001 BTC -> 500/(60000*0.001) = 8.33 kontrat
    b = boyut_hesapla(enstruman(0.1, 1.0, 1.0, carpan=0.001), 60000.0, Yon.LONG, KasaKurallari())
    assert b.gecerli
    assert b.adet == pytest.approx(8.0)                 # aşağı yuvarlanır
    assert b.notional_usd == pytest.approx(480.0)


def test_kaba_adim_reddedilir():
    # 1 kontrat = 1 BTC ise 500$ notional imkânsız -> işlem yok
    b = boyut_hesapla(enstruman(0.1, 1.0, 1.0), 60000.0, Yon.LONG, KasaKurallari())
    assert not b.gecerli
    assert "notional" in b.neden or "adım" in b.neden


def test_stop_fiyati_long_short_simetri():
    k = KasaKurallari()
    e = enstruman()
    long_stop = stop_fiyati(e, 100.0, Yon.LONG, k)
    short_stop = stop_fiyati(e, 100.0, Yon.SHORT, k)
    assert long_stop < 100.0 < short_stop
    assert (100.0 - long_stop) / 100.0 == pytest.approx((short_stop - 100.0) / 100.0, rel=0.02)


def test_stop_net_zarari_10_dolar():
    """Stop dolduğunda net zarar -10 $ olmalı (komisyon dahil)."""
    k = KasaKurallari()
    e = enstruman(0.0001, 0.0001)
    giris, notional = 2.0, 500.0
    stop = stop_fiyati(e, giris, Yon.LONG, k, notional)
    brut = (stop / giris - 1.0) * notional
    net = brut - k.gidis_donus_komisyon_usd
    assert net == pytest.approx(-k.stop_net_usd, abs=0.6)   # kayma payı kadar tolerans


# ------------------------------------------------------------------ tasfiye
def test_tasfiye_mesafesi_monoton():
    k = KasaKurallari()
    onceki = 999.0
    for n in (1, 5, 10, 20, 40, 100):
        m = tasfiye_mesafesi_pct(1000.0, n, k)
        assert m < onceki
        onceki = m


def test_yirmi_pozisyonda_tasfiye_mesafesi_9_5():
    k = KasaKurallari()
    assert tasfiye_mesafesi_pct(1000.0, 20, k) == pytest.approx(0.095, abs=1e-6)


def test_kasa_kapasitesi_yirmi_pozisyon():
    k = KasaKurallari()
    assert k.max_es_zamanli_pozisyon(1000.0) == 20
    assert k.max_es_zamanli_pozisyon(49.0) == 0


def test_guvenli_max_pozisyon():
    assert guvenli_max_pozisyon(1000.0, KasaKurallari(), 0.10) == 19


def test_risk_profili_aciklama():
    p = RiskProfili()
    metin = p.aciklama()
    assert "cross" in metin and "-10$" in metin.replace(" ", "")


# ------------------------------------------------------------------ sinyal
def test_sinyal_esikleri():
    from bot.v8.signals import HacimPatlamasi
    d = HacimPatlamasi(MotorAyarlari())
    # eşik altı hacim
    assert d.bak("X", {"vol_mult": 1.0, "hacim_usd": 99999, "ret_pct": 2.0, "bias": 0.5}, 0.0) is None
    # yönlü akış uyumsuz
    assert d.bak("X", {"vol_mult": 8.0, "hacim_usd": 99999, "ret_pct": 2.0, "bias": -0.5}, 0.0) is None
    # geçerli sinyal
    s = d.bak("X", {"vol_mult": 8.0, "hacim_usd": 99999, "ret_pct": 2.0, "bias": 0.5}, 0.0)
    assert s is not None and s.yon is Yon.LONG and 0 < s.skor <= 1.0
