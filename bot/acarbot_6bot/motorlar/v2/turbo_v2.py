# -*- coding: utf-8 -*-
"""BOT 1 v2 — TURBO V2.

v1'den farklari (30 dk testi bulgularina gore):
  1. TrendMotor kapisi      : 30/60 sn trendine karsi giris yasak (BARD/SOXL dersi)
  2. KarKilidi              : kar sonrasi 90 sn ayni sembole giris yok (BARD -15,22 $ dersi)
  3. PozisyonDefteri        : v2 ailesinde ayni sembolde ters yon yasak
  4. Siki trailing          : tepe karin %82-88'i kilitlenir (v1'de yakalama %55'ti)
  5. Ters zaman asimi       : tepe kar gormeden 4 dk ters yonde surunen pozisyon kapanir
  6. symbol_cooldown        : 20 sn -> 90 sn
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import turbo_engine
from v2 import ortak


class TurboV2(turbo_engine.RealTimeVolumeShockEngine):
    AD = "BOT1_TURBO_V2"

    def __init__(self) -> None:
        cfg = turbo_engine.TurboConfig(
            be_trigger_usd=3.50,
            trail_trigger_usd=6.00,
            exhaustion_tp_min_usd=4.00,
            symbol_cooldown_sec=90.0,
            vol_explosion_mult=3.0,
            min_burst_usd=12_000.0,
            min_velocity_pct=0.30,
        )
        super().__init__(cfg=cfg)

    # ---------------------------------------------------------- giris kapisi
    def _evaluate_and_enter(self, tape, now_ts: float,
                            precomputed_metrics: Optional[Dict[str, float]] = None) -> bool:
        try:
            m = precomputed_metrics or tape.metrics(self.cfg.burst_window_sec)
            rb = float(m.get("ret_burst_pct", 0.0))
            r30 = float(m.get("ret_30s_pct", 0.0))
            side = 1 if (rb >= 0.0 or r30 >= 0.0) else -1
            ok, _sebep = ortak.giris_izni(self.AD, tape.symbol, side, now_ts)
            if not ok:
                return False
        except Exception:
            return super()._evaluate_and_enter(tape, now_ts, precomputed_metrics)
        return super()._evaluate_and_enter(tape, now_ts, precomputed_metrics)

    # ---------------------------------------------------------- cikis kapisi
    def _manage_single_position(self, pos, tape, now_ts: float) -> None:
        super()._manage_single_position(pos, tape, now_ts)
        if pos.id not in self.positions:          # v1 kurallari zaten kapatti
            return
        px = tape.last_price
        net = float(pos.net_pnl_usd)
        zirve = float(pos.peak_pnl_usd)

        # 1) kademeli siki trailing
        taban = ortak.siki_taban(zirve)
        if taban is not None and net <= taban:
            self._close_position(pos, px, net, "V2_SIKI_TRAILING_KAR_AL", now_ts)
            return

        # 2) tepe kar gormeden ters yonde surunme -> zaman asimi
        if ortak.ters_zaman_asimi(pos.opened_ts, zirve, net, now_ts):
            self._close_position(pos, px, net, "V2_TERS_YON_ZAMAN_ASIMI", now_ts)

    # ---------------------------------------------------------- ek rapor
    def ek_snapshot(self) -> Dict[str, Any]:    # pragma: no cover
        return {"koruma_veto": dict(ortak.VETO.get(self.AD, {}))}


if __name__ == "__main__":
    import turbo_engine as _t
    print("TurboV2 hazir:", TurboV2.AD, _t.TurboConfig().notional_per_trade_usd, "$")
