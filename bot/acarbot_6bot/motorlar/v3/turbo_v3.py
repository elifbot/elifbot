# -*- coding: utf-8 -*-
"""BOT 1 v3 — TURBO V3.

TURBO v2 8 botluk testin en iyi tureviydi (+23,89 $ / v1 TURBO -6,70 $).
Bu yuzden giris mantigi ve parametreleri AYNEN korundu:
    be 3,50 · trail 6,00 · tukenis TP 4,00 · cooldown 90 sn · hacim 3,0x · burst 12.000 $

v3'te eklenen iki sey:
  FIX 1  ters zaman asimi artik sadece trend gercekten dondugunde kapatir
         (pullback'te 12 dk'ya kadar sabreder, -9 $ asilirsa keser)
  FIX 5  golge defteri: reddedilen sinyaller 120 sn sanal izlenir
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import turbo_engine
from v3 import ortak


class TurboV3(turbo_engine.RealTimeVolumeShockEngine):
    AD = "BOT9_TURBO_V3"

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
            px = float(m.get("px") or getattr(tape, "last_price", 0.0) or 0.0)
            ok, _sebep = ortak.giris_izni(self.AD, tape.symbol, side, now_ts, px)
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

        # 1) kademeli siki trailing (v2'den aynen)
        taban = ortak.siki_taban(zirve)
        if taban is not None and net <= taban:
            self._close_position(pos, px, net, "V3_SIKI_TRAILING_KAR_AL", now_ts)
            return

        # 2) FIX 1 — sadece trend dondugunde kes
        kes, sebep = ortak.ters_yon_asimi(pos.symbol, int(pos.side), pos.opened_ts,
                                          zirve, net, now_ts)
        if kes:
            self._close_position(pos, px, net, sebep, now_ts)

    # ---------------------------------------------------------- ek rapor
    def ek_snapshot(self) -> Dict[str, Any]:    # pragma: no cover
        return {"koruma_veto": dict(ortak.VETO.get(self.AD, {}))}


if __name__ == "__main__":
    import turbo_engine as _t
    print("TurboV3 hazir:", TurboV3.AD, _t.TurboConfig().notional_per_trade_usd, "$")
