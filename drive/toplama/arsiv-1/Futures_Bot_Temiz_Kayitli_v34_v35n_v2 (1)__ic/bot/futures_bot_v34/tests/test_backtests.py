"""Backtest motoru testleri — lookahead koruması, pencereleme, ablasyon."""
from __future__ import annotations

import pandas as pd
import pytest

from backtests.ablation import run_ablation
from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig, BacktestEngine, LookaheadError, WalkForwardPlan
from backtests.report import render_ablation, render_backtest, render_walk_forward
from backtests.walk_forward import run_walk_forward
from strategies.trend_follower import TrendFollowerStrategy
from tests.conftest import make_ohlcv


def test_lookahead_guard_raises() -> None:
    """Karar anından sonraki mum pencereye girerse LookaheadError."""

    class Dummy(BacktestEngine):
        def step(self) -> None:
            win = self.history
            self._assert_no_lookahead(win, int(win.iloc[0]["open_time"]) - 1)

        def results(self) -> dict:
            return {}

    eng = Dummy(BacktestConfig())
    eng.feed({"open_time": 1000, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    with pytest.raises(LookaheadError):
        eng.step()


def test_engine_runs_and_reports() -> None:
    """Motor uçtan uca çalışır ve metrik sözlüğü üretir."""
    df = make_ohlcv(320, drift=0.4, noise=0.5)
    engine = SimpleBacktestEngine(TrendFollowerStrategy(), BacktestConfig()).run(df)
    res = engine.results()
    assert res["bars"] == len(df)
    assert res["lookahead_checks"] > 0
    assert res["funding"] == "bilinmiyor"
    assert set(res) >= {"trades", "realized_pnl", "win_rate", "max_drawdown"}


def test_engine_uses_isolated_portfolio() -> None:
    """Her motor kendi portföyünü oluşturur."""
    a = SimpleBacktestEngine(TrendFollowerStrategy())
    b = SimpleBacktestEngine(TrendFollowerStrategy())
    assert a.portfolio is not b.portfolio


def test_walk_forward_windows_and_frozen_params() -> None:
    """Walk-forward pencere üretir ve parametre izi dondurulur."""
    df = make_ohlcv(700)
    out = run_walk_forward(df, TrendFollowerStrategy, train_bars=300, test_bars=150)
    assert out, "en az bir pencere üretilmeli"
    assert all(w.params_hash != "DONDURULMADI" for w in out)
    assert len({w.params_hash for w in out}) == 1, "parametreler pencere içinde değişmemeli"


def test_walk_forward_plan_geometry() -> None:
    """Pencere sınırları çakışmadan ilerler."""
    plan = WalkForwardPlan(train_bars=100, test_bars=50)
    windows = plan.windows(400)
    assert windows[0] == (0, 100, 100, 150)
    assert windows[1][0] == 50


def test_walk_forward_rejects_bad_sizes() -> None:
    """Geçersiz pencere boyutu hata verir."""
    with pytest.raises(ValueError):
        WalkForwardPlan(train_bars=0, test_bars=10)


def test_ablation_returns_baseline_and_families() -> None:
    """Ablasyon temel çizgi + her aile için sonuç döndürür."""
    df = make_ohlcv(320)
    res = run_ablation(df, TrendFollowerStrategy, families=("A", "B"))
    assert res[0].family == "BASE"
    assert {r.family for r in res} == {"BASE", "A", "B"}
    for r in res:
        assert r.trades >= 0


def test_ablation_disabled_family_changes_conditions() -> None:
    """Ailesi devre dışı bırakılan strateji farklı davranabilmeli (izolasyon)."""
    strat = TrendFollowerStrategy()
    assert strat.family_enabled("A")
    strat.disabled_families = {"A"}
    assert not strat.family_enabled("A")


def test_renderers_include_disclaimer() -> None:
    """Tüm rapor çıktıları 'performans değildir' uyarısını taşır."""
    df = make_ohlcv(320)
    engine = SimpleBacktestEngine(TrendFollowerStrategy()).run(df)
    assert "UYARI" in render_backtest(engine.results())
    wf = render_walk_forward(run_walk_forward(df, TrendFollowerStrategy, train_bars=250, test_bars=50))
    assert "WALK-FORWARD" in wf and "UYARI" in wf
    ab = render_ablation(run_ablation(df, TrendFollowerStrategy, families=("A",)))
    assert "ABLASYON" in ab and "UYARI" in ab
