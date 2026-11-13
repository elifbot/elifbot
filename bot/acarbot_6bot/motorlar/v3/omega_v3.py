# -*- coding: utf-8 -*-
"""BOT 2 v3 — OMEGA V3.

8 botluk testte OMEGA v2'nin tek buyuk hasari yeni "ters yon zaman asimi" kuralindan geldi:
BARD short 4. dakikada -8,95 $ ile kesildi, v1 ayni pozisyonu +6,43 $ ile kapatti (-16,34 $).

v3 degisiklikleri:
  FIX 1  zaman asimi artik YALNIZ trend gercekten dondugunde kapatir; trend hala
         pozisyonun yonundeyse pullback sayilir ve 12 dk'ya kadar tutulur
  FIX 5  golge defteri (reddedilen sinyallerin sanal sonucu)
Giris disiplini v2 ile ayni: edge/maliyet 6,0 · marjin %60 · adet tavani 10 · parabolik 15 $
"""
from __future__ import annotations

import time
from typing import Any, Dict

import acarbot_omega
from v3 import ortak


class OmegaV3(acarbot_omega.AcarbotOmegaEngine):
    AD = "BOT10_OMEGA_V3"

    def __init__(self) -> None:
        cfg = acarbot_omega.OmegaConfig(
            min_edge_to_cost_ratio=6.0,
            parabolic_arm_usd=15.0,
            exhaustion_tp_min_usd=4.2,
            be_trigger_usd=4.0,
            trail_arm_usd=6.5,
            symbol_cooldown_sec=90.0,
            deduplicate_base_asset_sec=30.0,
            margin_utilization_cap=0.60,
            council_min_approval_score=0.60,
            sqlite_db_path="omega_ledger_v3.sqlite3",
        )
        super().__init__(cfg=cfg)

    # ---------------------------------------------------------- giris kapisi
    def _evaluate_and_open(self, tape, snap, now_ts: float) -> bool:
        try:
            side, _tip = self.council.detect_candidate_direction(snap)
            if side == 0:
                return False
            sembol = getattr(snap, "base_asset", None) or getattr(tape, "symbol", "")
            px = float(getattr(snap, "price", 0.0) or getattr(tape, "last_price", 0.0) or 0.0)
            ok, _sebep = ortak.giris_izni(self.AD, sembol, side, now_ts, px)
            if not ok:
                return False
            if len(self.positions) >= 10:
                ortak.veto(self.AD, "ADET_TAVANI_10")
                return False
        except Exception:
            return super()._evaluate_and_open(tape, snap, now_ts)
        return super()._evaluate_and_open(tape, snap, now_ts)

    # ---------------------------------------------------------- cikis kapisi
    def ingest_ticks(self, ticks) -> int:
        acilan = super().ingest_ticks(ticks)
        if not self.positions:
            return acilan
        simdi = time.time()
        for pos in list(self.positions.values()):
            try:
                net = float(pos.net_pnl_usd)
                zirve = float(pos.peak_pnl_usd)
                px = float(pos.mark_price or pos.entry_price)
                if px <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            taban = ortak.siki_taban(zirve)
            if taban is not None and net <= taban:
                self._execute_close(pos, px, net, "V3_SIKI_TRAILING_KAR_AL", simdi)
                continue
            kes, sebep = ortak.ters_yon_asimi(pos.symbol, int(pos.side), pos.opened_ts,
                                              zirve, net, simdi)
            if kes:
                self._execute_close(pos, px, net, sebep, simdi)
        return acilan

    # ---------------------------------------------------------- ek rapor
    def koruma_ozeti(self) -> Dict[str, Any]:   # pragma: no cover
        return {"koruma_veto": dict(ortak.VETO.get(self.AD, {}))}


if __name__ == "__main__":
    print("OmegaV3 hazir:", OmegaV3.AD)
