import time
import pytest
from phoenix.config import Config
from phoenix.exchange_execution import ExchangeExecutor, validate_protective, OrderSkipped
from phoenix.models import Signal
from phoenix.trading import TradingService


class Ad:
    def __init__(self, exchange="BINANCE", bid=99.9, ask=100.1, tick=0.1, min_amount=0.0, min_cost=0.0, step=0.001):
        self.exchange_id = exchange
        self.bid, self.ask, self.tick = bid, ask, tick
        self.meta = {"min_amount": min_amount, "min_cost": min_cost, "amount_step": step, "price_tick": tick, "contract_size": 1.0}
        self.orders, self.cancelled, self.fail_types = [], [], set()
        self.remote = {}                       # order id -> dict
        self.open_orders, self.positions = [], []
        self.equity = 1000.0
        self.realized = 0.0
        self.mark = 100.0
    # market data
    def order_book(self, s, limit=5): return {"bids": [[self.bid, 5]], "asks": [[self.ask, 5]], "timestamp": time.time() * 1000}
    def price_tick(self, s): return self.tick
    def market_meta(self, s): return self.meta
    def amount_to_precision(self, s, a):
        st = self.meta["amount_step"]
        return round(__import__("math").floor(a / st + 1e-9) * st, 8) if st else a
    def price_to_precision(self, s, p): return round(round(p / self.tick) * self.tick, 8)
    def ticker(self, s): return {"last": self.mark}
    # orders
    def create_order(self, s, t, side, a, p, params):
        if t in self.fail_types:
            raise RuntimeError(f"rejected {t}")
        oid = f"o{len(self.orders) + 1}"
        self.orders.append({"id": oid, "symbol": s, "type": t, "side": side, "amount": a, "price": p, "params": dict(params)})
        self.remote.setdefault(oid, {"id": oid, "status": "open", "filled": 0, "average": None})
        return {"id": oid, "status": "open"}
    def cancel_order(self, oid, s):
        self.cancelled.append(oid)
        if self.remote.get(oid, {}).get("status") == "open":
            self.remote[oid]["status"] = "canceled"
        return {}
    def fetch_order(self, oid, s): return dict(self.remote[oid])
    # account
    def fetch_balance(self): return {"info": {"totalMarginBalance": str(self.equity)}, "total": {"USDT": self.equity}, "free": {"USDT": self.equity}}
    def fetch_positions(self): return list(self.positions)
    def fetch_open_orders(self, symbol=None): return list(self.open_orders)
    def fetch_my_trades(self, symbol=None, since=None, limit=None): return [{"info": {"realizedPnl": str(self.realized)}}] if self.realized else []
    def market(self, s): return {"limits": {"amount": {"min": self.meta["min_amount"]}, "cost": {"min": self.meta["min_cost"]}}, "contractSize": 1.0}


def sig(side="LONG", entry=100.0, qty=5.0, symbol="BTC/USDT:USDT", ex="BINANCE"):
    s_ = entry * (0.96 if side == "LONG" else 1.04)
    t_ = entry * (1.08 if side == "LONG" else 0.92)
    return Signal(ex, symbol, side, .5, entry, s_, t_, qty * entry, qty * entry / 10, 1.0, qty, [], 1.0)


# ---------------- maker pricing and params ----------------
def test_long_enters_on_bid_plus_tick_never_crossing_the_ask():
    ex = ExchangeExecutor(Ad(), Config())
    fitted, _ = ex.prepare(sig("LONG", entry=100.1))       # old behaviour: entry == ask (taker)
    assert fitted.entry == pytest.approx(100.0) and fitted.entry < 100.1


def test_short_enters_on_ask_minus_tick():
    ex = ExchangeExecutor(Ad(), Config())
    fitted, _ = ex.prepare(sig("SHORT", entry=99.9))
    assert fitted.entry == pytest.approx(100.0) and fitted.entry > 99.9


def test_one_tick_spread_joins_the_passive_side():
    ex = ExchangeExecutor(Ad(bid=100.0, ask=100.1), Config())
    assert ex.prepare(sig("LONG"))[0].entry == pytest.approx(100.0)
    assert ex.prepare(sig("SHORT"))[0].entry == pytest.approx(100.1)


def test_stop_and_target_shift_with_the_maker_price_keeping_distances():
    s = sig("LONG", entry=100.1)
    fitted, _ = ExchangeExecutor(Ad(), Config()).prepare(s)
    assert fitted.entry - fitted.stop == pytest.approx(s.entry - s.stop, abs=0.11)
    assert fitted.target - fitted.entry == pytest.approx(s.target - s.entry, abs=0.11)


def test_binance_entry_params_gtx_postonly_and_hedge_position_side():
    a = Ad("BINANCE")
    ExchangeExecutor(a, Config()).enter_post_only(sig())
    p = a.orders[-1]["params"]
    assert p["postOnly"] is True and p["timeInForce"] == "GTX" and "reduceOnly" not in p
    a2 = Ad("BINANCE")
    ExchangeExecutor(a2, Config(binance_pos_mode="hedge")).enter_post_only(sig("SHORT"))
    assert a2.orders[-1]["params"]["positionSide"] == "SHORT"


def test_okx_entry_params_tdmode_and_posside():
    a = Ad("OKX")
    ExchangeExecutor(a, Config()).enter_post_only(sig(ex="OKX"))
    p = a.orders[-1]["params"]
    assert p["tdMode"] == "cross" and p["postOnly"] is True and "posSide" not in p
    a2 = Ad("OKX")
    ExchangeExecutor(a2, Config(okx_pos_mode="long_short")).enter_post_only(sig("SHORT", ex="OKX"))
    assert a2.orders[-1]["params"]["posSide"] == "short"


def test_below_minimum_notional_is_skipped_with_reason_before_any_exchange_call():
    a = Ad(min_cost=5000.0, min_amount=1.0, step=1.0)
    with pytest.raises(OrderSkipped) as e:
        ExchangeExecutor(a, Config()).prepare(sig(qty=0.2))
    assert e.value.reason in {"zero_qty_after_rounding", "below_min_notional", "below_min_amount"} and a.orders == []


def test_zero_amount_after_precision_never_reaches_the_exchange():
    a = Ad(step=1.0)
    with pytest.raises(OrderSkipped):
        ExchangeExecutor(a, Config(auto_bump_max_factor=0)).prepare(sig(qty=0.4))


# ---------------- protective orders ----------------
def test_protective_validation_rules():
    assert validate_protective("LONG", 100, 96, 108)[0]
    assert not validate_protective("LONG", 100, 104, 108)[0]
    assert validate_protective("SHORT", 100, 104, 92)[0]
    assert not validate_protective("SHORT", 100, 96, 92)[0]
    assert not validate_protective("LONG", 100, 96, 108, mark=95)[0]       # would fire immediately
    assert not validate_protective("LONG", 0, 96, 108)[0]


def test_invalid_trigger_is_rejected_failsafe_and_nothing_is_sent():
    a = Ad()
    bad = sig("LONG"); bad = Signal(*(bad.exchange, bad.symbol, "LONG", .5, 100, 105, 108, 500, 50, 1, 5, [], 1.0))
    out = ExchangeExecutor(a, Config()).protective_orders(bad, 5)
    assert len(out) == 2 and all(x["status"] == "REJECTED" for x in out) and a.orders == []


def test_okx_protective_uses_unified_params_then_falls_back_to_raw():
    a = Ad("OKX")
    out = ExchangeExecutor(a, Config()).protective_orders(sig(ex="OKX"), 5)
    assert all(x["status"] == "SUBMITTED" for x in out)
    assert "stopLossPrice" in a.orders[0]["params"] and "takeProfitPrice" in a.orders[1]["params"]
    assert a.orders[0]["params"]["reduceOnly"] is True and a.orders[0]["params"]["tdMode"] == "cross"
    b = Ad("OKX"); b.fail_types = {"market", "conditional"}
    out = ExchangeExecutor(b, Config()).protective_orders(sig(ex="OKX"), 5)
    assert all(x["status"] == "REJECTED" for x in out)            # unified failed, raw 'conditional' ... also tried
    c = Ad("OKX"); orig = c.create_order
    def picky(s, t, side, am, p, params):
        if t == "market": raise RuntimeError("unified unsupported")
        return orig(s, t, side, am, p, params)
    c.create_order = picky
    out = ExchangeExecutor(c, Config()).protective_orders(sig(ex="OKX"), 5)
    assert all(x["status"] == "SUBMITTED" for x in out) and "slTriggerPx" in c.orders[0]["params"]


def test_binance_protective_legs_are_reduce_only_mark_price():
    a = Ad("BINANCE")
    ExchangeExecutor(a, Config()).protective_orders(sig(), 5)
    assert [o["type"] for o in a.orders] == ["STOP_MARKET", "TAKE_PROFIT_MARKET"]
    assert all(o["params"]["reduceOnly"] and o["params"]["workingType"] == "MARK_PRICE" for o in a.orders)


# ---------------- trading service ----------------
def svc(tmp_path, a=None, **cfg):
    a = a or Ad()
    return TradingService(a, Config(**cfg), str(tmp_path / "s.json")), a


def test_submit_reports_stage_for_each_gate(tmp_path):
    s, a = svc(tmp_path, max_open_positions=1)
    ok = s.submit(sig(), 1000, [], 0)
    assert ok["status"] == "SUBMITTED" and ok["client_order_id"].startswith("ph")
    dup = s.submit(sig(), 1000, [], 0)
    assert (dup["stage"], dup["reason"]) == ("RISK", "duplicate_open_order")
    s2, a2 = svc(tmp_path / "x" if False else tmp_path, a=Ad(min_cost=1e6))
    skip = s2.submit(sig("LONG", symbol="ETH/USDT:USDT"), 1000, [], 0)
    assert skip["stage"] == "SIZING"


def test_submit_blocked_when_halted(tmp_path):
    s, a = svc(tmp_path)
    st = s.state.load(); st["risk"] = {"halted_reason": "daily_loss_kill_switch"}; s.state.save(st)
    r = s.submit(sig(), 1000, [], 0)
    assert r["status"] == "REJECTED" and r["reason"].startswith("halted:") and a.orders == []


def test_correlation_stage_in_live_path(tmp_path):
    s, a = svc(tmp_path)
    pos = type("P", (), {"symbol": "ETH/USDT:USDT", "side": "LONG", "status": "OPEN", "reserved_margin": 50, "margin": 50})()
    rets = {"BTC/USDT:USDT": [(-1) ** i * .001 * (1 + i / 40) for i in range(40)]}
    rets["ETH/USDT:USDT"] = list(rets["BTC/USDT:USDT"])
    r = s.submit(sig(), 1000, [pos], 0, returns=rets)
    assert (r["stage"], r["reason"]) == ("CORRELATION", "correlation_limit") and a.orders == []


def test_timeout_on_create_is_resolved_by_client_id_not_resent(tmp_path):
    s, a = svc(tmp_path)
    orig = a.create_order
    def flaky(sym, t, side, am, p, params):
        orig(sym, t, side, am, p, params)
        a.open_orders = [{"id": "o1", "clientOrderId": params["clientOrderId"]}]
        raise TimeoutError("request timed out after the order reached the exchange")
    a.create_order = flaky
    r = s.submit(sig(), 1000, [], 0)
    assert r["status"] == "SUBMITTED" and r["exchange_order_id"] == "o1" and len(a.orders) == 1


def test_partial_fill_then_cancel_still_gets_protection(tmp_path):
    s, a = svc(tmp_path)
    rec = s.submit(sig(), 1000, [], 0)
    a.remote[rec["exchange_order_id"]] = {"id": rec["exchange_order_id"], "status": "canceled", "filled": 2.0, "average": 100.0}
    out = s.reconcile_order(rec["id"])
    assert out["status"] == "FILLED" and out["partial_final"] and out["protective_ok"]
    assert len([o for o in a.orders if o["type"] in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}]) == 2
    assert a.orders[-1]["amount"] == pytest.approx(2.0)


def test_protection_failure_flattens_and_retries_until_closed(tmp_path):
    s, a = svc(tmp_path)
    rec = s.submit(sig(), 1000, [], 0)
    a.remote[rec["exchange_order_id"]] = {"id": rec["exchange_order_id"], "status": "closed", "filled": 5.0, "average": 100.0}
    a.fail_types = {"STOP_MARKET", "TAKE_PROFIT_MARKET", "market"}
    out = s.reconcile_order(rec["id"])
    assert out["status"] == "FILLED_PROTECTION_FAILED" and "emergency_close_error" in out
    a.fail_types = set()
    out = s.reconcile_order(rec["id"])
    assert out["status"] == "EMERGENCY_CLOSED"
    assert a.orders[-1]["type"] == "market" and a.orders[-1]["params"]["reduceOnly"] is True


def test_protective_cancel_failure_is_flagged_not_silent(tmp_path):
    s, a = svc(tmp_path)
    rec = {"id": "x", "symbol": "BTC/USDT:USDT", "protective_orders": [{"status": "SUBMITTED", "order": {"id": "p1"}}]}
    a.cancel_order = lambda oid, sym: (_ for _ in ()).throw(RuntimeError("exchange down"))
    assert s._cancel_protective(rec) == 1 and rec["cancel_failed"] is True
    assert rec["protective_orders"][0]["cancel_error"] == "exchange down"
    a.cancel_order = lambda oid, sym: (_ for _ in ()).throw(RuntimeError("Order does not exist"))
    assert s._cancel_protective(rec) == 0 and rec["cancel_failed"] is False


def test_maker_timeout_requotes_when_price_moved_and_gives_up_after_limit(tmp_path):
    s, a = svc(tmp_path, maker_timeout_sec=1, max_requotes=1, requote_bps=1.0, max_chase_bps=50.0)
    rec = s.submit(sig("LONG", entry=100.1), 1000, [], 0)
    first_id = rec["exchange_order_id"]
    st = s.state.load(); st["orders"][rec["id"]]["submitted_at"] -= 5; s.state.save(st)
    a.bid, a.ask = 100.2, 100.4                              # market moved up beyond requote_bps
    out = s.reconcile_order(rec["id"])
    assert first_id in a.cancelled and out["exchange_order_id"] != first_id and out["requotes"] == 1
    assert out["entry_price"] > 100.0
    st = s.state.load(); st["orders"][rec["id"]]["submitted_at"] -= 5; s.state.save(st)
    out = s.reconcile_order(rec["id"])
    assert out["status"] == "EXPIRED" and out["expire_reason"] == "maker_timeout"


def test_requote_respects_chase_limit(tmp_path):
    s, a = svc(tmp_path, maker_timeout_sec=1, max_requotes=2, requote_bps=1.0, max_chase_bps=5.0)
    rec = s.submit(sig("LONG", entry=100.1), 1000, [], 0)
    st = s.state.load(); st["orders"][rec["id"]]["submitted_at"] -= 5; s.state.save(st)
    a.bid, a.ask = 101.0, 101.2                              # ~90 bps away: do not chase
    out = s.reconcile_order(rec["id"])
    assert out["status"] == "EXPIRED" and out["expire_reason"] == "chase_limit"


def test_unchanged_price_keeps_queue_position_instead_of_cancelling(tmp_path):
    s, a = svc(tmp_path, maker_timeout_sec=1, max_requotes=2, requote_bps=5.0)
    rec = s.submit(sig("LONG", entry=100.1), 1000, [], 0)
    st = s.state.load(); st["orders"][rec["id"]]["submitted_at"] -= 5; s.state.save(st)
    out = s.reconcile_order(rec["id"])
    assert a.cancelled == [] and out["requotes"] == 1 and out["status"] == "SUBMITTED"


# ---------------- kill switch ----------------
def _kill_adapter():
    a = Ad(); a.equity = 100.0; a.realized = -100.0
    a.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 1, "side": "long", "initialMargin": 50, "notional": 500, "entryPrice": 100, "markPrice": 90}]
    a.open_orders = [{"id": "e1", "symbol": "ETH/USDT:USDT", "amount": 1, "price": 10, "info": {}},
                     {"id": "p1", "symbol": "BTC/USDT:USDT", "amount": 1, "price": 0, "reduceOnly": True, "info": {"reduceOnly": True}}]
    return a


def test_kill_switch_cancels_entries_first_verifies_then_closes_reduce_only(tmp_path):
    a = _kill_adapter()
    events = []
    a.cancel_order = lambda oid, s: events.append(("cancel", oid)) or (a.open_orders.__setitem__(slice(None), [o for o in a.open_orders if o["id"] != oid]) or {})
    orig = a.create_order
    a.create_order = lambda *x, **k: events.append(("create", x[1])) or orig(*x, **k)
    s = TradingService(a, Config(daily_loss_limit_usd=50), str(tmp_path / "s.json"))
    out = s.reconcile_all()
    kinds = [e[0] + ":" + str(e[1]) for e in events]
    assert kinds[0] == "cancel:e1" and kinds.index("create:market") > 0     # entry cancelled before the close
    assert any(x.get("status") == "CLOSE_SUBMITTED" for x in out if isinstance(x, dict))
    assert ("cancel", "p1") in events                                        # leftover protective leg cleaned up
    risk = s.state.load()["risk"]
    assert risk["halted_reason"] and risk["kill_complete"] is True


def test_kill_switch_unverified_cancel_is_retried_next_cycle_and_blocks_entries(tmp_path):
    a = _kill_adapter()
    a.cancel_order = lambda oid, s: {}                      # cancel "succeeds" but the order stays open
    s = TradingService(a, Config(daily_loss_limit_usd=50), str(tmp_path / "s.json"))
    out = s.reconcile_all()
    assert any(x.get("status") == "ENTRY_CANCEL_UNVERIFIED" for x in out if isinstance(x, dict))
    assert s.state.load()["risk"]["kill_complete"] is False
    assert s.submit(sig(), 1000, [], 0)["reason"].startswith("halted:")
    a.open_orders = [o for o in a.open_orders if o["id"] != "e1"]
    a.positions = []
    s.reconcile_all()
    assert s.state.load()["risk"]["kill_complete"] is True


def test_clear_halt_removes_persisted_halt(tmp_path):
    s, a = svc(tmp_path)
    st = s.state.load(); st["risk"] = {"halted_reason": "x", "halted_at": 1, "kill_complete": True}; s.state.save(st)
    s.clear_halt()
    assert "halted_reason" not in s.state.load()["risk"]
