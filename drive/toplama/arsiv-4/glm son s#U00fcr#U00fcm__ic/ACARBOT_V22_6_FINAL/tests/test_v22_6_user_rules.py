"""V22.6-FINAL acceptance tests for the user's rules, corrected so they are self-consistent.

1000 USD bankroll | 50 USD MARGIN entry x 10x = 500 USD notional | -$20 stop = ~4% price move
(REAL: inside the ~10% isolated liquidation distance) | NO position-count cap (collateral binds at
~19-20) | ATR never widens the stop | indicator TP only above 0.5R | breakeven + trailing stops |
LONG and SHORT symmetric | no daily/weekly loss halt | LIVE indicator TP available.
The legacy $50-NOTIONAL mode stays available (entry_mode=notional) with a liquidation-aware stop cap.
"""
import time

import pytest

from phoenix.config import Config
from phoenix.models import Market, Position, Signal, Snapshot
from phoenix.paper import PaperBroker
from phoenix.position_manager import PositionManager
from phoenix.risk import RiskManager
from phoenix.strategy import Strategy
from tests.test_v22_regressions import signal


def _snap(price=100.0, atr_pct=0.0, bull=True, rsi=None, price_chg=0.0):
    m = Market("BINANCE", "AAA/USDT:USDT", "AAA", "USDT", "USDT", "swap")
    v = 0.8 if bull else -0.8
    s = Snapshot(m, 1, price, price - 0.01, price + 0.01, 1.0, 50_000_000, 0, 0, v, v + .1 * (1 if bull else -1), v, 0.7 if bull else -0.7, v, False,
                 True, True, False, 1.0, atr_pct)
    if rsi is not None:
        s.rsi_14 = float(rsi)
        s.rsi_available = True
    s.price_chg_pct = price_chg
    return s


# ---- rules 1/2: $50 MARGIN x 10x = $500 notional ----------------------------------------------
def test_defaults_are_1000_equity_50_margin_10x_500_notional_20_stop():
    c = Config()
    assert (c.reference_equity, c.entry_mode, c.entry_margin_usd, c.leverage) == (1000, "margin", 50, 10)
    assert c.entry_notional_usd == 500
    assert c.entry_margin_effective == 50
    assert c.max_loss_usd == 20


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_signal_notional_is_500_and_margin_is_50(side):
    sig = Strategy(Config(min_score=.3)).evaluate(_snap(bull=side == "LONG"))
    assert sig is not None and sig.side == side
    assert sig.notional == pytest.approx(500, rel=1e-6) and sig.margin == pytest.approx(50, rel=1e-6)
    assert sig.qty * sig.entry == pytest.approx(500, rel=1e-6)


def test_notional_mode_still_available_for_legacy_50_usd_notional():
    c = Config(entry_mode="notional", entry_notional_usd=50)
    assert c.entry_notional_usd == 50 and c.entry_margin_effective == 5
    sig = Strategy(Config(entry_mode="notional", entry_notional_usd=50, min_score=.3)).evaluate(_snap())
    assert sig.notional == pytest.approx(50, rel=1e-6)


# ---- rule 3: the -$20 stop is now REAL ----------------------------------------------------------
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_modeled_net_loss_at_stop_is_20_usd_including_costs(side):
    cfg = Config()
    risk = RiskManager(cfg)
    entry = 100.0
    qty = 500 / entry
    fee = risk.estimated_entry_fee(500)
    stop = risk.stop_price(entry, side, qty, 1.0, fee)
    # -$20 budget minus reserved fees/slippage -> ~3.86% price move (well inside the 7% cap)
    assert abs(entry - stop) / entry == pytest.approx(0.04, abs=0.002)
    pos = Position("1", "BINANCE", "AAA/USDT:USDT", side, entry, qty, 500, 50, stop, 0.0, 0, entry_fee=fee)
    assert pos.net_pnl(stop, cfg.fee_bps_per_side, cfg.slippage_bps_reserve) == pytest.approx(-20.0, abs=0.01)


def test_contract_size_does_not_change_the_dollar_budget():
    cfg = Config()
    risk = RiskManager(cfg)
    entry, cs = 100.0, 0.01
    qty_contracts = 500 / (entry * cs)
    fee = risk.estimated_entry_fee(500)
    stop = risk.stop_price(entry, "LONG", qty_contracts, cs, fee)
    pos = Position("1", "OKX", "AAA/USDT:USDT", "LONG", entry, qty_contracts, 500, 50, stop, 0.0, 0, entry_fee=fee, contract_size=cs)
    assert pos.net_pnl(stop, cfg.fee_bps_per_side, cfg.slippage_bps_reserve) == pytest.approx(-20.0, abs=0.01)


def test_stop_sits_inside_liquidation_in_margin_mode_and_is_capped_in_notional_mode():
    c = Config()
    assert c.stop_distance_pct_estimate == pytest.approx(0.04)
    assert c.stop_distance_pct_estimate < c.stop_leverage_cap_pct          # 4% < 7%: cap never binds
    assert c.stop_beyond_liquidation is False
    legacy = Config(entry_mode="notional", entry_notional_usd=50)
    assert legacy.stop_distance_pct_estimate == pytest.approx(0.40)        # would be 40% ...
    risk = RiskManager(legacy)
    stop = risk.stop_price(100.0, "LONG", 0.5, 1.0, 0.0)
    assert abs(100.0 - stop) / 100.0 == pytest.approx(legacy.stop_leverage_cap_pct, rel=1e-3)  # ... capped to 7%


# ---- rule 4/5: no arbitrary position-count cap ---------------------------------------------------
def test_no_position_cap_well_past_the_old_20_limit():
    b = PaperBroker(Config(max_open_positions=0), equity=100_000)
    results = [b.submit(signal(symbol=f"U{i}/USDT:USDT")) for i in range(120)]
    assert all(r["status"] == "ACCEPTED" for r in results)
    assert len(b.open_positions()) == 120


def test_only_collateral_stops_new_positions():
    b = PaperBroker(Config(max_open_positions=0), equity=1000)
    results = [b.submit(signal(symbol=f"C{i}/USDT:USDT")) for i in range(40)]
    accepted = [r for r in results if r["status"] == "ACCEPTED"]
    assert 18 <= len(accepted) <= 21                                       # ~$50 margin each on $1000
    reasons = {r["reason"] for r in results if r["status"] != "ACCEPTED"}
    assert reasons == {"reserved_margin_cap"}


def test_loss_halts_are_off_by_default():
    c = Config()
    assert (c.daily_loss_limit_usd, c.weekly_loss_limit_usd, c.max_drawdown_pct) == (0, 0, 1.0)
    d = RiskManager(c).can_enter(1000, [], 0, 500, daily_loss=-900, weekly_loss=-900, peak_equity=2000)
    assert d.allowed


def test_loss_halts_can_still_be_enabled_explicitly():
    c = Config(daily_loss_limit_usd=100)
    assert not RiskManager(c).can_enter(1000, [], 0, 500, daily_loss=-100).allowed


# ---- rule 7: LONG and SHORT evaluated symmetrically ----------------------------------------------
def test_long_and_short_get_mirrored_stops():
    long_sig = Strategy(Config(min_score=.3)).evaluate(_snap(bull=True))
    short_sig = Strategy(Config(min_score=.3)).evaluate(_snap(bull=False))
    assert long_sig.side == "LONG" and short_sig.side == "SHORT"
    assert (long_sig.entry - long_sig.stop) == pytest.approx(short_sig.stop - short_sig.entry, rel=0.01)


# ---- rule 8: the exit engine pays winners properly ------------------------------------------------
def _pos(cfg, side):
    risk = RiskManager(cfg)
    qty = 500 / 100.0
    return Position("1", "BINANCE", "AAA/USDT:USDT", side, 100.0, qty, 500, 50,
                    risk.stop_price(100.0, side, qty, 1.0, risk.estimated_entry_fee(500)), 0.0, 0,
                    entry_fee=risk.estimated_entry_fee(500))


def test_indicator_take_profit_requires_half_r_profit():
    cfg = Config()
    pm = PositionManager(cfg)
    assert cfg.tp_min_net_effective == pytest.approx(10.0)                 # 0.5 x $20
    assert pm.indicator_exit(_pos(cfg, "LONG"), 101.2, 0.05) is None       # ~$5 net: below 0.5R
    assert pm.indicator_exit(_pos(cfg, "LONG"), 102.2, 0.05) == "INDICATOR_TP"   # ~$10+ net: fires
    assert pm.indicator_exit(_pos(cfg, "SHORT"), 97.8, -0.05) == "INDICATOR_TP"
    assert pm.indicator_exit(_pos(cfg, "LONG"), 102.2, 0.60) is None       # momentum still strong
    assert pm.indicator_exit(_pos(cfg, "LONG"), 97.0, -0.5) is None        # losers: stop decides


def test_breakeven_stop_arms_at_half_r_and_locks_costs():
    cfg = Config()
    pm = PositionManager(cfg)
    p = _pos(cfg, "LONG")
    old_stop = p.stop
    pm.check(p, 102.2)                                                      # net ~ $10.3 >= 0.5R: BE arms
    assert p.be_armed and p.stop > old_stop and p.stop >= p.entry           # locked at/above entry
    reason, net = pm.check(p, p.entry)                                      # collapse back to entry
    assert reason == "STOP" and net >= -1.0                                 # no longer a real loser


def test_trailing_stop_locks_profit_after_1r():
    cfg = Config()
    pm = PositionManager(cfg)
    p = _pos(cfg, "LONG")
    pm.check(p, 104.2)                                                      # peak net ~ $20.3: trail arms
    assert p.trail_armed
    assert p.stop > p.entry                                                 # stop trailed far above entry
    reason, net = pm.check(p, 102.0)                                        # give back <= 0.5R from the peak
    assert reason == "STOP" and net >= 5.0                                  # still books a solid profit


def test_paper_broker_runs_the_full_exit_engine_and_reports_payoff():
    b = PaperBroker(Config(), equity=1000)
    s = signal()
    assert b.submit(s)["status"] == "ACCEPTED"
    rec = b.indicator_exit("BINANCE", s.symbol, 102.4, 0.02, now=time.time() + 60)
    assert rec and rec["reason"] == "INDICATOR_TP" and rec["net_pnl"] > 0
    stats = b.summary()["trade_stats"]
    assert stats["avg_win_usd"] > 0 and stats["win_rate"] == 1.0
    assert {"avg_win_usd", "avg_loss_usd", "win_rate", "payoff_ratio", "expectancy_usd"} <= set(stats)


# ---- rule 9: ATR never widens the -20 stop ---------------------------------------------------
def test_atr_default_off_and_does_not_move_stop():
    assert Config().atr_stop_multiplier == 0.0
    a = Strategy(Config(min_score=.3)).evaluate(_snap(atr_pct=0.0005))
    b = Strategy(Config(min_score=.3)).evaluate(_snap(atr_pct=0.0))
    assert a.stop == pytest.approx(b.stop)


# ---- V22.6 signal-quality upgrades ----------------------------------------------------------------
def test_rsi_gate_blocks_overextended_entries():
    cfg = Config(min_score=.3)
    blocked = Strategy(cfg).evaluate(_snap(bull=True, rsi=85.0))
    assert blocked is None
    ok = Strategy(cfg).evaluate(_snap(bull=True, rsi=55.0))
    assert ok is not None and ok.side == "LONG"
    short_blocked = Strategy(cfg).evaluate(_snap(bull=False, rsi=15.0))
    assert short_blocked is None
    assert Strategy(cfg).evaluate(_snap(bull=False, rsi=45.0)) is not None
    # exits are never RSI-gated: score_only ignores the gate
    assert Strategy(cfg).score_only(_snap(bull=True, rsi=85.0))["score"] > 0


def test_oi_price_agreement_flips_oi_component_against_falling_price():
    cfg = Config(min_score=.3)
    # OI building while price FALLS = new shorts: the LONG oi component must turn negative
    d = Strategy(cfg).score_only(_snap(bull=True, price_chg=-1.0))
    assert d["raw_oi"] > 0 and d["oi"] < 0
    # OI building while price RISES = new longs: positive component
    d2 = Strategy(cfg).score_only(_snap(bull=True, price_chg=1.0))
    assert d2["oi"] > 0
    # no price context: legacy raw behaviour
    d3 = Strategy(cfg).score_only(_snap(bull=True, price_chg=0.0))
    assert d3["oi"] == d3["raw_oi"]


def test_conflict_penalty_reduces_score_when_timeframes_disagree():
    m = Market("BINANCE", "AAA/USDT:USDT", "AAA", "USDT", "USDT", "swap")
    # 15m strongly bullish, 1h/4h bearish
    s = Snapshot(m, 1, 100, 99.99, 100.01, 1.0, 50_000_000, 0, 0, 0.5, 0.5, 0.5, 0.8, -0.8, False,
                 True, True, False, 1.0, 0.0)
    d = Strategy(Config()).score_only(s)
    assert d["conflict"] is True and d["score"] == pytest.approx(d["score_raw"] * Config().conflict_penalty)


def test_paper_funding_accrual_charges_every_8h():
    cfg = Config()
    b = PaperBroker(cfg, equity=1000)
    s = signal()
    s.funding_rate = 0.0001                                                 # 0.01% per 8h
    assert b.submit(s)["status"] == "ACCEPTED"
    p = b.open_positions()[0]
    assert p.funding_at_open == pytest.approx(0.0001)
    b.update({("BINANCE", s.symbol): s.entry}, now=p.opened_at + 17 * 3600)
    assert p.funding_paid == pytest.approx(0.0001 * 500 * 2, rel=1e-6)      # 2 full 8h periods


# ---- rule 10: LIVE never starts by accident, but is no longer blocked by the indicator TP ---------
def test_live_is_off_by_default_and_needs_explicit_confirmation(monkeypatch):
    from phoenix.live import LiveConfig
    for k in ("PHOENIX_LIVE_TRADING", "PHOENIX_PAPER_TRADING", "PHOENIX_CONFIRM_LIVE"):
        monkeypatch.delenv(k, raising=False)
    assert LiveConfig.from_env().mode == "READ_ONLY"


# ---- V22.6 LIVE exit engine: bot-managed stop amendment + indicator TP ---------------------------
def test_live_position_control_moves_stop_and_closes_on_tp(tmp_path):
    from phoenix.trading import TradingService
    from phoenix.position_manager import PositionManager

    created = []

    class Ex:
        exchange_id = "BINANCE"

        def amount_to_precision(self, s, a): return a

        def price_to_precision(self, s, p): return p

        def create_order(self, s, t, side, a, p, params):
            created.append({"type": t, "side": side, "params": params})
            return {"id": f"oid-{len(created)}", "status": "open", "type": t}

        def fetch_order(self, oid, s): return {"id": oid, "status": "closed", "filled": 5, "average": 100}

        def cancel_order(self, oid, s): return {"id": oid, "status": "canceled"}

        def market(self, s): return {"limits": {"amount": {"min": 0}, "cost": {"min": 0}}}

    svc = TradingService(Ex(), Config(), str(tmp_path / "state.json"))
    sig = Signal("BINANCE", "BTC/USDT:USDT", "LONG", .9, 100, 96, 0, 500, 50, 1, 5)
    rec = svc.submit(sig, 1000, [], 0)
    rec = svc.reconcile_order(rec["id"])
    assert rec["status"] == "FILLED" and rec["protective_ok"]
    pm = PositionManager(Config())
    # run-up: net >= 1R -> breakeven + trailing stop armed and MOVED on the exchange
    res = svc.position_control(rec, 104.2, 0.5, pm)
    assert res["action"] == "STOP_MOVED" and rec["signal"]["stop"] > 100
    assert rec["stop_amendments"] == 1
    # score fades while net >= 0.5R -> reduce-only market close, protective legs cancelled
    res = svc.position_control(rec, 102.4, 0.0, pm)
    assert res["action"] == "CLOSED_TP" and rec["status"] == "CLOSED_TP" and rec["exit_reason"] == "INDICATOR_TP"
    close = [c for c in created if c["type"] == "market"]
    assert close and close[-1]["params"].get("reduceOnly") is True


def test_live_position_control_holds_when_nothing_fires(tmp_path):
    from phoenix.trading import TradingService
    from phoenix.position_manager import PositionManager

    class Ex(test_live_position_control_moves_stop_and_closes_on_tp.__wrapped__.__globals__["Ex"] if False else object):
        exchange_id = "BINANCE"

        def amount_to_precision(self, s, a): return a

        def price_to_precision(self, s, p): return p

        def create_order(self, s, t, side, a, p, params):
            return {"id": f"oid-{t}-{side}", "status": "open", "type": t}

        def fetch_order(self, oid, s): return {"id": oid, "status": "closed", "filled": 5, "average": 100}

        def cancel_order(self, oid, s): return {"id": oid, "status": "canceled"}

        def market(self, s): return {"limits": {"amount": {"min": 0}, "cost": {"min": 0}}}

    svc = TradingService(Ex(), Config(), str(tmp_path / "state.json"))
    sig = Signal("BINANCE", "BTC/USDT:USDT", "LONG", .9, 100, 96, 0, 500, 50, 1, 5)
    rec = svc.reconcile_order(svc.submit(sig, 1000, [], 0)["id"])
    pm = PositionManager(Config())
    res = svc.position_control(rec, 100.5, 0.6, pm)      # small profit, momentum strong: hold
    assert res["action"] == "HOLD" and rec["status"] == "FILLED"
