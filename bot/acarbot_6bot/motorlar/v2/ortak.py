# -*- coding: utf-8 -*-
"""ACARBOT v2 — ortak koruma katmani.

30 dakikalik testte tespit edilen 3 yapisal hatayi kapatan servisler:

  HATA 1  Trendin tersine giris
          OMEGA BARD short (30 sn trend yukari) -> -20 $ ; HYBRID/APEX SOXL short -> -9,35 $
          COZUM   TrendMotor.uyum()  -> 30 ve 60 sn trendine karsi giris yasak

  HATA 2  Kar aldiktan sonra ayni sembole tepeden tekrar giris
          TURBO BARD +6,64 ile cikti, 24 sn sonra 0,1630'dan tekrar long -> -15,22 $
          COZUM   KarKilidi  ->  kar sonrasi 90 sn, zarar sonrasi 45 sn giris kilidi

  HATA 3  Bir bot long iken digerinin ayni sembolde short olmasi
          BARD: TURBO long / OMEGA short ayni anda
          COZUM   PozisyonDefteri -> v2 ailesi icinde ters yon kilidi (ayni yon serbest)

Ayrica kar yakalama oranini yukselten iki arac:
  siki_taban()        -> kademeli sikilasmis trailing tabani (tepe karin %82-88'ini kilitler)
  ters_zaman_asimi()  -> tepe kar gormeden 4 dk ters yonde surunen pozisyonu kapatir (SOXL dersi)
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

# ------------------------------------------------------------------ ayarlar
TREND_KARSI_ESIK = 0.25      # % - 30 ve 60 sn getirisi bu kadar ters ise giris yasak
KAR_KILIT_SEC = 90.0         # kar sonrasi ayni sembole yeniden giris kilidi
ZARAR_KILIT_SEC = 45.0       # zarar sonrasi kisa kilit
TERS_ASIMI_SEC = 240.0       # ters yonde 4 dk
TERS_ASIMI_ZARAR = -3.0      # ... ve -3 $'dan kotuyse
TERS_ASIMI_TEPE = 1.0        # hic +1 $ tepe gormediyse


# ------------------------------------------------------------------ trend
class TrendMotor:
    """Sembol bazli cok pencereli gercek fiyat trendi (botlardan bagimsiz olcumer)."""

    def __init__(self) -> None:
        self.seri: Dict[str, Deque[Tuple[float, float]]] = {}

    def besle(self, ticks) -> None:
        for t in ticks:
            try:
                sym = str(t.get("symbol") or "")
                px = float(t.get("price") or 0.0)
                ts = float(t.get("ts") or time.time())
            except (TypeError, ValueError):
                continue
            if not sym or px <= 0:
                continue
            d = self.seri.get(sym)
            if d is None:
                d = deque(maxlen=1200)
                self.seri[sym] = d
            d.append((ts, px))

    def _px_geri(self, key: str, pencere: float) -> Optional[float]:
        d = self.seri.get(key)
        if not d:
            return None
        simdi, son = d[-1]
        for ts, px in reversed(d):
            if simdi - ts >= pencere:
                return (son / px - 1.0) * 100.0 if px > 0 else None
        return None

    def getiriler(self, key: str) -> Tuple[Optional[float], Optional[float]]:
        return self._px_geri(key, 30.0), self._px_geri(key, 60.0)

    def skor(self, key: str) -> float:
        r30, r60 = self.getiriler(key)
        if r30 is None or r60 is None:
            return 0.0
        return round(0.6 * r30 + 0.4 * r60, 4)

    def uyum(self, key: str, side: int, esik: float = TREND_KARSI_ESIK) -> Tuple[bool, str]:
        r30, r60 = self.getiriler(key)
        if r30 is None or r60 is None:
            return True, "TREND_VERISI_YOK"
        if side < 0 and r30 > esik and r60 > esik:
            return False, "TREND_TERS_SHORT"
        if side > 0 and r30 < -esik and r60 < -esik:
            return False, "TREND_TERS_LONG"
        return True, "TREND_UYUMLU"


# ------------------------------------------------------------------ defter
def baz(sembol: str) -> str:
    s = str(sembol or "").upper()
    for e in ("-USDT-SWAP", "-USDT", "USDT", "-USD", "USD", "PERP"):
        if s.endswith(e):
            s = s[: -len(e)]
            break
    return s.split("-")[0] if "-" in s else s


class PozisyonDefteri:
    """v2 ailesinin canli pozisyon defteri: ayni sembolde ters yon yasak."""

    def __init__(self) -> None:
        self.kayit: Dict[str, Dict[str, int]] = defaultdict(dict)   # base -> {bot: side}

    def senkron(self, botlar) -> None:
        """botlar: [(ad, motor), ...] -> motor.positions uzerinden defteri tazele."""
        yeni: Dict[str, Dict[str, int]] = defaultdict(dict)
        for ad, motor in botlar:
            try:
                pozlar = getattr(motor, "positions", None) or getattr(motor, "pozisyonlar", {}) or {}
            except Exception:
                pozlar = {}
            for p in list(pozlar.values()):
                try:
                    sym = getattr(p, "symbol", "") or getattr(p, "key", "")
                    side = getattr(p, "side", None)
                    if side is None:
                        side = getattr(p, "yon", 0)
                    side = int(1 if float(side) > 0 else -1)
                except (TypeError, ValueError):
                    continue
                yeni[baz(sym)][ad] = side
        self.kayit = yeni

    def izin(self, bot: str, sembol: str, side: int) -> Tuple[bool, str]:
        b = baz(sembol)
        for sahip, yon in self.kayit.get(b, {}).items():
            if sahip != bot and yon != side:
                return False, "TERS_POZISYON_KILIDI"
        return True, ""


class KarKilidi:
    """Kar/zarar sonrasi ayni sembole yeniden giris kilidi."""

    def __init__(self) -> None:
        self.bitis: Dict[Tuple[str, str], float] = {}

    def isaretle(self, bot: str, sembol: str, net: float, simdi: Optional[float] = None) -> None:
        simdi = simdi or time.time()
        kilit = KAR_KILIT_SEC if net > 0 else ZARAR_KILIT_SEC
        self.bitis[(bot, baz(sembol))] = simdi + kilit

    def izin(self, bot: str, sembol: str, simdi: Optional[float] = None) -> Tuple[bool, str]:
        simdi = simdi or time.time()
        if self.bitis.get((bot, baz(sembol)), 0.0) > simdi:
            return False, "KAR_SONRASI_KILIT"
        return True, ""


# ------------------------------------------------------------------ global servisler
TREND = TrendMotor()
DEFTER = PozisyonDefteri()
KILIT = KarKilidi()
VETO: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))


def veto(bot: str, sebep: str) -> None:
    VETO[bot][sebep] += 1


def giris_izni(bot: str, sembol: str, side: int, simdi: float) -> Tuple[bool, str]:
    ok, sebep = TREND.uyum(sembol, side)
    if not ok:
        veto(bot, sebep)
        return False, sebep
    ok, sebep = DEFTER.izin(bot, sembol, side)
    if not ok:
        veto(bot, sebep)
        return False, sebep
    ok, sebep = KILIT.izin(bot, sembol, simdi)
    if not ok:
        veto(bot, sebep)
        return False, sebep
    return True, "OK"


def siki_taban(zirve: float) -> Optional[float]:
    """Kademeli sikilasitirilmis kar kilidi; 30 dk testinde yakalama orani %44-55'ti."""
    if zirve >= 25.0:
        return zirve * 0.88
    if zirve >= 12.0:
        return zirve * 0.85
    if zirve >= 7.0:
        return zirve * 0.82
    return None


def ters_zaman_asimi(opened_ts: float, zirve: float, net: float, simdi: float,
                     bekle: float = TERS_ASIMI_SEC) -> bool:
    return (simdi - float(opened_ts)) >= bekle and zirve < TERS_ASIMI_TEPE and net <= TERS_ASIMI_ZARAR
