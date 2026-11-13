"""
strategies/trend_follower.py — Aday A: trend takip.

Girdi: EMA şeridi (A) + ADX (A) + MACD (B) + Supertrend (A).
Kural: dört koşul birden sağlanmazsa HOLD. Kısmi uyum sinyal üretmez.
"""
from __future__ import annotations

import pandas as pd

import config
from indicators.core import add_core_indicators
from strategies.base import (
    HOLD,
    LONG,
    SHORT,
    Contributor,
    SignalResult,
    StrategyBase,
)


class TrendFollowerStrategy(StrategyBase):
    """EMA şeridi + ADX + MACD + Supertrend trend takip adayı."""

    STATUS = "SHADOW"
    NAME = "trend_follower_A"
    MIN_ROWS = 210  # EMA200 için >= 200 kapalı mum + pay

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        problem = self._check_frame(df)
        if problem:
            return self._hold(problem, df)

        ind = add_core_indicators(df)
        last = ind.iloc[-1]

        # EMA şerit yönü
        cols = [f"ema_{p}" for p in config.EMA_PERIODS]
        if last[cols].isna().any():
            return self._hold("ema_warmup_yetersiz", df)

        values = [float(last[c]) for c in cols]
        if all(a > b for a, b in zip(values, values[1:])):
            ribbon = "BULLISH"
        elif all(a < b for a, b in zip(values, values[1:])):
            ribbon = "BEARISH"
        else:
            ribbon = "HOLD"

        adx_v = float(last["adx"]) if pd.notna(last["adx"]) else None
        hist_v = float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else None
        st_v = float(last["st_trend"]) if pd.notna(last["st_trend"]) else None
        close_v = float(last["close"])

        log = [
            Contributor("ema_ribbon", None, ribbon, "A").as_dict(),
            Contributor("adx", adx_v, self._trend_vote(adx_v), "A").as_dict(),
            Contributor("macd_hist", hist_v, self._sign_vote(hist_v), "B").as_dict(),
            Contributor("supertrend", st_v, self._sign_vote(st_v), "A").as_dict(),
        ]

        if adx_v is None or hist_v is None or st_v is None:
            return SignalResult(
                signal=HOLD,
                strategy_name=self.NAME,
                regime="warmup_eksik",
                contributor_log=log,
                active_families=["A", "B"],
                missing_families=[],
                data_timestamp=int(last["open_time"]),
                status=self.STATUS,
                notes=["gösterge warmup'ı tamamlanmadı"],
            )

        trend_ok = adx_v >= config.ADX_TREND_THRESHOLD

        # Ablasyon: devre dışı bırakılan ailenin koşulu gerekli olmaktan çıkar.
        long_ok = (
            self._req("A", ribbon == "BULLISH")
            and self._req("A", trend_ok)
            and self._req("A", close_v > st_v)
            and self._req("B", hist_v > 0)
        )
        short_ok = (
            self._req("A", ribbon == "BEARISH")
            and self._req("A", trend_ok)
            and self._req("A", close_v < st_v)
            and self._req("B", hist_v < 0)
        )

        if long_ok and not short_ok:
            signal, regime = LONG, "trend_up"
        elif short_ok and not long_ok:
            signal, regime = SHORT, "trend_down"
        else:
            signal, regime = HOLD, "kosullar_saglanmadi"

        self._state["evaluations"] += 1
        self._state["last_signal"] = signal
        return SignalResult(
            signal=signal,
            strategy_name=self.NAME,
            regime=regime,
            contributor_log=log,
            active_families=["A", "B"],
            missing_families=[],
            data_timestamp=int(last["open_time"]),
            status=self.STATUS,
        )

    @staticmethod
    def _trend_vote(adx_v: float | None) -> str:
        if adx_v is None:
            return "UNAVAILABLE"
        return "TREND_OK" if adx_v >= config.ADX_TREND_THRESHOLD else "WEAK_TREND"

    @staticmethod
    def _sign_vote(v: float | None) -> str:
        if v is None:
            return "UNAVAILABLE"
        if v > 0:
            return LONG
        if v < 0:
            return SHORT
        return "NEUTRAL"
