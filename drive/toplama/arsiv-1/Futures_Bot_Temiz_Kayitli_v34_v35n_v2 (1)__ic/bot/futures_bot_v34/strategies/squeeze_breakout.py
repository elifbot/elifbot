"""
strategies/squeeze_breakout.py — Aday C: sıkışma kırılımı.

Girdi: BB-Keltner squeeze (C) + hacim z-skoru (D) + 3 mumluk momentum (B).
Kural: sıkışma açıkken hacim patlaması + aynı yönde momentum gerekir.
"""
from __future__ import annotations

import pandas as pd

import config
from indicators.core import add_core_indicators
from indicators.volume import bb_keltner_squeeze, volume_zscore
from strategies.base import (
    HOLD,
    LONG,
    SHORT,
    Contributor,
    SignalResult,
    StrategyBase,
)

MOMENTUM_LOOKBACK = 3


class SqueezeBreakoutStrategy(StrategyBase):
    """BB-Keltner squeeze kırılım adayı."""

    STATUS = "SHADOW"
    NAME = "squeeze_breakout_C"
    MIN_ROWS = 60

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        problem = self._check_frame(df)
        if problem:
            return self._hold(problem, df)

        ind = add_core_indicators(df)
        ind = pd.concat([ind, bb_keltner_squeeze(ind)], axis=1)
        ind["volume_z"] = volume_zscore(ind)

        last = ind.iloc[-1]
        close_v = float(last["close"])
        prev_close = ind["close"].iloc[-(MOMENTUM_LOOKBACK + 1)]
        momentum = (close_v - float(prev_close)) / float(prev_close)

        squeeze_on = bool(last["squeeze_on"]) if pd.notna(last["squeeze_on"]) else False
        vz = float(last["volume_z"]) if pd.notna(last["volume_z"]) else None
        atr_v = float(last["atr"]) if pd.notna(last["atr"]) else None

        log = [
            Contributor("squeeze_on", 1.0 if squeeze_on else 0.0,
                        "SQUEEZE" if squeeze_on else "NO_SQUEEZE", "C").as_dict(),
            Contributor("volume_z", vz, self._vol_vote(vz), "D").as_dict(),
            Contributor("momentum_3", momentum, self._sign_vote(momentum), "B").as_dict(),
            Contributor("atr", atr_v, "NEUTRAL", "C").as_dict(),
        ]

        if vz is None:
            return SignalResult(
                signal=HOLD,
                strategy_name=self.NAME,
                regime="warmup_eksik",
                contributor_log=log,
                active_families=["B", "C", "D"],
                missing_families=[],
                data_timestamp=int(last["open_time"]),
                status=self.STATUS,
                notes=["volume_z warmup'ı tamamlanmadı"],
            )

        volume_blast = vz >= config.VOLUME_ZSCORE_THRESHOLD

        long_ok = (
            self._req("C", squeeze_on)
            and self._req("D", volume_blast)
            and self._req("B", momentum > 0)
        )
        short_ok = (
            self._req("C", squeeze_on)
            and self._req("D", volume_blast)
            and self._req("B", momentum < 0)
        )

        if long_ok and not short_ok:
            signal, regime = LONG, "sikisma_yukari"
        elif short_ok and not long_ok:
            signal, regime = SHORT, "sikisma_asagi"
        else:
            signal, regime = HOLD, "kosullar_saglanmadi"

        self._state["evaluations"] += 1
        self._state["last_signal"] = signal
        return SignalResult(
            signal=signal,
            strategy_name=self.NAME,
            regime=regime,
            contributor_log=log,
            active_families=["B", "C", "D"],
            missing_families=[],
            data_timestamp=int(last["open_time"]),
            status=self.STATUS,
        )

    @staticmethod
    def _vol_vote(vz: float | None) -> str:
        if vz is None:
            return "UNAVAILABLE"
        return "BLAST" if vz >= config.VOLUME_ZSCORE_THRESHOLD else "NORMAL"

    @staticmethod
    def _sign_vote(v: float) -> str:
        if v > 0:
            return LONG
        if v < 0:
            return SHORT
        return "NEUTRAL"
