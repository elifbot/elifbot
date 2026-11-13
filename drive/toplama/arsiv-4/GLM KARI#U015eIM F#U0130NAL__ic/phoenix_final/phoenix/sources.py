"""Sinyal kaynakları: backtest için önden hesaplı (Precomputed), canlı için kayan (Rolling).

PrecomputedSource: göstergeler sembol başına BİR KEZ hesaplanır; sinyal i. indekste okunur
(ileriye bakış yok — nedensellik enrich'in min_periods garantisindedir). HTF oybirliği
(1h/4h) 15m veriden nedensel yeniden örneklenerek her bar için hazırlanır: bir 15m ts'de
yalnızca KAPANMIŞ HTF mumlarının oyu kullanılır.

RollingSource: canlı paper — her sembolün son N kapalı mumundan göstergeleri yeniden
hesaplar; backtest ile AYNI evaluate fonksiyonunu kullanır.
"""
from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

from .indicators import ema, enrich
from .models import Signal
from .strategy import evaluate, htf_bias_at, htf_consensus, resample_htf


def _htf_bias_series(df_indexed: pd.DataFrame, rule: str) -> tuple[np.ndarray, list[str]]:
    """(geçerlilik_ts_ms_dizisi, bias listesi): bir HTF mumunun oyu, mumun kapanışından
    (index + rule) itibaren geçerlidir."""
    h = resample_htf(df_indexed, rule)
    if len(h) == 0:
        return np.array([], dtype=np.int64), []
    x = h.copy()
    x["e20"] = ema(x.close, 20)
    x["e50"] = ema(x.close, 50)
    x["vw"] = (x.close * x.volume).rolling(30, min_periods=30).sum() / \
        x.volume.rolling(30, min_periods=30).sum().replace(0, np.nan)
    valid = (x.index + pd.Timedelta(rule)).asi8 // 10**6  # ms
    biases = [htf_bias_at(x, i) for i in range(len(x))]
    return valid, biases


class PrecomputedSource:
    def __init__(self, data: dict[str, pd.DataFrame], cfg):
        """data: sym → KAPANMIŞ 15m mumlar (ts sütunlu ham frame; DatetimeIndex'e çevrilir)."""
        self.cfg = cfg
        from .datafeed import to_indexed

        self.ind: dict[str, pd.DataFrame] = {}
        self._htf: dict[str, list[tuple[np.ndarray, list[str]]]] = {}
        for s, df in data.items():
            dxi = to_indexed(df)
            self.ind[s] = enrich(dxi, cfg)
            self._htf[s] = [_htf_bias_series(dxi, rule) for rule in cfg.market.htf_timeframes]
        self._breadth: dict[pd.Timestamp, float | None] = {}

    def timestamps(self) -> list[pd.Timestamp]:
        return sorted({t for ind in self.ind.values() for t in ind.index})

    def _htf_of(self, sym: str, ts: pd.Timestamp) -> str:
        """Kapanmış HTF mumlarının oybirliği (FUSION_PRO consensus)."""
        biases = []
        for valid, blist in self._htf.get(sym, []):
            if len(valid) == 0:
                continue
            pos = bisect.bisect_right(valid, int(ts.value // 10**6)) - 1
            if pos >= 0:
                biases.append(blist[pos])
        return htf_consensus(biases)

    def signal(self, sym: str, ts: pd.Timestamp) -> tuple[Signal | None, str]:
        ind = self.ind.get(sym)
        if ind is None or ts not in ind.index:
            return None, "NO_BAR"
        i = ind.index.get_loc(ts)
        sig = evaluate(ind, self.cfg, i=i, htf=self._htf_of(sym, ts))
        return sig, ("SIGNAL" if sig.side != 0 else ("VETO" if sig.vetoes else "THRESHOLD"))

    def breadth(self, ts: pd.Timestamp) -> float | None:
        if ts not in self._breadth:
            flags = []
            for ind in self.ind.values():
                if ts in ind.index:
                    i = ind.index.get_loc(ts)
                    if i >= 25:
                        flags.append(bool(ind.close.iloc[i] > ind.ema_f.iloc[i]))
            self._breadth[ts] = round(sum(flags) / len(flags) * 2 - 1, 3) if flags else None
        return self._breadth[ts]


class RollingSource:
    def __init__(self, history: dict[str, list[tuple[int, float, float, float, float, float]]],
                 cfg, window: int = 600, htf_data: dict[str, dict[str, pd.DataFrame]] | None = None):
        """history: sym → [(ts_ms, o, h, l, c, v), ...] artan sıra.
        htf_data: sym → {"1h": df, "4h": df} — başlangıçta yüklenir, canlıda periyodik tazelenir."""
        self.history = history
        self.cfg = cfg
        self.window = window
        self.htf_data = htf_data or {}
        self._htf_cache: dict[str, str] = {}

    def signal(self, sym: str, ts: pd.Timestamp) -> tuple[Signal | None, str]:
        bars = self.history.get(sym, [])[-self.window:]
        if not bars or bars[-1][0] != int(ts.timestamp() * 1000):
            return None, "NO_BAR"
        df = pd.DataFrame(bars, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.ts, unit="ms", utc=True)
        x = enrich(df, self.cfg)
        sig = evaluate(x, self.cfg, i=len(x) - 1, htf=self.htf_of(sym))
        return sig, ("SIGNAL" if sig.side != 0 else ("VETO" if sig.vetoes else "THRESHOLD"))

    def htf_of(self, sym: str) -> str:
        frames = self.htf_data.get(sym) or {}
        biases = []
        for rule, df in frames.items():
            if df is not None and len(df) > 210:
                biases.append(htf_bias_at(df, len(df) - 1))
        return htf_consensus(biases)

    def breadth(self, ts: pd.Timestamp) -> float | None:
        flags = []
        for bars in self.history.values():
            if len(bars) >= 25 and bars[-1][0] == int(ts.timestamp() * 1000):
                closes = [b[4] for b in bars[-120:]]
                e20 = ema(pd.Series(closes), 20)
                flags.append(bool(closes[-1] > e20.iloc[-1]))
        return round(sum(flags) / len(flags) * 2 - 1, 3) if flags else None
