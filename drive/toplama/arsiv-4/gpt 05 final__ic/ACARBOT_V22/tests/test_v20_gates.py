import json
import pytest
from phoenix.config import Config
from phoenix.models import Signal, Market, Snapshot, Position
from phoenix.paper import PaperBroker
from phoenix.portfolio import PortfolioRisk
from phoenix.risk import RiskManager
from phoenix.sizing import fit_order, MarketMeta
from phoenix.strategy import Strategy


def sig(symbol="BTC/USDT:USDT", side="LONG", entry=100.0, qty=5.0, ex="BINANCE", cs=1.0, score=.5):
    c = Config(); r = RiskManager(c)
    notional = qty * entry * cs
    stop = r.stop_price(entry, side, qty, cs, r.estimated_entry_fee(notional))
    d = abs(entry - stop)
    target = entry + d * c.tp_r if side == "LONG" else entry - d * c.tp_r
    return Signal(ex, symbol, side, score, entry, stop, target, notional, notional / c.leverage, 1.0, qty, [], cs)


# ---------------- correlation ----------------
def _series(sign=1, n=30):
    return [sign * (0.001 if i % 2 else -0.001) * (1 + i / 50) for i in range(n)]


def test_correlation_skips_when_sample_too_small():
    p = PortfolioRisk(.85, 96, min_samples=20)
    pos = Position("1", "B", "ETH/USDT:USDT", "LONG", 1, 1, 1, 1, .5, 2, 0)
    r = p.evaluate("BTC/USDT:USDT", {"BTC/USDT:USDT": [.1, .2, .3, .4], "ETH/USDT:USDT": [.1, .2, .3, .4]}, [pos], "LONG")
    assert not r["blocked"] and r["skipped_reason"] == "insufficient_samples"
    assert p.stats["skipped_insufficient_samples"] == 1


def test_correlation_blocks_same_direction_stacking():
    p = PortfolioRisk(.85, 96, 20)
    pos = Position("1", "B", "ETH/USDT:USDT", "LONG", 1, 1, 1, 1, .5, 2, 0)
    rets = {"BTC/USDT:USDT": _series(), "ETH/USDT:USDT": _series()}
    assert p.evaluate("BTC/USDT:USDT", rets, [pos], "LONG")["blocked"]


def test_positive_correlation_with_opposite_side_is_a_hedge_not_a_block():
    p = PortfolioRisk(.85, 96, 20)
    pos = Position("1", "B", "ETH/USDT:USDT", "SHORT", 1, 1, 1, 1, 2, .5, 0)
    rets = {"BTC/USDT:USDT": _series(), "ETH/USDT:USDT": _series()}
    assert not p.evaluate("BTC/USDT:USDT", rets, [pos], "LONG")["blocked"]


def test_negative_correlation_with_opposite_side_stacks_risk_and_blocks():
    p = PortfolioRisk(.85, 96, 20)
    pos = Position("1", "B", "ETH/USDT:USDT", "SHORT", 1, 1, 1, 1, 2, .5, 0)
    rets = {"BTC/USDT:USDT": _series(1), "ETH/USDT:USDT": _series(-1)}
    assert p.evaluate("BTC/USDT:USDT", rets, [pos], "LONG")["blocked"]


def test_negative_correlation_same_side_is_diversifying_no_abs():
    p = PortfolioRisk(.85, 96, 20)
    pos = Position("1", "B", "ETH/USDT:USDT", "LONG", 1, 1, 1, 1, .5, 2, 0)
    rets = {"BTC/USDT:USDT": _series(1), "ETH/USDT:USDT": _series(-1)}
    assert not p.evaluate("BTC/USDT:USDT", rets, [pos], "LONG")["blocked"]


# ---------------- sizing ----------------
def test_sizing_rounds_down_and_keeps_loss_budget():
    c = Config(); r = RiskManager(c)
    s = sig(qty=5.37, entry=100.0)
    f, reason, _ = fit_order(s, MarketMeta(0.1, 5, 0.1, 0.01, 1.0), r, c)
    assert reason == "ok" and abs(f.qty - 5.3) < 1e-9 and f.notional == pytest.approx(530.0)
    assert f.stop < f.entry < f.target


def test_sizing_bumps_to_exchange_minimum_when_cheap_enough():
    c = Config(auto_bump_max_factor=1.5); r = RiskManager(c)
    s = sig(qty=0.0007, entry=100000.0)            # 70 USD notional; minimum 100 <= 70*1.5
    f, reason, info = fit_order(s, MarketMeta(0.001, 100, 0.001, 0.1, 1.0), r, c)
    assert reason == "auto_bumped" and f.qty == pytest.approx(0.001) and f.notional >= 100
    assert "auto_bumped" in f.reasons and f.stop < f.entry


def test_sizing_skips_when_minimum_is_far_above_target_notional():
    c = Config(); r = RiskManager(c)
    s = sig(qty=0.005, entry=100000.0)             # 500 USD
    f, reason, info = fit_order(s, MarketMeta(0.01, 0, 0.01, 0.1, 1.0), r, c)
    assert f is None and reason in {"zero_qty_after_rounding", "below_min_amount", "below_min_notional"}


def test_sizing_zero_after_rounding_is_reported_not_sent():
    c = Config(auto_bump_max_factor=0); r = RiskManager(c)
    f, reason, _ = fit_order(sig(qty=0.004, entry=100000.0), MarketMeta(0.01, 0, 0.01, 0.1, 1.0), r, c)
    assert f is None and reason == "zero_qty_after_rounding"


# ---------------- paper pipeline ----------------
def broker(tmp_path, **cfg):
    return PaperBroker(Config(**cfg), equity=1000, state_path=str(tmp_path / "p.json"), journal_path=str(tmp_path / "j.jsonl"))


def test_paper_accepts_and_reports_stage_on_each_rejection(tmp_path):
    b = broker(tmp_path, max_open_positions=1)
    ok = b.submit(sig("AAA/USDT:USDT"), returns={}, meta={"min_amount": 0.1, "amount_step": 0.1, "contract_size": 1.0})
    assert ok["status"] == "ACCEPTED"
    dup = b.submit(sig("AAA/USDT:USDT"))
    assert (dup["stage"], dup["reason"]) == ("RISK", "already_open_symbol")
    full = b.submit(sig("BBB/USDT:USDT"))
    assert (full["stage"], full["reason"]) == ("RISK", "max_open_positions")
    tiny = b.submit(sig("CCC/USDT:USDT", qty=0.0001), meta={"min_amount": 1, "amount_step": 1, "contract_size": 1.0})
    assert tiny["stage"] == "SIZING"


def test_paper_correlation_stage_after_risk(tmp_path):
    b = broker(tmp_path)
    assert b.submit(sig("AAA/USDT:USDT"))["status"] == "ACCEPTED"
    rets = {"AAA/USDT:USDT": _series(), "BBB/USDT:USDT": _series()}
    r = b.submit(sig("BBB/USDT:USDT"), returns=rets)
    assert (r["stage"], r["reason"]) == ("CORRELATION", "correlation_limit")


def test_paper_reserved_margin_cap_is_a_risk_rejection(tmp_path):
    b = broker(tmp_path, max_reserved_margin_pct=0.10, max_open_positions=20)
    r = b.submit(sig("AAA/USDT:USDT"))          # needs 50 margin > 100 cap? 1000*0.1=100 -> ok
    assert r["status"] == "ACCEPTED"
    r2 = b.submit(sig("BBB/USDT:USDT"))
    assert r2["stage"] == "RISK" and r2["reason"] == "reserved_margin_cap"


def test_paper_target_stop_time_and_pnl_accounting(tmp_path):
    clock = {"t": 1_000.0}
    b = PaperBroker(Config(max_hold_bars=2), equity=1000, state_path=str(tmp_path / "s.json"),
                    journal_path=str(tmp_path / "j.jsonl"), clock=lambda: clock["t"])
    s = sig("AAA/USDT:USDT")
    assert b.submit(s)["status"] == "ACCEPTED"
    closed = b.update({("BINANCE", "AAA/USDT:USDT"): s.target + 1}, now=clock["t"] + 60)
    assert closed and closed[0]["reason"] == "TARGET" and closed[0]["net_pnl"] > 0
    s2 = sig("BBB/USDT:USDT")
    b.submit(s2)
    closed = b.update({("BINANCE", "BBB/USDT:USDT"): s2.stop - 1}, now=clock["t"] + 120)
    assert closed[0]["reason"] in {"STOP", "HARD_LOSS"} and closed[0]["net_pnl"] < 0
    s3 = sig("CCC/USDT:USDT")
    b.submit(s3)
    closed = b.update({("BINANCE", "CCC/USDT:USDT"): s3.entry}, now=clock["t"] + 3 * 900 + 5)
    assert closed[0]["reason"] == "TIME"
    assert b.stats["closed"] == 3 and abs(b.equity() - (1000 + b.realized_total)) < 1e-9
    rows = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert sum(r["event"] == "CLOSE" for r in rows) == 3


def test_paper_daily_loss_kill_switch_blocks_new_entries(tmp_path):
    b = broker(tmp_path, daily_loss_limit_usd=5)
    s = sig("AAA/USDT:USDT")
    b.submit(s)
    b.update({("BINANCE", "AAA/USDT:USDT"): s.stop - 5})
    r = b.submit(sig("BBB/USDT:USDT"))
    assert (r["stage"], r["reason"]) == ("RISK", "daily_loss_kill_switch")


def test_paper_state_roundtrip_resume(tmp_path):
    b = broker(tmp_path)
    b.submit(sig("AAA/USDT:USDT"))
    b2 = PaperBroker(Config(), equity=1000, state_path=str(tmp_path / "p.json"), resume=True)
    assert len(b2.open_positions()) == 1 and b2.open_positions()[0].symbol == "AAA/USDT:USDT"


# ---------------- strategy alignment ----------------
def _snap(trend, htf):
    m = Market("B", "BTC/USDT:USDT", "BTC", "USDT", "USDT", "swap")
    return Snapshot(m, 1, 100, 99.99, 100.01, 1, 10_000_000, 0, 0, 0.9, 0.9, 0.0, trend, htf, False)


def test_alignment_is_shadow_counted_but_enforced_only_when_enabled():
    s = _snap(0.9, -0.2)
    sig_off, reason, d = Strategy(Config(min_score=.2)).evaluate_details(s)
    assert d["aligned"] is False and sig_off is not None
    sig_on, reason_on, _ = Strategy(Config(min_score=.2, require_alignment=True)).evaluate_details(s)
    assert sig_on is None and reason_on == "alignment_failed"
    ok, _, d2 = Strategy(Config(min_score=.2, require_alignment=True)).evaluate_details(_snap(0.9, 0.5))
    assert ok is not None and d2["aligned"] is True


def test_default_min_score_is_030_and_env_override_works(monkeypatch):
    assert Config().min_score == 0.30 and Config.from_env({}).min_score == 0.30
    assert Config.from_env({"PHOENIX_MIN_SCORE": "0.4"}).min_score == 0.4


def test_new_config_validation():
    with pytest.raises(ValueError):
        Config(okx_pos_mode="weird")
    with pytest.raises(ValueError):
        Config(correlation_min_samples=1)
    c = Config.from_env({"PHOENIX_REQUIRE_ALIGNMENT": "1", "PHOENIX_BINANCE_POS_MODE": "hedge"})
    assert c.require_alignment and c.binance_pos_mode == "hedge"


# ---------------- backtest ----------------
def test_backtest_enters_at_next_bar_open_not_signal_close():
    from phoenix.backtest import Backtester, Bar
    c = Config(max_loss_usd=20, fee_bps_per_side=0, slippage_bps_reserve=0, tp_r=2.0)
    bars = [Bar(1, 100, 100, 100, 100, 0.8),            # signal bar closes at 100
            Bar(2, 110, 111, 109, 110, 0),              # gap: next open is 110, NOT 100
            Bar(3, 110, 205, 109, 204, 0)]
    r = Backtester(c).run(bars)
    # 10x leverage with a 70% liquidation-buffer fraction caps the stop
    # at a 7% adverse move: 3.50 USD modeled risk on a 50 USD notional.
    assert r.trades == 1 and r.net_pnl == pytest.approx(7.0, rel=1e-6)


def test_backtest_ignores_signal_on_last_bar():
    from phoenix.backtest import Backtester, Bar
    assert Backtester(Config()).run([Bar(1, 100, 100, 100, 100, 0.9)]).trades == 0
