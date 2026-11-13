"""
strategies/spike_momentum.py — Aday D: ani hacim/fiyat hareketi (spike) momentumu.

Mantık: hacim patlaması (rvol) + belirgin fiyat hareketi aynı yönde ise
hareketin kısa vadede sürmesi varsayımıyla pozisyon alınır.

  LONG  : ANI_YUKSELIS  (ret_k >= +eşik ve rvol >= eşik) ve kapanış > VWAP
  SHORT : ANI_DUSUS     (ret_k <= -eşik ve rvol >= eşik) ve kapanış < VWAP

DÜRÜST NOT: "Spike'ın yönü sürer" varsayımı bu projede KANITLANMAMIŞTIR.
Bu yüzden aday SHADOW durumundadır ve tek başına işlem kararı vermez.
"""
from __future__ import annotations

import pandas as pd

import config
from indicators.volume import session_vwap
from scanner.spike import ANI_DUSUS, ANI_YUKSELIS, compute_spike
from strategies.base import (
    HOLD,
    LONG,
    SHORT,
    Contributor,
    SignalResult,
    StrategyBase,
)


class SpikeMomentumStrategy(StrategyBase):
    """Hacim patlaması + ani fiyat hareketi adayı."""

    STATUS = "SHADOW"
    NAME = "spike_momentum_D"
    MIN_ROWS = 80

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        problem = self._check_frame(df)
        if problem:
            return self._hold(problem, df)

        metrics = compute_spike(
            df,
            self.NAME,
            lookback=config.SCAN_LOOKBACK_BARS,
            k_bars=config.SCAN_K_BARS,
            ret_threshold_pct=config.SCAN_RET_THRESHOLD_PCT,
            rvol_threshold=config.SCAN_RVOL_THRESHOLD,
        )
        if metrics is None:
            return self._hold("spike_hesaplanamadi", df)

        vwap = session_vwap(df)
        vwap_v = float(vwap.iloc[-1]) if pd.notna(vwap.iloc[-1]) else None
        close_v = float(df["close"].iloc[-1])

        log = [
            Contributor("rvol", metrics.rvol, self._rvol_vote(metrics.rvol), "D").as_dict(),
            Contributor("volume_z", metrics.volume_z, "NEUTRAL", "D").as_dict(),
            Contributor("ret_k_pct", metrics.ret_k_pct, self._ret_vote(metrics.ret_k_pct), "B").as_dict(),
            Contributor("range_expansion", metrics.range_expansion, "NEUTRAL", "C").as_dict(),
            Contributor("vwap", vwap_v, "NEUTRAL", "D").as_dict(),
            Contributor("spike_label", None, metrics.label, "D").as_dict(),
        ]

        if vwap_v is None:
            return self._hold("vwap_hesaplanamadi", df)

        long_ok = (
            self._req("D", metrics.label == ANI_YUKSELIS)
            and self._req("D", close_v > vwap_v)
        )
        short_ok = (
            self._req("D", metrics.label == ANI_DUSUS)
            and self._req("D", close_v < vwap_v)
        )

        if long_ok and not short_ok:
            signal, regime = LONG, ANI_YUKSELIS.lower()
        elif short_ok and not long_ok:
            signal, regime = SHORT, ANI_DUSUS.lower()
        else:
            signal, regime = HOLD, "spike_yok"

        self._state["evaluations"] += 1
        self._state["last_signal"] = signal
        return SignalResult(
            signal=signal,
            strategy_name=self.NAME,
            regime=regime,
            contributor_log=log,
            active_families=["B", "C", "D"],
            missing_families=["F"],
            data_timestamp=int(df["open_time"].iloc[-1]),
            status=self.STATUS,
            notes=["spike sürekliliği kanıtlanmadı — SHADOW"],
        )

    @staticmethod
    def _rvol_vote(rvol: float) -> str:
        return "BLAST" if rvol >= config.SCAN_RVOL_THRESHOLD else "NORMAL"

    @staticmethod
    def _ret_vote(ret: float) -> str:
        if ret >= config.SCAN_RET_THRESHOLD_PCT:
            return LONG
        if ret <= -config.SCAN_RET_THRESHOLD_PCT:
            return SHORT
        return "NEUTRAL"
