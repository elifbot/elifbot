# -*- coding: utf-8 -*-
"""ACARBOT v7 — "BEŞ" : TURBO + OMEGA'nın iyi taraflarını tek botta birleştirir.

VERİYE DAYANAK (4 seans, TURBO 31 + OMEGA 40 kapanan işlem):

  İKİ BOTUN DA KAYBETTİĞİ TARAF — aynı:
     TURBO  HACIM_PATLAMASI_LONG (3,0-3,6x) : 3 işlem × -20 $ = -60 $
     OMEGA  OMEGA_HACIM_PATLAMASI_LONG       : 13 işlem        = -4,74 $ (tüm -20 stoplar buradan)
     ortak imza: tepe kâr < 1 $ -> girer girmez ters dönüyor (kovalama)

  İKİ BOTUN DA KAZANDIĞI TARAF — aynı:
     TURBO  COKUS_PATLAMASI_SHORT : +0,55 · +0,76 · +5,04 · +6,48 · +6,69 · +15,02
            HACIM_COKUSU_SHORT    : +30,80 (6 işlem)
            HACIM_PATLAMASI_LONG  ama hacim >= 4,3x : +6,44 · +6,64 · +7,09 · +9,04 · +10,91 · +11,99 · +12,03
     OMEGA  COKUS_PATLAMASI_SHORT : +42,96 (19 işlem)
            HACIM_COKUSU_LONG/SHORT: +12,21 · +12,56 · +17,54
     ortak imza: tepe kâr >= 3 $ -> 26+34 işlem, +168 / +178 $

  YANİ: "çöküşe SHORT" iki botun para basan tarafı, "zayıf hacimle patlamaya LONG"
        iki botun para yakan tarafı.

ÜÇ'ÜN KURALLARI
  1. GİRİŞ — iki motorun anlaşması (2/2, 20 sn) VEYA güçlü tek sinyal istisnası:
       çöküş SHORT + hacim >= 4,0x + satıcı akışı <= -0,20  (kanıtlanmış arketip)
  2. KALİTE KAPISI — ortak kaybeden taraf elenir:
       LONG patlama < 4,5x  ->  RED (ZAYIF_LONG_PATLAMASI)
       ivme > %0,60 (8x + 0,35 akış + 25k $ istisnası)  ->  RED
       trende karşı yön                                  ->  RED
       kâr sonrası 90 sn aynı sembol                     ->  RED
       sembol başına 1 pozisyon · ters yön yok
  3. ÇIKIŞ — iki motorun kazandıran çıkışları birleşti:
       -10 $ net stop · BE 3,5 $ (1,3 kilit) · trail 6,0 $ (%22 giveback)
       sıkı taban (%82-88) · tükeniş TP (kâr>=4 $, hacim çöktü)
       parabolik kâr al (>=15 $) · trend dönüşü kâr al (zirve>=1,5 $)
       ZOMBİ ÇIKIŞI: 8 dk açık + net < +0,5 $  ->  kapat (4. turun ana bulgusu)
  4. MARJİN: kasanın %90'ı (işlem adedi sınırsız, sadece teminat sınırı)
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import acarbot_omega
import turbo_engine
from v3 import ortak

KASA = 1000.0
TEMINAT = 50.0
KALDIRAC = 10.0
NOTIONAL = TEMINAT * KALDIRAC
KOMISYON_ORANI = 0.0005
STOP_USD = 10.0
MAKS_MARJIN_PCT = 0.90

OY_PENCERE = 20.0
BE_TRIGGER, BE_LOCK = 3.5, 1.3
TRAIL_TRIGGER, GIVEBACK = 6.0, 0.22
PARABOLIK = 15.0
EXHAUSTION_MIN = 4.0
HUSRAN_SEC, HUSRAN_TEPE = 90.0, 1.00      # 90 sn içinde +1 $ göremeyen işlem ölü
ZOMBI_SEC, ZOMBI_ESIK = 1200.0, 0.50         # 20 dk (kazananların ortalama ömrü 5-6 dk)

# ---- 4 seans, 71 kapanan işlem (TURBO 31 + OMEGA 40) — indikatör karnesi --------------
# KAZANAN (TUT):  OMEGA_COKUS_PATLAMASI_SHORT +42,96 (19) · COKUS_PATLAMASI_SHORT +34,54 (7)
#                 HACIM_COKUSU_SHORT +30,80 (6) · OMEGA_HACIM_COKUSU_LONG +29,75 (4)
#                 OMEGA_HACIM_COKUSU_SHORT +12,56 (4) · HACIM_PATLAMASI_LONG +5,14 (12)
# KAYBEDEN (ÇIKAR): HACIM_COKUSU_LONG -2,15 (6) · OMEGA_HACIM_PATLAMASI_LONG -4,74 (13)
BEYAZ_LISTE = (
    "COKUS_PATLAMASI_SHORT", "HACIM_COKUSU_SHORT",
    "OMEGA_COKUS_PATLAMASI_SHORT", "OMEGA_HACIM_COKUSU_SHORT", "OMEGA_HACIM_COKUSU_LONG",
    "HACIM_PATLAMASI_LONG",
)
SIYAH_LISTE = ("HACIM_COKUSU_LONG", "OMEGA_HACIM_PATLAMASI_LONG")

# hacim kanıtı (iki bot birleşik):  LONG 2,5-3,5x = -45,72 $ · 3,5-4,5x = +31,55 $
#                                   LONG 4,5-6x  = +43,46 $ · SHORT her kovada artı
LONG_MIN_HACIM = 3.5   # kanıt: LONG 2,5-3,5x = -45,72 $ (4 işlem x -20 $ stop)
KOVALAMA_PENCERE = 30.0   # son 30 saniyede fiyat ne kadar hareket etmişse
KOVALAMA_TAVAN = 1.2      # bu yüzdeden fazlaysa giriş yok (tepe kovalama yasağı)
SHORT_MIN_HACIM = 2.0
ZAYIF_LONG_HACIM = LONG_MIN_HACIM               # geriye dönük uyumluluk
GUCLU_SHORT_HACIM = 4.0                       # güçlü tek sinyal istisnası
GUCLU_SHORT_AKIS = -0.20


def _metrik(motor, sembol: str) -> Dict[str, float]:
    """Dedektörün kendi tape'inden anlık kalite metrikleri (vol/ivme/akış/burst)."""
    for key, tape in (getattr(motor, "tapes", {}) or {}).items():
        try:
            sym = str(getattr(tape, "symbol", "") or key)
            if ortak.baz(sym) != ortak.baz(sembol):
                continue
            for ad in ("metrik", "metrics"):
                fn = getattr(tape, ad, None)
                if callable(fn):
                    try:
                        m = fn(12.0)
                    except TypeError:
                        m = fn()
                    if m:
                        return m
        except Exception:
            continue
    return {}


class UcPoz:
    __slots__ = ("id", "symbol", "base", "yon", "giris", "ts", "notional", "komisyon",
                 "zirve_net", "taban", "tetik", "oylar")

    def __init__(self, symbol: str, yon: int, px: float, ts: float, tetik: str, oylar: str):
        self.id = uuid.uuid4().hex[:8]
        self.symbol = symbol
        self.base = ortak.baz(symbol)
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


class BesBot:
    """"DÖRT" — 1 ve 2'nin KAZANAN indikatörleri, kaybedenleri dışarıda."""

    AD = "BOT5_BES"

    def __init__(self) -> None:
        self.turbo = turbo_engine.RealTimeVolumeShockEngine()
        self.omega = acarbot_omega.AcarbotOmegaEngine()
        self._besleme = {"TURBO": "ingest_batch", "OMEGA": "ingest_ticks"}
        self.dedektorler = {"TURBO": self.turbo, "OMEGA": self.omega}
        self._gorulen: Dict[str, set] = defaultdict(set)

        self.fiyat: Dict[str, float] = {}
        self.sembol: Dict[str, str] = {}
        self.oylar: Dict[Tuple[str, int], List[dict]] = defaultdict(list)

        self.pozisyonlar: Dict[str, UcPoz] = {}
        self.realize = 0.0
        self.kapanan: List[dict] = []
        self.kilit: Dict[str, float] = {}
        self.veto: Dict[str, int] = defaultdict(int)
        self.oy_sayaci: Dict[str, int] = defaultdict(int)
        self.tick = 0
        self.son_sifirlama = 0.0
        self.gecmis: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        self._hata_sayaci: Dict[str, int] = {}

    # ------------------------------------------------------------------ hesap
    def acik_pnl(self) -> float:
        return sum(p.net(self.fiyat.get(p.symbol, p.giris)) for p in self.pozisyonlar.values())

    def equity(self) -> float:
        return KASA + self.realize + self.acik_pnl()

    def kullanilan_teminat(self) -> float:
        return len(self.pozisyonlar) * TEMINAT

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
            self.sembol[ortak.baz(sym)] = sym
            g = self.gecmis[sym]
            g.append((float(t.get("ts") or time.time()), px))
            if len(g) > 400:
                del g[:-400]
        self.tick += len(ticks)
        simdi = float(ticks[-1].get("ts") or time.time()) if ticks else time.time()

        for ad, motor in self.dedektorler.items():
            try:
                getattr(motor, self._besleme[ad])(ticks)
            except Exception:
                import os, traceback
                if os.environ.get("UC_DIAG"):
                    print("DIAG besleme hata", ad, flush=True)
                    traceback.print_exc()
                self._hata_sayaci[ad] = self._hata_sayaci.get(ad, 0) + 1

        self._oy_topla(simdi)
        self._girisleri_dene(simdi)
        self._yonet(simdi)
        import os
        if os.environ.get("UC_DIAG") and self.tick // 2000 != getattr(self, "_diag_son", -1):
            self._diag_son = self.tick // 2000
            try:
                t, o = self.turbo, self.omega
                print("DIAG tick=%d oy=%s hata=%s Tpos=%d Opos=%d Teq=%.1f Oeq=%.1f Tkapa=%d Okapa=%d" % (
                    self.tick, dict(self.oy_sayaci), self._hata_sayaci,
                    len(getattr(t, "positions", {})), len(getattr(o, "positions", {})),
                    getattr(t, "live_equity_usd", lambda: -1)(), getattr(o, "live_equity_usd", lambda: -1)(),
                    len(getattr(t, "closed_trades", []) or []), len(getattr(o, "closed_trades", []) or [])), flush=True)
            except Exception as e:
                print("DIAG hata", e, flush=True)
        return 0

    # ------------------------------------------------------------------ oy
    def _oy_topla(self, simdi: float) -> None:
        for ad, motor in self.dedektorler.items():
            pozlar = getattr(motor, "positions", None) or getattr(motor, "pozisyonlar", {}) or {}
            for pid, p in list(pozlar.items()):
                if pid in self._gorulen[ad]:
                    continue
                self._gorulen[ad].add(pid)
                try:
                    sym = str(getattr(p, "symbol", "") or getattr(p, "key", ""))
                    yon = getattr(p, "side", None)
                    if yon is None:
                        yon = getattr(p, "yon", 0)
                    yon = 1 if float(yon) > 0 else -1
                    tetik = str(getattr(p, "tetik", "") or getattr(p, "trigger_type", "") or "")
                except (TypeError, ValueError):
                    continue
                m = _metrik(motor, sym)
                self.oylar[(ortak.baz(sym), yon)].append({
                    "ts": simdi, "ad": ad, "sembol": sym, "tetik": tetik,
                    "vol": float(m.get("vol_mult") or 0.0),
                    "akis": float(m.get("orderflow_bias") or 0.0),
                    "ivme": float(m.get("ret_burst_pct") or 0.0),
                    "burst": float(m.get("burst_usd") or 0.0),
                })
                self.oy_sayaci[ad] += 1
                # NOT: dedektörün pozisyonu KALIR. Eskiden burada defterden siliniyordu ve
                # motorun "sembol başına 1 pozisyon" kilidi (active_symbol_keys) hiç
                # açılmadığı için 30 sembolün tamamı ~15 dakikada kilitleniyor, oy akışı
                # TAMAMEN duruyordu (canlı testte oy_sayaci 45'te dondu). Artık dedektör
                # kendi çıkışını yapıyor, kilit açılıyor, oy akışı 3 saat sürüyor.

    def _girisleri_dene(self, simdi: float) -> None:
        """DÖRT'ün girişi: TEK motorun sinyali yeter — ama yalnız KAZANAN indikatörler.

        ÜÇ'ün yaptığı hatayı yapmaz: iki motorun anlaşmasını BEKLEMEZ (anlaşma, hareketin
        tepesinde gerçekleşiyordu -> girer girmez ters dönüş). Kanıt: 71 işlemde kazanan
        tarafın tamamı tek motor sinyalleriyle üretilmişti.
        """
        for anahtar in list(self.oylar.keys()):
            oylar = [o for o in self.oylar[anahtar] if simdi - o["ts"] <= OY_PENCERE]
            if not oylar:
                self.oylar.pop(anahtar, None)
                continue
            self.oylar[anahtar] = oylar
            b, yon = anahtar

            if any(p.base == b for p in self.pozisyonlar.values()):
                continue
            if self.kullanilan_teminat() + TEMINAT > self.equity() * MAKS_MARJIN_PCT:
                self.veto["MARJIN_SINIRI"] += 1
                continue
            if self.kilit.get(b, 0.0) > simdi:
                self.veto["KAR_SONRASI_KILIT"] += 1
                continue

            # en güçlü oy (hacim, sonra ivme)
            en = max(oylar, key=lambda o: (o["vol"], abs(o["ivme"])))
            vol, akis, ivme, burst = en["vol"], en["akis"], en["ivme"], en["burst"]
            tetik_adi = str(en["tetik"] or "")
            saf = tetik_adi.split("(")[0].strip()

            # 1) SİYAH LİSTE — 4 seansta para kaybettiren indikatörler
            if any(saf.startswith(x) or x in saf for x in SIYAH_LISTE):
                self.veto["KARA_LISTE"] += 1
                continue
            # 2) BEYAZ LİSTE — yalnız kanıtlanmış kazananlar
            if not any(saf.startswith(x) or x in saf for x in BEYAZ_LISTE):
                self.veto["BEYAZ_LISTE_DISI"] += 1
                continue
            # 3) HACİM KURALI — zayıf LONG yok, SHORT serbest
            if yon > 0 and vol < LONG_MIN_HACIM:
                self.veto["ZAYIF_LONG_PATLAMASI"] += 1
                continue
            if yon < 0 and vol < SHORT_MIN_HACIM:
                self.veto["COK_ZAYIF_SHORT"] += 1
                continue
            # 4) KOVALAMA FİLTRESİ — son 30 sn'de %1,2'den fazla hareket olduysa girme
            if KOVALAMA_TAVAN > 0:
                g = self.gecmis.get(self.sembol.get(b) or "", [])
                if g:
                    simdi_ts = g[-1][0]
                    eski = None
                    for ts_, px_ in reversed(g):
                        if simdi_ts - ts_ >= KOVALAMA_PENCERE:
                            eski = px_
                            break
                    if eski and eski > 0:
                        degisim = 100.0 * (g[-1][1] / eski - 1.0)
                        if abs(degisim) > KOVALAMA_TAVAN:
                            self.veto["KOVALAMA"] += 1
                            continue

            # 5) ivme tavanı (aşırı hızlı hareketi kovalama)
            ok, _s = ortak.ivme_izni(self.AD, ivme, vol, akis, burst)
            if not ok:
                continue

            sembol = self.sembol.get(b)
            px = self.fiyat.get(sembol or "", 0.0)
            if not sembol or px <= 0:
                continue
            tetik = "TEK_SINYAL · %s · %.1fx" % (saf[:40], vol)
            pos = UcPoz(sembol, yon, px, simdi, tetik, en["ad"])
            self.pozisyonlar[pos.id] = pos
            self.oylar.pop(anahtar, None)

    # ------------------------------------------------------------------ çıkış
    def _kapat(self, pos: UcPoz, px: float, sebep: str) -> None:
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
        self.kilit[pos.base] = time.time() + (90.0 if net > 0 else 45.0)

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

            if net <= -STOP_USD:
                self._kapat(pos, px, "ZARAR_KES_-10$")
                continue

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

            # parabolik kâr al (OMEGA'nın iyi tarafı)
            if pos.zirve_net >= PARABOLIK and net >= PARABOLIK * 0.85:
                self._kapat(pos, px, "PARABOLIK_KAR_AL")
                continue

            m = _metrik(self.turbo, pos.symbol) or {}
            vol = float(m.get("vol_mult") or 9.9)
            akis = float(m.get("orderflow_bias") or 0.0) * pos.yon

            # tükeniş kâr hasadı (TURBO'nun iyi tarafı)
            if net >= EXHAUSTION_MIN and vol < 1.0 and akis <= -0.10:
                self._kapat(pos, px, "TUKENIS_KAR_AL")
                continue

            # trend dönüşü kâr al
            uyumlu, _s = ortak.TREND.uyum(pos.symbol, pos.yon)
            if not uyumlu and pos.zirve_net >= 1.5:
                self._kapat(pos, px, "TREND_DONUSU_KAR_AL")
                continue

            # HÜSRAN ÇIKIŞI (v6.1 — 4 seans 71 işlem: tepe < 1 $ olan 6 işlemin TAMAMI -20 $ stop
            # oldu, içlerinde tek kazanan yok; 90 sn'de kapatmak -120 $ yerine ~-15 $ bırakıyordu)
            if (simdi - pos.ts) >= HUSRAN_SEC and pos.zirve_net < HUSRAN_TEPE and net < 0.5:
                self._kapat(pos, px, "HUSRAN_CIKIS")
                continue

            # ZOMBİ çıkışı (4. turun ana bulgusu)
            if (simdi - pos.ts) >= ZOMBI_SEC and net < ZOMBI_ESIK:
                self._kapat(pos, px, "ZOMBI_CIKIS")
                continue

            # 30 dk stagnation (uzun seans için üst sınır)
            if (simdi - pos.ts) >= 1800.0 and net >= 0.0:
                self._kapat(pos, px, "ZAMAN_SONUMLENME_KAR_AL")

    # ------------------------------------------------------------------ rapor
    def snapshot(self) -> Dict[str, Any]:
        kazan = [t for t in self.kapanan if t["net_pnl_usd"] > 0]
        kayip = [t for t in self.kapanan if t["net_pnl_usd"] <= 0]
        brut_kar = sum(t["net_pnl_usd"] for t in kazan)
        brut_zarar = abs(sum(t["net_pnl_usd"] for t in kayip))
        acik = [{"id": p.id, "symbol": p.symbol, "side": "LONG" if p.yon > 0 else "SHORT",
                 "net_pnl_usd": round(p.net(self.fiyat.get(p.symbol, p.giris)), 2),
                 "peak_pnl_usd": round(p.zirve_net, 2), "opened_ts": p.ts,
                 "trigger_type": p.tetik, "oylar": p.oylar}
                for p in self.pozisyonlar.values()]
        return {
            "account": {
                "live_equity_usd": round(self.equity(), 2),
                "realized_pnl_usd": round(self.realize, 2),
                "unrealized_pnl_usd": round(self.acik_pnl(), 2),
                "open_count": len(self.pozisyonlar),
                "closed_count": len(self.kapanan),
                "win_rate": round(len(kazan) / len(self.kapanan), 3) if self.kapanan else 0.0,
                "profit_factor": round(brut_kar / brut_zarar, 2) if brut_zarar > 0 else None,
                "used_margin_usd": round(self.kullanilan_teminat(), 2),
                "open_risk_usd": round(len(self.pozisyonlar) * STOP_USD, 2),
            },
            "universe": {"total_symbols": len(self.sembol), "total_ticks": self.tick},
            "filtre": {"veto_sayaci": dict(self.veto)},
            "open_positions": acik,
            "closed_trades": list(self.kapanan)[-60:],
            "ek": {"koruma_veto": dict(self.veto), "oy_sayaci": dict(self.oy_sayaci)},
        }


if __name__ == "__main__":
    b = BesBot()
    print("BES hazir:", b.AD, "| marjin tavani", MAKS_MARJIN_PCT, "| stop", STOP_USD)
