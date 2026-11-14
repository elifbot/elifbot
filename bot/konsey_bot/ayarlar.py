from dataclasses import dataclass

@dataclass
class Ayarlar:
    kasa_usd: float = 1000.0
    teminat_usd: float = 50.0
    kaldiraç: float = 10.0
    stop_net_usd: float = -10.0
    komisyon_oran: float = 0.0005
    evren_sayisi: int = 6

    @property
    def notional_usd(self) -> float:
        return self.teminat_usd * self.kaldiraç

    @property
    def stop_yuzde(self) -> float:
        return (self.stop_net_usd / self.notional_usd) * 100
