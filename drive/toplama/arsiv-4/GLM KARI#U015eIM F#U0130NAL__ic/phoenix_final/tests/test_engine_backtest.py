"""Motor + backtest testleri: stop-once semantiği, sonraki-açılış giriş, ücret/funding,
kılıf-çıkışlar (END) ve uçtan uca sentetik backtest."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from phoenix.config import Config
from phoenix.datafeed import to_indexed
from phoenix.engine import Engine
from phoenix.models import Bar, Signal
from phoenix.backtest import run_backtest
from phoenix.sources import PrecomputedSource


class StubSource:
    """Belirli zamanlarda sabit sinyal veren sahte kaynak."""

    def __init__(self, signals: dict[str, list[tuple[pd.Timestamp, Signal]]]):
        self.signals = signals

    def signal(self, sym, ts):
        for t, sig in self.signals.get(sym, []):
            if t == ts:
                return sig, "SIGNAL"
        return None, "THRESHOLD"

    def breadth(self, ts):
        return None


def ts_at(day, hour, minute=0):
    return pd.Timestamp(f"2025-01-{day:02d} {hour:02d}:{minute:02d}", tz="UTC")


def bar(t, o, h, l, c, v=100.0):
    return Bar(int(t.value // 10**6), o, h, l, c, v)


def test_entry_next_open_with_slippage():
    cfg = Config().validate()
    t0 = ts_at(1, 10)
    t1 = ts_at(1, 10, 15)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)  # drift sınırı = 0.5×3 = 1.5 > 1.05
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    assert "X" in eng.pending
    eng.step(t1, {"X": bar(t1, 101, 102, 100, 101.5)})
    p = eng.positions["X"]
    # giriş = sonraki açılış × (1 + slip+halfspread)
    slip = (cfg.risk.slip_bps + cfg.risk.spread_bps / 2) / 10_000
    assert p.entry == pytest.approx(101 * (1 + slip), rel=1e-9)
    assert p.tp1_done is False


def test_stop_wins_on_same_bar():
    cfg = Config().validate()
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    # stop ≈ 101.05 − 4.5 = 96.55; mum low 95 → stop; aynı mumda hedef yok
    eng.step(ts_at(1, 10, 15), {"X": bar(ts_at(1, 10, 15), 101, 103, 95, 101)})
    assert len(eng.trades) == 1
    assert eng.trades[0].reason in ("STOP", "BREAKEVEN")
    assert eng.trades[0].pnl < 0


def test_target_exit_positive_r():
    cfg = Config().validate()
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    # hedef = giriş + 2×(1.5×3) ≈ 110.05; mum high 111 → TARGET
    t1 = ts_at(1, 10, 15)
    eng.step(t1, {"X": bar(t1, 101, 102, 100, 101.5)})
    t2 = ts_at(1, 10, 30)
    eng.step(t2, {"X": bar(t2, 102, 111, 101.5, 110.8)})
    assert len(eng.trades) == 1 and eng.trades[0].reason == "TARGET"
    assert eng.trades[0].r_mult > 1.5


def test_tp1_partial_then_breakeven():
    """r_fav 1R'yi aşar → %35 kısmi + stop başaboya."""
    cfg = Config().validate()
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    t1 = ts_at(1, 10, 15)
    # tp1 eşiği ≈ 101.05 + 4.5 = 105.55; mum high 106 → tp1 tetiklenir
    eng.step(t1, {"X": bar(t1, 101, 106, 100, 104)})
    p = eng.positions["X"]
    assert p.tp1_done
    assert p.stop_kind == "BREAKEVEN"
    assert p.qty < p.qty0


def test_funding_applied_every_8h():
    """Giriş sonraki mumda dolar; funding bir sonraki 8 saatlik sınırda uygulanır."""
    cfg = Config().validate()
    t0 = ts_at(1, 7, 45)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    # 08:00 mumunda giriş dolar (last_funding_k = 08:00 dilimi); 16:00 sınırı long’u yorar
    eng.step(ts_at(1, 8), {"X": bar(ts_at(1, 8), 101, 102, 100, 101.5)})
    eng.step(ts_at(1, 16), {"X": bar(ts_at(1, 16), 101, 102, 100, 101.5)})
    p = eng.positions["X"]
    assert p.funding < 0  # long öder
    # short tarafı funding alır: 08:15 sinyali → 16:00’da dolar → ertesi 00:00’da alır
    t2 = ts_at(1, 8, 15)
    sig2 = Signal(-1, -5.0, atr=3.0, price=101.0, ts=t2)
    eng2 = Engine(cfg, StubSource({"Y": [(t2, sig2)]}), bar_ms=900_000)
    eng2.step(t2, {"Y": bar(t2, 101, 102, 100, 101.5)})
    eng2.step(ts_at(1, 16), {"Y": bar(ts_at(1, 16), 101, 102, 100, 101)})
    eng2.step(ts_at(2, 0), {"Y": bar(ts_at(2, 0), 101, 102, 100, 101)})
    assert eng2.positions["Y"].funding > 0


def test_max_hold_time_exit():
    cfg = Config().validate()
    cfg.exit.max_hold_bars = 2
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    eng.step(ts_at(1, 10, 15), {"X": bar(ts_at(1, 10, 15), 101, 101.5, 100, 101)})
    eng.step(ts_at(1, 10, 30), {"X": bar(ts_at(1, 10, 30), 101, 101.5, 100, 101)})
    eng.step(ts_at(1, 10, 45), {"X": bar(ts_at(1, 10, 45), 101, 101.5, 100, 101)})
    assert any(t.reason == "TIME" for t in eng.trades)


def test_end_closes_all_positions():
    cfg = Config().validate()
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    eng.step(ts_at(1, 10, 15), {"X": bar(ts_at(1, 10, 15), 101, 102, 100, 101.5)})
    eng.finish({"X": bar(ts_at(1, 10, 30), 101, 101.8, 100.5, 101.2)}, ts_at(1, 10, 30))
    assert len(eng.trades) == 1 and eng.trades[0].reason == "END"


def test_fees_deducted_both_ways():
    cfg = Config().validate()
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=1.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 100.5, 99.5, 100.2)})
    # 10:15’te giriş dolar; 10:30’da stop (98.75 altı) kapanır
    eng.step(ts_at(1, 10, 15), {"X": bar(ts_at(1, 10, 15), 100.2, 100.4, 99.0, 99.3)})
    eng.step(ts_at(1, 10, 30), {"X": bar(ts_at(1, 10, 30), 100.0, 100.3, 98.0, 98.5)})
    assert len(eng.trades) == 1
    t = eng.trades[0]
    assert t.fees > 0
    gross = t.side * (t.exit - t.entry) * t.qty
    assert t.pnl < gross  # ücretler eksi


def test_backtest_synthetic_end_to_end():
    """Sentetik veride uçtan uca: motor çalışır, ücret sonrası sonuçlar tutarlıdır."""
    cfg = Config().validate()
    n = 800
    rng = np.random.default_rng(3)
    steps = rng.normal(0.15, 0.5, n)
    price = 100 * np.exp(np.cumsum(steps / 100))
    high = price * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = price * (1 - np.abs(rng.normal(0, 0.005, n)))
    open_ = np.r_[price[0], price[:-1]]
    vol = rng.uniform(100, 1000, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({"ts": (idx.asi8 // 10**6).astype("int64"), "open": open_,
                       "high": np.maximum.reduce([open_, price, high]),
                       "low": np.minimum.reduce([open_, price, low]),
                       "close": price, "volume": vol})
    r = run_backtest({"SYN": df}, cfg)
    for t in r.trades:
        assert t.fees > 0
        assert -6.0 < t.r_mult < 8.0  # makul R aralığı
    assert r.stats.get("OPENED", 0) == len(r.trades)


def test_state_save_load_roundtrip(tmp_path):
    cfg = Config().validate()
    cfg.exec.state_file = str(tmp_path / "state.json")
    t0 = ts_at(1, 10)
    sig = Signal(1, 5.0, atr=3.0, price=100.0, ts=t0)
    eng = Engine(cfg, StubSource({"X": [(t0, sig)]}), bar_ms=900_000)
    eng.step(t0, {"X": bar(t0, 100, 101, 99, 100.5)})
    eng.step(ts_at(1, 10, 15), {"X": bar(ts_at(1, 10, 15), 101, 102, 100, 101.5)})
    bal_before = eng.balance
    eng.save_state(cfg.exec.state_file)
    eng2 = Engine(cfg, StubSource({}), bar_ms=900_000)
    assert eng2.load_state(cfg.exec.state_file)
    assert eng2.balance == bal_before
    assert "X" in eng2.positions
