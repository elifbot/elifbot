# -*- coding: utf-8 -*-
"""BOT 2 v2 — OMEGA V2.

v1'de bulunan ana hata: trendin tersine giris (BARD short, 30 sn trend yukari -> -20 $)
ve edge esigi 2,4'un hemen ustundeki "cop dolgu" pozisyonlar (10 pozisyon, -9,79 $).

v2 degisiklikleri:
  1. min_edge_to_cost_ratio 2,4 -> 6,0  (kapanan kazananlarin edge'i 6,6-70,3 araligindaydi)
  2. TrendMotor kapisi (30/60 sn trendine karsi giris yasak)
  3. KarKilidi (kar sonrasi 90 sn) + PozisyonDefteri (ters yon kilidi)
  4. Adet tavani 10 (kod kapisi) + marjin tavani %60 (v1'de 10 pozisyon 500 $ teminat baglayip -9,79 uretti)
  5. parabolic_arm 22 -> 15 $, exhaustion_tp 4,8 -> 4,2 $
  6. Siki trailing + ters yon zaman asimi (v1'den devralinan SOXL dersi)
"""
from __future__ import annotations

import time
from typing import Any, Dict

import acarbot_omega
from v2 import ortak


class OmegaV2(acarbot_omega.AcarbotOmegaEngine):
    AD = "BOT2_OMEGA_V2"

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
            sqlite_db_path="omega_ledger_v2.sqlite3",
        )
        super().__init__(cfg=cfg)

    # ---------------------------------------------------------- giris kapisi
    def _evaluate_and_open(self, tape, snap, now_ts: float) -> bool:
        try:
            side, _tip = self.council.detect_candidate_direction(snap)
            if side == 0:
                return False
            sembol = getattr(snap, "base_asset", None) or getattr(tape, "symbol", "")
            ok, _sebep = ortak.giris_izni(self.AD, sembol, side, now_ts)
            if not ok:
                return False
            # v2 adet tavani: 10 pozisyon (v1'de 10 pozisyon 500 $ baglayip -9,79 $ uretti)
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
                self._execute_close(pos, px, net, "V2_SIKI_TRAILING_KAR_AL", simdi)
                continue
            if ortak.ters_zaman_asimi(pos.opened_ts, zirve, net, simdi):
                self._execute_close(pos, px, net, "V2_TERS_YON_ZAMAN_ASIMI", simdi)
        return acilan

    # ---------------------------------------------------------- ek rapor
    def koruma_ozeti(self) -> Dict[str, Any]:   # pragma: no cover
        return {"koruma_veto": dict(ortak.VETO.get(self.AD, {}))}


if __name__ == "__main__":
    print("OmegaV2 hazir:", OmegaV2.AD)
