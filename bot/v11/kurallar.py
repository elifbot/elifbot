"""Kullanıcı kuralları — değiştirilemez. bot/v8/config.py ile birebir aynı değerler.

  Kasa 1000 $ · teminat 50 $ · kaldıraç 10x (500 $ notional) · CROSS · pozisyon limiti yok
  Net zarar kes −10 $ (komisyon dahil) · taker %0.05 (gidiş-dönüş 0.50 $)
"""
from __future__ import annotations

from dataclasses import dataclass

KASA_USD = 1000.0
TEMINAT_USD = 50.0
KALDIRAC = 10
NOTIONAL_USD = TEMINAT_USD * KALDIRAC          # 500 $
MARJIN_MODU = "cross"
STOP_NET_USD = 10.0
TAKER_ORAN = 0.0005                              # %0.05 · tek taraf
GIDIS_DONUS_KOMISYON_USD = NOTIONAL_USD * 2 * TAKER_ORAN   # 0.50 $
# Net −10 $ için fiyat mesafesi (komisyon dahil): (10 − 0.50) / 500 = %1.90
STOP_FIYAT_ORANI = (STOP_NET_USD - GIDIS_DONUS_KOMISYON_USD) / NOTIONAL_USD


@dataclass(frozen=True)
class Kurallar:
    kasa: float = KASA_USD
    teminat: float = TEMINAT_USD
    kaldirac: int = KALDIRAC
    marjin: str = MARJIN_MODU
    stop_net_usd: float = STOP_NET_USD
    taker: float = TAKER_ORAN

    def dogrula(self) -> None:
        """Kullanıcı kuralından sapma varsa hata verir."""
        if (self.kasa, self.teminat, self.kaldirac, self.marjin, self.stop_net_usd, self.taker) != (
            KASA_USD, TEMINAT_USD, KALDIRAC, MARJIN_MODU, STOP_NET_USD, TAKER_ORAN):
            raise ValueError("Kullanıcı kuralı ihlali: kasa/teminat/kaldıraç/marjin/stop değiştirilemez")
