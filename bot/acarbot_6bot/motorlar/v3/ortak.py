# -*- coding: utf-8 -*-
"""ACARBOT v3 — ortak koruma katmani (8 botluk testin bulgularina gore).

v2'den devralinanlar (ispatlanmis, korunuyor):
  TrendMotor.uyum()   -> 30/60 sn trendine karsi giris yasak
  PozisyonDefteri     -> v3 ailesinde ayni sembolde ters yon yasak
  KarKilidi           -> kar sonrasi 90 sn / zarar sonrasi 45 sn yeniden giris kilidi
  siki_taban()        -> tepe karin %82-88'ini kilitleyen kademeli trailing

v3'te DUZELTILENLER (8 bot testinde v2'nin kaybettigi noktalar):
  FIX 1  ters zaman asimi artik YALNIZ trend gercekten dondugunde kapatir.
         v2'de BARD short 4. dakikada -8,95 $ ile kesildi, v1 ayni pozisyonu +6,43 $ ile
         kapatti -> kural pullback'i kesiyordu. Yeni kural:
            trend hala bizim yonde  -> TUT (pullback) ; sadece 12 dk + -9 $ asilirsa kes
            trend ters dondu        -> kes
  FIX 2  ivme tavani kosullu: taban %0,60 (kazanan v1 degeri); %0,60 ustune YALNIZ
         hacim >= 8x + akis >= 0,35 + burst >= 25.000 $ ise izin var.
         v2'de tavan dogrudan %1,60 yapilinca BARD LONG +%1,54 -> -20,03 $ olmustu.
  FIX 3  min hacim kati HYBRID/APEX icin 3,8x -> 4,5x (marjinal 4,2-4,3x girisler elenir)
  FIX 4  stagnation hasadi kazanan v1 degerine cekildi: 300 sn -> 900 sn (churn bitti)
  FIX 5  GOLGE DEFTERI: kilit/trend nedeniyle reddedilen her sinyal 120 sn sanal olarak
         izlenir, kacirilan kâr $ olarak raporlanir (kilidin firsat maliyeti olcumu)
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, Tuple

# ------------------------------------------------------------------ ayarlar
TREND_KARSI_ESIK = 0.25       # % - 30 ve 60 sn getirisi bu kadar ters ise giris yasak
KAR_KILIT_SEC = 90.0          # kar sonrasi ayni sembole yeniden giris kilidi
ZARAR_KILIT_SEC = 45.0        # zarar sonrasi kisa kilit

# FIX 1 — zaman asimi artik trend sartina bagli
TERS_ASIMI_SEC = 240.0        # 4 dk surunme
TERS_ASIMI_ZARAR = -3.0       # ... ve -3 $'dan kotuyse
TERS_ASIMI_TEPE = 1.0         # ... ve +1 $ tepe gormediyse
PULLBACK_SABIR_SEC = 720.0    # trend hala bizim yonde ise 12 dk sabret
PULLBACK_SABIR_ZARAR = -9.0   # ... ama bu kadar zarar asilirsa yine kes

# FIX 2 — kosullu ivme tavani
IVME_TABAN = 0.60             # % - kazanan v1 degeri (HYBRID/APEX v1 bu degerle +%100 WR)
IVME_ISTISNA_HACIM = 8.0      # istisna icin hacim kati
IVME_ISTISNA_AKIS = 0.35      # istisna icin alici/satici akis dengesi
IVME_ISTISNA_BURST = 25_000.0 # istisna icin minimum burst $

# gölge defteri
GOLGE_UFAK_SEC = 120.0        # reddedilen sinyal 120 sn izlenir
GOLGE_TEKRAR_SEC = 30.0       # ayni bot/sembol icin 30 sn'de bir kayit
GOLGE_MAKS = 3000             # bellek tavani
SANAL_NOTIONAL = 500.0        # 50 $ teminat x 10x


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
        """True = giris/pozisyon trendle uyumlu."""
        r30, r60 = self.getiriler(key)
        if r30 is None or r60 is None:
            return True, "TREND_VERISI_YOK"
        if side < 0 and r30 > esik and r60 > esik:
            return False, "TREND_TERS_SHORT"
        if side > 0 and r30 < -esik and r60 < -esik:
            return False, "TREND_TERS_LONG"
        return True, "TREND_UYUMLU"


# ------------------------------------------------------------------ sembol
def baz(sembol: str) -> str:
    s = str(sembol or "").upper()
    for e in ("-USDT-SWAP", "-USDT", "USDT", "-USD", "USD", "PERP"):
        if s.endswith(e):
            s = s[: -len(e)]
            break
    return s.split("-")[0] if "-" in s else s


# ------------------------------------------------------------------ defter
class PozisyonDefteri:
    """v3 ailesinin canli pozisyon defteri: ayni sembolde ters yon yasak."""

    def __init__(self) -> None:
        self.kayit: Dict[str, Dict[str, int]] = defaultdict(dict)

    def senkron(self, botlar) -> None:
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


# ------------------------------------------------------------------ FIX 5: golge defteri
class GolgeDefteri:
    """Kilit/trend nedeniyle REDDEDILEN sinyalleri sanal olarak izler.

    Kilit dogru calisiyor olabilir ama firsat maliyeti olculmuyordu (v2'de
    HYBRID/APEX 90 kez kilitlendi). Her reddedilen sinyal 120 sn boyunca
    izlenir; kacirilan kâr/zarar $ olarak raporlanir.
    """

    def __init__(self) -> None:
        self.acik: Dict[str, List[dict]] = defaultdict(list)   # baz sembol -> kayitlar
        self.kapali: List[dict] = []
        self._son: Dict[Tuple[str, str], float] = {}
        self.toplam = 0

    def kaydet(self, bot: str, sembol: str, side: int, px: Optional[float],
               ts: float, sebep: str, ufuk: float = GOLGE_UFAK_SEC) -> None:
        try:
            px = float(px or 0.0)
        except (TypeError, ValueError):
            return
        if px <= 0:
            return
        b = baz(sembol)
        anahtar = (bot, b)
        if ts - self._son.get(anahtar, 0.0) < GOLGE_TEKRAR_SEC:
            return
        if len(self.kapali) >= GOLGE_MAKS:
            return
        self._son[anahtar] = ts
        self.toplam += 1
        self.acik[b].append({"bot": bot, "sembol": b, "side": int(side), "px0": px,
                            "ts": float(ts), "sebep": sebep, "ufuk": float(ufuk)})

    def fiyat(self, sembol: str, px: float, ts: float) -> None:
        b = baz(sembol)
        kayitlar = self.acik.get(b)
        if not kayitlar:
            return
        try:
            px = float(px)
        except (TypeError, ValueError):
            return
        kalan = []
        for s in kayitlar:
            if ts - s["ts"] >= s["ufuk"] and px > 0:
                pct = (px / s["px0"] - 1.0) * 100.0
                sanal = SANAL_NOTIONAL * (pct / 100.0) * s["side"]
                self.kapali.append({**s, "px1": px, "pct": round(pct, 4),
                                    "sanal_pnl": round(sanal, 2)})
            else:
                kalan.append(s)
        if kalan:
            self.acik[b] = kalan
        else:
            self.acik.pop(b, None)

    def ozet(self) -> dict:
        if not self.kapali:
            return {"kayit": self.toplam, "olculen": 0, "sanal_pnl": 0.0,
                    "kacirilan_kar": 0.0, "kacinilan_zarar": 0.0, "sebep": {}}
        toplam = sum(s["sanal_pnl"] for s in self.kapali)
        kar = sum(s["sanal_pnl"] for s in self.kapali if s["sanal_pnl"] > 0)
        zarar = sum(s["sanal_pnl"] for s in self.kapali if s["sanal_pnl"] < 0)
        sebep: Dict[str, Dict[str, float]] = defaultdict(lambda: {"adet": 0, "pnl": 0.0})
        for s in self.kapali:
            d = sebep[s["sebep"]]
            d["adet"] += 1
            d["pnl"] = round(d["pnl"] + s["sanal_pnl"], 2)
        for s in self.kapali:
            sebep[s["sebep"]]["pnl"] = round(sebep[s["sebep"]]["pnl"], 2)
        return {"kayit": self.toplam, "olculen": len(self.kapali),
                "sanal_pnl": round(toplam, 2),
                "kacirilan_kar": round(kar, 2),
                "kacinilan_zarar": round(zarar, 2),
                "sebep": {k: dict(v) for k, v in sebep.items()},
                "ornek": sorted(self.kapali, key=lambda s: s["sanal_pnl"])[:8]}


# ------------------------------------------------------------------ global servisler
TREND = TrendMotor()
DEFTER = PozisyonDefteri()
KILIT = KarKilidi()
GOLGE = GolgeDefteri()
VETO: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))


def veto(bot: str, sebep: str) -> None:
    VETO[bot][sebep] += 1


def giris_izni(bot: str, sembol: str, side: int, simdi: float,
               px: Optional[float] = None) -> Tuple[bool, str]:
    """Uc kapi: trend uyumu -> ters pozisyon kilidi -> kar sonrasi kilit.

    Reddedilirse ve fiyat verilmisse golge defterine yazilir (firsat maliyeti olcumu).
    """
    ok, sebep = TREND.uyum(sembol, side)
    if not ok:
        veto(bot, sebep)
        GOLGE.kaydet(bot, sembol, side, px, simdi, sebep)
        return False, sebep
    ok, sebep = DEFTER.izin(bot, sembol, side)
    if not ok:
        veto(bot, sebep)
        GOLGE.kaydet(bot, sembol, side, px, simdi, sebep)
        return False, sebep
    ok, sebep = KILIT.izin(bot, sembol, simdi)
    if not ok:
        veto(bot, sebep)
        GOLGE.kaydet(bot, sembol, side, px, simdi, sebep)
        return False, sebep
    return True, "OK"


def ivme_izni(bot: str, ivme_pct: float, vol_mult: float, akis: float,
              burst_usd: float) -> Tuple[bool, str]:
    """FIX 2 — kazanan v1 tabanini koru, istisnayi sadece cok guclu sinyale ac."""
    try:
        hiz = abs(float(ivme_pct))
    except (TypeError, ValueError):
        return True, "OK"
    if hiz <= IVME_TABAN:
        return True, "OK"
    try:
        if (float(vol_mult) >= IVME_ISTISNA_HACIM
                and float(akis) >= IVME_ISTISNA_AKIS
                and float(burst_usd) >= IVME_ISTISNA_BURST):
            return True, "IVME_ISTISNA"
    except (TypeError, ValueError):
        pass
    veto(bot, "IVME_TAVANI_KOSULLU")
    return False, "IVME_TAVANI_KOSULLU"


def siki_taban(zirve: float) -> Optional[float]:
    """Kademeli sikilasitirilmis kar kilidi."""
    if zirve >= 25.0:
        return zirve * 0.88
    if zirve >= 12.0:
        return zirve * 0.85
    if zirve >= 7.0:
        return zirve * 0.82
    return None


def ters_yon_asimi(sembol: str, side: int, opened_ts: float, zirve: float,
                   net: float, simdi: float) -> Tuple[bool, str]:
    """FIX 1 — v2'nin "4 dk + eksi" kurali pullback'i de kesiyordu.

    Yeni kural:
      trend ters donmus            -> kes  (gercek trend donusu)
      trend hala bizim yonde ise   -> TUT, sadece 12 dk + -9 $ asilirsa kes
      trend notr                   -> TUT, sadece 12 dk + -9 $ asilirsa kes
    """
    sure = simdi - float(opened_ts or 0.0)
    if sure < TERS_ASIMI_SEC or zirve >= TERS_ASIMI_TEPE or net > TERS_ASIMI_ZARAR:
        return False, ""
    uyumlu, _sebep = TREND.uyum(sembol, side)
    if not uyumlu:
        return True, "V3_TERS_YON_ZAMAN_ASIMI"
    if sure >= PULLBACK_SABIR_SEC and net <= PULLBACK_SABIR_ZARAR:
        return True, "V3_UZUN_SURUNME"
    return False, "V3_PULLBACK_TUT"
