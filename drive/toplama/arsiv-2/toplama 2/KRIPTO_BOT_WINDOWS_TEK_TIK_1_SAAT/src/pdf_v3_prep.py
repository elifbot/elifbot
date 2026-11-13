"""PDF v3 Hazırlık Paketi — Üç PDF'te yer alıp botta henüz bulunmayan teknik,
istatistiksel rejim, mikro-yapı, takvim ve risk-analitiği modülleri.

ÖNEMLİ:
  • Bu modül şu an çalışan 1 saatlik paper oturumunun baseline kurallarına
    DOKUNMAZ; tamamen izole ve tak-çalıştır (plug-ready) olarak hazırlanmıştır.
  • Tüm OHLCV hesapları yalnızca kapanmış mumları kullanır (lookahead yok).
  • Çıktılar JSON-güvenlidir (NaN / Inf üretmez).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .indicators import Indicators


def _finite(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _last(series: pd.Series, default: float = 0.0) -> float:
    if series is None or len(series) == 0:
        return float(default)
    return _finite(series.iloc[-1], default)


# ---------------------------------------------------------------------------
# 1. Eksik Jesse & Freqtrade Hareketli Ortalamaları (RMA, T3, FRAMA, VIDYA, JMA, EMA Ribbon)
# ---------------------------------------------------------------------------
def rma(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Moving Average (RMA / SMMA): alpha = 1 / period."""
    p = max(1, int(period))
    return series.astype(float).ewm(alpha=1.0 / p, adjust=False).mean()


def t3(series: pd.Series, period: int = 10, vfactor: float = 0.7) -> pd.Series:
    """Tillson T3 Moving Average (6 katmanlı EMA genelleştirmesi)."""
    p = max(1, int(period))
    vf = max(0.0, min(1.0, float(vfactor)))
    e1 = Indicators.ema(series, p)
    e2 = Indicators.ema(e1, p)
    e3 = Indicators.ema(e2, p)
    e4 = Indicators.ema(e3, p)
    e5 = Indicators.ema(e4, p)
    e6 = Indicators.ema(e5, p)
    c1 = -(vf ** 3)
    c2 = 3.0 * (vf ** 2) + 3.0 * (vf ** 3)
    c3 = -6.0 * (vf ** 2) - 3.0 * vf - 3.0 * (vf ** 3)
    c4 = 1.0 + 3.0 * vf + (vf ** 3) + 3.0 * (vf ** 2)
    return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


def frama(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 16,
) -> pd.Series:
    """Ehlers Fractal Adaptive Moving Average (FRAMA)."""
    n = max(4, int(period))
    if n % 2 == 1:
        n += 1
    half = n // 2
    h = high.astype(float).to_numpy()
    lw = low.astype(float).to_numpy()
    c = close.astype(float).to_numpy()
    out = np.full(len(c), np.nan, dtype=float)
    if len(c) == 0:
        return pd.Series(out, index=close.index)

    out[0] = c[0]
    for i in range(1, len(c)):
        if i < n:
            out[i] = out[i - 1] * 0.8 + c[i] * 0.2
            continue
        n1 = (np.max(h[i - n + 1 : i - half + 1]) - np.min(lw[i - n + 1 : i - half + 1])) / half
        n2 = (np.max(h[i - half + 1 : i + 1]) - np.min(lw[i - half + 1 : i + 1])) / half
        n3 = (np.max(h[i - n + 1 : i + 1]) - np.min(lw[i - n + 1 : i + 1])) / n
        if n1 > 0 and n2 > 0 and n3 > 0:
            dimen = (math.log(n1 + n2) - math.log(n3)) / math.log(2.0)
            dimen = max(1.0, min(2.0, dimen))
            alpha = math.exp(-4.6 * (dimen - 1.0))
            alpha = max(0.01, min(1.0, alpha))
        else:
            alpha = 0.01
        out[i] = alpha * c[i] + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=close.index)


def vidya(series: pd.Series, period: int = 14, cmo_period: int = 9) -> pd.Series:
    """Chande Variable Index Dynamic Average (VIDYA — CMO uyarlamalı)."""
    p = max(2, int(period))
    cp = max(2, int(cmo_period))
    vals = series.astype(float)
    diff = vals.diff()
    up = diff.clip(lower=0.0).rolling(cp, min_periods=cp).sum()
    dn = (-diff.clip(upper=0.0)).rolling(cp, min_periods=cp).sum()
    denom = (up + dn).replace(0.0, np.nan)
    cmo_abs = ((up - dn).abs() / denom).fillna(0.0).to_numpy()

    k = 2.0 / (p + 1.0)
    arr = vals.to_numpy()
    out = np.zeros(len(arr), dtype=float)
    if len(arr) == 0:
        return pd.Series(out, index=series.index)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        alpha = max(0.005, min(1.0, k * cmo_abs[i]))
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def jma_approx(series: pd.Series, period: int = 14, phase: float = 0.0) -> pd.Series:
    """Faz-kontrollü 2-kutuplu adaptif yumuşatma (Jurik-tipi düşük gecikmeli yaklaşım)."""
    p = max(2, int(period))
    ph = max(-100.0, min(100.0, float(phase)))
    phase_ratio = 0.5 if ph < -100 else (2.5 if ph > 100 else ph / 100.0 + 1.5)
    beta = 0.45 * (p - 1.0) / (0.45 * (p - 1.0) + 2.0)
    alpha_base = beta

    arr = series.astype(float).to_numpy()
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return pd.Series(out, index=series.index)

    e0 = arr[0]
    e1 = 0.0
    e2 = 0.0
    jma_prev = arr[0]
    out[0] = arr[0]
    vol_win: deque[float] = deque(maxlen=max(10, p * 2))

    for i in range(1, n):
        del_val = abs(arr[i] - e0)
        vol_win.append(del_val)
        avg_vol = sum(vol_win) / len(vol_win) if vol_win else 0.0
        rel_vol = min(10.0, del_val / avg_vol) if avg_vol > 1e-12 else 1.0
        kv = alpha_base ** (1.0 / max(0.5, min(3.0, rel_vol)))
        e0 = (1.0 - kv) * arr[i] + kv * e0
        e1 = (arr[i] - e0) * (1.0 - beta) + beta * e1
        e2 = (e0 + phase_ratio * e1 - jma_prev) * ((1.0 - kv) ** 2) + (kv ** 2) * e2
        jma_prev = jma_prev + e2
        out[i] = jma_prev
    return pd.Series(out, index=series.index)


def ema_ribbon_state(
    series: pd.Series,
    periods: tuple[int, ...] = (5, 8, 10, 13, 21, 34, 50, 100, 200),
) -> dict[str, Any]:
    """EMA Ribbon (Şerit) sıralama uyumu ve sıkışma/açılma durumu."""
    if len(series) < 5:
        return {
            "score": 0.0,
            "bull_stacked": False,
            "bear_stacked": False,
            "expansion_pct": 0.0,
        }
    emas = [_last(Indicators.ema(series, p)) for p in periods]
    pairs = len(emas) - 1
    ordered_up = sum(1 for i in range(pairs) if emas[i] > emas[i + 1])
    ordered_dn = sum(1 for i in range(pairs) if emas[i] < emas[i + 1])
    score = ((ordered_up - ordered_dn) / max(1, pairs)) * 100.0
    mid = abs(emas[len(emas) // 2]) or 1.0
    expansion_pct = (max(emas) - min(emas)) / mid * 100.0
    return {
        "score": round(_finite(score), 2),
        "bull_stacked": ordered_up == pairs,
        "bear_stacked": ordered_dn == pairs,
        "expansion_pct": round(_finite(expansion_pct), 4),
    }


# ---------------------------------------------------------------------------
# 2. Eksik Osilatörler (Klasik Hızlı/Yavaş Stochastic + EMA-Yumuşatılmış RSI/MFI/CCI)
# ---------------------------------------------------------------------------
def classic_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    smooth_k: int = 3,
    d_period: int = 3,
) -> dict[str, float]:
    """Freqtrade fastk / slowk / slowd klasik Stochastic osilatörü."""
    kp = max(2, int(k_period))
    sk = max(1, int(smooth_k))
    dp = max(1, int(d_period))
    lowest = low.astype(float).rolling(kp, min_periods=kp).min()
    highest = high.astype(float).rolling(kp, min_periods=kp).max()
    span = (highest - lowest).replace(0.0, np.nan)
    fast_k = ((close.astype(float) - lowest) / span * 100.0).fillna(50.0).clip(0.0, 100.0)
    slow_k = fast_k.rolling(sk, min_periods=1).mean()
    slow_d = slow_k.rolling(dp, min_periods=1).mean()
    fk = _last(fast_k, 50.0)
    sk_v = _last(slow_k, 50.0)
    sd_v = _last(slow_d, 50.0)
    return {
        "stoch_fast_k": round(fk, 2),
        "stoch_slow_k": round(sk_v, 2),
        "stoch_slow_d": round(sd_v, 2),
        "stoch_cross": 1 if sk_v > sd_v and fk < 80 else (-1 if sk_v < sd_v and fk > 20 else 0),
    }


def ema_smoothed_oscillators(df: pd.DataFrame, ema_span: int = 5) -> dict[str, float]:
    """Freqtrade topluluk stratejilerindeki EMA-yumuşatılmış RSI, MFI ve CCI."""
    span = max(2, int(ema_span))
    rsi_s = Indicators.ema(Indicators.rsi(df["close"], 14).fillna(50.0), span)
    mfi_s = Indicators.ema(
        Indicators.mfi(df["high"], df["low"], df["close"], df["volume"], 14).fillna(50.0),
        span,
    )
    cci_s = Indicators.ema(
        Indicators.cci(df["high"], df["low"], df["close"], 20).fillna(0.0),
        span,
    )
    rsi_slope = _last(rsi_s.diff(), 0.0)
    return {
        "rsi_ema": round(_last(rsi_s, 50.0), 2),
        "mfi_ema": round(_last(mfi_s, 50.0), 2),
        "cci_ema": round(_last(cci_s, 0.0), 2),
        "rsi_ema_slope": round(rsi_slope, 3),
    }


# ---------------------------------------------------------------------------
# 3. Eksik Stop & Çıkış Araştırma Modelleri (Elder SafeZone + Minimal ROI Table)
# ---------------------------------------------------------------------------
def elder_safezone_stop(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 15,
    coeff: float = 2.5,
) -> dict[str, float]:
    """Alexander Elder SafeZone Stop (Jesse kütüphanesindeki gürültü-dirençli stop)."""
    lb = max(3, int(lookback))
    cf = max(0.5, float(coeff))
    lw = low.astype(float)
    hg = high.astype(float)
    cl = close.astype(float)

    down_pen = (lw.shift(1) - lw).clip(lower=0.0)
    up_pen = (hg - hg.shift(1)).clip(lower=0.0)

    def _avg_nonzero(arr: np.ndarray) -> float:
        nz = arr[arr > 0]
        return float(nz.mean()) if len(nz) > 0 else 0.0

    avg_dn = down_pen.rolling(lb, min_periods=2).apply(_avg_nonzero, raw=True).fillna(0.0)
    avg_up = up_pen.rolling(lb, min_periods=2).apply(_avg_nonzero, raw=True).fillna(0.0)

    raw_long = lw.shift(1) - cf * avg_dn
    raw_short = hg.shift(1) + cf * avg_up
    long_stop = raw_long.rolling(3, min_periods=1).max()
    short_stop = raw_short.rolling(3, min_periods=1).min()
    px = _last(cl, 0.0)
    return {
        "safezone_long": round(_last(long_stop, px * 0.95), 6),
        "safezone_short": round(_last(short_stop, px * 1.05), 6),
    }


DEFAULT_MINIMAL_ROI_TABLE: dict[int, float] = {
    0: 4.0,     # 0+ dakikada >= %4.0 net fiyat kârı
    15: 2.5,    # 15+ dakikada >= %2.5
    30: 1.5,    # 30+ dakikada >= %1.5
    60: 0.8,    # 60+ dakikada >= %0.8
}


def minimal_roi_exit_check(
    elapsed_sec: float,
    net_profit_pct: float,
    roi_table: dict[int, float] | None = None,
) -> dict[str, Any]:
    """Freqtrade Minimal ROI tablosu değerlendiricisi (yalnız Shadow karşılaştırması için)."""
    table = roi_table if roi_table is not None else DEFAULT_MINIMAL_ROI_TABLE
    elapsed_min = max(0.0, float(elapsed_sec)) / 60.0
    applicable = [thr for minute, thr in sorted(table.items()) if elapsed_min >= float(minute)]
    if not applicable:
        return {"should_exit": False, "target_pct": None, "elapsed_min": round(elapsed_min, 2)}
    target = float(applicable[-1])
    return {
        "should_exit": float(net_profit_pct) >= target,
        "target_pct": target,
        "elapsed_min": round(elapsed_min, 2),
    }


# ---------------------------------------------------------------------------
# 4. Volume Profile HVN / LVN + Tahmini Likidasyon Kümeleri + Emir Defteri Anomali
# ---------------------------------------------------------------------------
def volume_profile_nodes(df: pd.DataFrame, bins: int = 24) -> dict[str, Any]:
    """HVN (High Volume Nodes) ve LVN (Low Volume Nodes) destek/boşluk seviyeleri."""
    n_bins = max(8, int(bins))
    if len(df) < 10:
        px = _last(df["close"], 0.0) if len(df) else 0.0
        return {"hvn_levels": [], "lvn_levels": [], "nearest_hvn": px, "nearest_lvn": px}

    tp = ((df["high"] + df["low"] + df["close"]) / 3.0).astype(float).to_numpy()
    vol = df["volume"].astype(float).clip(lower=0.0).to_numpy()
    lo, hi = float(np.min(tp)), float(np.max(tp))
    px = float(df["close"].iloc[-1])
    if not math.isfinite(lo) or not math.isfinite(hi) or hi - lo <= 1e-12 or float(vol.sum()) <= 0:
        return {"hvn_levels": [round(px, 6)], "lvn_levels": [], "nearest_hvn": round(px, 6), "nearest_lvn": round(px, 6)}

    hist, edges = np.histogram(tp, bins=n_bins, range=(lo, hi), weights=vol)
    centers = 0.5 * (edges[:-1] + edges[1:])
    mean_v = float(hist.mean())

    hvn: list[float] = []
    lvn: list[float] = []
    for i in range(1, len(hist) - 1):
        if hist[i] >= hist[i - 1] and hist[i] >= hist[i + 1] and hist[i] >= mean_v * 1.15:
            hvn.append(round(float(centers[i]), 6))
        elif hist[i] <= hist[i - 1] and hist[i] <= hist[i + 1] and hist[i] <= mean_v * 0.65:
            lvn.append(round(float(centers[i]), 6))

    if not hvn:
        poc_idx = int(np.argmax(hist))
        hvn.append(round(float(centers[poc_idx]), 6))

    nearest_hvn = min(hvn, key=lambda lv: abs(lv - px)) if hvn else round(px, 6)
    nearest_lvn = min(lvn, key=lambda lv: abs(lv - px)) if lvn else round(px, 6)
    in_lvn_vacuum = any(abs(px - lv) / max(px, 1e-12) * 100.0 <= 0.25 for lv in lvn)
    return {
        "hvn_levels": hvn[:5],
        "lvn_levels": lvn[:5],
        "nearest_hvn": nearest_hvn,
        "nearest_lvn": nearest_lvn,
        "in_lvn_vacuum": in_lvn_vacuum,
    }


def estimated_liquidation_clusters(
    df: pd.DataFrame,
    leverages: tuple[int, ...] = (10, 20, 50, 100),
    lookback: int = 60,
    maintenance_margin_pct: float = 0.5,
) -> dict[str, Any]:
    """Hacim ağırlıklı son giriş kümelerinden tahmini likidasyon mıknatıs bölgeleri.

    Not: Gerçek borsa pozisyon defteri gizli olduğundan bu hesap Coinglass tarzı
    deterministik kaldıraç-kümesi yaklaşımıdır.
    """
    if len(df) < 5:
        return {"long_liq_zones": [], "short_liq_zones": [], "magnet_bias": 0}
    sub = df.tail(max(5, int(lookback)))
    px = float(sub["close"].iloc[-1])
    vol = sub["volume"].astype(float).to_numpy()
    anchors = ((sub["high"] + sub["low"] + sub["close"]) / 3.0).astype(float).to_numpy()
    top_idx = np.argsort(vol)[-3:]
    mm = float(maintenance_margin_pct) / 100.0

    long_zones: list[float] = []
    short_zones: list[float] = []
    for idx in top_idx:
        anchor = float(anchors[idx])
        for lev in leverages:
            lv = max(2, int(lev))
            dist = max(0.002, (1.0 / lv) - mm)
            l_px = anchor * (1.0 - dist)
            s_px = anchor * (1.0 + dist)
            if l_px < px:
                long_zones.append(round(l_px, 6))
            if s_px > px:
                short_zones.append(round(s_px, 6))

    long_zones = sorted(set(long_zones), key=lambda z: abs(px - z))[:4]
    short_zones = sorted(set(short_zones), key=lambda z: abs(px - z))[:4]
    magnet_bias = 0
    if long_zones and short_zones:
        d_long = abs(px - long_zones[0]) / max(px, 1e-12)
        d_short = abs(short_zones[0] - px) / max(px, 1e-12)
        if d_short < d_long * 0.75:
            magnet_bias = 1   # Yukarıdaki short likidasyon kümesi daha yakın
        elif d_long < d_short * 0.75:
            magnet_bias = -1  # Aşağıdaki long likidasyon kümesi daha yakın
    return {
        "long_liq_zones": long_zones,
        "short_liq_zones": short_zones,
        "magnet_bias": magnet_bias,
    }


class OrderBookAnomalyTracker:
    """20-kademe emir defteri + işlem akışından Spoofing & Iceberg ADAY dedektörü.

    L3 emir-ID verisi olmadan kesin borsa manipülasyonu iddiasında bulunmaz;
    fiyata dokunmadan hızla çekilen duvarları ``DUVAR_CEKILME_ADAYI`` ve
    yüksek karşı hacme rağmen erimeyen kademeleri ``ICEBERG_EMILIM_ADAYI`` olarak işaretler.
    """

    def __init__(self, wall_mult: float = 3.5, window_sec: float = 15.0):
        self.wall_mult = max(2.0, float(wall_mult))
        self.window_sec = max(3.0, float(window_sec))
        self._books: deque[tuple[float, dict[float, float], dict[float, float]]] = deque(maxlen=40)
        self._trades: deque[tuple[float, float, float, bool]] = deque(maxlen=400)

    def on_book(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]], ts: float) -> None:
        b_map = {round(float(p), 8): float(q) * float(p) for p, q in bids[:20] if float(p) > 0 and float(q) > 0}
        a_map = {round(float(p), 8): float(q) * float(p) for p, q in asks[:20] if float(p) > 0 and float(q) > 0}
        self._books.append((float(ts), b_map, a_map))

    def on_trade(self, price: float, qty: float, is_buyer_maker: bool, ts: float) -> None:
        self._trades.append((float(ts), round(float(price), 8), float(price) * float(qty), bool(is_buyer_maker)))

    def detect(self, now_ts: float | None = None) -> dict[str, Any]:
        if len(self._books) < 2:
            return {"spoof_candidate": "YOK", "iceberg_candidate": "YOK"}
        now = float(now_ts if now_ts is not None else self._books[-1][0])
        cutoff = now - self.window_sec
        recent_books = [b for b in self._books if b[0] >= cutoff]
        if len(recent_books) < 2:
            return {"spoof_candidate": "YOK", "iceberg_candidate": "YOK"}

        first_ts, b0, a0 = recent_books[0]
        _, b1, a1 = recent_books[-1]
        recent_trades = [t for t in self._trades if t[0] >= first_ts]

        spoof = "YOK"
        avg_b0 = (sum(b0.values()) / len(b0)) if b0 else 0.0
        avg_a0 = (sum(a0.values()) / len(a0)) if a0 else 0.0

        # Bid duvarı fiyata işlem değmeden kayboldu mu?
        for px, usdt0 in b0.items():
            if avg_b0 > 0 and usdt0 >= avg_b0 * self.wall_mult:
                usdt1 = b1.get(px, 0.0)
                traded_at_px = sum(u for _, tpx, u, _ in recent_trades if abs(tpx - px) / max(px, 1e-12) < 0.0005)
                if usdt1 < usdt0 * 0.20 and traded_at_px < usdt0 * 0.15:
                    spoof = "SAHTE_ALIS_DUVARI_CEKILDI"
                    break

        if spoof == "YOK":
            for px, usdt0 in a0.items():
                if avg_a0 > 0 and usdt0 >= avg_a0 * self.wall_mult:
                    usdt1 = a1.get(px, 0.0)
                    traded_at_px = sum(u for _, tpx, u, _ in recent_trades if abs(tpx - px) / max(px, 1e-12) < 0.0005)
                    if usdt1 < usdt0 * 0.20 and traded_at_px < usdt0 * 0.15:
                        spoof = "SAHTE_SATIS_DUVARI_CEKILDI"
                        break

        # Iceberg emilim: belirli bir fiyatta başlangıçtaki görünür kademenin >2 katı işlem geçmesine rağmen kademe hâlâ duruyor mu?
        iceberg = "YOK"
        for px, usdt0 in b0.items():
            if usdt0 <= 0:
                continue
            sell_hit = sum(u for _, tpx, u, seller in recent_trades if seller and abs(tpx - px) / max(px, 1e-12) < 0.0005)
            if sell_hit >= usdt0 * 2.0 and b1.get(px, 0.0) >= usdt0 * 0.60:
                iceberg = "GIZLI_ALICI_ICEBERG_ADAYI"
                break
        if iceberg == "YOK":
            for px, usdt0 in a0.items():
                if usdt0 <= 0:
                    continue
                buy_hit = sum(u for _, tpx, u, seller in recent_trades if (not seller) and abs(tpx - px) / max(px, 1e-12) < 0.0005)
                if buy_hit >= usdt0 * 2.0 and a1.get(px, 0.0) >= usdt0 * 0.60:
                    iceberg = "GIZLI_SATICI_ICEBERG_ADAYI"
                    break

        return {"spoof_candidate": spoof, "iceberg_candidate": iceberg}


# ---------------------------------------------------------------------------
# 5. İstatistiksel Rejim Sınıflandırıcı (K-Means + Markov Geçiş Olasılıkları) & BTC Korelasyon
# ---------------------------------------------------------------------------
def classify_statistical_regime(
    df: pd.DataFrame,
    window: int = 120,
    seed: int = 42,
) -> dict[str, Any]:
    """Saf NumPy deterministik K-Means + 1. derece Markov geçiş olasılıklı rejim modeli."""
    if len(df) < 40:
        return {
            "state": "INSUFFICIENT_DATA",
            "persistence_prob": 0.0,
            "shock_prob": 0.0,
            "regime_vote": 0,
        }
    sub = df.tail(max(40, int(window))).copy()
    close = sub["close"].astype(float)
    ret = close.pct_change().fillna(0.0)
    rvol = ret.rolling(10, min_periods=3).std().fillna(0.0)
    slope = close.pct_change(8).fillna(0.0)

    feats = np.column_stack([ret.to_numpy(), rvol.to_numpy(), slope.to_numpy()])
    std = feats.std(axis=0)
    std[std < 1e-12] = 1.0
    z = (feats - feats.mean(axis=0)) / std

    # Deterministik başlangıç merkezleri (kuantillere dayalı — rastgele kayma yapmaz)
    k = 4
    q_idx = [
        int(np.argmin(z[:, 1])),          # düşük oynaklık
        int(np.argmax(z[:, 2])),          # pozitif trend
        int(np.argmin(z[:, 2])),          # negatif trend
        int(np.argmax(z[:, 1])),          # yüksek oynaklık şoku
    ]
    centers = z[q_idx].copy()
    labels = np.zeros(len(z), dtype=int)
    rng = np.random.default_rng(seed)

    for _ in range(15):
        dists = ((z[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = np.argmin(dists, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for c_id in range(k):
            mask = labels == c_id
            if np.any(mask):
                centers[c_id] = z[mask].mean(axis=0)
            else:
                centers[c_id] = z[int(rng.integers(0, len(z)))]

    # Kümelere ekonomik anlam ata
    vol_by_c = [float(feats[labels == c_id, 1].mean()) if np.any(labels == c_id) else 0.0 for c_id in range(k)]
    slope_by_c = [float(feats[labels == c_id, 2].mean()) if np.any(labels == c_id) else 0.0 for c_id in range(k)]
    shock_c = int(np.argmax(vol_by_c))
    lowvol_c = int(np.argmin(vol_by_c))

    cur_c = int(labels[-1])
    if cur_c == shock_c and vol_by_c[cur_c] > float(np.median(feats[:, 1])) * 1.35:
        state = "HIGH_VOL_SHOCK"
        vote = 0
    elif cur_c == lowvol_c and abs(slope_by_c[cur_c]) < 0.003:
        state = "LOW_VOL_RANGE"
        vote = 0
    elif slope_by_c[cur_c] > 0:
        state = "BULL_TREND"
        vote = 1
    elif slope_by_c[cur_c] < 0:
        state = "BEAR_TREND"
        vote = -1
    else:
        state = "LOW_VOL_RANGE"
        vote = 0

    # Markov geçiş matrisi P(next | current)
    trans = np.ones((k, k), dtype=float) * 0.25  # Laplace yumuşatma
    for a, b in zip(labels[:-1], labels[1:]):
        trans[int(a), int(b)] += 1.0
    probs = trans[cur_c] / trans[cur_c].sum()
    return {
        "state": state,
        "persistence_prob": round(_finite(probs[cur_c]), 4),
        "shock_prob": round(_finite(probs[shock_c]), 4),
        "regime_vote": vote,
    }


def btc_regime_and_correlation(
    asset_df: pd.DataFrame,
    btc_df: pd.DataFrame | None,
    window: int = 48,
) -> dict[str, Any]:
    """Altcoin–BTC korelasyon, Beta katsayısı ve göreli güç (Relative Strength) filtresi."""
    if btc_df is None or len(btc_df) < 15 or len(asset_df) < 15:
        return {
            "available": False,
            "corr_btc": 0.0,
            "beta_btc": 0.0,
            "rs_vs_btc_pct": 0.0,
            "btc_trend": "UNKNOWN",
        }
    w = min(int(window), len(asset_df) - 1, len(btc_df) - 1)
    a_ret = asset_df["close"].astype(float).pct_change().tail(w).to_numpy()
    b_ret = btc_df["close"].astype(float).pct_change().tail(w).to_numpy()
    if len(a_ret) < 10 or np.std(a_ret) < 1e-12 or np.std(b_ret) < 1e-12:
        corr = 0.0
        beta = 0.0
    else:
        corr = float(np.corrcoef(a_ret, b_ret)[0, 1])
        beta = float(np.cov(a_ret, b_ret)[0, 1] / max(np.var(b_ret), 1e-12))

    a_cum = (float(asset_df["close"].iloc[-1]) / max(float(asset_df["close"].iloc[-w]), 1e-12) - 1.0) * 100.0
    b_cum = (float(btc_df["close"].iloc[-1]) / max(float(btc_df["close"].iloc[-w]), 1e-12) - 1.0) * 100.0
    btc_ema50 = _last(Indicators.ema(btc_df["close"], 50))
    btc_ema200 = _last(Indicators.ema(btc_df["close"], min(200, len(btc_df))))
    btc_px = _last(btc_df["close"])
    btc_trend = "BULL" if btc_px > btc_ema50 >= btc_ema200 else ("BEAR" if btc_px < btc_ema50 <= btc_ema200 else "NEUTRAL")
    return {
        "available": True,
        "corr_btc": round(_finite(corr), 4),
        "beta_btc": round(_finite(beta), 4),
        "rs_vs_btc_pct": round(_finite(a_cum - b_cum), 4),
        "btc_trend": btc_trend,
    }


# ---------------------------------------------------------------------------
# 6. Kripto-VADER Duygu + Ters Sentiment & Makro/Token-Unlock Takvim Koruyucu
# ---------------------------------------------------------------------------
_VADER_CRYPTO_LEXICON: dict[str, float] = {
    "bullish": 2.6, "surge": 2.4, "breakout": 2.2, "rally": 2.3, "approved": 2.8,
    "inflow": 2.1, "accumulation": 2.0, "partnership": 1.7, "moon": 1.8, "ath": 2.5,
    "upgrade": 1.6, "adoption": 2.1, "yükseliş": 2.2, "onay": 2.3, "rekor": 2.1,
    "bearish": -2.6, "crash": -3.1, "dump": -2.6, "hack": -3.5, "hacked": -3.6,
    "exploit": -3.5, "bankrupt": -3.6, "insolvent": -3.4, "sec": -1.4, "lawsuit": -2.4,
    "delist": -2.9, "outflow": -2.0, "liquidation": -2.2, "çöküş": -3.1, "iflas": -3.5,
}
_VADER_NEGATIONS = {"not", "no", "never", "denied", "false", "fake", "without", "değil", "yok", "yalan"}
_VADER_BOOSTERS = {"very": 0.35, "extremely": 0.5, "massive": 0.45, "huge": 0.4, "record": 0.35, "aşırı": 0.45, "dev": 0.4}


def vader_crypto_sentiment(text: str, contrarian_threshold: float = 0.65) -> dict[str, Any]:
    """VADER normalizasyonlu (-1..+1) kripto duygu skoru + CyberPunkMetalHead ters sentiment modu."""
    if not text or not str(text).strip():
        return {"compound": 0.0, "label": "NEUTRAL", "contrarian_signal": 0}
    words = [w.strip(".,!?;:()[]\"'").lower() for w in str(text).split()]
    valences: list[float] = []
    for i, w in enumerate(words):
        v = _VADER_CRYPTO_LEXICON.get(w, 0.0)
        if v == 0.0:
            continue
        window = words[max(0, i - 3) : i]
        for bw in window:
            if bw in _VADER_BOOSTERS:
                v += math.copysign(_VADER_BOOSTERS[bw], v)
        if any(nw in _VADER_NEGATIONS for nw in window):
            v *= -0.74
        valences.append(v)

    if not valences:
        return {"compound": 0.0, "label": "NEUTRAL", "contrarian_signal": 0}
    sum_v = sum(valences)
    compound = sum_v / math.sqrt(sum_v * sum_v + 15.0)
    label = "BULLISH" if compound >= 0.20 else ("BEARISH" if compound <= -0.20 else "NEUTRAL")
    # CyberPunkMetalHead aşırı kalabalık coşkuda ters yön sinyali
    contrarian = -1 if compound >= contrarian_threshold else (1 if compound <= -contrarian_threshold else 0)
    return {
        "compound": round(_finite(compound), 4),
        "label": label,
        "contrarian_signal": contrarian,
    }


@dataclass(frozen=True)
class CalendarEvent:
    name: str
    ts_utc: float
    kind: str = "MACRO"         # MACRO (FOMC/CPI/NFP) veya TOKEN_UNLOCK
    symbol: str = "*"           # "*" = tüm piyasa, "ARB/USDT" = tek parite
    pre_Pad_min: int = 30
    post_pad_min: int = 30


class MacroCalendarGuard:
    """FOMC, CPI, NFP ve Token Unlock takvim pencerelerinde giriş koruma filtresi."""

    def __init__(self, events: list[CalendarEvent] | None = None):
        self.events: list[CalendarEvent] = list(events or [])

    def check(self, symbol: str, now_ts: float) -> dict[str, Any]:
        sym = str(symbol or "*").upper()
        ts = float(now_ts)
        for ev in self.events:
            if ev.symbol not in ("*", sym):
                continue
            start = ev.ts_utc - ev.pre_Pad_min * 60.0
            end = ev.ts_utc + ev.post_pad_min * 60.0
            if start <= ts <= end:
                return {
                    "blocked": True,
                    "event": ev.name,
                    "kind": ev.kind,
                    "minutes_to_event": round((ev.ts_utc - ts) / 60.0, 1),
                }
        return {"blocked": False, "event": "", "kind": "", "minutes_to_event": None}


# ---------------------------------------------------------------------------
# 7. Monte Carlo Özsermaye / Drawdown Simülasyonu & İleri Performans Metrikleri
# ---------------------------------------------------------------------------
def advanced_performance_metrics(
    trade_pnls_usdt: list[float],
    start_balance: float = 1_000.0,
) -> dict[str, float]:
    """Sharpe, Sortino, Calmar, Max Drawdown (%) ve Expectancy (USDT/işlem)."""
    bal0 = max(1.0, float(start_balance))
    if not trade_pnls_usdt:
        return {
            "expectancy_usdt": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "max_drawdown_pct": 0.0,
        }
    arr = np.asarray(trade_pnls_usdt, dtype=float)
    rets = arr / bal0
    mean_r = float(rets.mean())
    std_r = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    downside = rets[rets < 0.0]
    down_std = float(np.sqrt(np.mean(downside ** 2))) if len(downside) > 0 else 0.0

    eq = bal0 + np.cumsum(arr)
    peaks = np.maximum.accumulate(np.insert(eq, 0, bal0))[1:]
    dd_pct = ((peaks - eq) / np.maximum(peaks, 1e-12)) * 100.0
    max_dd_pct = float(np.max(dd_pct)) if len(dd_pct) else 0.0
    total_ret_pct = (float(eq[-1]) / bal0 - 1.0) * 100.0

    sharpe = (mean_r / std_r * math.sqrt(len(rets))) if std_r > 1e-12 else 0.0
    sortino = (mean_r / down_std * math.sqrt(len(rets))) if down_std > 1e-12 else 0.0
    calmar = (total_ret_pct / max_dd_pct) if max_dd_pct > 1e-9 else 0.0
    return {
        "expectancy_usdt": round(_finite(arr.mean()), 4),
        "sharpe": round(_finite(sharpe), 4),
        "sortino": round(_finite(sortino), 4),
        "calmar": round(_finite(calmar), 4),
        "max_drawdown_pct": round(_finite(max_dd_pct), 4),
    }


def monte_carlo_drawdown(
    trade_pnls_usdt: list[float],
    start_balance: float = 1_000.0,
    n_sims: int = 1_000,
    ruin_threshold_pct: float = 50.0,
    seed: int = 42,
) -> dict[str, float]:
    """Bootstrap Monte Carlo simülasyonu (%50 ve %95 MaxDD + Risk of Ruin)."""
    bal0 = max(1.0, float(start_balance))
    if not trade_pnls_usdt:
        return {"mc_median_dd_pct": 0.0, "mc_p95_dd_pct": 0.0, "risk_of_ruin_pct": 0.0}
    arr = np.asarray(trade_pnls_usdt, dtype=float)
    sims = max(50, int(n_sims))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(sims, len(arr)))
    sampled = arr[idx]
    eq = bal0 + np.cumsum(sampled, axis=1)
    eq_with_start = np.concatenate([np.full((sims, 1), bal0), eq], axis=1)
    peaks = np.maximum.accumulate(eq_with_start, axis=1)
    dds = ((peaks - eq_with_start) / np.maximum(peaks, 1e-12)) * 100.0
    max_dds = np.max(dds, axis=1)
    ruin_floor = bal0 * (1.0 - float(ruin_threshold_pct) / 100.0)
    ruined = np.any(eq <= ruin_floor, axis=1)
    return {
        "mc_median_dd_pct": round(_finite(np.percentile(max_dds, 50)), 4),
        "mc_p95_dd_pct": round(_finite(np.percentile(max_dds, 95)), 4),
        "risk_of_ruin_pct": round(_finite(ruined.mean() * 100.0), 4),
    }


# ---------------------------------------------------------------------------
# 8. Birleşik PDF v3 Hazırlık Snapshot Fonksiyonu (Tak-Çalıştır Giriş Noktası)
# ---------------------------------------------------------------------------
def pdf_v3_snapshot(df: pd.DataFrame, btc_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Kapanmış OHLCV (+ opsiyonel BTC OHLCV) üzerinden tüm PDF v3 eksik göstergeleri üretir."""
    if df is None or len(df) < 35:
        return {
            "schema": "pdf-v3-prep-v1",
            "data_ready": False,
            "values": {},
            "regime_model": {"state": "INSUFFICIENT_DATA", "regime_vote": 0},
            "btc_context": {"available": False},
            "volume_nodes": {"hvn_levels": [], "lvn_levels": []},
            "liq_clusters": {"long_liq_zones": [], "short_liq_zones": [], "magnet_bias": 0},
        }

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    px = _last(close)

    t3_v = _last(t3(close, 10), px)
    frama_v = _last(frama(high, low, close, 16), px)
    vidya_v = _last(vidya(close, 14, 9), px)
    jma_v = _last(jma_approx(close, 14, 0.0), px)
    rma_v = _last(rma(close, 14), px)
    ribbon = ema_ribbon_state(close)
    stoch = classic_stochastic(high, low, close)
    smooth_osc = ema_smoothed_oscillators(df)
    safezone = elder_safezone_stop(high, low, close)
    vp_nodes = volume_profile_nodes(df)
    liq_clusters = estimated_liquidation_clusters(df)
    stat_regime = classify_statistical_regime(df)
    btc_ctx = btc_regime_and_correlation(df, btc_df)

    adaptive_votes = [
        1 if px > m else (-1 if px < m else 0)
        for m in (t3_v, frama_v, vidya_v, jma_v)
    ]
    adaptive_consensus = 1 if sum(adaptive_votes) >= 2 else (-1 if sum(adaptive_votes) <= -2 else 0)

    return {
        "schema": "pdf-v3-prep-v1",
        "data_ready": True,
        "values": {
            "t3_10": round(t3_v, 6),
            "frama_16": round(frama_v, 6),
            "vidya_14": round(vidya_v, 6),
            "jma_14": round(jma_v, 6),
            "rma_14": round(rma_v, 6),
            "adaptive_ma_consensus": adaptive_consensus,
            "ema_ribbon_score": ribbon["score"],
            "ema_ribbon_bull": ribbon["bull_stacked"],
            "ema_ribbon_bear": ribbon["bear_stacked"],
            "ema_ribbon_expansion_pct": ribbon["expansion_pct"],
            **stoch,
            **smooth_osc,
            **safezone,
        },
        "regime_model": stat_regime,
        "btc_context": btc_ctx,
        "volume_nodes": vp_nodes,
        "liq_clusters": liq_clusters,
    }
