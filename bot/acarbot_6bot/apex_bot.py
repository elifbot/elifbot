# -*- coding: utf-8 -*-
"""BOT 4 - APEX.

Kanitlanmis kazanan kovalar (5x+ hacim, %0,18-0,60 ivme) + portfoy risk tavani.
Kasa 1.000 $ - teminat 50 $ x 10x CAPRAZ - pozisyon basina kesin -20 $ net stop.

Calistirma:
    python apex_bot.py --self-test
    python apex_bot.py --ticks-file tickler.jsonl --out apex_ozet.json
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from cekirdek import Filtre, FiltreKurallari, Motor, cli


class Apex(Motor):
    AD = "BOT4_APEX"

    def __init__(self) -> None:
        super().__init__()
        # Konsey K1/K2/K3/K4: 2-5x kovasi ve %0,60+ kovalama yasak
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
        # K5: acik risk kasanin %25'ini gecemez (4.200 $ / 6,62x dersi)
        self.max_open_risk_pct = 0.25
        # K8: kar motoru sikilastirildi
        self.be_trigger = 4.50
        self.be_lock = 1.20
        self.trail_trigger = 7.50
        self.giveback = (0.25, 0.16, 0.12)
        self.exhaustion_min = 4.80

    def _risk_izni(self, track: str) -> Tuple[bool, str]:
        esik = max(1.0, self.equity()) * self.max_open_risk_pct
        if self.acik_risk() + self.stop > esik:
            return False, "PORTFOY_RISK_TAVANI"
        return super()._risk_izni(track)

    def ek_snapshot(self) -> Dict[str, Any]:
        esik = max(1.0, self.equity()) * self.max_open_risk_pct
        return {
            "risk_tavani_usd": round(esik, 2),
            "risk_kullanimi_pct": round(100.0 * self.acik_risk() / esik, 1),
        }


if __name__ == "__main__":
    raise SystemExit(cli("BOT 4 - APEX", Apex()))
