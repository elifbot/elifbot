"""Risk testleri: boyutlandırma kırpması, uyarlanır kaldıraç, devre kesici, edge kapısı."""
from __future__ import annotations

import pandas as pd
import pytest

from phoenix.config import Config
from phoenix.risk import CircuitBreaker, adaptive_leverage, edge_ratio, liq_distance_pct, size_position


def test_size_position_capped_by_max_notional():
    cfg = Config().validate()
    # devasa equity + küçük stop → notional tavanı kırpma
    qty, risk_usd, lev, why = size_position(1_000_000, 100.0, 0.5, 0.5, cfg)
    assert qty * 100.0 <= cfg.risk.max_notional_per_trade * 1.0001
    assert risk_usd <= 1_000_000 * cfg.risk.risk_per_trade_pct / 100.0 + 1e-6


def test_size_position_scales_with_equity():
    """Tavan devre dışı kaldığında (küçük sermaye) adet sermayeyle doğrusal ölçeklenir."""
    cfg = Config().validate()
    q1, _, _, _ = size_position(1000, 100.0, 2.0, 0.5, cfg)
    q2, _, _, _ = size_position(2000, 100.0, 2.0, 0.5, cfg)
    assert q2 == pytest.approx(2 * q1, rel=1e-6)


def test_adaptive_leverage_derates_with_volatility():
    """ATR% (YÜZDE): 0.5% sakin→5x; 2.0% oynak→3x; 3.5% aşırı→2x."""
    cfg = Config().validate()
    assert adaptive_leverage(0.5, cfg) == cfg.risk.leverage_base
    assert adaptive_leverage(2.0, cfg) < cfg.risk.leverage_base
    assert adaptive_leverage(3.5, cfg) == 2


def test_liq_distance_monotonic():
    cfg = Config().validate()
    assert liq_distance_pct(5, cfg) > liq_distance_pct(10, cfg)
    assert liq_distance_pct(1, cfg) > 90


def test_edge_ratio_zero_when_atr_zero():
    cfg = Config().validate()
    assert edge_ratio(100.0, 0.0, cfg) == 0.0


class CfgStub:
    """Kesici testi için minik sahte cfg."""

    class risk:
        daily_loss_pct = 2.0
        max_consec_losses = 3
        loss_pause_bars = 10
        equity_halt_pct = 20.0

    class exec:
        kill_file = "/tmp/__phx_test_STOP__"


def test_breaker_daily_loss():
    import pathlib

    p = pathlib.Path(CfgStub.exec.kill_file)
    p.unlink(missing_ok=True)
    cfg = Config().validate()
    br = CircuitBreaker(cfg, base_equity=1000.0)
    ts = pd.Timestamp("2025-01-01 00:10", tz="UTC")
    ok, why = br.allow(ts, 1000.0)
    assert ok
    # %3 günlük zarar (1000×0.97=970 altı) → giriş yasak
    ok, why = br.allow(ts, 965.0)
    assert not ok and why == "DAILY_LOSS"


def test_breaker_consec_losses_pause():
    import pathlib

    p = pathlib.Path(CfgStub.exec.kill_file)
    p.unlink(missing_ok=True)
    cfg = Config().validate()
    br = CircuitBreaker(cfg, base_equity=1000.0)
    ts = pd.Timestamp("2025-01-01 00:10", tz="UTC")
    br.on_close(ts, -1.0, bar_ms=900_000)
    br.on_close(ts, -1.0, bar_ms=900_000)
    ok, why = br.allow(ts, 998.0)
    assert ok  # henüz 2 ardışık kayıp (limit 4) — izin var
    br.on_close(ts, -1.0, bar_ms=900_000)  # 3.
    br.on_close(ts, -1.0, bar_ms=900_000)  # 4. ardışık → duraksama
    ok, why = br.allow(ts, 997.0)
    assert not ok and why == "LOSS_PAUSE"
    ok, why = br.allow(ts + pd.Timedelta(minutes=60 * 15 + 5), 997.0)
    assert ok  # 60 bar (15h) sonra açılır


def test_breaker_equity_halt_permanent():
    import pathlib

    p = pathlib.Path(CfgStub.exec.kill_file)
    p.unlink(missing_ok=True)
    cfg = Config().validate()
    br = CircuitBreaker(cfg, base_equity=1000.0)
    ts = pd.Timestamp("2025-01-01 00:10", tz="UTC")
    ok, why = br.allow(ts, 740.0)  # %25+ zarar
    assert not ok and why == "EQUITY_HALT"
    ok2, _ = br.allow(ts + pd.Timedelta(days=5), 900.0)
    assert not ok2  # kalıcı


def test_breaker_kill_file(tmp_path):
    cfg = Config().validate()
    cfg.exec.kill_file = str(tmp_path / "STOP")
    br = CircuitBreaker(cfg, base_equity=1000.0)
    ts = pd.Timestamp("2025-01-01 00:10", tz="UTC")
    ok, why = br.allow(ts, 1000.0)
    assert ok
    (tmp_path / "STOP").write_text("x")
    ok, why = br.allow(ts, 1000.0)
    assert not ok and why == "KILL_FILE"
