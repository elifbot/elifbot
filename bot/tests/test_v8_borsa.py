# -*- coding: utf-8 -*-
"""Borsa fiziği testleri: teminat reddi, stop emrinin borsada durması, CROSS tasfiye.

Bu testler eski 6-bot paketindeki iki yapısal hatayı kalıcı olarak kapatır:
  1) Bakiyede olmayan teminatla pozisyon açmak
  2) Stop'u Python'da tick kontrolüyle uygulamak (gap'te zarara dönüşen "kâr koruma")
"""
from __future__ import annotations

import pytest

from bot.v8.broker import SimuleBorsa
from bot.v8.config import KasaKurallari
from bot.v8.types import EmirIstegi, EmirTipi, Enstruman, Yon


def borsa(kasa=1000.0, sembol="AAA-USDT-SWAP", fiyat=100.0, hacim=5e9):
    k = KasaKurallari()
    b = SimuleBorsa(ad="test", kurallar=k, kasa_usd=kasa)
    b.enstrumanlar[sembol] = Enstruman("test", sembol, "AAA", 0.01, 0.01, 0.01, 5.0)
    b.son_fiyat[sembol] = fiyat
    b.hacim24[sembol] = hacim
    return b


def giris_emri(sembol="AAA-USDT-SWAP", adet=5.0, yon=Yon.LONG):
    return EmirIstegi("test", sembol, yon, EmirTipi.MARKET, adet, meta={"baz": "AAA"})


def test_market_giris_ve_teminat_kilitlenir():
    b = borsa()
    s = b.emir_gonder(giris_emri(), ts=1000.0)
    assert s.basarili
    assert b.kullanilan_teminat() > 0
    assert b.kullanilan_teminat() <= 50.5          # 5 adet * 100 = 500 notional / 10x


def test_teminat_yetmezse_emir_reddedilir():
    b = borsa(kasa=60.0)
    s = b.emir_gonder(giris_emri(adet=50.0), ts=1000.0)   # 5000 notional -> 500$ teminat
    assert not s.basarili
    assert "TEMINAT_YETERSIZ" in s.hata
    assert not b.pozisyonlar


def test_yirmi_pozisyon_da_kasa_dolar():
    """1.000 $ kasa, 50 $ teminat -> komisyon sonrası 19 pozisyon; fazlası reddedilir.

    Düz hesap 20 der; her girişin taker komisyonu (0.25 $) serbest teminatı
    aşındırdığı için gerçek sınır 19'dur. Borsa da tam olarak bunu yapar.
    """
    b = borsa(kasa=1000.0)
    for i in range(30):
        s = "S%d-USDT-SWAP" % i
        b.enstrumanlar[s] = Enstruman("test", s, "S%d" % i, 0.01, 0.01, 0.01, 5.0)
        b.son_fiyat[s] = 100.0
        b.hacim24[s] = 5e9
        b.emir_gonder(giris_emri(s, adet=5.0), ts=1000.0)
    assert len(b.pozisyonlar) == 19
    assert b.serbest_teminat() < 50.0


def test_stop_emri_borsada_durar_ve_tetiklenir():
    b = borsa()
    b.emir_gonder(giris_emri(), ts=1000.0)
    poz = b.pozisyonlar["AAA-USDT-SWAP"]
    assert poz.giris > 0
    s = b.emir_gonder(EmirIstegi("test", "AAA-USDT-SWAP", Yon.LONG, EmirTipi.STOP_MARKET,
                                 5.0, fiyat=98.0, reduce_only=True, meta={"baz": "AAA"}),
                      ts=1000.0)
    assert s.basarili and s.emir_id in b.duran
    # stop tetiklenmeden fiyat düşmez
    b.tick_islet("AAA-USDT-SWAP", 99.0)
    assert "AAA-USDT-SWAP" in b.pozisyonlar
    # tetiklenince kapanır (kayma dahil)
    b.tick_islet("AAA-USDT-SWAP", 97.9)
    assert "AAA-USDT-SWAP" not in b.pozisyonlar
    assert b.realize_usd < 0


def test_stop_gap_atlarsa_yine_kapanir():
    """v1..v7'de kâr koruması gap'te zarara dönüyordu; stop emri gap'i yakalar."""
    b = borsa()
    b.emir_gonder(giris_emri(), ts=1000.0)
    b.emir_gonder(EmirIstegi("test", "AAA-USDT-SWAP", Yon.LONG, EmirTipi.STOP_MARKET,
                             5.0, fiyat=102.0, reduce_only=True, meta={"baz": "AAA"}),
                  ts=1000.0)
    b.tick_islet("AAA-USDT-SWAP", 90.0)      # tek print'te %10 gap
    assert "AAA-USDT-SWAP" not in b.pozisyonlar


def test_reduce_only_pozisyonsuz_reddedilir():
    b = borsa()
    s = b.emir_gonder(EmirIstegi("test", "AAA-USDT-SWAP", Yon.LONG, EmirTipi.MARKET,
                                 1.0, reduce_only=True, meta={"baz": "AAA"}), ts=1000.0)
    assert not s.basarili and "AZALTACAK" in s.hata


def test_cross_tasfiye():
    """Özkaynak bakım marjının altına düşerse tüm pozisyonlar kapanır."""
    b = borsa(kasa=1000.0)
    # 19 pozisyon x 500 notional = 9.500 notional, bakım %0.5 = 47.5 $
    for i in range(25):
        s = "S%d-USDT-SWAP" % i
        b.enstrumanlar[s] = Enstruman("test", s, "S%d" % i, 0.01, 0.01, 0.01, 5.0)
        b.son_fiyat[s] = 100.0
        b.hacim24[s] = 5e9
        b.emir_gonder(giris_emri(s, adet=5.0), ts=1000.0)
    assert len(b.pozisyonlar) == 19
    # hepsi %9.6 düşsün -> tasfiye eşiği
    for s in list(b.pozisyonlar):
        b.son_fiyat[s] = 100.0 * 0.904
    b.tick_islet("S0-USDT-SWAP", 90.4)
    assert b.tasfiye_sayisi >= 1
    assert not b.pozisyonlar


def test_komisyon_kasaya_yansir():
    b = borsa(kasa=1000.0)
    b.emir_gonder(giris_emri(adet=5.0), ts=1000.0)
    assert b.komisyonlar_usd > 0
    assert b.kasa_usd < 1000.0
