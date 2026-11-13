# -*- coding: utf-8 -*-
"""ACARBOT CEKIRDEK v2 - BOT 4 (APEX) ve BOT 3 (HYBRID v2) icin ortak motor.

Bagimsiz calisir: sadece Python standart kutuphanesi kullanir.
Kasa 1.000 $ - teminat 50 $ x 10x CAPRAZ - pozisyon basina kesin -20 $ net stop.

Tick formati (JSON nesnesi):
    {"exchange":"binance","symbol":"BTCUSDT","price":65000.0,
     "ts":1794563956.0,"delta_usd":1200.0,"buy_usd":900.0}

  price     : islem fiyati (zorunlu)
  delta_usd : o tickteki islem hacmi, $ (zorunlu, > 0)
  buy_usd   : bu hacmin alici-agresif kismi, $ (yoksa 0 -> akis filtresi reddeder)
  kline_q / kline_ts : alternatif hacim kaynagi (24s hacim farki)
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

KASA = 1000.0
TEMINAT = 50.0
KALDIRAC = 10
KOMISYON_ORANI = 0.0005
STOP_USD = 10.0


def baz_varlik(sembol: str) -> str:
    """BTC-USDT-SWAP / BTCUSDT / BTC_USDT -> BTC (ayni varliga kilitlenme onlenir)."""
    s = str(sembol or "").upper()
    for ayirac in ("-", "/", "_"):
        if ayirac in s:
            return s.split(ayirac)[0]
    for ek in ("USDT", "USDC", "BUSD", "USD", "PERP"):
        if s.endswith(ek) and len(s) > len(ek):
            return s[: -len(ek)]
    return s


# ------------------------------------------------------------------ FILTRE
@dataclass
class FiltreKurallari:
    """Ajan konseyinin K1-K4 kararlarindan turetilmis giris kapilari."""

    min_vol_mult: float = 5.0        # 2-5x kovasi -28,14 $ -> yasak
    min_ivme_pct: float = 0.18       # K3 tabani
    max_ivme_pct: float = 0.60       # K2: %0,60+ kovalama -32,74 $ -> yasak
    min_akis: float = 0.15
    min_burst_usd: float = 8000.0
    max_chop: float = 64.0
    baz_dedupe_sec: float = 15.0     # AKE ailesi -65,57 $ dersi
    sembol_cooldown_sec: float = 25.0


class Filtre:
    def __init__(self, kurallar: Optional[FiltreKurallari] = None) -> None:
        self.k = kurallar or FiltreKurallari()
        self._sembol: Dict[str, float] = {}
        self._baz: Dict[str, float] = {}
        self.veto: Dict[str, int] = defaultdict(int)

    def kontrol(self, sembol: str, yon: int, vol: float, ivme: float, akis: float,
                burst: float, chop: float, simdi: float) -> Tuple[bool, str]:
        k = self.k
        iv = abs(ivme)
        if vol < k.min_vol_mult:
            self.veto["VOL_ZAYIF"] += 1
            return False, "VOL_ZAYIF"
        if burst and burst < k.min_burst_usd:
            self.veto["HACIM_YETERSIZ"] += 1
            return False, "HACIM_YETERSIZ"
        if iv < k.min_ivme_pct:
            self.veto["IVME_ZAYIF"] += 1
            return False, "IVME_ZAYIF"
        if k.max_ivme_pct and iv > k.max_ivme_pct:
            self.veto["IVME_KOVALAMA"] += 1
            return False, "IVME_KOVALAMA"
        if akis * yon < k.min_akis:
            self.veto["AKIS_TERS"] += 1
            return False, "AKIS_TERS"
        if chop > k.max_chop:
            self.veto["TESTERE"] += 1
            return False, "TESTERE"
        if simdi - self._baz.get(baz_varlik(sembol), -1e18) < k.baz_dedupe_sec:
            self.veto["BAZ_DEDUPE"] += 1
            return False, "BAZ_DEDUPE"
        if simdi - self._sembol.get(sembol, -1e18) < k.sembol_cooldown_sec:
            self.veto["SEMBOL_COOLDOWN"] += 1
            return False, "SEMBOL_COOLDOWN"
        return True, "KABUL"

    def kaydet(self, sembol: str, simdi: float) -> None:
        self._sembol[sembol] = simdi
        self._baz[baz_varlik(sembol)] = simdi

    def snapshot(self) -> Dict[str, Any]:
        return {"kurallar": asdict(self.k), "veto_sayaci": dict(self.veto)}


# ------------------------------------------------------------------ MIKRO-TAPE
@dataclass
class Ornek:
    ts: float
    px: float
    delta: float
    buy: float


class Tape:
    """Tek sembolun son 90 saniyelik islem akisi."""

    __slots__ = ("exchange", "symbol", "samples", "son_kline_ts", "son_kline_q")

    def __init__(self, exchange: str, symbol: str) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.samples: Deque[Ornek] = deque(maxlen=2000)
        self.son_kline_ts = 0.0
        self.son_kline_q = 0.0

    def ekle(self, ts: float, px: float, delta: float, buy: float) -> None:
        self.samples.append(Ornek(ts, px, delta, buy))
        while self.samples and ts - self.samples[0].ts > 90.0:
            self.samples.popleft()

    def metrik(self, pencere: float = 12.0) -> Dict[str, float]:
        if len(self.samples) < 4:
            return {}
        simdi = self.samples[-1].ts
        son = [s for s in self.samples if simdi - s.ts <= pencere]
        if len(son) < 3:
            return {}
        eski = [s for s in self.samples if pencere < simdi - s.ts <= 60.0]
        son_hacim = sum(s.delta for s in son)
        son_hiz = son_hacim / max(1.0, pencere)
        if len(eski) >= 2:
            sure = max(1.0, eski[-1].ts - eski[0].ts)
            eski_hiz = sum(s.delta for s in eski) / sure
        else:
            eski_hiz = 0.0
        vol_mult = son_hiz / eski_hiz if eski_hiz > 1e-9 else 0.0
        fiyatlar = [s.px for s in son]
        ilk = fiyatlar[0]
        son_px = fiyatlar[-1]
        ret_burst = (son_px / ilk - 1.0) * 100.0 if ilk > 0 else 0.0
        otuz = [s for s in self.samples if simdi - s.ts <= 30.0]
        ret_30 = (son_px / otuz[0].px - 1.0) * 100.0 if len(otuz) > 1 and otuz[0].px > 0 else ret_burst
        top_buy = sum(s.buy for s in son)
        akis = (2.0 * top_buy / son_hacim - 1.0) if son_hacim > 1e-9 else 0.0
        lo = min(fiyatlar)
        hi = max(fiyatlar)
        rpos = (son_px - lo) / (hi - lo) if hi > lo else 0.5
        donus = 0
        for i in range(1, len(fiyatlar) - 1):
            if (fiyatlar[i] - fiyatlar[i - 1]) * (fiyatlar[i + 1] - fiyatlar[i]) < 0:
                donus += 1
        chop = min(100.0, 200.0 * donus / max(1, len(fiyatlar) - 2))
        return {
            "vol_mult": vol_mult,
            "burst_usd": son_hacim,
            "ret_burst_pct": ret_burst,
            "ret_30s_pct": ret_30,
            "orderflow_bias": max(-1.0, min(1.0, akis)),
            "range_pos": rpos,
            "choppiness": chop,
            "px": son_px,
            "ts": simdi,
        }


# ------------------------------------------------------------------ POZISYON
@dataclass
class Pozisyon:
    id: str
    key: str
    exchange: str
    symbol: str
    yon: int
    giris: float
    ts: float
    notional: float
    komisyon: float
    zirve_net: float = 0.0
    taban: float = -1e9
    track: str = "FAST_TRACK"
    tetik: str = ""

    def net(self, px: float) -> float:
        if px <= 0 or self.giris <= 0:
            return 0.0
        return self.yon * (px / self.giris - 1.0) * self.notional - self.komisyon


# ------------------------------------------------------------------ MOTOR
class Motor:
    AD = "MOTOR"

    def __init__(self) -> None:
        self.baslangic = KASA
        self.teminat = TEMINAT
        self.kaldirac = KALDIRAC
        self.komisyon_orani = KOMISYON_ORANI
        self.stop = STOP_USD
        self.margin_cap = 0.98

        self.filtre = Filtre()
        self.be_trigger = 4.5
        self.be_lock = 1.2
        self.trail_trigger = 7.5
        self.giveback = (0.30, 0.20, 0.16)
        self.exhaustion_min = 4.8
        self.stagnation_sec = 0.0
        self.stagnation_min = 2.2

        self.tapes: Dict[str, Tape] = {}
        self.pozisyonlar: Dict[str, Pozisyon] = {}
        self.kapanan: Deque[Dict[str, Any]] = deque(maxlen=1000)
        self.realize = 0.0
        self.zirve_equity = KASA
        self.veto: Dict[str, int] = defaultdict(int)
        self.gov: Dict[str, Any] = {
            "margin_blocks": 0,
            "dd_pct": 0.0,
            "survival": False,
            "free_margin": KASA,
            "edge": 0.0,
        }
        self.tick = 0
        self.acilan = 0
        self.ilk_ts = 0.0
        self.son_ts = 0.0

    # ----------------------------- temel
    @property
    def notional(self) -> float:
        return self.teminat * self.kaldirac

    @property
    def komisyon(self) -> float:
        return self.notional * self.komisyon_orani * 2.0

    def _fiyat(self, key: str) -> float:
        tape = self.tapes.get(key)
        return tape.samples[-1].px if tape is not None and tape.samples else 0.0

    def equity(self) -> float:
        acik = 0.0
        for p in self.pozisyonlar.values():
            acik += p.net(self._fiyat(p.key))
        return self.baslangic + self.realize + acik

    def kullanilan_teminat(self) -> float:
        return len(self.pozisyonlar) * self.teminat

    def serbest_teminat(self) -> float:
        return self.equity() - self.kullanilan_teminat()

    def acik_risk(self) -> float:
        return len(self.pozisyonlar) * self.stop

    # ----------------------------- tick isleme
    def _tick(self, t: Dict[str, Any]) -> Optional[str]:
        try:
            ex = str(t.get("exchange") or "?")
            sym = str(t.get("symbol") or "?")
            px = float(t.get("price") or 0.0)
            if px <= 0 or sym == "?":
                return None
            ts = float(t.get("ts") or time.time())
            key = "%s:%s" % (ex, sym)
            tape = self.tapes.get(key)
            if tape is None:
                tape = Tape(ex, sym)
                self.tapes[key] = tape
            delta = float(t.get("delta_usd") or 0.0)
            buy = float(t.get("buy_usd") or 0.0)
            kq = t.get("kline_q")
            if delta <= 0 and kq is not None:
                kq = float(kq)
                kts = float(t.get("kline_ts") or 0.0)
                if tape.son_kline_ts == kts and tape.son_kline_q > 0:
                    delta = max(0.0, kq - tape.son_kline_q)
                else:
                    delta = kq
                tape.son_kline_ts = kts
                tape.son_kline_q = kq
            if buy <= 0:
                buy = delta * 0.5
            tape.ekle(ts, px, delta, buy)
            if not self.ilk_ts:
                self.ilk_ts = ts
            self.son_ts = max(self.son_ts, ts)
            return key
        except (TypeError, ValueError):
            return None

    def ingest_batch(self, ticks: List[Dict[str, Any]]) -> int:
        if not ticks:
            return 0
        self.tick += len(ticks)
        for t in ticks:
            self._tick(t)
        self.gov_guncelle()
        self.blokaj_dene()
        acilan = 0
        for key in list(self.tapes.keys()):
            acilan += self._giris_dene(key)
        self._yonet()
        self.acilan += acilan
        return acilan

    def ingest_ticks(self, ticks: List[Dict[str, Any]]) -> int:
        return self.ingest_batch(ticks)

    def ingest_tick(self, tick: Dict[str, Any]) -> int:
        return self.ingest_batch([tick])

    # ----------------------------- giris
    def _esikler(self) -> Dict[str, float]:
        k = self.filtre.k
        return {"vol": k.min_vol_mult, "vel": k.min_ivme_pct,
                "akis": k.min_akis, "burst": k.min_burst_usd}

    def _tetik(self, m: Dict[str, float]) -> Tuple[int, str]:
        e = self._esikler()
        vol = m["vol_mult"]
        rb = m["ret_burst_pct"]
        r30 = m["ret_30s_pct"]
        akis = m["orderflow_bias"]
        rpos = m["range_pos"]
        hacim_ok = vol >= e["vol"] and m["burst_usd"] >= e["burst"]
        if hacim_ok and (rb >= e["vel"] or r30 >= e["vel"] * 1.35) \
                and akis >= e["akis"] and rpos >= 0.45:
            return 1, "HACIM_PATLAMASI_LONG (%.1fx | %+.2f%%)" % (vol, max(rb, r30))
        if hacim_ok and (rb <= -e["vel"] or r30 <= -e["vel"] * 1.35) \
                and akis <= -e["akis"] and rpos <= 0.55:
            return -1, "COKUS_PATLAMASI_SHORT (%.1fx | %+.2f%%)" % (vol, min(rb, r30))
        return 0, ""

    def _track_sec(self, key: str, m: Dict[str, float], yon: int) -> Optional[str]:
        return "FAST_TRACK"

    def _risk_izni(self, track: str) -> Tuple[bool, str]:
        if self.serbest_teminat() < self.teminat:
            return False, "MARJIN_YETERSIZ"
        if (self.kullanilan_teminat() + self.teminat) > self.equity() * self.margin_cap:
            return False, "MARJIN_YETERSIZ"
        return True, ""

    def blokaj_kaydet(self, key: str, yon: int, tetik: str, m: Dict[str, float],
                      track: str, sebep: str) -> None:
        return None

    def blokaj_dene(self) -> None:
        return None

    def gov_guncelle(self) -> None:
        eq = self.equity()
        self.zirve_equity = max(self.zirve_equity, eq)
        dd = (self.zirve_equity - eq) / max(1.0, self.zirve_equity) * 100.0
        self.gov["dd_pct"] = round(dd, 2)
        self.gov["free_margin"] = round(self.serbest_teminat(), 2)
        self.gov["survival"] = dd > 8.0

    def gov_kapanis(self, net: float) -> None:
        return None

    def track_acildi(self, track: str) -> None:
        return None

    def track_kapandi(self, track: str, net: float) -> None:
        return None

    def _giris_dene(self, key: str) -> int:
        for p in self.pozisyonlar.values():
            if p.key == key:
                return 0
        tape = self.tapes.get(key)
        if tape is None:
            return 0
        m = tape.metrik(12.0)
        if not m:
            return 0
        yon, tetik = self._tetik(m)
        if yon == 0:
            return 0
        ok, _sebep = self.filtre.kontrol(
            tape.symbol, yon, m["vol_mult"], m["ret_burst_pct"],
            m["orderflow_bias"], m["burst_usd"], m["choppiness"], m["ts"])
        if not ok:
            return 0
        track = self._track_sec(key, m, yon)
        if track is None:
            return 0
        izin, sebep = self._risk_izni(track)
        if not izin:
            self.gov["margin_blocks"] = int(self.gov.get("margin_blocks", 0)) + 1
            self.veto[sebep] += 1
            self.blokaj_kaydet(key, yon, tetik, m, track, sebep)
            return 0
        self._ac(tape, yon, tetik, track, m)
        return 1

    def _ac(self, tape: Tape, yon: int, tetik: str, track: str, m: Dict[str, float]) -> None:
        key = "%s:%s" % (tape.exchange, tape.symbol)
        pos = Pozisyon(
            id=uuid.uuid4().hex[:8], key=key, exchange=tape.exchange,
            symbol=tape.symbol, yon=yon, giris=m["px"], ts=m["ts"],
            notional=self.notional, komisyon=self.komisyon,
            track=track, tetik=tetik)
        self.pozisyonlar[pos.id] = pos
        self.filtre.kaydet(tape.symbol, m["ts"])
        self.track_acildi(track)

    # ----------------------------- yonetim / cikis
    def _yonet(self) -> None:
        for pid in list(self.pozisyonlar.keys()):
            pos = self.pozisyonlar.get(pid)
            if pos is None:
                continue
            px = self._fiyat(pos.key)
            if px <= 0:
                continue
            net = pos.net(px)
            if net > pos.zirve_net:
                pos.zirve_net = net
            tape = self.tapes.get(pos.key)
            m = tape.metrik(12.0) if tape is not None else {}
            akis = (m.get("orderflow_bias", 0.0) if m else 0.0) * pos.yon
            simdi = m.get("ts", pos.ts) if m else pos.ts

            if pos.zirve_net >= 25.0:
                gb = self.giveback[2]
            elif akis >= 0.15:
                gb = self.giveback[0]
            else:
                gb = self.giveback[1]
            if pos.zirve_net >= self.trail_trigger:
                esik = pos.zirve_net * (1.0 - gb)
                if esik > pos.taban:
                    pos.taban = esik
            elif pos.zirve_net >= self.be_trigger:
                if self.be_lock > pos.taban:
                    pos.taban = self.be_lock

            if net <= -self.stop:
                self._kapat(pos, px, "ZARAR_KES_-10USD")
                continue
            if pos.taban > -1e8 and net <= pos.taban:
                sebep = "AI_TRAILING_KAR_AL" if pos.taban >= 3.0 else "BE_KAR_KORUMA"
                self._kapat(pos, px, sebep)
                continue
            if net >= self.exhaustion_min and m and akis <= -0.10 \
                    and m.get("vol_mult", 9.9) < 1.0:
                self._kapat(pos, px, "AI_TUKENIS_KAR_HASADI")
                continue
            if self.stagnation_sec and (simdi - pos.ts) >= self.stagnation_sec \
                    and net >= self.stagnation_min:
                self._kapat(pos, px, "AI_ZAMAN_SONUMLENME_KAR_HASADI")

    def _kapat(self, pos: Pozisyon, px: float, sebep: str) -> None:
        net = pos.net(px)
        self.realize += net
        self.kapanan.append({
            "id": pos.id,
            "symbol": pos.symbol,
            "exchange": pos.exchange,
            "side": "LONG" if pos.yon > 0 else "SHORT",
            "entry_price": round(pos.giris, 10),
            "exit_price": round(px, 10),
            "track": pos.track,
            "trigger_type": pos.tetik,
            "exit_reason": sebep,
            "net_pnl_usd": round(net, 2),
            "peak_pnl_usd": round(pos.zirve_net, 2),
            "opened_ts": pos.ts,
            "closed_ts": px and time.time(),
        })
        self.pozisyonlar.pop(pos.id, None)
        self.track_kapandi(pos.track, net)
        self.gov_kapanis(net)
        self.gov_guncelle()

    # ----------------------------- rapor
    def snapshot(self) -> Dict[str, Any]:
        eq = self.equity()
        acik = 0.0
        acik_liste: List[Dict[str, Any]] = []
        for p in self.pozisyonlar.values():
            px = self._fiyat(p.key)
            net = p.net(px)
            acik += net
            acik_liste.append({
                "id": p.id,
                "symbol": p.symbol,
                "exchange": p.exchange,
                "side": p.yon,
                "entry_price": p.giris,
                "mark_price": px,
                "track": p.track,
                "net_pnl_usd": round(net, 2),
                "peak_pnl_usd": round(p.zirve_net, 2),
                "floor_usd": round(p.taban, 2) if p.taban > -1e8 else None,
            })
        kapanan = list(self.kapanan)
        pnls = [k["net_pnl_usd"] for k in kapanan]
        kaz = [x for x in pnls if x > 0]
        kay = [x for x in pnls if x <= 0]
        brut_kay = abs(sum(kay))
        pf = round(sum(kaz) / brut_kay, 2) if brut_kay > 0 else None
        calisma = (self.son_ts - self.ilk_ts) if self.ilk_ts and self.son_ts > self.ilk_ts else 0.0
        return {
            "bot": self.AD,
            "account": {
                "margin_mode": "CROSS (CAPRAZ)",
                "initial_equity_usd": self.baslangic,
                "live_equity_usd": round(eq, 2),
                "realized_pnl_usd": round(self.realize, 2),
                "unrealized_pnl_usd": round(acik, 2),
                "margin_per_trade_usd": self.teminat,
                "leverage": self.kaldirac,
                "used_margin_usd": round(self.kullanilan_teminat(), 2),
                "free_margin_usd": round(self.serbest_teminat(), 2),
                "open_count": len(self.pozisyonlar),
                "closed_count": len(pnls),
                "win_rate": round(len(kaz) / len(pnls), 3) if pnls else 0.0,
                "profit_factor": pf,
                "open_risk_usd": round(self.acik_risk(), 2),
            },
            "open_positions": acik_liste,
            "closed_trades": kapanan[-40:],
            "filtre": self.filtre.snapshot(),
            "governor": dict(self.gov),
            "universe": {
                "total_symbols": len(self.tapes),
                "total_ticks": self.tick,
                "calisma_sn": round(calisma, 1),
            },
            "ek": self.ek_snapshot(),
        }

    def ek_snapshot(self) -> Dict[str, Any]:
        return {}

    def ozet(self) -> Dict[str, Any]:
        s = self.snapshot()
        a = s["account"]
        return {
            "bot": self.AD,
            "live_equity_usd": a["live_equity_usd"],
            "realized_pnl_usd": a["realized_pnl_usd"],
            "unrealized_pnl_usd": a["unrealized_pnl_usd"],
            "open_count": a["open_count"],
            "closed_count": a["closed_count"],
            "win_rate": a["win_rate"],
            "profit_factor": a["profit_factor"],
            "used_margin_usd": a["used_margin_usd"],
            "open_risk_usd": a["open_risk_usd"],
            "filtre_veto": s["filtre"]["veto_sayaci"],
            "governor": s["governor"],
            "universe": s["universe"],
            "ek": s["ek"],
            "kurallar": s["filtre"]["kurallar"],
        }


# ------------------------------------------------------------------ SENTETIK DOGRULAMA
def sentetik_tickler(sembol: str = "TEST-USDT-SWAP", t0: Optional[float] = None) -> List[Dict[str, Any]]:
    """SADECE kod dogrulamasi. Performans iddiasi degildir."""
    t0 = t0 or 1760000000.0
    ticks: List[Dict[str, Any]] = []
    for i in range(50):
        ticks.append({"exchange": "okx", "symbol": sembol, "price": 100.0,
                      "delta_usd": 300.0, "buy_usd": 150.0, "ts": t0 + i})
    ticks.append({"exchange": "okx", "symbol": sembol, "price": 100.30,
                  "delta_usd": 30000.0, "buy_usd": 29000.0, "ts": t0 + 50.0})
    ticks.append({"exchange": "okx", "symbol": sembol, "price": 100.34,
                  "delta_usd": 6000.0, "buy_usd": 5000.0, "ts": t0 + 51.0})
    ticks.append({"exchange": "okx", "symbol": sembol, "price": 100.36,
                  "delta_usd": 2000.0, "buy_usd": 1800.0, "ts": t0 + 52.0})
    return ticks


def cli(ad: str, motor: Motor) -> int:
    ap = argparse.ArgumentParser(description=ad)
    ap.add_argument("--self-test", action="store_true", help="sentetik ticklerle hizli dogrulama")
    ap.add_argument("--ticks-file", default=None, help="JSONL tick dosyasi")
    ap.add_argument("--out", default=None, help="ozet JSON yolu")
    ap.add_argument("--tam", action="store_true", help="tam snapshot yaz")
    args = ap.parse_args()

    if args.ticks_file:
        try:
            with open(args.ticks_file, "r", encoding="utf-8") as fh:
                for satir in fh:
                    satir = satir.strip()
                    if not satir:
                        continue
                    try:
                        veri = json.loads(satir)
                    except json.JSONDecodeError:
                        continue
                    motor.ingest_batch(veri if isinstance(veri, list) else [veri])
        except OSError as exc:
            print("DOSYA OKUNAMADI: %s" % exc)
            return 2
    elif args.self_test:
        motor.ingest_batch(sentetik_tickler())
    else:
        ap.print_help()
        return 0

    cikti = motor.snapshot() if args.tam else motor.ozet()
    print(json.dumps(cikti, ensure_ascii=False, indent=2))
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(cikti, fh, ensure_ascii=False, indent=2)
            print("yazildi: %s" % args.out)
        except OSError as exc:
            print("UYARI: yazilamadi (%s)" % exc)
    return 0
