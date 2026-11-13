"""strategies/trend_follower.py — Bağımsız EMA Şeridi + ADX + MACD + Supertrend Adayı.

Walk-forward, ablasyon ve gecikme/kayma stres motorlarıyla sıfır harici legacy
bağımlılıkla çalışır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import (
    HOLD,
    LONG,
    SHORT,
    Contributor,
    SignalResult,
    StrategyBase,
)

EMA_PERIODS = (9, 21, 50, 200)
ADX_TREND_THRESHOLD = 20.0


def _compute_core_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)

    for p in EMA_PERIODS:
        out[f"ema_{p}"] = close.ewm(span=p, adjust=False, min_periods=p).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = macd - sig

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr14 = tr.ewm(alpha=1.0 / 14.0, adjust=False).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = 100.0 * pd.Series(plus_dm, index=out.index).ewm(alpha=1.0 / 14.0, adjust=False).mean() / atr14.replace(0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=out.index).ewm(alpha=1.0 / 14.0, adjust=False).mean() / atr14.replace(0, np.nan)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100.0
    out["adx"] = dx.ewm(alpha=1.0 / 14.0, adjust=False).mean()

    hl2 = (high + low) / 2.0
    upper_band = hl2 + 2.5 * atr14
    lower_band = hl2 - 2.5 * atr14
    st_line = pd.Series(index=out.index, dtype=float)
    direction = 1
    for i in range(len(out)):
        if i == 0:
            st_line.iloc[i] = float(lower_band.iloc[i])
            continue
        c_prev = float(close.iloc[i - 1])
        c_now = float(close.iloc[i])
        lb = float(lower_band.iloc[i])
        ub = float(upper_band.iloc[i])
        prev_st = float(st_line.iloc[i - 1])
        if direction == 1:
            curr_st = max(lb, prev_st) if c_prev >= prev_st else lb
            if c_now < curr_st:
                direction = -1
                curr_st = ub
        else:
            curr_st = min(ub, prev_st) if c_prev <= prev_st else ub
            if c_now > curr_st:
                direction = 1
                curr_st = lb
        st_line.iloc[i] = curr_st
    out["st_trend"] = st_line
    return out


class TrendFollowerStrategy(StrategyBase):
    """EMA şeridi + ADX + MACD + Supertrend trend takip adayı."""

    STATUS = "SHADOW"
    NAME = "trend_follower_A"
    MIN_ROWS = 210

    def evaluate(self, df: pd.DataFrame) -> SignalResult:
        problem = self._check_frame(df)
        if problem:
            return self._hold(problem, df)

        ind = _compute_core_columns(df)
        last = ind.iloc[-1]

        cols = [f"ema_{p}" for p in EMA_PERIODS]
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
            Contributor("supertrend", st_v, self._sign_vote(close_v - (st_v or close_v)), "A").as_dict(),
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

        trend_ok = adx_v >= ADX_TREND_THRESHOLD
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
        return "TREND_OK" if adx_v >= ADX_TREND_THRESHOLD else "WEAK_TREND"

    @staticmethod
    def _sign_vote(v: float | None) -> str:
        if v is None:
            return "UNAVAILABLE"
        if v > 0:
            return LONG
        if v < 0:
            return SHORT
        return "NEUTRAL"
