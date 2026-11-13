"""Gerçek teknik indikatörler — saf pandas/numpy ile hesaplanır (TA-Lib gerekmez).

İndikatör seti:
  Trend      : MA 20/50, EMA 9/21/50/200, MACD, ADX, Donchian, Supertrend
  Momentum   : RSI, Stokastik RSI, CCI, Williams %R
  Hacim/Akış : MFI, OBV, UTC günlük/haftalık VWAP, swing-anchored VWAP, Volume Profile
  Volatilite : ATR, Bollinger Bandwidth, Keltner sıkışması
  Türev      : Funding Rate (kalabalık karşıtı sinyal)
  Rejim      : TREND / RANGE / SIKISMA / BREAKOUT; eski skor A/B için korunur
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class Indicators:
    """Tüm indikatör hesapları (vektörel, hızlı). Girdi: OHLCV DataFrame sütunları."""

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False, min_periods=period).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(period, min_periods=period).mean()

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        result = 100 - (100 / (1 + rs))
        result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
        result = result.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
        result = result.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        return result.fillna(50)

    @staticmethod
    def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        macd_line = Indicators.ema(close, fast) - Indicators.ema(close, slow)
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line, macd_line - signal_line

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat(
            [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    @staticmethod
    def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0):
        mid = close.rolling(period, min_periods=period).mean()
        std = close.rolling(period, min_periods=period).std()
        return mid + mult * std, mid, mid - mult * std

    @staticmethod
    def stochastic_rsi(close: pd.Series, rsi_period: int = 14,
                       stoch_period: int = 14, k: int = 3, d: int = 3):
        rsi = Indicators.rsi(close, rsi_period)
        lowest = rsi.rolling(stoch_period, min_periods=stoch_period).min()
        highest = rsi.rolling(stoch_period, min_periods=stoch_period).max()
        raw = (((rsi - lowest) / (highest - lowest).replace(0, np.nan)) * 100).fillna(50)
        k_line = raw.rolling(k, min_periods=1).mean()
        return k_line, k_line.rolling(d, min_periods=1).mean()

    @staticmethod
    def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        hh = high.rolling(period, min_periods=period).max()
        ll = low.rolling(period, min_periods=period).min()
        return (((hh - close) / (hh - ll).replace(0, np.nan)) * -100).fillna(-50)

    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
        up = high.diff()
        dn = -low.diff()
        plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=high.index)
        prev_close = close.shift(1)
        tr_raw = pd.concat(
            [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        tr = tr_raw.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr.replace(0, np.nan)
        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
        adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        return adx.fillna(0), plus_di.fillna(0), minus_di.fillna(0)

    @staticmethod
    def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
        tp = (high + low + close) / 3
        sma_tp = tp.rolling(period, min_periods=period).mean()
        mad = (tp - sma_tp).abs().rolling(period, min_periods=period).mean()
        return ((tp - sma_tp) / (0.015 * mad.replace(0, np.nan))).fillna(0)

    @staticmethod
    def mfi(high: pd.Series, low: pd.Series, close: pd.Series,
            volume: pd.Series, period: int = 14) -> pd.Series:
        tp = (high + low + close) / 3
        mf = tp * volume
        prev_tp = tp.shift(1)
        pos_mf = pd.Series(np.where(tp > prev_tp, mf, 0.0), index=tp.index)
        neg_mf = pd.Series(np.where(tp < prev_tp, mf, 0.0), index=tp.index)
        positive = pos_mf.rolling(period, min_periods=period).sum()
        negative = neg_mf.rolling(period, min_periods=period).sum()
        mfr = positive / negative.replace(0, np.nan)
        result = 100 - (100 / (1 + mfr))
        result = result.mask((negative == 0) & (positive > 0), 100.0)
        result = result.mask((positive == 0) & (negative > 0), 0.0)
        result = result.mask((positive == 0) & (negative == 0), 50.0)
        return result.fillna(50)

    @staticmethod
    def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        direction = np.sign(close.diff()).fillna(0)
        return (direction * volume).cumsum()

    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        tp = (high + low + close) / 3
        cum_vol = volume.cumsum().replace(0, np.nan)
        return ((tp * volume).cumsum() / cum_vol).ffill()

    @staticmethod
    def donchian(high: pd.Series, low: pd.Series, period: int = 20):
        return (high.rolling(period, min_periods=period).max(),
                low.rolling(period, min_periods=period).min())

    @staticmethod
    def supertrend(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 10,
        multiplier: float = 3.0,
    ):
        """ATR Supertrend; +1 yükseliş, -1 düşüş yönünü döndürür.

        Hesap yalnızca mevcut ve önceki mumları kullanır. İlk ısınma mumlarında
        ATR sıfır kabul edilir; gelecek değerlerle doldurma (bfill) yapılmaz.
        """
        atr = Indicators.atr(high, low, close, period).fillna(0.0)
        hl2 = (high + low) / 2.0
        basic_upper = (hl2 + multiplier * atr).to_numpy(dtype=float)
        basic_lower = (hl2 - multiplier * atr).to_numpy(dtype=float)
        closes = close.to_numpy(dtype=float)
        n = len(close)
        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        directions = np.ones(n, dtype=int)
        lines = np.full(n, np.nan)
        for i in range(n):
            if i == 0:
                final_upper[i] = basic_upper[i]
                final_lower[i] = basic_lower[i]
                directions[i] = 1
            else:
                final_upper[i] = (
                    basic_upper[i]
                    if basic_upper[i] < final_upper[i - 1] or closes[i - 1] > final_upper[i - 1]
                    else final_upper[i - 1]
                )
                final_lower[i] = (
                    basic_lower[i]
                    if basic_lower[i] > final_lower[i - 1] or closes[i - 1] < final_lower[i - 1]
                    else final_lower[i - 1]
                )
                if directions[i - 1] == 1:
                    directions[i] = -1 if closes[i] < final_lower[i] else 1
                else:
                    directions[i] = 1 if closes[i] > final_upper[i] else -1
            lines[i] = final_lower[i] if directions[i] == 1 else final_upper[i]
        return (
            pd.Series(lines, index=close.index),
            pd.Series(directions, index=close.index),
        )

    @staticmethod
    def keltner(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 20,
        atr_period: int = 10,
        multiplier: float = 2.0,
    ):
        mid = Indicators.ema(close, period)
        atr = Indicators.atr(high, low, close, atr_period)
        return mid + multiplier * atr, mid, mid - multiplier * atr

    @staticmethod
    def session_vwap(df: pd.DataFrame, session: str = "D") -> pd.Series:
        """UTC günlük/haftalık VWAP; zaman damgası yoksa kümülatif VWAP."""
        high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
        fallback = Indicators.vwap(high, low, close, volume)
        stamp = df.get("ts", df.get("timestamp"))
        if stamp is None or len(df) == 0:
            return fallback
        try:
            if pd.api.types.is_numeric_dtype(stamp):
                numeric = pd.to_numeric(stamp, errors="coerce")
                finite = numeric[np.isfinite(numeric)]
                if finite.empty:
                    return fallback
                unit = "ms" if float(finite.median()) > 100_000_000_000 else "s"
                times = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
            else:
                times = pd.to_datetime(stamp, utc=True, errors="coerce")
            time_series = pd.Series(times, index=df.index)
            if str(session).upper() in {"W", "WEEK", "WEEKLY"}:
                utc_days = time_series.dt.floor("D")
                sessions = utc_days - pd.to_timedelta(utc_days.dt.day_of_week, unit="D")
            else:
                sessions = time_series.dt.floor("D")
            if sessions.isna().all():
                return fallback
            typical = (high + low + close) / 3.0
            pv = (typical * volume).groupby(sessions).cumsum()
            vol = volume.groupby(sessions).cumsum().replace(0, np.nan)
            return (pv / vol).where(sessions.notna()).fillna(fallback)
        except (TypeError, ValueError, OverflowError):
            return fallback

    @staticmethod
    def anchored_vwap(df: pd.DataFrame, anchor_pos: int) -> pd.Series:
        """Belirli bir mum konumundan itibaren VWAP; anchor gelecekten seçilemez."""
        high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
        anchor = max(0, min(int(anchor_pos), len(df) - 1))
        typical = (high + low + close) / 3.0
        pv = (typical * volume).iloc[anchor:].cumsum()
        vol = volume.iloc[anchor:].cumsum().replace(0, np.nan)
        return pv / vol

    @staticmethod
    def volume_profile(
        df: pd.DataFrame,
        lookback: int = 100,
        bins: int = 24,
        value_area_pct: float = 0.70,
    ) -> dict:
        """Mum tipik fiyatlarından yaklaşık POC/VAH/VAL üretir.

        Bu, borsanın tick-seviyeli hacim profili değildir; yalnızca mevcut OHLCV
        ile hesaplanabilen, look-ahead içermeyen bir yaklaşıklıktır.
        """
        sample = df.tail(max(2, int(lookback)))
        low = sample["low"].to_numpy(dtype=float)
        high = sample["high"].to_numpy(dtype=float)
        close = sample["close"].to_numpy(dtype=float)
        volume = np.maximum(sample["volume"].to_numpy(dtype=float), 0.0)
        typical = (low + high + close) / 3.0
        lo, hi = float(np.min(low)), float(np.max(high))
        if not np.isfinite(lo + hi) or hi <= lo or volume.sum() <= 0:
            price = float(close[-1])
            return {"poc": price, "vah": price, "val": price}
        bin_count = max(4, int(bins))
        edges = np.linspace(lo, hi, bin_count + 1)
        indices = np.clip(np.digitize(typical, edges) - 1, 0, bin_count - 1)
        volumes = np.bincount(indices, weights=volume, minlength=bin_count)
        poc_idx = int(np.argmax(volumes))
        selected = {poc_idx}
        covered = float(volumes[poc_idx])
        target = float(volume.sum() * value_area_pct)
        left = right = poc_idx
        while covered < target and (left > 0 or right < bin_count - 1):
            left_vol = volumes[left - 1] if left > 0 else -1.0
            right_vol = volumes[right + 1] if right < bin_count - 1 else -1.0
            if right_vol > left_vol:
                right += 1
                selected.add(right)
                covered += float(volumes[right])
            else:
                left -= 1
                selected.add(left)
                covered += float(volumes[left])
        return {
            "poc": float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0),
            "vah": float(edges[max(selected) + 1]),
            "val": float(edges[min(selected)]),
        }


def _last(series: pd.Series, default: float = 0.0) -> float:
    try:
        v = series.iloc[-1]
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return default
        return float(v)
    except Exception:
        return default


def indicator_score(
    df: pd.DataFrame,
    funding_rate: float | None = None,
    regime_aware: bool = True,
    volume_z_threshold: float = 1.5,
) -> dict:
    """Rejim bazlı teknik skor: -100 (güçlü SAT) .. +100 (güçlü AL).

    ``regime_aware=False`` önceki toplam skoru korur; böylece eski/yeni model
    aynı walk-forward verisinde adil biçimde karşılaştırılabilir. Yeni modda
    trend ve mean-reversion osilatörleri aynı rejimde birbirini nötrleştirmez.
    """
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    price = float(close.iloc[-1])
    comps: dict[str, float] = {}
    total = 0.0

    # --- EMA trend (ağırlıklı) ---
    e9 = _last(Indicators.ema(close, 9), price)
    e21 = _last(Indicators.ema(close, 21), price)
    e50 = _last(Indicators.ema(close, 50), price)
    e200 = _last(Indicators.ema(close, 200), 0.0)
    ma20 = _last(Indicators.sma(close, 20), 0.0)
    ma50 = _last(Indicators.sma(close, 50), 0.0)
    ema9_s, ema21_s = Indicators.ema(close, 9), Indicators.ema(close, 21)
    t = 0.0
    if price > e9 > e21:
        t += 8
    elif price < e9 < e21:
        t -= 8
    t += 4 if price > e50 else -4
    if len(close) > 1:
        if ema9_s.iloc[-2] <= ema21_s.iloc[-2] and e9 > e21:
            t += 5
        elif ema9_s.iloc[-2] >= ema21_s.iloc[-2] and e9 < e21:
            t -= 5
    comps["ema_trend"] = t
    total += t * 1.2

    ma_score = 0.0
    if ma20 > 0 and ma50 > 0:
        ma_score += 4 if ma20 > ma50 else -4
    if e200 > 0:
        ma_score += 4 if price > e200 else -4
    comps["ma_trend"] = ma_score
    total += ma_score

    # Mean-reversion bileşenleri yalnızca RANGE rejiminde ana skora girer.
    rsi = _last(Indicators.rsi(close, 14), 50)
    r = 10 if rsi < 25 else (5 if rsi < 35 else (-10 if rsi > 75 else (-5 if rsi > 65 else (2 if rsi > 55 else (-2 if rsi < 45 else 0)))))
    comps["rsi"] = r
    total += r

    macd_line, macd_signal, macd_h = Indicators.macd(close)
    macd_value = _last(macd_line, 0.0)
    macd_signal_value = _last(macd_signal, 0.0)
    mh = _last(macd_h, 0.0)
    m = 0.0
    if len(macd_h) > 1:
        prev_h = float(macd_h.iloc[-2])
        m += 4 if mh > 0 else -4
        if prev_h <= 0 < mh:
            m += 6
        elif prev_h >= 0 > mh:
            m -= 6
    comps["macd"] = m
    total += m

    u, mid, lower_band = Indicators.bollinger(close)
    uu, mm, ll = _last(u, price), _last(mid, price), _last(lower_band, price)
    b = 6 if price <= ll else (-6 if price >= uu else (2 if price > mm else -2))
    comps["bollinger"] = b
    total += b

    k, d = Indicators.stochastic_rsi(close)
    kk, dd = _last(k, 50), _last(d, 50)
    s = 6 if (kk < 20 and dd < 20) else (-6 if (kk > 80 and dd > 80) else (2 if kk > dd else -2))
    comps["stoch_rsi"] = s
    total += s

    wr = _last(Indicators.williams_r(high, low, close), -50)
    w = 5 if wr < -80 else (-5 if wr > -20 else 0)
    comps["williams_r"] = w
    total += w

    adx_v, pdi, mdi = Indicators.adx(high, low, close)
    adx_last = _last(adx_v, 0)
    a = 0.0
    if adx_last >= 20:
        a = 4 if _last(pdi, 0) > _last(mdi, 0) else -4
    comps["adx"] = a
    total += a

    cci_v = _last(Indicators.cci(high, low, close), 0.0)
    c = 6 if cci_v < -100 else (-6 if cci_v > 100 else (2 if cci_v > 0 else -2))
    comps["cci"] = c
    total += c

    mfi_v = _last(Indicators.mfi(high, low, close, vol), 50)
    mf = 6 if mfi_v < 20 else (-6 if mfi_v > 80 else (2 if mfi_v > 55 else (-2 if mfi_v < 45 else 0)))
    comps["mfi"] = mf
    total += mf

    obv = Indicators.obv(close, vol)
    slope = float(obv.iloc[-1] - obv.iloc[-6]) if len(obv) > 6 else 0.0
    o = 4 if slope > 0 else (-4 if slope < 0 else 0.0)
    comps["obv"] = o
    total += o

    # Eski kümülatif VWAP yalnızca legacy skor için saklanır.
    cumulative_vwap = _last(Indicators.vwap(high, low, close, vol), price)
    v = 4 if price > cumulative_vwap else -4
    comps["vwap"] = v
    total += v

    dh, dl = Indicators.donchian(high, low)
    prev_h = float(dh.iloc[-2]) if len(dh) > 1 and np.isfinite(dh.iloc[-2]) else price
    prev_l = float(dl.iloc[-2]) if len(dl) > 1 and np.isfinite(dl.iloc[-2]) else price
    breakout_long = price > prev_h
    breakout_short = price < prev_l
    breakout_dir = 1 if breakout_long else (-1 if breakout_short else 0)
    dc = 5 if breakout_long else (-5 if breakout_short else 0)
    comps["donchian"] = dc
    total += dc

    fp = 0.0
    if funding_rate is not None:
        f = float(funding_rate)
        fp = -6 if f > 0.001 else (6 if f < -0.001 else 0)
        comps["funding"] = fp
        total += fp

    # --- Yeni, birbirinden bağımsız rejim/onay bileşenleri ---
    st_line, st_direction = Indicators.supertrend(high, low, close)
    st_value = _last(st_line, price)
    st_dir = 1 if _last(st_direction, 1) >= 0 else -1
    st_score = st_dir * 8.0
    comps["supertrend"] = st_score

    session_vwap_s = Indicators.session_vwap(df)
    session_vwap = _last(session_vwap_s, cumulative_vwap)
    weekly_vwap = _last(Indicators.session_vwap(df, session="W"), cumulative_vwap)
    session_v = 4.0 if price > session_vwap else -4.0
    comps["session_vwap"] = session_v

    trend_dir = 0
    if price > e50 and e9 > e21 and st_dir > 0:
        trend_dir = 1
    elif price < e50 and e9 < e21 and st_dir < 0:
        trend_dir = -1

    recent = df.tail(min(100, len(df)))
    if trend_dir < 0:
        anchor_local = int(np.argmax(recent["high"].to_numpy(dtype=float)))
    else:
        anchor_local = int(np.argmin(recent["low"].to_numpy(dtype=float)))
    anchor_pos = len(df) - len(recent) + anchor_local
    anchored_vwap_s = Indicators.anchored_vwap(df, anchor_pos)
    anchored_vwap = _last(anchored_vwap_s, session_vwap)
    avwap_score = 4.0 if price > anchored_vwap else -4.0
    comps["anchored_vwap"] = avwap_score

    profile = Indicators.volume_profile(df)
    poc, vah, val = profile["poc"], profile["vah"], profile["val"]
    if price > vah:
        vp_trend = 3.0
    elif price < val:
        vp_trend = -3.0
    else:
        vp_trend = 1.0 if price > poc else (-1.0 if price < poc else 0.0)
    vp_range = -vp_trend if val <= price <= vah else 0.0
    comps["volume_profile"] = vp_trend

    prior_volume = vol.iloc[:-1].tail(50)
    volume_z = 0.0
    if len(prior_volume) >= 10:
        vol_mean = float(prior_volume.mean())
        vol_std = float(prior_volume.std(ddof=0))
        current_volume = float(vol.iloc[-1])
        if vol_std > 1e-12:
            volume_z = (current_volume - vol_mean) / vol_std
        elif current_volume != vol_mean:
            volume_z = 20.0 if current_volume > vol_mean else -20.0
    volume_z = float(np.clip(volume_z, -20.0, 20.0))
    volume_confirmed = volume_z >= float(volume_z_threshold)
    breakout_score = breakout_dir * (6.0 if volume_confirmed else 0.0)
    comps["confirmed_breakout"] = breakout_score

    ku, _, kl = Indicators.keltner(high, low, close)
    ku_last, kl_last = _last(ku, uu), _last(kl, ll)
    squeeze_on = bool(uu < ku_last and ll > kl_last)
    previous_squeeze = False
    if len(df) > 1:
        pu = float(u.iloc[-2]) if np.isfinite(u.iloc[-2]) else uu
        pl = float(lower_band.iloc[-2]) if np.isfinite(lower_band.iloc[-2]) else ll
        pku = float(ku.iloc[-2]) if np.isfinite(ku.iloc[-2]) else ku_last
        pkl = float(kl.iloc[-2]) if np.isfinite(kl.iloc[-2]) else kl_last
        previous_squeeze = bool(pu < pku and pl > pkl)
    squeeze_release = bool(previous_squeeze and not squeeze_on)
    bb_width = (uu - ll) / mm * 100.0 if mm else 0.0
    atr14 = _last(Indicators.atr(high, low, close, 14), 0.0)
    atr_pct = atr14 / price * 100.0 if price > 0 else 0.0

    if squeeze_on:
        regime = "SIKISMA"
    elif breakout_dir:
        regime = "BREAKOUT"
    elif adx_last >= 20 and trend_dir:
        regime = "TREND"
    else:
        regime = "RANGE"

    # Legacy ``total`` buraya kadar eski formülle aynıdır.
    legacy_score = float(np.clip(total, -100, 100))
    trend_components = {
        "ema_trend": t * 1.2,
        "ma_trend": ma_score,
        "macd": m,
        "adx": a,
        "obv": o,
        "session_vwap": session_v,
        "supertrend": st_score,
        "anchored_vwap": avwap_score,
        "volume_profile": vp_trend,
        "confirmed_breakout": breakout_score,
        "funding": fp,
    }
    range_components = {
        "rsi": r,
        "bollinger": b,
        "stoch_rsi": s,
        "williams_r": w,
        "cci": c,
        "mfi": mf,
        "session_vwap": -session_v,
        "volume_profile": vp_range,
    }
    legacy_components = {
        "ema_trend": t * 1.2,
        "ma_trend": ma_score,
        "rsi": r,
        "macd": m,
        "bollinger": b,
        "stoch_rsi": s,
        "williams_r": w,
        "adx": a,
        "cci": c,
        "mfi": mf,
        "obv": o,
        "vwap": v,
        "donchian": dc,
        "funding": fp,
    }
    if not regime_aware:
        active_components = legacy_components
        entry_allowed = True
        block_reason = ""
    elif regime == "RANGE":
        active_components = range_components
        entry_allowed = True
        block_reason = ""
    else:
        multiplier = 0.35 if regime == "SIKISMA" else 1.0
        active_components = {
            name: value * multiplier for name, value in trend_components.items()
        }
        entry_allowed = not squeeze_on and (not breakout_dir or volume_confirmed)
        block_reason = (
            "BB/KC sıkışması: kırılım ve hacim onayı bekleniyor"
            if squeeze_on
            else "Hacimsiz kırılım: işlem açılmaz"
            if breakout_dir and not volume_confirmed
            else ""
        )

    # Yalnız bu bileşenler mevcut rejimde teknik skora fiilen katkı verir.
    # Leave-one-out giriş analizi aynı katkıları teker teker çıkararak sinyali
    # yeniden hesaplar; tanısal ``components`` içindeki pasif değerleri kullanmaz.
    active_score_unclipped = float(sum(active_components.values()))
    score = float(np.clip(active_score_unclipped, -100, 100))

    setup = (
        "BREAKOUT" if breakout_dir else
        "SIKISMA" if regime == "SIKISMA" else
        "PULLBACK" if regime == "TREND" else
        "RANGE"
    )
    return {
        "score": score,
        "legacy_score": legacy_score,
        "bias": "LONG" if score >= 25 else ("SHORT" if score <= -25 else "NOTR"),
        "regime": regime,
        "setup": setup,
        "entry_allowed": bool(entry_allowed),
        "entry_block_reason": block_reason,
        "components": comps,
        "active_components": {
            name: float(value) for name, value in active_components.items()
        },
        "active_score_unclipped": active_score_unclipped,
        "snapshot": {
            "price": price,
            "score": score,
            "active_components": {
                name: float(value) for name, value in active_components.items()
            },
            "active_score_unclipped": active_score_unclipped,
            "ma20": ma20,
            "ma50": ma50,
            "ema9": e9,
            "ema21": e21,
            "ema50": e50,
            "ema200": e200,
            "rsi": rsi,
            "adx": adx_last,
            "macd": macd_value,
            "macd_signal": macd_signal_value,
            "macd_hist": mh,
            "mfi": mfi_v,
            "cci": cci_v,
            "vwap": session_vwap,
            "session_vwap": session_vwap,
            "weekly_vwap": weekly_vwap,
            "cumulative_vwap": cumulative_vwap,
            "anchored_vwap": anchored_vwap,
            "anchored_vwap_pos": anchor_pos,
            "williams_r": wr,
            "supertrend": st_value,
            "supertrend_direction": st_dir,
            "volume_profile_poc": poc,
            "volume_profile_vah": vah,
            "volume_profile_val": val,
            "bollinger_bandwidth_pct": bb_width,
            "bb_width_pct": bb_width,
            "atr": atr14,
            "atr_pct": atr_pct,
            "bb_kc_squeeze": squeeze_on,
            "squeeze_release": squeeze_release,
            "breakout_long": breakout_long,
            "breakout_short": breakout_short,
            "volume_zscore": volume_z,
            "volume_z_threshold": float(volume_z_threshold),
            "regime": regime,
            "setup": setup,
            "regime_aware": bool(regime_aware),
            "entry_allowed": bool(entry_allowed),
            "entry_block_reason": block_reason,
        },
    }

def compute_htf_trend(df: pd.DataFrame, timeframe: str = "1h") -> dict:
    """Büyük zaman dilimi (`1h` veya `4h`) ana trend yönünü ve gücünü hesaplar.

    Kullanılan bileşenler:
      • EMA 20 / EMA 50 / EMA 200 dizilimi ve fiyat konumu
      • EMA 20 ve EMA 50 eğimi (slope)
      • MACD histogram yönü
      • ADX (+DI / -DI) trend şiddeti
      • RSI (50 üstü boğa, 50 altı ayı rejimi)
    """
    if df is None or len(df) < 10:
        return {
            "timeframe": timeframe,
            "trend": "NEUTRAL",
            "score": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "ema200": 0.0,
            "rsi": 50.0,
            "adx": 0.0,
        }

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    price = float(close.iloc[-1])

    e20_s = Indicators.ema(close, min(20, max(5, len(close) // 3)))
    e50_s = Indicators.ema(close, min(50, max(10, len(close) // 2)))
    e200_s = Indicators.ema(close, min(200, len(close)))

    e20 = _last(e20_s, price)
    e50 = _last(e50_s, price)
    e200 = _last(e200_s, price)
    rsi_v = _last(Indicators.rsi(close, 14), 50.0)
    _, _, macd_h = Indicators.macd(close)
    mh = _last(macd_h, 0.0)
    adx_s, pdi_s, mdi_s = Indicators.adx(high, low, close)
    adx_v = _last(adx_s, 0.0)
    pdi_v = _last(pdi_s, 0.0)
    mdi_v = _last(mdi_s, 0.0)

    score = 0.0
    # 1) Fiyat ve EMA hiyerarşisi (-40 .. +40)
    if price > e20 > e50:
        score += 30.0
    elif price < e20 < e50:
        score -= 30.0
    else:
        score += 12.0 if price > e50 else -12.0

    if price > e200:
        score += 10.0
    elif price < e200:
        score -= 10.0

    # 2) EMA20 eğimi (-15 .. +15)
    lookback = min(5, len(e20_s) - 1)
    if lookback >= 1:
        prev_e20 = float(e20_s.iloc[-1 - lookback])
        if prev_e20 > 0:
            slope_pct = (e20 - prev_e20) / prev_e20 * 100.0
            if slope_pct > 0.15:
                score += 15.0
            elif slope_pct < -0.15:
                score -= 15.0

    # 3) MACD Histogram (-15 .. +15)
    score += 15.0 if mh > 0 else (-15.0 if mh < 0 else 0.0)

    # 4) ADX + DI yönü (-15 .. +15)
    if adx_v >= 18:
        score += 15.0 if pdi_v > mdi_v else -15.0

    # 5) RSI rejim filtresi (-15 .. +15)
    if rsi_v >= 55:
        score += 15.0
    elif rsi_v <= 45:
        score -= 15.0

    score = float(np.clip(round(score, 1), -100.0, 100.0))
    if score >= 15.0:
        trend = "UP"
    elif score <= -15.0:
        trend = "DOWN"
    else:
        trend = "NEUTRAL"

    return {
        "timeframe": timeframe,
        "trend": trend,
        "score": score,
        "ema20": round(e20, 4),
        "ema50": round(e50, 4),
        "ema200": round(e200, 4),
        "rsi": round(rsi_v, 1),
        "adx": round(adx_v, 1),
    }


def multi_timeframe_filter(
    df_1h: pd.DataFrame | None = None,
    df_4h: pd.DataFrame | None = None,
    bearish_block_th: float = -15.0,
    bullish_block_th: float = 15.0,
) -> dict:
    """Çoklu Zaman Dilimi (Multi-Timeframe — `1h` ve `4h`) Trend Filtresi.

    Ana trend (`1h` / `4h`) aşağı yönlüyken (`BEARISH`) botun `1m` veya `5m`
    grafikteki küçük tepkilere aldanıp `LONG` açmasını engeller (`allow_long=False`).
    Ana trend yukarı yönlüyken (`BULLISH`) ise ters `SHORT` açmasını engeller (`allow_short=False`).
    """
    t1 = compute_htf_trend(df_1h, "1h") if df_1h is not None else None
    t4 = compute_htf_trend(df_4h, "4h") if df_4h is not None else None

    if t1 and t4:
        combined_score = round(t1["score"] * 0.45 + t4["score"] * 0.55, 1)
    elif t4:
        combined_score = t4["score"]
    elif t1:
        combined_score = t1["score"]
    else:
        combined_score = 0.0

    if combined_score <= bearish_block_th:
        macro_trend = "BEARISH"
        allow_long = False
        allow_short = True
        reason = (
            f"1h/4h Ana Trend DÜŞÜŞ ({combined_score:+.1f}) → "
            f"Küçük tepkilerde LONG engellendi"
        )
    elif combined_score >= bullish_block_th:
        macro_trend = "BULLISH"
        allow_long = True
        allow_short = False
        reason = (
            f"1h/4h Ana Trend YÜKSELİŞ ({combined_score:+.1f}) → "
            f"Ters yönlü SHORT engellendi"
        )
    else:
        macro_trend = "NEUTRAL"
        allow_long = True
        allow_short = True
        reason = f"1h/4h Ana Trend NÖTR ({combined_score:+.1f}) → Çift yön serbest"

    return {
        "trend": macro_trend,
        "score": combined_score,
        "allow_long": allow_long,
        "allow_short": allow_short,
        "tf_1h": t1 or {"timeframe": "1h", "trend": "NEUTRAL", "score": 0.0},
        "tf_4h": t4 or {"timeframe": "4h", "trend": "NEUTRAL", "score": 0.0},
        "reason": reason,
    }
