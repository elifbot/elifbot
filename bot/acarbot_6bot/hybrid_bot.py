# -*- coding: utf-8 -*-
"""BOT 3 - HYBRID v2.

BOT 1'in hizli tetikleyicisi + BOT 2'nin maliyet/marjin disiplini.

Cift hat:
  FAST_TRACK    : 5x hacim + 0,15 akis + 8.000 $ burst  -> hizli giris
  COUNCIL_TRACK : 7x hacim + 0,30 akis + 12.000 $ burst + testere < 55 + skor >= 0,56
Vali (governor): drawdown %8 -> hizli hat kapanir, edge < 1,6 -> giris yok.
Kuyruk (backlog): marjin yoksa COUNCIL sinyali 30 sn bekler, fiyat %0,6'dan fazla
                  kaymadiysa yer acilinca aktive olur.

Kasa 1.000 $ - teminat 50 $ x 10x CAPRAZ - pozisyon basina kesin -20 $ net stop.

Calistirma:
    python hybrid_bot.py --self-test
    python hybrid_bot.py --ticks-file tickler.jsonl --out hybrid_ozet.json
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from cekirdek import Filtre, FiltreKurallari, Motor, cli


def _bos_track() -> Dict[str, float]:
    return {"opened": 0, "closed": 0, "wins": 0, "pnl_usd": 0.0}


class HybridV2(Motor):
    AD = "BOT3_HYBRID_V2"

    def __init__(self) -> None:
        super().__init__()
        self.filtre = Filtre(FiltreKurallari(
            min_vol_mult=5.0,
            min_ivme_pct=0.18,
            max_ivme_pct=0.60,
            min_akis=0.15,
            min_burst_usd=8000.0,
            max_chop=64.0,
            baz_dedupe_sec=15.0,
            sembol_cooldown_sec=25.0,
        ))
        self.fast = {"vol": 5.0, "akis": 0.15, "burst": 8000.0}
        self.council = {"vol": 7.0, "akis": 0.30, "burst": 12000.0,
                        "chop": 55.0, "skor": 0.56}
        self.edge_esigi = 1.6

        self.be_trigger = 4.50
        self.be_lock = 1.10
        self.trail_trigger = 7.80
        self.giveback = (0.28, 0.18, 0.14)
        self.exhaustion_min = 4.80
        self.stagnation_sec = 900.0
        self.stagnation_min = 2.20

        self.kuyruk: List[Dict[str, Any]] = []
        self.kuyruk_ttl = 30.0
        self.kuyruk_kayma = 0.006
        self._son: List[float] = []
        self.tracks: Dict[str, Dict[str, float]] = {
            "FAST_TRACK": _bos_track(),
            "COUNCIL_TRACK": _bos_track(),
        }

    # ----------------------------- skor / hat secimi
    def skor(self, m: Dict[str, float], yon: int) -> float:
        return (0.40 * min(1.0, m["vol_mult"] / 10.0)
                + 0.35 * min(1.0, abs(m["ret_burst_pct"]) / 0.60)
                + 0.25 * min(1.0, max(0.0, m["orderflow_bias"] * yon)))

    def _track_sec(self, key: str, m: Dict[str, float], yon: int) -> Optional[str]:
        c = self.council
        ayni_yon = (m["ret_burst_pct"] * yon > 0) and (m["ret_30s_pct"] * yon > 0)
        konsey = (m["vol_mult"] >= c["vol"]
                  and m["orderflow_bias"] * yon >= c["akis"]
                  and m["burst_usd"] >= c["burst"]
                  and m["choppiness"] <= c["chop"]
                  and ayni_yon
                  and self.skor(m, yon) >= c["skor"])
        if konsey:
            return "COUNCIL_TRACK"
        if self.gov.get("survival"):
            return None
        f = self.fast
        if (m["vol_mult"] >= f["vol"]
                and m["orderflow_bias"] * yon >= f["akis"]
                and m["burst_usd"] >= f["burst"]):
            return "FAST_TRACK"
        return None

    # ----------------------------- vali + marjin
    def _risk_izni(self, track: str) -> Tuple[bool, str]:
        if track == "FAST_TRACK" and self.gov.get("survival"):
            return False, "VALI_SURVIVAL"
        if len(self._son) >= 10 and self.gov.get("edge", 9.9) < self.edge_esigi:
            return False, "EDGE_ESIGI"
        return super()._risk_izni(track)

    # ----------------------------- kuyruk
    def blokaj_kaydet(self, key: str, yon: int, tetik: str, m: Dict[str, float],
                      track: str, sebep: str) -> None:
        if track != "COUNCIL_TRACK":
            return
        self.kuyruk.append({"key": key, "yon": yon, "tetik": tetik,
                            "ts": m["ts"], "px": m["px"], "sebep": sebep})
        if len(self.kuyruk) > 20:
            self.kuyruk = self.kuyruk[-20:]

    def blokaj_dene(self) -> None:
        if not self.kuyruk:
            return
        simdi = 0.0
        for t in self.tapes.values():
            if t.samples and t.samples[-1].ts > simdi:
                simdi = t.samples[-1].ts
        kalan: List[Dict[str, Any]] = []
        for k in self.kuyruk:
            tape = self.tapes.get(k["key"])
            if tape is None or not tape.samples:
                continue
            if simdi - k["ts"] > self.kuyruk_ttl:
                self.gov["kuyruk_suresi_doldu"] = int(self.gov.get("kuyruk_suresi_doldu", 0)) + 1
                continue
            px = tape.samples[-1].px
            if k["px"] > 0 and abs(px / k["px"] - 1.0) > self.kuyruk_kayma:
                self.gov["kuyruk_bayat"] = int(self.gov.get("kuyruk_bayat", 0)) + 1
                continue
            izin, _sebep = self._risk_izni("COUNCIL_TRACK")
            if not izin:
                kalan.append(k)
                continue
            m = tape.metrik(12.0)
            if not m:
                kalan.append(k)
                continue
            self._ac(tape, k["yon"], k["tetik"] + " [KUYRUK]", "COUNCIL_TRACK", m)
            self.gov["kuyruk_aktive"] = int(self.gov.get("kuyruk_aktive", 0)) + 1
        self.kuyruk = kalan

    # ----------------------------- istatistik
    def track_acildi(self, track: str) -> None:
        g = self.tracks.setdefault(track, _bos_track())
        g["opened"] = int(g["opened"]) + 1

    def track_kapandi(self, track: str, net: float) -> None:
        g = self.tracks.setdefault(track, _bos_track())
        g["closed"] = int(g["closed"]) + 1
        if net > 0:
            g["wins"] = int(g["wins"]) + 1
        g["pnl_usd"] = round(float(g["pnl_usd"]) + net, 2)

    def gov_kapanis(self, net: float) -> None:
        self._son.append(net)
        if len(self._son) > 30:
            self._son = self._son[-30:]
        kaz = [x for x in self._son if x > 0]
        kay = [abs(x) for x in self._son if x < 0]
        if kaz and kay and sum(kay) > 0 and sum(kaz) > 0:
            edge = (sum(kaz) / len(kaz)) / (sum(kay) / len(kay))
        else:
            edge = 9.9
        self.gov["edge"] = round(edge, 2)
        self.gov["rolling_win_rate"] = round(len(kaz) / len(self._son), 3)

    def ek_snapshot(self) -> Dict[str, Any]:
        return {
            "tracks": self.tracks,
            "kuyruk": {
                "bekleyen": len(self.kuyruk),
                "aktive": int(self.gov.get("kuyruk_aktive", 0)),
                "suresi_dolan": int(self.gov.get("kuyruk_suresi_doldu", 0)),
                "bayatlayan": int(self.gov.get("kuyruk_bayat", 0)),
            },
            "vali": {
                "dd_pct": self.gov.get("dd_pct"),
                "survival": self.gov.get("survival"),
                "edge": self.gov.get("edge"),
                "edge_esigi": self.edge_esigi,
                "skor_tabani": self.council["skor"],
                "serbest_teminat": self.gov.get("free_margin"),
            },
        }


if __name__ == "__main__":
    raise SystemExit(cli("BOT 3 - HYBRID v2", HybridV2()))
