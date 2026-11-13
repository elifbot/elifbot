"""Backtest + walk-forward (örneklem-dışı doğrulama).

Kötümser semantik engine.py'de tek yerde tanımlıdır — backtest ile canlı paper AYNI
motoru kullanır (sentez-bot'un "aynı motor" disiplini).

Walk-forward (sentez-bot): kayan pencerede eğitimde en iyi ayar seçilir, HİÇ GÖRÜLMEMİŞ
test penceresinde uygulanır ve sabit varsayılanla karşılaştırılır.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

import pandas as pd

from .datafeed import TIMEFRAME_MS, to_indexed
from .engine import Engine
from .models import Bar, Trade
from .report import metrics
from .sources import PrecomputedSource


@dataclass
class RunResult:
    trades: list[Trade]
    equity_curve: list[tuple[pd.Timestamp, float]]
    stats: dict[str, int]
    breaker_trips: dict[str, int]
    start_ts: pd.Timestamp | None
    end_ts: pd.Timestamp | None


def run_backtest(data: dict[str, pd.DataFrame], cfg, source: PrecomputedSource | None = None,
                 start_ts=None, end_ts=None,
                 on_event: Optional[Callable[[str, dict], None]] = None) -> RunResult:
    """data: sym → ham OHLCV DataFrame (ts sütunlu, ms). [start_ts, end_ts) aralığında koşar."""
    cfg = cfg.validate()
    if source is None:
        source = PrecomputedSource(data, cfg)
    indexed = {s: to_indexed(df) for s, df in data.items()}
    by_ts: dict[pd.Timestamp, dict[str, Bar]] = {}
    for s, df in indexed.items():
        for row in df.itertuples():
            t = row.Index
            by_ts.setdefault(t, {})[s] = Bar(int(t.value // 10**6), row.open, row.high,
                                             row.low, row.close, row.volume)
    stamps = [t for t in source.timestamps() if t in by_ts
              and (start_ts is None or t >= start_ts) and (end_ts is None or t < end_ts)]
    bar_ms = TIMEFRAME_MS[cfg.market.timeframe]
    eng = Engine(cfg, source, bar_ms, on_event)
    if not stamps:
        return RunResult([], [], dict(eng.stats), {}, None, None)
    last_bars: dict[str, Bar] = {}
    for t in stamps:
        cur = by_ts[t]
        last_bars.update(cur)
        eng.step(t, cur)
    eng.finish(last_bars, stamps[-1])
    eng.equity_curve.append((stamps[-1], eng.balance))
    return RunResult(eng.trades, eng.equity_curve, dict(eng.stats), dict(eng.breaker.trips),
                     stamps[0], stamps[-1])


DEFAULT_GRID: dict[str, list] = {
    "score_threshold": [3.5, 4.5, 5.5],
    "stop_atr": [1.2, 1.5, 2.0],
    "tp_r": [1.5, 2.0, 2.5],
}


def _score(trades: list[Trade], min_trades: int) -> float:
    """Eğitim skoru: ort. R × √n. Az işlemli ayarlar elenir."""
    if len(trades) < min_trades:
        return -math.inf
    return (sum(t.r_mult for t in trades) / len(trades)) * math.sqrt(len(trades))


def walk_forward(data: dict[str, pd.DataFrame], cfg, train_bars: int = 1200,
                 test_bars: int = 400, grid: dict[str, list] | None = None,
                 min_trades: int = 8, max_combos: int = 27,
                 progress: Optional[Callable[[str], None]] = None) -> dict:
    """Kayan pencere: eğitimde en iyi ayar → hiç görülmemiş test penceresi."""
    grid = grid or DEFAULT_GRID
    keys = list(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*grid.values())][:max_combos]
    src = PrecomputedSource(data, cfg)
    stamps = src.timestamps()
    folds: list[dict] = []
    oos_trades: list[Trade] = []
    base_trades: list[Trade] = []
    i = 0
    while i + train_bars + test_bars <= len(stamps):
        tr0, tr1 = stamps[i], stamps[i + train_bars]
        te0, te1 = tr1, stamps[i + train_bars + test_bars - 1]
        best, best_score = None, -math.inf
        for combo in combos:
            c = replace(cfg)
            # grid anahtarları strategy/exit bölümlerine kesişimsel uygulanır
            for k, v in combo.items():
                if hasattr(c.strategy, k):
                    setattr(c.strategy, k, v)
                if hasattr(c.exit, k):
                    setattr(c.exit, k, v)
            r = run_backtest(data, c, src, tr0, tr1)
            sc = _score(r.trades, min_trades)
            if sc > best_score:
                best, best_score = combo, sc
        chosen = replace(cfg)
        for k, v in (best or {}).items():
            if hasattr(chosen.strategy, k):
                setattr(chosen.strategy, k, v)
            if hasattr(chosen.exit, k):
                setattr(chosen.exit, k, v)
        r_test = run_backtest(data, chosen, src, te0, te1)
        r_base = run_backtest(data, cfg, src, te0, te1)
        oos_trades += r_test.trades
        base_trades += r_base.trades
        folds.append({
            "test_aralik": [str(te0), str(te1)],
            "secilen": best,
            "oos_islem": len(r_test.trades),
            "oos_ort_R": round(sum(t.r_mult for t in r_test.trades) / len(r_test.trades), 3)
                          if r_test.trades else 0.0,
            "baz_ort_R": round(sum(t.r_mult for t in r_base.trades) / len(r_base.trades), 3)
                          if r_base.trades else 0.0,
        })
        if progress:
            progress(f"fold {len(folds)}: secilen={best} oos_islem={len(r_test.trades)}")
        i += test_bars
    return {"folds": folds, "n_folds": len(folds),
            "oos_n": len(oos_trades),
            "oos_ort_R": round(sum(t.r_mult for t in oos_trades) / len(oos_trades), 3) if oos_trades else 0.0,
            "baz_oos_ort_R": round(sum(t.r_mult for t in base_trades) / len(base_trades), 3) if base_trades else 0.0}
