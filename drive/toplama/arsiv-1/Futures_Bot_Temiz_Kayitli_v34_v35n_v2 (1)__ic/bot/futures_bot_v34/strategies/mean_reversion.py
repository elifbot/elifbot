"""
strategies/mean_reversion.py — Aday B: ortalamaya dönüş.

Girdi: RSI (B) + Bollinger alt/üst bandı (C) + Session VWAP (D).
Kural: üç koşul birden sağlanmalı.
"""
from __future__ import annotations

import pandas as pd

import config
from indicators.core import add_core_indicators
from indicators.volume import session_vwap
from strategies.base import (
    HOLD,
    LONG,
    SHORT,
    Contributor,
    SignalResult,
    StrategyBase,
)


class MeanReversionStrategy(StrategyBase):
    """RSI + Bollinger dokunuşu + VWAP ortalamaya dönüş adayı."""

    STATUS = "SHADOW"
    NAME = "mean_reversion_B"
    MIN_ROWS = 60  # RSI(14) + BB(20) warmup'ı için yeterli

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        problem = self._check_frame(df)
        if problem:
            return self._hold(problem, df)

        ind = add_core_indicators(df)
        ind["vwap"] = session_vwap(ind)
        last = ind.iloc[-1]

        rsi_v = float(last["rsi"]) if pd.notna(last["rsi"]) else None
        close_v = float(last["close"])
        bb_upper = float(last["bb_upper"]) if pd.notna(last["bb_upper"]) else None
        bb_lower = float(last["bb_lower"]) if pd.notna(last["bb_lower"]) else None
        vwap_v = float(last["vwap"]) if pd.notna(last["vwap"]) else None

        log = [
            Contributor("rsi", rsi_v, self._rsi_vote(rsi_v), "B").as_dict(),
            Contributor("bb_lower", bb_lower, "NEUTRAL", "C").as_dict(),
            Contributor("bb_upper", bb_upper, "NEUTRAL", "C").as_dict(),
            Contributor("vwap", vwap_v, "NEUTRAL", "D").as_dict(),
        ]

        if None in (rsi_v, bb_upper, bb_lower, vwap_v):
            return SignalResult(
                signal=HOLD,
                strategy_name=self.NAME,
                regime="warmup_eksik",
                contributor_log=log,
                active_families=["B", "C", "D"],
                missing_families=[],
                data_timestamp=int(last["open_time"]),
                status=self.STATUS,
                notes=["gösterge warmup'ı tamamlanmadı"],
            )

        long_ok = (
            self._req("B", rsi_v <= config.RSI_OVERSOLD)
            and self._req("C", close_v <= bb_lower)
            and self._req("D", close_v < vwap_v)
        )
        short_ok = (
            self._req("B", rsi_v >= config.RSI_OVERBOUGHT)
            and self._req("C", close_v >= bb_upper)
            and self._req("D", close_v > vwap_v)
        )

        if long_ok and not short_ok:
            signal, regime = LONG, "asiri_satim"
        elif short_ok and not long_ok:
            signal, regime = SHORT, "asiri_alim"
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
    def _rsi_vote(rsi_v: float | None) -> str:
        if rsi_v is None:
            return "UNAVAILABLE"
        if rsi_v <= config.RSI_OVERSOLD:
            return LONG
        if rsi_v >= config.RSI_OVERBOUGHT:
            return SHORT
        return "NEUTRAL"
