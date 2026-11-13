# -*- coding: utf-8 -*-
"""types.py — v8'in ortak veri tipleri. Borsadan bağımsız (Binance/OKX aynı şemayı üretir)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Yon(Enum):
    LONG = 1
    SHORT = -1

    @property
    def etiket(self) -> str:
        return "LONG" if self is Yon.LONG else "SHORT"

    @property
    def karsi(self) -> "Yon":
        return Yon.SHORT if self is Yon.LONG else Yon.LONG


class EmirTipi(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"      # reduceOnly zarar kes
    TAKE_PROFIT_MARKET = "tp_market"


class EmirDurumu(Enum):
    YENI = "new"
    KISMI = "partially_filled"
    DOLDU = "filled"
    IPTAL = "canceled"
    RED = "rejected"
    GECERSIZ = "expired"


@dataclass(frozen=True)
class Enstruman:
    """Borsanın enstrüman tanımı — adım/fiyat yuvarlaması buradan gelir."""

    borsa: str
    sembol: str                  # borsanın kendi kodu: BTCUSDT / BTC-USDT-SWAP
    baz: str                     # normalize edilmiş varlık: BTC
    fiyat_adimi: float           # tickSize
    miktar_adimi: float          # stepSize / lotSz
    min_miktar: float
    min_notional_usd: float
    kontrat_carpani: float = 1.0  # OKX ctVal; Binance'te 1.0
    max_kaldirac: int = 125
    durum: str = "live"

    def fiyat_yuvarla(self, px: float) -> float:
        if self.fiyat_adimi <= 0:
            return px
        return round(round(px / self.fiyat_adimi) * self.fiyat_adimi, 12)

    def miktar_yuvarla(self, adet: float, asagi: bool = True) -> float:
        if self.miktar_adimi <= 0:
            return adet
        n = adet / self.miktar_adimi
        n = float(int(n)) if asagi else float(round(n))
        return round(n * self.miktar_adimi, 12)


@dataclass(frozen=True)
class Tick:
    borsa: str
    sembol: str
    baz: str
    fiyat: float
    delta_usd: float = 0.0       # bu dilimde işlem gören USD hacim
    alis_usd: float = 0.0        # alıcı yönlü hacim
    ts: float = field(default_factory=time.time)
    hacim24_usd: float = 0.0


@dataclass(frozen=True)
class Sinyal:
    baz: str
    yon: Yon
    skor: float                  # 0..1
    motor: str
    gerekce: str
    ts: float
    giris_tipi: str = "market"


@dataclass
class Pozisyon:
    kimlik: str                  # bizim ürettiğimiz id (idempotency)
    borsa: str
    sembol: str
    baz: str
    yon: Yon
    adet: float
    giris_fiyati: float
    notional_usd: float
    teminat_usd: float
    acilis_ts: float
    stop_fiyati: float
    stop_emir_id: str | None = None
    en_iyi_fiyat: float = 0.0
    en_iyi_pnl_usd: float = 0.0
    kapanis_ts: float | None = None
    cikis_fiyati: float | None = None
    net_pnl_usd: float = 0.0
    cikis_nedeni: str = ""
    komisyon_usd: float = 0.0

    def guncel_pnl(self, fiyat: float) -> float:
        yon = self.yon.value
        brut = yon * (fiyat / self.giris_fiyati - 1.0) * self.notional_usd
        return brut - self.komisyon_usd

    def to_dict(self) -> dict[str, Any]:
        return {
            "kimlik": self.kimlik, "borsa": self.borsa, "sembol": self.sembol,
            "yon": self.yon.etiket, "adet": self.adet, "giris": self.giris_fiyati,
            "notional_usd": self.notional_usd, "teminat_usd": self.teminat_usd,
            "stop": self.stop_fiyati, "stop_emir_id": self.stop_emir_id,
            "acilis_ts": self.acilis_ts, "en_iyi_pnl_usd": round(self.en_iyi_pnl_usd, 4),
            "net_pnl_usd": round(self.net_pnl_usd, 4), "cikis_nedeni": self.cikis_nedeni,
        }


@dataclass(frozen=True)
class KapananIslem:
    kimlik: str
    borsa: str
    sembol: str
    yon: str
    giris_fiyati: float
    cikis_fiyati: float
    net_pnl_usd: float
    en_iyi_pnl_usd: float
    acilis_ts: float
    kapanis_ts: float
    neden: str
    motor: str = ""

    @property
    def bekleme_sn(self) -> float:
        return round(max(0.0, self.kapanis_ts - self.acilis_ts), 1)


@dataclass(frozen=True)
class EmirIstegi:
    borsa: str
    sembol: str
    yon: Yon
    tip: EmirTipi
    adet: float
    fiyat: float | None = None
    reduce_only: bool = False
    post_only: bool = False
    istemci_id: str = ""         # newClientOrderId / clOrdId — idempotency
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmirSonucu:
    basarili: bool
    emir_id: str = ""
    durum: EmirDurumu = EmirDurumu.YENI
    dolen_adet: float = 0.0
    ort_fiyat: float = 0.0
    hata: str = ""
    ham: dict[str, Any] = field(default_factory=dict)


@dataclass
class KasaDurumu:
    kasa_usd: float
    realize_usd: float = 0.0
    acik_pnl_usd: float = 0.0
    kullanilan_teminat_usd: float = 0.0
    serbest_teminat_usd: float = 0.0
    acik_pozisyon: int = 0
    kapanan: int = 0
    kazanan: int = 0

    @property
    def toplam_usd(self) -> float:
        return round(self.kasa_usd + self.acik_pnl_usd, 4)

    @property
    def kaldirac(self) -> float:
        return round(10.0 * self.kullanilan_teminat_usd / max(1e-9, self.kasa_usd), 2)

    @property
    def win_rate(self) -> float:
        return round(self.kazanan / self.kapanan, 4) if self.kapanan else 0.0
