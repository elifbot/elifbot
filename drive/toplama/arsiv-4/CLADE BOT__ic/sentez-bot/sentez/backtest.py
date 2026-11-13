"""Backtest ve walk-forward (örneklem-dışı doğrulama)."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Optional, Sequence

from .engine import Engine
from .models import Bar, Config, Trade
from .report import metrics
from .signals import PrecomputedSource


@dataclass
class RunResult:
    cfg: Config
    trades: list[Trade]
    equity_curve: list[tuple[int, float]]
    stats: dict[str, int]
    breaker_trips: dict[str, int]
    start_ts: int
    end_ts: int


def prepare(data: dict[str, Sequence[Bar]], cfg: Config) -> PrecomputedSource:
    return PrecomputedSource(data, cfg)


def run_backtest(data: dict[str, Sequence[Bar]], cfg: Config,
                 source: Optional[PrecomputedSource] = None,
                 start_ts: Optional[int] = None, end_ts: Optional[int] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None) -> RunResult:
    """[start_ts, end_ts) aralığında koşar. source verilirse göstergeler yeniden hesaplanmaz.

    Uyarı: source başka bir Config ile hazırlandıysa göstergeler aynıdır (göstergeler ayarlardan
    bağımsızdır), ama conf_th/max_chop/bar_ms source.cfg'den okunur — bu yüzden aşağıda
    source.cfg güncellenir.
    """
    cfg = cfg.validate()
    if source is None:
        source = PrecomputedSource(data, cfg)
    source.cfg = cfg
    by_ts = {s: {b.ts: b for b in bars} for s, bars in data.items()}
    stamps = [t for t in source.timestamps()
              if (start_ts is None or t >= start_ts) and (end_ts is None or t < end_ts)]
    eng = Engine(cfg, source, on_event)
    last_bars: dict[str, Bar] = {}
    last_ts = stamps[-1] if stamps else 0
    for t in stamps:
        cur = {s: m[t] for s, m in by_ts.items() if t in m}
        last_bars.update(cur)
        eng.step(t, cur)
    eng.finish(last_bars, last_ts)
    eng.equity_curve.append((last_ts, eng.balance))
    return RunResult(cfg, eng.trades, eng.equity_curve, dict(eng.stats), dict(eng.breaker.trips),
                     stamps[0] if stamps else 0, last_ts)


DEFAULT_GRID: dict[str, list] = {
    "conf_th": [3, 4, 5],
    "stop_atr": [1.0, 1.5],
    "tp_atr": [2.0, 3.0],
}


def _score(trades: Sequence[Trade], min_trades: int) -> float:
    """Eğitim skoru: ortalama R × √n. Az işlemli ayarlar elenir (-inf)."""
    if len(trades) < min_trades:
        return -math.inf
    return (sum(t.r_mult for t in trades) / len(trades)) * math.sqrt(len(trades))


def walk_forward(data: dict[str, Sequence[Bar]], cfg: Config, train_bars: int = 1200,
                 test_bars: int = 400, grid: Optional[dict[str, list]] = None,
                 min_trades: int = 8, progress: Optional[Callable[[str], None]] = None) -> dict:
    """Kayan pencere: eğitimde en iyi ayarı seç, hiç görülmemiş test penceresinde uygula.

    Dönüş: her fold için seçilen ayar + test sonucu, birleşik örneklem-dışı (OOS) metrikler ve
    aynı pencerelerde SABİT varsayılan ayarın sonucu (karşılaştırma tabanı).
    """
    grid = grid or DEFAULT_GRID
    keys = list(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*grid.values())]
    src = PrecomputedSource(data, cfg)
    stamps = src.timestamps()
    folds, oos_trades, base_trades = [], [], []
    i = 0
    while i + train_bars + test_bars <= len(stamps):
        tr0, tr1 = stamps[i], stamps[i + train_bars]
        te0 = tr1
        te1 = stamps[i + train_bars + test_bars - 1] + 1
        best, best_score = None, -math.inf
        for combo in combos:
            c = replace(cfg, **combo)
            r = run_backtest(data, c, src, tr0, tr1)
            sc = _score(r.trades, min_trades)
            if sc > best_score:
                best, best_score = combo, sc
        chosen = replace(cfg, **(best or {}))
        r_test = run_backtest(data, chosen, src, te0, te1)
        r_base = run_backtest(data, cfg, src, te0, te1)
        oos_trades += r_test.trades
        base_trades += r_base.trades
        folds.append({"train_range": [tr0, tr1], "test_range": [te0, te1], "chosen": best,
                      "train_score": None if best_score == -math.inf else round(best_score, 3),
                      "test": metrics(r_test.trades, r_test.equity_curve, cfg),
                      "baseline": metrics(r_base.trades, r_base.equity_curve, cfg)})
        if progress:
            progress(f"fold {len(folds)}: seçilen={best} oos_işlem={len(r_test.trades)}")
        i += test_bars
    return {"folds": folds,
            "oos": metrics(oos_trades, [], cfg), "baseline_oos": metrics(base_trades, [], cfg),
            "n_folds": len(folds)}
