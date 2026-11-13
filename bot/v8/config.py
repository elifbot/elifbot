# -*- coding: utf-8 -*-
"""config.py — ACARBOT v8 · kullanıcı kural seti ve türetilmiş risk sayıları.

KULLANICI KURALI (değiştirilemez, `KasaKurallari.dogrula()` ihlali reddeder)
----------------------------------------------------------------------------
  * Başlangıç kasası ........ 1.000 $
  * Pozisyon başına teminat .. 50 $
  * Kaldıraç ................. 10x  -> pozisyon başına 500 $ notional
  * Marjin modu .............. CROSS (izole DEĞİL)
  * İşlem / pozisyon limiti .. YOK (portföy stopu yok)
  * Zarar kes ................ pozisyon başına net -10 $

TÜRETİLMİŞ SAYILAR (pazarlık konusu değil, aritmetik)
-----------------------------------------------------
  komisyon (taker gidiş-dönüş) = 500 $ * (0.05% + 0.05%) = 0.50 $
  -10 $ net stop için fiyat mesafesi = (10 - 0.50) / 500 = 1.90%
  kaldıraç = 10 * 50 * açık_pozisyon / kasa

`RiskProfili` içindeki sayılar bu kurallardan türetilir; elle yazılmaz.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------- sabitler
BORSLAR = ("binance", "okx")
MARJIN_MODU = "cross"


@dataclass(frozen=True)
class KasaKurallari:
    """Kullanıcının verdiği kasa kuralı. Tek doğruluk kaynağı."""

    baslangic_kasa_usd: float = 1000.0
    teminat_per_pozisyon_usd: float = 50.0
    kaldirac: int = 10
    marjin_modu: str = MARJIN_MODU          # "cross" — izole değil
    max_pozisyon: int = 0                   # 0 = SINIRSIZ (kullanıcı kuralı)
    stop_net_usd: float = 10.0              # net, komisyon dahil
    taker_fee_orani: float = 0.0005         # Binance futures taker %0.05
    maker_fee_orani: float = 0.0002         # Binance futures maker %0.02

    # --- türetilmiş -----------------------------------------------------
    @property
    def notional_per_pozisyon_usd(self) -> float:
        return self.teminat_per_pozisyon_usd * self.kaldirac

    @property
    def gidis_donus_komisyon_usd(self) -> float:
        return self.notional_per_pozisyon_usd * 2.0 * self.taker_fee_orani

    @property
    def stop_fiyat_mesafesi(self) -> float:
        """Net -10 $ için fiyatın kaç oran ters gitmesi gerekir (komisyon dahil)."""
        butce = self.stop_net_usd - self.gidis_donus_komisyon_usd
        if butce <= 0:
            raise ValueError("stop_net_usd komisyondan büyük olmalı")
        return butce / self.notional_per_pozisyon_usd

    @property
    def basabas_fiyat_mesafesi(self) -> float:
        """Sadece komisyonu karşılayan hareket (0 $ net)."""
        return self.gidis_donus_komisyon_usd / self.notional_per_pozisyon_usd

    def max_es_zamanli_pozisyon(self, kasa_usd: float) -> int:
        """Kasa bu kadar 50 $ teminatı kaldırır. Borsanın kendi sınırı budur.

        0 = sınırsız kuralı *emir sayısını* sınırlamaz; ama hiçbir borsa
        bakiyede olmayan teminatla pozisyon açtırmaz. v8 bu fiziksel sınırı
        uygular, hayalî teminat üretmez.
        """
        if kasa_usd <= 0:
            return 0
        return max(0, int(kasa_usd // self.teminat_per_pozisyon_usd))

    def tasima_orani(self, kasa_usd: float) -> float:
        """Kasa kaç katı notional taşıyor (10x kaldıraç, n pozisyon)."""
        if kasa_usd <= 0:
            return float("inf")
        return self.notional_per_pozisyon_usd / kasa_usd

    def dogrula(self) -> None:
        if self.baslangic_kasa_usd <= 0:
            raise ValueError("başlangıç kasası pozitif olmalı")
        if self.teminat_per_pozisyon_usd <= 0:
            raise ValueError("teminat pozitif olmalı")
        if self.kaldirac < 1:
            raise ValueError("kaldıraç >= 1 olmalı")
        if self.marjin_modu != "cross":
            raise ValueError("kullanıcı kuralı gereği marjin modu 'cross' olmalı (izole değil)")
        if self.stop_net_usd <= self.gidis_donus_komisyon_usd:
            raise ValueError("net stop komisyondan küçük olamaz")
        if self.max_pozisyon != 0:
            raise ValueError("kullanıcı kuralı: pozisyon limiti YOK (max_pozisyon=0)")


@dataclass(frozen=True)
class MotorAyarlari:
    """Sinyal + uygulama ayarları. Kenar (edge) buradan gelir, kural değil."""

    # --- sinyal eşikleri
    patlama_pencere_sn: float = 12.0
    hacim_carpan_esigi: float = 3.0
    min_patlama_usd: float = 12_000.0
    min_hiz_pct: float = 0.30
    min_akim_biyasi: float = 0.18
    hacim_cokus_orani: float = 0.32

    # --- kovalama yasağı (v7'nin düzeltilmiş hâli: yalnızca aşırı harekette)
    kovalama_pencere_sn: float = 30.0
    kovalama_esik_pct: float = 1.20

    # --- pozisyon ömrü
    zombi_sn: float = 20 * 60.0        # 20 dk hareketsiz pozisyon kapanır
    sembol_soguma_sn: float = 20.0

    # --- uygulama
    giris_tipi: str = "maker_sonra_taker"   # post-only dene, N ms sonra taker
    maker_bekleme_ms: int = 1500
    max_kayma_bps: float = 25.0             # 0.25% üstü kaymada emir iptal
    emir_gecerlilik_sn: float = 3.0
    min_24s_hacim_usd: float = 1_000_000.0  # likidite tabanı (gerçek: 25k çok düşük)
    min_notional_usd: float = 5.0
    max_sinyal_yasi_sn: float = 2.0

    # --- operasyonel durdurucular (ticaret kuralı DEĞİL, güvenlik)
    veri_bayat_sn: float = 10.0
    saat_kaymasi_sn: float = 2.0
    red_orani_durdur: float = 0.25          # emirlerin %25'i reddedilirse dur
    red_penceresi: int = 50


@dataclass(frozen=True)
class Guvenlik:
    """Canlı para kilidi. Varsayılan: KAPALI."""

    canli_izni_env: str = "ACARBOT_CANLI_ONAY"
    canli_izni_degeri: str = "EVET-RISKI-ANLIYORUM"

    def canli_acik_mi(self) -> bool:
        return os.getenv(self.canli_izni_env) == self.canli_izni_degeri


@dataclass
class RiskProfili:
    kurallar: KasaKurallari = field(default_factory=KasaKurallari)
    motor: MotorAyarlari = field(default_factory=MotorAyarlari)
    guvenlik: Guvenlik = field(default_factory=Guvenlik)

    def __post_init__(self) -> None:
        self.kurallar.dogrula()

    def aciklama(self) -> str:
        k = self.kurallar
        return (
            f"kasa={k.baslangic_kasa_usd:.0f}$ teminat={k.teminat_per_pozisyon_usd:.0f}$ "
            f"x{k.kaldirac} notional={k.notional_per_pozisyon_usd:.0f}$ marjin={k.marjin_modu} "
            f"stop=-{k.stop_net_usd:.0f}$ (%.2f%%) komisyon={k.gidis_donus_komisyon_usd:.2f}$"
            % (100.0 * k.stop_fiyat_mesafesi)
        )
