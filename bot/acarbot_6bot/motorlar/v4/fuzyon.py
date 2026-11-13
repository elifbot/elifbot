# -*- coding: utf-8 -*-
"""ACARBOT v4 — FÜZYON: 4 motorun sinyalini TEK botta toplar.

Fikir (12 bot turunun dersi): 12 botu yan yana kosturmak yerine, 4 dedektorun
(TURBO · OMEGA · HYBRID · APEX) ayni sembol + ayni yon icin verdigi oylari tek
defterde birlestir. Boylece "ayni hatayi 6 bot ayni saniyede yapar" durumu biter,
tek pozisyon acilir.

Uc varyant (yalniz oy esigi farkli):
  FUZYON-A  >=2/4 dedektor ayni fikirde   (dengeli)
  FUZYON-B  >=3/4 dedektor ayni fikirde   (secici)
  FUZYON-C  >=2/4 ve en az biri TURBO veya HYBRID (hizli tetikleyici sart)

Kurallar (kullanici ayari):
  kasa 1.000 $ · pozisyon 50 $ teminat x 10x = 500 $ · zarar stopu -10 $ net
  acik pozisyon sayisi SINIRSIZ (marjin bitene kadar, ~20 pozisyon)
  sembol basina tek pozisyon · ayni sembolde ters yon yok · trende karsi giris yok

Cikis yonetimi: -10 $ stop · 3 $ BE (1 $ kilit) · 5 $ trail (%22 giveback) ·
siki taban (7/12/25 $ zirvelerde %82-88) · trend donusu kâr al · 10 dk stagnation.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from v3 import ortak

KASA = 1000.0
TEMINAT = 50.0
KALDIRAC = 10.0
NOTIONAL = TEMINAT * KALDIRAC          # 500 $
KOMISYON_ORANI = 0.0005
STOP_USD = 10.0

OY_PENCERE = 20.0                      # oy gecerlilik penceresi (sn)
BE_TRIGGER, BE_LOCK = 3.0, 1.0
TRAIL_TRIGGER, GIVEBACK = 5.0, 0.22
STAGNATION_SEC, STAGNATION_MIN = 600.0, 1.50


def baz(sembol: str) -> str:
    return ortak.baz(sembol)


class FuzyonPoz:
    __slots__ = ("id", "symbol", "base", "yon", "giris", "ts", "notional",
                 "komisyon", "zirve_net", "taban", "tetik", "oylar")

    def __init__(self, symbol: str, yon: int, px: float, ts: float, tetik: str, oylar: str):
        self.id = uuid.uuid4().hex[:8]
        self.symbol = symbol
        self.base = baz(symbol)
        self.yon = yon
        self.giris = px
        self.ts = ts
        self.notional = NOTIONAL
        self.komisyon = NOTIONAL * KOMISYON_ORANI * 2.0
        self.zirve_net = 0.0
        self.taban = -1e9
        self.tetik = tetik
        self.oylar = oylar

    def net(self, px: float) -> float:
        if px <= 0 or self.giris <= 0:
            return 0.0
        return self.yon * (px / self.giris - 1.0) * self.notional - self.komisyon


class FuzyonMotor:
    """4 dedektorun oylarini tek defterde birlestiren bot."""

    AD = "FUZYON"
    ESIK = 2
    ZORUNLU: Optional[Tuple[str, ...]] = None      # ("TURBO","HYBRID")

    def __init__(self, ad: str, esik: int, zorunlu: Optional[Tuple[str, ...]] = None) -> None:
        self.AD = ad
        self.ESIK = int(esik)
        self.ZORUNLU = zorunlu

        self.dedektorler: Dict[str, Any] = {}
        self._besleme: Dict[str, str] = {}
        self._gorulen: Dict[str, set] = defaultdict(set)

        self.fiyat: Dict[str, float] = {}
        self.sembol: Dict[str, str] = {}
        self.oylar: Dict[Tuple[str, int], List[Tuple[float, str]]] = defaultdict(list)

        self.pozisyonlar: Dict[str, FuzyonPoz] = {}
        self.realize = 0.0
        self.kapanan: List[dict] = []
        self.veto: Dict[str, int] = defaultdict(int)
        self.oy_sayaci: Dict[str, int] = defaultdict(int)
        self.tick = 0

    # ------------------------------------------------------------------ kurulum
    def dedektor_ekle(self, ad: str, motor: Any, metod: str = "ingest_batch") -> None:
        self.dedektorler[ad] = motor
        self._besleme[ad] = metod

    # ------------------------------------------------------------------ hesap
    def acik_pnl(self) -> float:
        t = 0.0
        for p in self.pozisyonlar.values():
            px = self.fiyat.get(p.symbol, p.giris)
            t += p.net(px)
        return t

    def equity(self) -> float:
        return KASA + self.realize + self.acik_pnl()

    # ------------------------------------------------------------------ besleme
    def ingest_batch(self, ticks) -> int:
        for t in ticks:
            try:
                sym = str(t.get("symbol") or "")
                px = float(t.get("price") or 0.0)
            except (TypeError, ValueError):
                continue
            if not sym or px <= 0:
                continue
            self.fiyat[sym] = px
            self.sembol[baz(sym)] = sym
        self.tick += len(ticks)

        # 1) dedektorleri besle
        for ad, motor in self.dedektorler.items():
            try:
                getattr(motor, self._besleme[ad])(ticks)
            except Exception:
                pass

        # 2) yeni acilan dedektor pozisyonlari = OY
        simdi = ticks[-1].get("ts") if ticks else time.time()
        for ad, motor in self.dedektorler.items():
            pozlar = getattr(motor, "positions", None) or getattr(motor, "pozisyonlar", {}) or {}
            for pid, p in list(pozlar.items()):
                if pid in self._gorulen[ad]:
                    continue
                self._gorulen[ad].add(pid)
                try:
                    sym = str(getattr(p, "symbol", "") or getattr(p, "key", ""))
                    yon = int(getattr(p, "side", None) if getattr(p, "side", None) is not None
                              else getattr(p, "yon", 0))
                    yon = 1 if yon > 0 else -1
                except (TypeError, ValueError):
                    continue
                self.oylar[(baz(sym), yon)].append((float(simdi), ad))
                self.oy_sayaci[ad] += 1

        # 3) oylari degerlendir ve gerekiyorsa gir
        self._girisleri_dene(float(simdi))

        # 4) acik pozisyonlari yonet
        self._yonet(float(simdi))
        return 0

    # ------------------------------------------------------------------ giris
    def _girisleri_dene(self, simdi: float) -> None:
        for anahtar in list(self.oylar.keys()):
            oylar = [(ts, ad) for ts, ad in self.oylar[anahtar] if simdi - ts <= OY_PENCERE]
            if oylar:
                self.oylar[anahtar] = oylar
            else:
                self.oylar.pop(anahtar, None)
                continue

            b, yon = anahtar
            verenler = {ad for _ts, ad in oylar}
            if len(verenler) < self.ESIK:
                continue
            if self.ZORUNLU and not (verenler & set(self.ZORUNLU)):
                self.veto["ZORUNLU_DEDEKTOR_YOK"] += 1
                continue

            # sembol basina tek pozisyon + ters yon yasagi
            if any(p.base == b for p in self.pozisyonlar.values()):
                continue
            sym = self.sembol.get(b)
            px = self.fiyat.get(sym or "", 0.0) if sym else 0.0
            if not sym or px <= 0:
                continue
            # trende karsi giris yok
            uyumlu, _s = ortak.TREND.uyum(sym, yon)
            if not uyumlu:
                self.veto["TREND_TERS_GIRIS"] += 1
                continue

            oy_metni = "+".join(sorted(verenler))
            pos = FuzyonPoz(sym, yon, px, simdi, f"FUZYON_{len(verenler)}OY", oy_metni)
            self.pozisyonlar[pos.id] = pos
            self.oylar.pop(anahtar, None)

    # ------------------------------------------------------------------ yonetim
    def _kapat(self, pos: FuzyonPoz, px: float, sebep: str) -> None:
        net = pos.net(px)
        self.realize += net
        self.kapanan.append({
            "id": pos.id, "symbol": pos.symbol, "side": "LONG" if pos.yon > 0 else "SHORT",
            "entry_price": round(pos.giris, 10), "exit_price": round(px, 10),
            "trigger_type": pos.tetik, "exit_reason": sebep,
            "net_pnl_usd": round(net, 2), "peak_pnl_usd": round(pos.zirve_net, 2),
            "opened_ts": pos.ts, "closed_ts": time.time(), "oylar": pos.oylar,
        })
        self.pozisyonlar.pop(pos.id, None)

    def _yonet(self, simdi: float) -> None:
        for pid in list(self.pozisyonlar.keys()):
            pos = self.pozisyonlar.get(pid)
            if pos is None:
                continue
            px = self.fiyat.get(pos.symbol, 0.0)
            if px <= 0:
                continue
            net = pos.net(px)
            if net > pos.zirve_net:
                pos.zirve_net = net

            # stop
            if net <= -STOP_USD:
                self._kapat(pos, px, "ZARAR_KES_-10$")
                continue

            # kademeli taban: BE + trail + siki taban
            if pos.zirve_net >= TRAIL_TRIGGER:
                esik = pos.zirve_net * (1.0 - GIVEBACK)
                if esik > pos.taban:
                    pos.taban = esik
            elif pos.zirve_net >= BE_TRIGGER:
                if BE_LOCK > pos.taban:
                    pos.taban = BE_LOCK
            siki = ortak.siki_taban(pos.zirve_net)
            if siki is not None and siki > pos.taban:
                pos.taban = siki
            if pos.taban > -1e8 and net <= pos.taban:
                self._kapat(pos, px, "TRAILING_KAR_AL" if pos.taban >= 2.0 else "BE_KAR_KORUMA")
                continue

            # trend donusu -> kâr al
            uyumlu, _s = ortak.TREND.uyum(pos.symbol, pos.yon)
            if not uyumlu and pos.zirve_net >= 1.5:
                self._kapat(pos, px, "TREND_DONUSU_KAR_AL")
                continue

            # stagnation
            if (simdi - pos.ts) >= STAGNATION_SEC and net >= STAGNATION_MIN:
                self._kapat(pos, px, "ZAMAN_SONUMLENME_KAR_AL")

    # ------------------------------------------------------------------ rapor
    def snapshot(self) -> Dict[str, Any]:
        kazan = [t for t in self.kapanan if t["net_pnl_usd"] > 0]
        kayip = [t for t in self.kapanan if t["net_pnl_usd"] <= 0]
        brut_kar = sum(t["net_pnl_usd"] for t in kazan)
        brut_zarar = abs(sum(t["net_pnl_usd"] for t in kayip))
        acik = []
        for p in self.pozisyonlar.values():
            px = self.fiyat.get(p.symbol, p.giris)
            acik.append({"id": p.id, "symbol": p.symbol,
                         "side": "LONG" if p.yon > 0 else "SHORT",
                         "net_pnl_usd": round(p.net(px), 2),
                         "peak_pnl_usd": round(p.zirve_net, 2),
                         "opened_ts": p.ts, "oylar": p.oylar})
        return {
            "account": {
                "live_equity_usd": round(self.equity(), 2),
                "realized_pnl_usd": round(self.realize, 2),
                "unrealized_pnl_usd": round(self.acik_pnl(), 2),
                "open_count": len(self.pozisyonlar),
                "closed_count": len(self.kapanan),
                "win_rate": round(len(kazan) / len(self.kapanan), 3) if self.kapanan else 0.0,
                "profit_factor": round(brut_kar / brut_zarar, 2) if brut_zarar > 0 else None,
                "used_margin_usd": round(len(self.pozisyonlar) * TEMINAT, 2),
                "open_risk_usd": round(len(self.pozisyonlar) * STOP_USD, 2),
            },
            "universe": {"total_symbols": len(self.sembol), "total_ticks": self.tick},
            "filtre": {"veto_sayaci": dict(self.veto)},
            "open_positions": acik,
            "closed_trades": list(self.kapanan)[-40:],
            "ek": {"koruma_veto": dict(self.veto), "oy_esigi": self.ESIK,
                   "zorunlu": list(self.ZORUNLU or []), "oy_sayaci": dict(self.oy_sayaci)},
        }


# ---------------------------------------------------------------------- uc varyant
def fuzyon_a():
    from v4.dedektorler import dedektorleri_kur
    m = FuzyonMotor("BOT5_FUZYON_A", 2)
    dedektorleri_kur(m)
    return m


def fuzyon_b():
    from v4.dedektorler import dedektorleri_kur
    m = FuzyonMotor("BOT6_FUZYON_B", 3)
    dedektorleri_kur(m)
    return m


def fuzyon_c():
    from v4.dedektorler import dedektorleri_kur
    m = FuzyonMotor("BOT7_FUZYON_C", 2, ("TURBO", "HYBRID"))
    dedektorleri_kur(m)
    return m


if __name__ == "__main__":
    m = fuzyon_a()
    print("Fuzyon hazir:", m.AD, "esik", m.ESIK, "dedektorler", list(m.dedektorler))
