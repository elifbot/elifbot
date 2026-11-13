"""Deterministic no-network regression tests for v6.1 changes."""
from pathlib import Path

import pytest

from backtest.funding import FundingCoverage, match_funding_symbols
from core.config import SuperConfig
from tools.momentum_research import (Bar, aggregate, ema, load_csv, rsi,
                                     simulate, summary, trend_at)
from tools.validate_strategy import merge_windows

M = 300_000


def bar(t, op=100., hi=101., lo=99., close=100.):
    return Bar(t, op, hi, lo, close, 10.)


def test_aggregation_full_bucket_and_ohlcv():
    rows = [bar(i*M, 100+i, 102+i, 99+i, 101+i) for i in range(3)]
    out, drop = aggregate(rows, 3*M)
    assert drop == 0 and len(out) == 1
    assert (out[0].op, out[0].high, out[0].low, out[0].close, out[0].volume) == (100, 104, 99, 103, 30)


def test_gap_or_duplicate_bucket_is_discarded():
    out, drop = aggregate([bar(0), bar(M), bar(3*M), bar(4*M), bar(5*M)], 3*M)
    assert drop == 1 and len(out) == 1 and out[0].ts == 3*M
    out, drop = aggregate([bar(0), bar(M), bar(M)], 3*M)
    assert not out and drop == 1


def test_invalid_aggregation_multiple():
    with pytest.raises(ValueError):
        aggregate([], 2*M+1)


def test_only_closed_higher_tf_is_visible():
    rows = [bar(0), bar(3600000)]
    fast, slow = [2., 0.], [1., 1.]
    assert trend_at(rows, 3600000, 3599999, fast, slow) == 0
    assert trend_at(rows, 3600000, 3600000, fast, slow) == 1
    assert trend_at(rows, 3600000, 7199999, fast, slow) == 1
    assert trend_at(rows, 3600000, 7200000, fast, slow) == -1


def test_indicator_values_do_not_depend_on_future():
    a = [float(i) for i in range(1, 61)]
    b = a[:40] + [9999.]*20
    assert ema(a, 20)[:40] == ema(b, 20)[:40]
    assert rsi(a)[:40] == rsi(b)[:40]


def test_signal_enters_next_bar_not_signal_bar_and_stop_first():
    rows = [bar(900000, hi=1000, lo=1), bar(1800000, hi=102, lo=98)]
    trade = simulate(rows, 0, 1, 1., .0007, max_bars=1)
    assert trade['entry_ts'] == 1800000
    assert trade['exit_reason'] == 'stop'
    assert trade['gross_r'] == -1
    assert trade['net_r'] < -1


def test_gap_stop_is_not_filled_at_better_stop():
    rows = [bar(900000), bar(1800000), bar(2700000, op=96, hi=97, lo=95, close=96)]
    t = simulate(rows, 0, 1, 2., 0., max_bars=2)
    assert t['exit_reason'] == 'gap_stop' and t['gross_r'] == -2


def test_missing_exit_candle_does_not_fabricate_results():
    rows = [bar(900000), bar(1800000), bar(3600000)]
    assert simulate(rows, 0, 1, 10., .0007, max_bars=2) is None


def test_net_is_gross_less_cost_and_stress_is_worse():
    rows = [bar(900000), bar(1800000, hi=102, lo=99.5)]
    t = simulate(rows, 0, 1, 1., .0007, max_bars=1)
    assert t['net_r'] == pytest.approx(t['gross_r'] - t['cost_r'])
    t['entry_ts'] = 1800000
    s = summary([t], 100)
    assert s['mean_net_r_2x_cost'] < s['mean_net_r']
    assert s['day_bootstrap_95'] is None


def test_csv_invalid_ohlc_rejected(tmp_path):
    f = tmp_path / 'x.csv'
    f.write_text('timestamp,open,high,low,close,volume\n300000,100,99,98,100,1\n')
    with pytest.raises(ValueError):
        load_csv(f)


def test_funding_exchange_key_maps_exactly():
    c = FundingCoverage('BTC-USDT-SWAP', 2, 0, 1, 2, 2)
    rates, state = match_funding_symbols({'BTC-USDT-SWAP': [(1, .01)]},
                                        {'BTC-USDT-SWAP': c}, ['okx:BTC-USDT-SWAP'])
    assert rates['okx:BTC-USDT-SWAP'] == [(1, .01)]
    assert state['durum'] == 'UYGULANDI'


def test_funding_missing_symbol_never_reported_fully_applied():
    c = FundingCoverage('BTC-USDT-SWAP', 2, 0, 1, 2, 2)
    rates, state = match_funding_symbols({'BTC-USDT-SWAP': [(1, .01)]},
                                        {'BTC-USDT-SWAP': c},
                                        ['okx:BTC-USDT-SWAP', 'okx:ETH-USDT-SWAP'])
    assert len(rates) == 1 and state['durum'] == 'EKSIK_KAPSAMA'
    assert state['eslesmeyen_semboller'] == ['okx:ETH-USDT-SWAP']


def test_funding_does_not_match_wrong_instrument():
    rates, state = match_funding_symbols({'BTCUSDT': [(1, .01)]}, {}, ['okx:BTC-USDT-SWAP'])
    assert rates == {} and state['durum'] == 'UYGULANMADI'


def test_disjoint_1m_cache_is_not_full_coverage():
    windows = merge_windows([(1000000, 1060000), (2000000, 2060000)])
    assert len(windows) == 2
    assert not any(a <= 1500000 and 1560000 <= b for a, b in windows)


def test_live_defaults_stay_closed():
    live = SuperConfig().v2.live
    assert live.enabled is False and live.live_allowed_timeframes == ()
    assert live.live_requires_edge_proof


def test_validator_uses_symbol_matching_and_real_windows():
    text = Path('tools/validate_strategy.py').read_text(encoding='utf-8')
    assert 'match_funding_symbols(' in text
    assert '(c.timestamp, c.timestamp + 60_000) for c in rows' in text


def test_validator_strict_cost_coverage_refuses_assumptions(tmp_path):
    from tools.validate_strategy import main
    result = main(['--require-cost-coverage', '--symbols', 'BTC-USDT-SWAP',
                   '--days', '1', '--fine-mode', 'off', '--data-dir', str(tmp_path),
                   '--out', str(tmp_path / 'out.json')])
    assert result == 2 and not (tmp_path / 'out.json').exists()


def test_packaging_gate_stays_closed_without_reference():
    from tools.package_release import check_consistency
    errors, _ = check_consistency()
    if not Path('docs/backtest_referans.json').exists():
        assert any('backtest_referans.json yok' in error for error in errors)
