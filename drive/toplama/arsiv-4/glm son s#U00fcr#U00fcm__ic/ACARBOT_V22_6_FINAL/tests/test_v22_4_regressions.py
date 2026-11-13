"""V22.0.4/V22.0.5: $50 NOTIONAL x10 (~$5 margin), fixed -$20 stop, indicator take profit."""
import pathlib
import time

import pytest

from phoenix import __version__
from phoenix.config import Config
from phoenix.exchange_execution import validate_protective
from phoenix.models import Position, Market, Snapshot
from phoenix.paper import PaperBroker
from phoenix.position_manager import PositionManager
from phoenix.risk import RiskManager
from phoenix.strategy import Strategy
from phoenix.trading import replace_signal
from tests.test_v20_pipeline import make
from tests.test_v22_regressions import signal

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _snap(price=100.0, atr_pct=0.0):
    m = Market("BINANCE", "AAA/USDT:USDT", "AAA", "USDT", "USDT", "swap")
    return Snapshot(m, 1, price, price - 0.01, price + 0.01, 1.0, 50_000_000, 0, 0, 0.8, 0.9, 0.8, 0.7, 0.8, False,
                    True, True, False, 1.0, atr_pct)


# ---- strategy rules ---------------------------------------------------------------------
def test_entry_is_500_notional_10x_50_margin_with_fixed_20_usd_stop():
    cfg = Config(min_score=0.3)
    sig = Strategy(cfg).evaluate(_snap())
    assert sig.notional == pytest.approx(500, rel=1e-6) and sig.margin == pytest.approx(50, rel=1e-6)
    pos = Position("1", "BINANCE", sig.symbol, sig.side, sig.entry, sig.qty, sig.notional, sig.margin, sig.stop,
                   sig.target, 0, entry_fee=RiskManager(cfg).estimated_entry_fee(sig.notional))
    net_at_stop = pos.net_pnl(sig.stop, cfg.fee_bps_per_side, cfg.slippage_bps_reserve)
    assert net_at_stop == pytest.approx(-20.0, abs=0.01)           # stop = -$20 including fees and slippage


def test_atr_does_not_move_the_stop_by_default_but_can_tighten_when_enabled():
    cfg = Config(min_score=0.3)
    a = Strategy(cfg).evaluate(_snap(atr_pct=0.0005))
    b = Strategy(cfg).evaluate(_snap(atr_pct=0.0))
    assert a.stop == pytest.approx(b.stop)
    tight = Strategy(Config(min_score=0.3, atr_stop_multiplier=2.0)).evaluate(_snap(atr_pct=0.0005))
    assert tight.stop > b.stop                                      # LONG: tighter stop is closer to entry
    assert abs(tight.entry - tight.stop) < abs(b.entry - b.stop)


def test_indicator_mode_has_no_fixed_target_and_fixed_rr_still_available():
    assert Strategy(Config(min_score=0.3)).evaluate(_snap()).target == 0.0
    fixed = Strategy(Config(min_score=0.3, tp_mode="fixed_rr")).evaluate(_snap())
    assert fixed.target > fixed.entry


def test_stop_beyond_liquidation_is_flagged_not_refused_by_default():
    cfg = Config()                                                  # $20 stop on $500 = 4%: INSIDE liquidation
    assert cfg.stop_beyond_liquidation is False
    assert cfg.stop_distance_pct_estimate == pytest.approx(0.04)
    notional50 = Config(entry_mode="notional", entry_notional_usd=50)         # legacy $50-notional mode
    assert notional50.stop_distance_pct_estimate == pytest.approx(0.40)
    assert notional50.stop_beyond_liquidation is True
    assert Config(entry_mode="notional", entry_notional_usd=500).stop_beyond_liquidation is False
    with pytest.raises(ValueError):
        Config(entry_mode="notional", entry_notional_usd=50, strict_liquidation_guard=True)   # opt-in hard refusal


# ---- indicator take profit -----------------------------------------------------------------
def _pos(cfg, side="LONG", entry=100.0):
    risk = RiskManager(cfg)
    qty = 500 / entry
    stop = risk.stop_price(entry, side, qty, 1.0, risk.estimated_entry_fee(500))
    return Position("1", "BINANCE", "AAA/USDT:USDT", side, entry, qty, 500, 50, stop, 0.0, 0,
                    entry_fee=risk.estimated_entry_fee(500))


def test_indicator_exit_requires_net_profit_and_a_faded_score():
    cfg = Config()
    pm = PositionManager(cfg)
    p = _pos(cfg)
    assert pm.indicator_exit(p, 102.2, 0.05) == "INDICATOR_TP"       # net >= 0.5R ($10) and score faded
    assert pm.indicator_exit(p, 102.2, 0.45) is None                 # profitable but momentum still strong
    assert pm.indicator_exit(p, 101.2, 0.0) is None                  # +gross (~$6) but below the 0.5R floor
    assert pm.indicator_exit(p, 98.0, -0.5) is None                  # losers are never cut by indicators: stop decides
    s = _pos(cfg, "SHORT")
    assert pm.indicator_exit(s, 97.8, -0.05) == "INDICATOR_TP"       # SHORT uses the mirrored score
    assert pm.indicator_exit(s, 97.8, -0.45) is None
    assert PositionManager(Config(tp_mode="fixed_rr")).indicator_exit(p, 102.2, 0.0) is None


def test_paper_indicator_exit_books_pnl_and_reports_reason_and_exposure():
    broker = PaperBroker(Config(), equity=1000)
    s = signal()
    assert broker.submit(s)["status"] == "ACCEPTED"
    summ = broker.summary()
    assert summ["gross_notional_usd"] == pytest.approx(500, rel=0.01) and summ["net_notional_usd"] == pytest.approx(500, rel=0.01)
    assert 0 < summ["open_risk_usd"] <= 20.01
    assert summ["trade_stats"] is not None                        # V22.6 payoff stats exist
    rec = broker.indicator_exit("BINANCE", s.symbol, 102.4, 0.02, now=time.time() + 60)
    assert rec and rec["reason"] == "INDICATOR_TP" and rec["net_pnl"] > 0
    assert broker.summary()["closed_by_reason"] == {"INDICATOR_TP": 1}
    assert broker.indicator_exit("BINANCE", s.symbol, 102.4, 0.02) is None      # already closed


def test_fixed_rr_mode_still_closes_on_target():
    cfg = Config(tp_mode="fixed_rr")
    broker = PaperBroker(cfg, equity=1000)
    s = signal()
    assert s.target > s.entry
    assert broker.submit(s)["status"] == "ACCEPTED"
    closed = broker.update({("BINANCE", s.symbol): s.target + 1}, now=time.time() + 60)
    assert closed and closed[0]["reason"] == "TARGET"


def test_runner_scores_open_positions_and_closes_on_indicator_exit(tmp_path):
    r = make(tmp_path, max_cycles=1, duration_sec=3)
    r.run()
    pos = r.paper.open_positions()[0]
    r._evaluate_open_positions()
    assert r.tm.exit_eval["evaluated"] >= 1 and r.paper.has_open(pos.exchange, pos.symbol)   # strong trend: keep
    pos.entry = pos.entry * 0.97                                    # make it net-profitable vs the 110 mark
    r.strategy.score_only = lambda s: {"score": 0.0}                # indicators fade
    r._evaluate_open_positions()
    assert not r.paper.has_open(pos.exchange, pos.symbol)
    assert r.tm.exit_eval["indicator_tp"] >= 1
    assert r.paper.closed[-1]["reason"] == "INDICATOR_TP"


# ---- exchange protective orders without a take-profit leg ------------------------------------
def test_protective_validation_accepts_stop_only_when_target_is_zero():
    assert validate_protective("LONG", 100, 96, 0.0, 99)[0]
    assert validate_protective("SHORT", 100, 104, 0.0, 101)[0]
    assert not validate_protective("LONG", 100, 101, 0.0)[0]
    assert validate_protective("LONG", 100, 96, 105, 99)[0]


def test_replace_signal_keeps_zero_target_zero():
    from dataclasses import replace
    s = replace(signal(), target=0.0)
    assert replace_signal(s, 101.0, 1.0).target == 0.0


# ---- report / logging --------------------------------------------------------------------------
def test_rejections_are_reported_by_side(tmp_path):
    r = make(tmp_path, max_cycles=1)
    r.tm.record_paper_rejection("RISK", "reserved_margin_cap", "BINANCE:AAA/USDT:USDT:LONG")
    r.tm.record_paper_rejection("RISK", "reserved_margin_cap", "BINANCE:BBB/USDT:USDT:SHORT")
    rep = r.tm.build_report(mode="PAPER", universe_discovered=0, cycles=0, elapsed=0, errors=0, unique_signals=0,
                            signals_seen=0, detail_per_exchange=0, exchanges=[], final=True)
    assert rep["paper_rejections_by_side"] == {"RISK:reserved_margin_cap|LONG": 1, "RISK:reserved_margin_cap|SHORT": 1}


def test_score_log_has_price_and_components(tmp_path):
    log = tmp_path / "scores.jsonl"
    r = make(tmp_path, max_cycles=1, score_log_path=str(log))
    r.run()
    row = __import__("json").loads(log.read_text().splitlines()[0])
    for k in ("px", "atr_pct", "trend", "htf", "oi", "book", "funding", "liquidation", "score"):
        assert k in row


# ---- version single source -------------------------------------------------------------------------
def test_version_is_single_sourced_everywhere():
    from phoenix.telemetry import VERSION
    root = (ROOT / "__init__.py").read_text()
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert VERSION == __version__ and __version__ in root
    assert f'version="{__version__.split("-")[0]}"' in pyproject
