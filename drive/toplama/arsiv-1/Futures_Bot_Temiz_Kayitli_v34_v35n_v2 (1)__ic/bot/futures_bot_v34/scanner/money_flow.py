"""Gerçek agresif alış/satış (taker) para-akışı ölçümü.

Bu modül yalnızca borsanın gerçekleşen işlem verisini kullanır. OBV/MFI gibi
mum-proxy'lerini CVD diye etiketlemez. İlk canlı kaynak OKX `trades` kanalıdır;
SWAP miktarı kontrat olduğundan USD ve base dönüşümü ctVal*ctMult ile yapılır.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import math

MAX_AKIS_MS = 300_000
AKIS_PENCERELERI = (5, 15, 30, 60)


@dataclass(frozen=True)
class AkisAnlik:
    hazir: bool = False
    pencere_sn: int = 0
    alis_usd: float = 0.0
    satis_usd: float = 0.0
    toplam_usd: float = 0.0
    cvd_usd: float = 0.0
    alis_orani: float | None = None
    vwap: float | None = None
    islem_adedi: int = 0
    son_islem_yas_ms: int | None = None


class YuvarlananAkis:
    """Bir sembolün gerçek işlemlerinden kayan USD CVD ve VWAP üretir."""

    def __init__(self, max_ms: int = MAX_AKIS_MS):
        self.max_ms = int(max_ms)
        # ts, alış-base, satış-base, alış-quote, satış-quote
        self.olaylar = deque()
        self.son_ts = 0

    def ekle(self, ts: int, fiyat: float, base_miktar: float, yon: str) -> None:
        ts, fiyat, base_miktar = int(ts), float(fiyat), float(base_miktar)
        if ts <= 0 or not math.isfinite(fiyat) or not math.isfinite(base_miktar) \
                or fiyat <= 0 or base_miktar <= 0 or yon not in ("buy", "sell"):
            return
        usd = fiyat * base_miktar
        if not math.isfinite(usd) or usd <= 0:
            return
        alis_b, satis_b = (base_miktar, 0.0) if yon == "buy" else (0.0, base_miktar)
        alis_u, satis_u = (usd, 0.0) if yon == "buy" else (0.0, usd)
        self.olaylar.append((ts, alis_b, satis_b, alis_u, satis_u))
        self.son_ts = max(self.son_ts, ts)
        self._budala(ts)

    def _budala(self, simdi: int) -> None:
        esik = int(simdi) - self.max_ms
        while self.olaylar and self.olaylar[0][0] < esik:
            self.olaylar.popleft()

    def anlik(self, simdi: int, pencere_sn: int) -> AkisAnlik:
        simdi, pencere_sn = int(simdi), int(pencere_sn)
        self._budala(simdi)
        esik = simdi - pencere_sn * 1000
        ab = sb = au = su = 0.0
        adet = 0
        for ts, a_b, s_b, a_u, s_u in reversed(self.olaylar):
            if ts < esik:
                break
            ab += a_b; sb += s_b; au += a_u; su += s_u; adet += 1
        toplam = au + su
        return AkisAnlik(
            hazir=toplam > 0,
            pencere_sn=pencere_sn,
            alis_usd=au,
            satis_usd=su,
            toplam_usd=toplam,
            cvd_usd=au - su,
            alis_orani=au / toplam if toplam > 0 else None,
            vwap=(au + su) / (ab + sb) if ab + sb > 0 else None,
            islem_adedi=adet,
            son_islem_yas_ms=max(0, simdi - self.son_ts) if self.son_ts else None,
        )


class AkisDefteri:
    def __init__(self):
        self._kayitlar: dict[tuple[str, str], YuvarlananAkis] = {}
        self.trade_sayisi = 0
        self.hata_sayisi = 0

    def ekle(self, exchange: str, sembol: str, fiyat: float, base: float,
             yon: str, ts: int) -> None:
        """Base miktarı bilinen gerçek bir taker işlemini ekle."""
        try:
            fiyat, base, ts = float(fiyat), float(base), int(ts)
            if (not math.isfinite(fiyat) or not math.isfinite(base)
                    or fiyat <= 0 or base <= 0 or ts <= 0 or yon not in ("buy", "sell")):
                raise ValueError("geçersiz akış işlemi")
            anahtar = (exchange, sembol)
            if anahtar not in self._kayitlar:
                self._kayitlar[anahtar] = YuvarlananAkis()
            self._kayitlar[anahtar].ekle(ts, fiyat, base, yon)
            self.trade_sayisi += 1
        except (TypeError, ValueError, OverflowError):
            self.hata_sayisi += 1

    def okx_ekle(self, sembol: str, fiyat: float, kontrat: float, yon: str,
                 ts: int, kontrat_carpani: float) -> None:
        try:
            carpan = float(kontrat_carpani)
            if not math.isfinite(carpan) or carpan <= 0:
                raise ValueError("geçersiz OKX kontrat çarpanı")
            base = float(kontrat) * carpan
        except (TypeError, ValueError, OverflowError):
            self.hata_sayisi += 1
            return
        self.ekle("okx", sembol, fiyat, base, yon, ts)

    def binance_ekle(self, sembol: str, fiyat: float, base: float,
                     yon: str, ts: int) -> None:
        self.ekle("binance", sembol, fiyat, base, yon, ts)

    def anlik(self, exchange: str, sembol: str, simdi: int,
              pencere_sn: int) -> AkisAnlik:
        kayit = self._kayitlar.get((exchange, sembol))
        return kayit.anlik(simdi, pencere_sn) if kayit else AkisAnlik(pencere_sn=pencere_sn)

    def alanlar(self, exchange: str, sembol: str, simdi: int,
                on_ek: str = "") -> dict:
        sonuc = {}
        for pencere in AKIS_PENCERELERI:
            a = self.anlik(exchange, sembol, simdi, pencere)
            tag = f"{on_ek}{pencere}s"
            sonuc[f"{tag}_cvd_usd"] = round(a.cvd_usd, 8) if a.hazir else ""
            sonuc[f"{tag}_alis_orani"] = round(a.alis_orani, 8) if a.alis_orani is not None else ""
            sonuc[f"{tag}_toplam_usd"] = round(a.toplam_usd, 8) if a.hazir else ""
            sonuc[f"{tag}_vwap"] = round(a.vwap, 10) if a.vwap is not None else ""
            sonuc[f"{tag}_islem_adedi"] = a.islem_adedi
        son_60 = self.anlik(exchange, sembol, simdi, 60)
        sonuc[f"{on_ek}hazir"] = int(son_60.hazir)
        sonuc[f"{on_ek}son_islem_yas_ms"] = son_60.son_islem_yas_ms if son_60.son_islem_yas_ms is not None else ""
        return sonuc


def akis_csv_alanlari(on_ek: str = "") -> list[str]:
    alanlar = []
    for pencere in AKIS_PENCERELERI:
        tag = f"{on_ek}{pencere}s"
        alanlar.extend((f"{tag}_cvd_usd", f"{tag}_alis_orani",
                        f"{tag}_toplam_usd", f"{tag}_vwap", f"{tag}_islem_adedi"))
    return alanlar + [f"{on_ek}hazir", f"{on_ek}son_islem_yas_ms"]
