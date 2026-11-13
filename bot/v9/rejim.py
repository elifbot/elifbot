# -*- coding: utf-8 -*-
"""rejim.py — piyasa hâli ve sembol başına kayan metrikler.

Neden: aynı sinyal trendde kâr, sıkışmada zarar üretir. v1–v7 motorları bunu ayırmadığı
için aynı eşikler her piyasada çalıştırıldı.

**Kalibrasyon notu (v9.1):** oynaklık eşiği mutlak değil **göreli**. İlk sürümde eşik
0.0015 sabitti ve 0.5 sn'lik bucket'ta tek tick getirisi ~0.00002 olduğu için 78.516
tick'in tamamı "sıkışma" sınıfına düşmüştü. Artık eşik, sembolün kendi oynaklık
medyanına göre ölçülür: bucket boyu ne olursa olsun doğru sınıflar.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from bot.v8.types import Tick


class Rejim(str, Enum):
    TREND_YUKARI = "trend_yukari"
    TREND_ASAGI = "trend_asagi"
    SIKISMA = "sikisma"        # oynaklık kendi medyanının çok altında: kırılım beklenir
    DAGILMA = "dagilma"        # yön yok, oynaklık var: dönüş avı


# rejim -> hangi dedektörler konuşabilir
REJIM_KAPISI: dict[Rejim, set[str]] = {
    Rejim.TREND_YUKARI: {"hacim_kirilim", "vwap_donus"},
    Rejim.TREND_ASAGI: {"hacim_kirilim", "vwap_donus"},
    Rejim.SIKISMA: {"hacim_kirilim", "biyik_donus"},
    Rejim.DAGILMA: {"biyik_donus", "parabolik_tukenis"},
}


@dataclass
class Hafiza:
    """Bir sembolün kayan hafızası. Tüm metrikler O(1) (medyan hariç, o O(k log k))."""

    baz: str
    pencere: int = 240
    ema_hizli: float = 0.0
    ema_yavas: float = 0.0
    oynaklik: float = 0.0          # |getiri| üzerine EMA = ATR vekili
    fiyat: float = 0.0
    n: int = 0
    _vw: deque = field(default_factory=lambda: deque(maxlen=240), repr=False)
    _kuyruk: deque = field(default_factory=lambda: deque(maxlen=240), repr=False)
    _oyn: deque = field(default_factory=lambda: deque(maxlen=600), repr=False)
    _vw_num: float = 0.0
    _vw_den: float = 0.0
    _alim: float = 0.0
    _hacim: float = 0.0

    # ------------------------------------------------------------------ besle
    def ekle(self, t: Tick) -> None:
        if t.fiyat <= 0:
            return
        if self.n == 0:
            self.ema_hizli = self.ema_yavas = t.fiyat
        else:
            a_h, a_y = 2 / 13, 2 / 49
            getiri = abs(t.fiyat / self.fiyat - 1.0)
            self.oynaklik += (getiri - self.oynaklik) * a_h
            self._oyn.append(getiri)
            self.ema_hizli += (t.fiyat - self.ema_hizli) * a_h
            self.ema_yavas += (t.fiyat - self.ema_yavas) * a_y
        self.fiyat = t.fiyat
        self.n += 1

        hacim = max(0.0, t.delta_usd)
        if len(self._vw) == self._vw.maxlen:
            eski_p, eski_v = self._vw.popleft()
            self._vw_num -= eski_p * eski_v
            self._vw_den -= eski_v
        self._vw.append((t.fiyat, hacim))
        self._vw_num += t.fiyat * hacim
        self._vw_den += hacim

        if len(self._kuyruk) == self._kuyruk.maxlen:
            eski = self._kuyruk.popleft()
            self._alim -= eski[1]
            self._hacim -= eski[2]
        alis = min(hacim, max(0.0, t.alis_usd))
        self._kuyruk.append((t.fiyat, alis, hacim))
        self._alim += alis
        self._hacim += hacim

    # ------------------------------------------------------------- metrikler
    @property
    def hazir(self) -> bool:
        return self.n >= 60

    @property
    def oynaklik_medyan(self) -> float:
        """Son penceredeki tek-tick getirilerin medyanı — rejim eşiğinin ölçeği."""
        if len(self._oyn) < 30:
            return self.oynaklik
        s = sorted(self._oyn)
        return s[len(s) // 2]

    @property
    def vwap(self) -> float:
        return self._vw_num / self._vw_den if self._vw_den > 0 else self.fiyat

    @property
    def delta_orani(self) -> float:
        return self._alim / self._hacim if self._hacim > 0 else 0.5

    @property
    def hacim_orani(self) -> float:
        if not self._kuyruk:
            return 1.0
        hs = sorted(h for _, _, h in self._kuyruk if h > 0)
        if not hs:
            return 1.0
        med = hs[len(hs) // 2]
        return (self._kuyruk[-1][2] / med) if med > 0 else 1.0

    def kirilim(self, disarida: int = 5) -> tuple[float, float]:
        fs = [p for p, _, _ in self._kuyruk]
        if len(fs) <= disarida:
            return self.fiyat, self.fiyat
        govde = fs[:-disarida]
        return max(govde), min(govde)

    @property
    def trend_gucu(self) -> float:
        """EMA ayrışmasının oynaklığa oranı. 1.0 üstü = belirgin trend."""
        if self.oynaklik <= 0 or self.ema_yavas <= 0:
            return 0.0
        return abs(self.ema_hizli / self.ema_yavas - 1.0) / self.oynaklik


@dataclass(frozen=True)
class RejimSonucu:
    rejim: Rejim
    guc: float
    oynaklik: float
    esik: float = 0.0


def rejim_sinifla(h: Hafiza, sikisma_kat: float = 0.70,
                  trend_esigi: float = 1.0) -> RejimSonucu:
    """Göreli eşikli sınıflandırma.

    sikisma_kat: oynaklık, kendi medyanının bu katının altındaysa sıkışma.
                 Mutlak değil göreli olduğu için bucket boyundan bağımsız çalışır.
    trend_esigi: EMA ayrışması oynaklığın bu katına ulaşırsa trend.
    """
    med = h.oynaklik_medyan
    esik = med * sikisma_kat
    guc = h.trend_gucu
    if not h.hazir:
        return RejimSonucu(Rejim.SIKISMA, guc, h.oynaklik, esik)
    if med > 0 and h.oynaklik < esik:
        return RejimSonucu(Rejim.SIKISMA, guc, h.oynaklik, esik)
    if guc >= trend_esigi:
        yon = Rejim.TREND_YUKARI if h.ema_hizli >= h.ema_yavas else Rejim.TREND_ASAGI
        return RejimSonucu(yon, guc, h.oynaklik, esik)
    return RejimSonucu(Rejim.DAGILMA, guc, h.oynaklik, esik)
