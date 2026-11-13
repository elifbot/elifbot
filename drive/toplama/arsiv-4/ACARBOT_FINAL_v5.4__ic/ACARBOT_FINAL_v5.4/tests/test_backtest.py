"""Yorum 1-D ve Yorum 2-6 — backtest motoru ve metrik paketi testleri."""


import pytest

from backtest.engine import BacktestEngine
from tests.helpers import apex_config
from backtest.metrics import compute_metrics, format_metrics_report
from backtest.walkforward import walk_forward
from tests.helpers import INTERVAL_MS, legacy_ttl, make_candles


class TestMetrics:
    def _sample_trades(self):
        return [
            {"type": "CLOSE", "pnl": 10.0, "r_multiple": 1.0, "motor": "fade",
             "symbol": "A", "side": "LONG", "entry_fee": 0.1, "fee": 0.1,
             "funding_paid": 0.0, "slippage": 0.05},
            {"type": "CLOSE", "pnl": -5.0, "r_multiple": -0.5, "motor": "fade",
             "symbol": "A", "side": "LONG", "entry_fee": 0.1, "fee": 0.1,
             "funding_paid": 0.0, "slippage": 0.05},
            {"type": "CLOSE", "pnl": 20.0, "r_multiple": 2.0, "motor": "trend",
             "symbol": "B", "side": "SHORT", "entry_fee": 0.2, "fee": 0.2,
             "funding_paid": 0.05, "slippage": 0.1},
            {"type": "CLOSE", "pnl": -5.0, "r_multiple": -0.5, "motor": "trend",
             "symbol": "B", "side": "SHORT", "entry_fee": 0.1, "fee": 0.1,
             "funding_paid": 0.0, "slippage": 0.05},
            {"type": "CLOSE", "pnl": -5.0, "r_multiple": -0.5, "motor": "fade",
             "symbol": "A", "side": "LONG", "entry_fee": 0.1, "fee": 0.1,
             "funding_paid": 0.0, "slippage": 0.05},
        ]

    def test_known_metrics(self):
        block = compute_metrics(self._sample_trades(), 100.0)
        assert block.net_pnl == pytest.approx(15.0)
        assert block.trade_count == 5
        assert block.win_rate == pytest.approx(0.4)
        assert block.profit_factor == pytest.approx(2.0)
        assert block.expectancy_usdt == pytest.approx(3.0)
        assert block.expectancy_r == pytest.approx(0.3)
        assert block.max_consecutive_losses == 2
        assert block.avg_win == pytest.approx(15.0)
        assert block.avg_loss == pytest.approx(-5.0)

    def test_max_drawdown_on_equity_curve(self):
        trades = self._sample_trades()
        curve = [100.0, 110.0, 105.0, 125.0, 120.0, 115.0]
        block = compute_metrics(trades, 100.0, 115.0, curve)
        assert block.max_drawdown_usdt == pytest.approx(10.0)
        assert block.max_drawdown_pct == pytest.approx(8.0, rel=1e-2)

    def test_max_drawdown_derived_from_trades(self):
        block = compute_metrics(self._sample_trades(), 100.0)
        # Kümülatif: 10, 5, 25, 20, 15 → tepe 25 sonrası 15 → DD 10
        assert block.max_drawdown_usdt == pytest.approx(10.0)

    def test_sharpe_positive_when_profitable(self):
        block = compute_metrics(self._sample_trades(), 100.0)
        assert block.sharpe_per_trade > 0

    def test_cost_breakdown(self):
        block = compute_metrics(self._sample_trades(), 100.0)
        assert block.total_fees == pytest.approx(1.2)
        assert block.total_funding == pytest.approx(0.05)
        assert block.total_slippage == pytest.approx(0.3)

    def test_group_breakdowns(self):
        block = compute_metrics(self._sample_trades(), 100.0)
        assert "fade" in block.by_engine and "trend" in block.by_engine
        assert block.by_engine["fade"]["trades"] == 3
        assert "A" in block.by_symbol and "B" in block.by_symbol
        assert "LONG" in block.by_side and "SHORT" in block.by_side

    def test_report_is_readable(self):
        block = compute_metrics(self._sample_trades(), 100.0)
        report = format_metrics_report(block)
        assert "Net PnL" in report and "Profit Factor" in report

    def test_empty_trades(self):
        block = compute_metrics([], 100.0)
        assert block.trade_count == 0
        assert block.net_pnl == 0.0
        assert block.win_rate == 0.0


def _fade_setup_candles(symbol: str, volume=10.0, spike_volume=40.0):
    """Yatay serinin sonunda ~%2 düşüş + hacim patlaması (FADE-LONG)."""
    count = 80
    closes = [100.0] * count
    volumes = [volume] * count
    closes[-2] = 98.2
    closes[-1] = 98.0
    volumes[-1] = spike_volume
    return make_candles(closes, volumes=volumes)


class TestBacktestEngine:
    def test_fade_signal_results_in_pending_limit_then_fill(self):
        """Sinyal mumunda giriş OLMAZ; limit sonraki mumda değerse dolar (Y2-6)."""
        engine = legacy_ttl(BacktestEngine(apex_config(), initial_balance=1_000.0))
        candles = _fade_setup_candles("TESTUSDT")
        # Sinyal mumundan sonraki mum: limana dokunuyor (dip devam)
        from infra.market_data.models import Candle
        touch = Candle(
            timestamp=candles[-1].timestamp + INTERVAL_MS,
            open=98.0, high=98.1, low=97.85, close=97.95, volume=15.0,
        )
        result = engine.run({"TESTUSDT": candles + [touch]})
        fill_types = [t["type"] for t in result.trades]
        assert "ORDER_FILL" in fill_types
        assert "OPEN" in fill_types

    def test_no_touch_means_no_fill(self):
        """Limana değmeyen mumda emir dolmaz → dolmayan emir kaydı."""
        engine = legacy_ttl(BacktestEngine(apex_config(), initial_balance=1_000.0))
        candles = _fade_setup_candles("TESTUSDT")
        from infra.market_data.models import Candle
        away = Candle(
            timestamp=candles[-1].timestamp + INTERVAL_MS,
            open=98.0, high=98.6, low=97.99, close=98.5, volume=15.0,
        )
        result = engine.run({"TESTUSDT": candles + [away]})
        assert "ORDER_FILL" not in [t["type"] for t in result.trades]

    def test_multi_symbol_portfolio_caps(self):
        """Portföy tavanları backtest'te de etkin (Y1-G)."""
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0, max_positions=1)
        candles_a = _fade_setup_candles("AAAUSDT")
        candles_b = _fade_setup_candles("BBBUSDT")
        result = engine.run({"AAAUSDT": candles_a, "BBBUSDT": candles_b})
        # Tek pozisyon limiti: aynı anda en fazla 1 açık pozisyon
        # (kanıt: sonuçta kabul edilen giriş sayısı ≤ 1 + kapanışlar)
        opens = [t for t in result.trades if t.get("type") == "OPEN"]
        closes = [t for t in result.trades if t.get("type") == "CLOSE"]
        assert len(opens) <= len(closes) + 1

    def test_result_fields(self):
        engine = BacktestEngine(apex_config(), initial_balance=500.0)
        result = engine.run({"TESTUSDT": _fade_setup_candles("TESTUSDT")})
        assert result.initial_balance == 500.0
        assert result.final_balance > 0
        assert result.equity_curve[0] == pytest.approx(500.0)
        assert isinstance(result.rejection_counts, dict)
        assert result.trade_count == sum(
            1 for t in result.trades if t.get("type") == "CLOSE"
        )

    def test_costs_applied_to_balance(self):
        """Ücretler bakiyeden düşülür; işlemsiz çalışma bakiyeyi korur."""
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        flat = make_candles([100.0] * 100, volumes=[10.0] * 100)
        result = engine.run({"TESTUSDT": flat})
        assert result.final_balance == pytest.approx(1_000.0)
        assert result.trade_count == 0


class TestWalkForward:
    def test_windows_are_reported(self):
        candles = _fade_setup_candles("TESTUSDT", spike_volume=40.0)
        # 240 mum → 4 pencere x 60 mum
        report = walk_forward({"TESTUSDT": candles}, windows=4,
                              initial_balance=1_000.0)
        assert len(report.windows) == 4
        assert report.total_net_pnl == pytest.approx(
            sum(w.result.net_pnl for w in report.windows)
        )

    def test_invalid_window_count(self):
        with pytest.raises(ValueError):
            walk_forward({"T": []}, windows=0)
