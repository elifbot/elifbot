"""Gerçek teknik indikatörler — saf pandas/numpy ile hesaplanır (TA-Lib gerekmez).

İndikatör seti:
  Trend      : EMA 9/21/50, MACD, ADX (+DI/-DI), Donchian
  Momentum   : RSI, Stokastik RSI, CCI, Williams %R
  Hacim/Akış : MFI (Money Flow Index), OBV, VWAP
  Volatilite : ATR, Bollinger Bantları
  Türev      : Funding Rate (kalabalık karşıtı sinyal)
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
        return (100 - (100 / (1 + rs))).fillna(50)

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
        mfr = (pos_mf.rolling(period, min_periods=period).sum()
               / neg_mf.rolling(period, min_periods=period).sum().replace(0, np.nan))
        return (100 - (100 / (1 + mfr))).fillna(50)

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


def _last(series: pd.Series, default: float = 0.0) -> float:
    try:
        v = series.iloc[-1]
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return default
        return float(v)
    except Exception:
        return default


def indicator_score(df: pd.DataFrame, funding_rate: float | None = None) -> dict:
    """Tüm indikatörleri tek skorda birleştirir: -100 (güçlü SAT) .. +100 (güçlü AL)."""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    price = float(close.iloc[-1])
    comps: dict[str, float] = {}
    total = 0.0

    # --- EMA trend (ağırlıklı) ---
    e9 = _last(Indicators.ema(close, 9), price)
    e21 = _last(Indicators.ema(close, 21), price)
    e50 = _last(Indicators.ema(close, 50), price)
    ema9_s, ema21_s = Indicators.ema(close, 9), Indicators.ema(close, 21)
    t = 0.0
    if price > e9 > e21:
        t += 8
    elif price < e9 < e21:
        t -= 8
    t += 4 if price > e50 else -4
    try:
        if len(close) > 1:
            if ema9_s.iloc[-2] <= ema21_s.iloc[-2] and e9 > e21:
                t += 5  # golden cross
            elif ema9_s.iloc[-2] >= ema21_s.iloc[-2] and e9 < e21:
                t -= 5  # death cross
    except Exception:
        pass
    comps["ema_trend"] = t
    total += t * 1.2

    # --- RSI ---
    rsi = _last(Indicators.rsi(close, 14), 50)
    r = 10 if rsi < 25 else (5 if rsi < 35 else (-10 if rsi > 75 else (-5 if rsi > 65 else (2 if rsi > 55 else (-2 if rsi < 45 else 0)))))
    comps["rsi"] = r
    total += r

    # --- MACD ---
    _, _, macd_h = Indicators.macd(close)
    mh = _last(macd_h, 0.0)
    m = 0.0
    try:
        prev_h = float(macd_h.iloc[-2]) if len(macd_h) > 1 else 0.0
        m += 4 if mh > 0 else -4
        if prev_h <= 0 < mh:
            m += 6
        elif prev_h >= 0 > mh:
            m -= 6
    except Exception:
        pass
    comps["macd"] = m
    total += m

    # --- Bollinger ---
    u, mid, l = Indicators.bollinger(close)
    uu, mm, ll = _last(u, price), _last(mid, price), _last(l, price)
    b = 6 if price <= ll else (-6 if price >= uu else (2 if price > mm else -2))
    comps["bollinger"] = b
    total += b

    # --- Stokastik RSI ---
    k, d = Indicators.stochastic_rsi(close)
    kk, dd = _last(k, 50), _last(d, 50)
    s = 6 if (kk < 20 and dd < 20) else (-6 if (kk > 80 and dd > 80) else (2 if kk > dd else -2))
    comps["stoch_rsi"] = s
    total += s

    # --- Williams %R ---
    wr = _last(Indicators.williams_r(high, low, close), -50)
    w = 5 if wr < -80 else (-5 if wr > -20 else 0)
    comps["williams_r"] = w
    total += w

    # --- ADX trend gücü ---
    adx_v, pdi, mdi = Indicators.adx(high, low, close)
    adx_last = _last(adx_v, 0)
    a = 0.0
    if adx_last >= 20:
        a = 4 if _last(pdi, 0) > _last(mdi, 0) else -4
    comps["adx"] = a
    total += a

    # --- CCI ---
    cci_v = _last(Indicators.cci(high, low, close), 0)
    c = 6 if cci_v < -100 else (-6 if cci_v > 100 else (2 if cci_v > 0 else -2))
    comps["cci"] = c
    total += c

    # --- MFI (para akışı endeksi) ---
    mfi_v = _last(Indicators.mfi(high, low, close, vol), 50)
    mf = 6 if mfi_v < 20 else (-6 if mfi_v > 80 else (2 if mfi_v > 55 else (-2 if mfi_v < 45 else 0)))
    comps["mfi"] = mf
    total += mf

    # --- OBV eğimi ---
    obv = Indicators.obv(close, vol)
    try:
        slope = float(obv.iloc[-1] - obv.iloc[-6]) if len(obv) > 6 else 0.0
    except Exception:
        slope = 0.0
    o = 4 if slope > 0 else (-4 if slope < 0 else 0)
    comps["obv"] = o
    total += o

    # --- VWAP konumu ---
    vwap_v = _last(Indicators.vwap(high, low, close, vol), price)
    v = 4 if price > vwap_v else -4
    comps["vwap"] = v
    total += v

    # --- Donchian kırılımı ---
    dh, dl = Indicators.donchian(high, low)
    try:
        prev_h = float(dh.iloc[-2]) if len(dh) > 1 else price
        prev_l = float(dl.iloc[-2]) if len(dl) > 1 else price
        dc = 5 if price > prev_h else (-5 if price < prev_l else 0)
    except Exception:
        dc = 0
    comps["donchian"] = dc
    total += dc

    # --- Funding rate (kalabalık karşıtı) ---
    if funding_rate is not None:
        f = float(funding_rate)
        fp = -6 if f > 0.001 else (6 if f < -0.001 else 0)
        comps["funding"] = fp
        total += fp

    score = float(np.clip(total, -100, 100))
    return {
        "score": score,
        "bias": "LONG" if score >= 25 else ("SHORT" if score <= -25 else "NOTR"),
        "components": comps,
        "snapshot": {"price": price, "rsi": rsi, "adx": adx_last, "macd_hist": mh,
                     "mfi": mfi_v, "cci": cci_v, "vwap": vwap_v, "williams_r": wr},
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
