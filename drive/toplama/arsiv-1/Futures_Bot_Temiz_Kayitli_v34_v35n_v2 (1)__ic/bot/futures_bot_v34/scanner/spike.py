"""
scanner/spike.py — Ani hacim/fiyat hareketi (spike) tespiti.

"Ani yükselen / ani düşen" tanımı ölçülebilir hale getirilir:

  rvol           = son mum hacmi / son `lookback` mumun MEDYAN hacmi
  vol_z          = son mum hacminin z-skoru (ddof=1)
  ret_k          = son k mumdaki yüzde fiyat değişimi
  range_exp      = son mum aralığı (high-low) / ATR  (1.0 = normal)

  spike_score    = |ret_k| × min(rvol, 10) / 10  × range_exp  (0..~10)

Sınıflandırma:
  ANI_YUKSELIS : ret_k >= +esik  ve rvol >= rvol_esik
  ANI_DUSUS    : ret_k <= -esik  ve rvol >= rvol_esik
  NORMAL       : aksi

Uyarı: Bu bir "sinyal" değil, TARAMA ölçütüdür. Spike'ların yönü sürer mi
döner mi sorusu istatistiksel olarak kanıtlanmamıştır; ilgili strateji
`SHADOW` durumundadır.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import pandas as pd

ANI_YUKSELIS = "ANI_YUKSELIS"
ANI_DUSUS = "ANI_DUSUS"
NORMAL = "NORMAL"


@dataclass
class SpikeMetrics:
    """Tek sembolün ani hareket ölçümleri."""

    symbol: str
    last_price: float
    rvol: float
    volume_z: float
    ret_k_pct: float
    range_expansion: float
    spike_score: float
    label: str
    lookback: int

    def as_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "last": round(self.last_price, 8),
            "rvol": round(self.rvol, 2),
            "volume_z": round(self.volume_z, 2),
            "ret_k_pct": round(self.ret_k_pct, 3),
            "range_expansion": round(self.range_expansion, 2),
            "spike_score": round(self.spike_score, 3),
            "label": self.label,
        }


def compute_spike(
    df: pd.DataFrame,
    symbol: str,
    *,
    lookback: int = 60,
    k_bars: int = 5,
    ret_threshold_pct: float = 0.6,
    rvol_threshold: float = 2.5,
) -> SpikeMetrics | None:
    """
    Kapanmış mumlardan ani hareket ölçümü üretir.

    Yetersiz veri varsa None döner (uydurma değer üretilmez).
    """
    if df is None or len(df) < max(lookback, k_bars) + 2:
        return None

    win = df.iloc[-(lookback + 1) :]
    vols = win["volume"].iloc[:-1]
    base_median = float(vols.median())
    if base_median <= 0:
        return None

    last_vol = float(df["volume"].iloc[-1])
    rvol = last_vol / base_median

    try:
        mu = statistics.mean(vols.tolist())
        sd = statistics.stdev(vols.tolist())
    except statistics.StatisticsError:
        return None
    volume_z = (last_vol - mu) / sd if sd > 0 else 0.0

    close_now = float(df["close"].iloc[-1])
    close_prev = float(df["close"].iloc[-1 - k_bars])
    if close_prev <= 0:
        return None
    ret_k = (close_now / close_prev - 1.0) * 100.0

    # ATR tabanlı aralık genişlemesi (ATR yoksa 1.0 kabul edilir).
    from indicators.core import atr_wilder

    atr = atr_wilder(df, 14)
    atr_last = float(atr.iloc[-1]) if len(atr) and pd.notna(atr.iloc[-1]) else 0.0
    bar_range = float(df["high"].iloc[-1]) - float(df["low"].iloc[-1])
    range_exp = (bar_range / atr_last) if atr_last > 0 else 1.0

    capped_rvol = min(rvol, 10.0)
    spike_score = abs(ret_k) * (capped_rvol / 10.0) * max(range_exp, 0.1)

    if ret_k >= ret_threshold_pct and rvol >= rvol_threshold:
        label = ANI_YUKSELIS
    elif ret_k <= -ret_threshold_pct and rvol >= rvol_threshold:
        label = ANI_DUSUS
    else:
        label = NORMAL

    return SpikeMetrics(
        symbol=symbol,
        last_price=close_now,
        rvol=rvol,
        volume_z=volume_z,
        ret_k_pct=ret_k,
        range_expansion=range_exp,
        spike_score=spike_score,
        label=label,
        lookback=lookback,
    )


def rank_spikes(metrics: list[SpikeMetrics], limit: int = 5) -> list[SpikeMetrics]:
    """Spike skoruna göre azalan sıralar (spike olmayanlar da listede kalır)."""
    return sorted(metrics, key=lambda m: m.spike_score, reverse=True)[:limit]
