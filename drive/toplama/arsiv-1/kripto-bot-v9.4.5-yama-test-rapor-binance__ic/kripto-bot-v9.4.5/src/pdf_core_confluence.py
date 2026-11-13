"""Kripto Bot v9.0 — Odaklanmış PDF Çekirdek Uyum Kapısı (Top-3 Yüksek Alfa Metriği).

Denetim Madde 7 Çözümü:
  Eski sistemde `pdf_v2` (60+) ve `pdf_v3` (50+) toplam 110+ göstergeyi yalnızca
  `Shadow Lab` için hesaplıyor, ana strateji kararına sıfır etki ediyordu.
  `v9.0`'da:
    1. Gereksiz 100+ gölge gösterge varsayılan olarak kapatıldı (`pdf_v2.aktif=False`, `pdf_v3.aktif=False`).
    2. Yalnızca en yüksek istatistiksel kenara sahip **3 çekirdek metrik** O(N) vektörel hızda
       doğrudan ana strateji ve konsey kararına bağlandı:
       - **Choppiness Index (`CI_14`)**: `> 62.5` testere (chop) tespiti, `< 38.2` temiz trend ivmesi.
       - **Market Structure Break (`BOS`)**: Son 20 mumluk yapısal tepe/dip kırılımı (`+1` / `-1` / `0`).
       - **Rolling VWAP20 ATR Sapması (`vwap20_z`)**: Kurumsal adil değer mıknatısı ve yön uyumu.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def compute_pdf_core_confluence(df: pd.DataFrame) -> dict[str, Any]:
    """5m OHLCV üzerinden 3 çekirdek PDF uyum metriğini ve net skor katkısını hesaplar."""
    if df is None or len(df) < 22:
        return {
            "ready": False,
            "choppiness_14": 50.0,
            "is_choppy": False,
            "is_trending_clean": False,
            "bos_dir": 0,
            "vwap20_z": 0.0,
            "score_delta": 0.0,
        }

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float) if "volume" in df.columns else np.ones_like(close)

    # 1) Choppiness Index (14)
    n_ci = 14
    prev_c = np.roll(close, 1)
    prev_c[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
    tr_sum = float(np.sum(tr[-n_ci:]))
    hh_14 = float(np.max(high[-n_ci:]))
    ll_14 = float(np.min(low[-n_ci:]))
    hl_span = max(hh_14 - ll_14, 1e-12)
    if tr_sum > 0 and hl_span > 1e-12:
        raw_ci = 100.0 * math.log10(max(tr_sum / hl_span, 1.0)) / math.log10(n_ci)
        ci_14 = max(0.0, min(100.0, raw_ci))
    else:
        ci_14 = 50.0

    # 2) Market Structure Break of Structure (BOS - önceki 18 mumun swing high/low kırılımı)
    prior_high = float(np.max(high[-20:-1]))
    prior_low = float(np.min(low[-20:-1]))
    last_close = float(close[-1])
    bos_dir = 0
    if last_close > prior_high:
        bos_dir = 1
    elif last_close < prior_low:
        bos_dir = -1

    # 3) Rolling 20-bar Kurumsal VWAP & ATR14 Z-Skoru
    tp = (high[-20:] + low[-20:] + close[-20:]) / 3.0
    v20 = np.maximum(vol[-20:], 0.0)
    v_sum = float(np.sum(v20))
    vwap20 = float(np.sum(tp * v20) / v_sum) if v_sum > 0 else last_close
    atr14 = float(np.mean(tr[-14:]))
    vwap20_z = (last_close - vwap20) / atr14 if atr14 > 0 else 0.0

    is_choppy = ci_14 >= 62.5
    is_trending_clean = ci_14 <= 38.2

    # Net strateji skor katkısı (-10 .. +10 puan)
    score_delta = 0.0
    if bos_dir != 0:
        score_delta += 5.0 * bos_dir
    if 0.15 <= abs(vwap20_z) <= 2.4:
        score_delta += math.copysign(3.0, vwap20_z)
    if is_trending_clean and score_delta != 0.0:
        score_delta *= 1.25
    elif is_choppy:
        score_delta *= 0.35

    score_delta = max(-10.0, min(10.0, score_delta))
    return {
        "ready": True,
        "choppiness_14": round(ci_14, 2),
        "is_choppy": is_choppy,
        "is_trending_clean": is_trending_clean,
        "bos_dir": bos_dir,
        "vwap20": round(vwap20, 8),
        "vwap20_z": round(vwap20_z, 4),
        "score_delta": round(score_delta, 3),
    }
