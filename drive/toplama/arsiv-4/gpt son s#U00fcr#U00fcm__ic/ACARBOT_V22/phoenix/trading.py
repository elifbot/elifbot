from uuid import uuid4
import datetime
import logging
import time
from threading import RLock
from .risk import RiskManager
from .exchange_execution import ExchangeExecutor, OrderSkipped
from .state import StateStore
from .models import Position, Signal
from .portfolio import PortfolioRisk

log = logging.getLogger("phoenix.trading")

TERMINAL = {"FILLED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "EMERGENCY_CLOSED", "UNCONFIRMED"}
OPEN_REMOTE = {"open", "new", "partially_filled", "partial", "pending", "unknown"}


class TradingService:
    """Authenticated execution service; exchange state is authoritative after sync/restart."""
    def __init__(self, adapter, cfg, state_path="state.json"):
        self.adapter = adapter
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self.state = StateStore(state_path)
        self.exec = ExchangeExecutor(adapter, cfg)
        self.portfolio = PortfolioRisk(cfg.correlation_limit, cfg.correlation_window,
                                       cfg.correlation_min_samples, cfg.correlation_same_direction_only)
        self.counters = {}
        # Serialize submit/reconcile/kill-switch state transitions. Multiple loop
        # callbacks must not reserve the same collateral or submit duplicate entries.
        self._lock = RLock()

    @staticmethod
    def _day_start_ms(days=0):
        now = datetime.datetime.now(datetime.timezone.utc)
        start = (now - datetime.timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(start.timestamp() * 1000)

    @staticmethod
    def _trade_pnl(trade):
        info = trade.get("info") or {}
        for key in ("realizedPnl", "realizedProfit", "realized_pnl", "profit"):
            value = info.get(key, trade.get(key))
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return 0.0

    def _risk_state(self):
        st = self.state.load()
        risk = st.setdefault("risk", {})
        return st, risk

    def _market_contract_size(self, symbol, fallback=1.0):
        try:
            market = self.adapter.market(symbol)
            return float(market.get("contractSize") or fallback)
        except Exception:
            return float(fallback)

    def _fetch_realized_trades(self, since):
        if hasattr(self.adapter, "fetch_my_trades_paginated"):
            return self.adapter.fetch_my_trades_paginated(since=since, max_records=5000)
        return self.adapter.fetch_my_trades(since=since, limit=1000) or []

    def account_snapshot(self):
        balance = self.adapter.fetch_balance()
        total = balance.get("total") or {}
        free = balance.get("free") or {}
        info = balance.get("info") or {}
        equity = None
        for key in ("totalEquity", "totalMarginBalance", "equity", "walletBalance", "totalWalletBalance"):
            if info.get(key) is not None:
                try:
                    equity = float(info[key])
                    break
                except (TypeError, ValueError):
                    pass
        if equity is None:
            for key in ("USDT", "USD"):
                if total.get(key) is not None:
                    equity = float(total[key])
                    break
        if equity is None or equity <= 0:
            raise RuntimeError("exchange equity could not be determined")

        raw_positions = self.adapter.fetch_positions() or []
        positions = []
        for raw in raw_positions:
            contracts_raw = raw.get("contracts")
            if contracts_raw is None:
                contracts_raw = raw.get("contractSize")
            try:
                contracts_signed = float(contracts_raw or 0)
            except (TypeError, ValueError):
                contracts_signed = 0.0
            if contracts_signed == 0:
                continue
            side = str(raw.get("side") or "").upper()
            if side not in {"LONG", "SHORT"}:
                side = "LONG" if contracts_signed > 0 else "SHORT"
            qty = abs(contracts_signed)
            symbol = str(raw.get("symbol") or raw.get("id") or "")
            contract_size = self._market_contract_size(symbol, raw.get("contractSize") or 1.0)
            try:
                margin = float(raw.get("initialMargin") or raw.get("margin") or 0)
            except (TypeError, ValueError):
                margin = 0.0
            try:
                notional = abs(float(raw.get("notional") or 0))
            except (TypeError, ValueError):
                notional = 0.0
            mark = float(raw.get("markPrice") or 0)
            entry = float(raw.get("entryPrice") or 0)
            if notional <= 0:
                notional = abs(mark or entry) * qty * contract_size
            # Some CCXT exchange payloads omit initialMargin. Do not treat such
            # positions as free collateral: conservatively estimate their margin.
            if margin <= 0 and notional > 0:
                margin = notional / self.cfg.leverage
            funding = float(raw.get("fundingFee") or 0)
            positions.append(Position(
                id=str(raw.get("id") or symbol), exchange=getattr(self.adapter, "exchange_id", ""), symbol=symbol,
                side=side, entry=entry, qty=qty, notional=notional, margin=max(0.0, margin), stop=0.0, target=0.0,
                opened_at=float(raw.get("timestamp") or int(time.time()*1000)), funding_paid=funding,
                reserved_margin=max(0.0, margin), contract_size=contract_size, highest=mark or entry, lowest=mark or entry,
            ))

        open_orders = self.adapter.fetch_open_orders() or []
        pending_reserved = 0.0
        for order in open_orders:
            info_o = order.get("info") or {}
            reduce_only = bool(order.get("reduceOnly") or info_o.get("reduceOnly"))
            if reduce_only:
                continue
            try:
                amount = float(order.get("remaining") or order.get("amount") or 0)
                price = float(order.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if amount and price:
                contract_size = self._market_contract_size(str(order.get("symbol") or ""), 1.0)
                pending_reserved += abs(amount * price * contract_size) / self.cfg.leverage

        daily_trades = self._fetch_realized_trades(self._day_start_ms())
        weekly_trades = self._fetch_realized_trades(self._day_start_ms(7))
        daily = sum(self._trade_pnl(t) for t in daily_trades)
        weekly = sum(self._trade_pnl(t) for t in weekly_trades)
        timestamp = int(time.time() * 1000)
        return {
            "equity": equity,
            "free": float(free.get("USDT") or free.get("USD") or 0.0),
            "positions": positions,
            "open_orders": open_orders,
            "pending_reserved": pending_reserved,
            "daily_loss": min(0.0, daily),
            "weekly_loss": min(0.0, weekly),
            "timestamp": timestamp,
        }

    def refresh_risk_state(self):
        snapshot = self.account_snapshot()
        st, risk = self._risk_state()
        risk["daily_loss"] = snapshot["daily_loss"]
        risk["weekly_loss"] = snapshot["weekly_loss"]
        risk["peak_equity"] = max(float(risk.get("peak_equity", snapshot["equity"])), snapshot["equity"])
        risk["last_exchange_sync"] = snapshot["timestamp"]
        st["equity"] = snapshot["equity"]
        st["risk"] = risk
        st["exchange"] = {
            "equity": snapshot["equity"], "open_positions": len(snapshot["positions"]),
            "pending_reserved": snapshot["pending_reserved"], "open_orders": snapshot["open_orders"],
            "positions": [self._position_summary(p) for p in snapshot["positions"]],
            "synced_at": snapshot["timestamp"],
        }
        old = {v.get("symbol"): v for v in st.get("positions", {}).values()}
        new = {}
        for p in snapshot["positions"]:
            prior = old.get(p.symbol, {})
            data = {
                "id": p.id, "exchange": p.exchange, "symbol": p.symbol, "side": p.side,
                "entry": p.entry or prior.get("entry", 0), "qty": p.qty, "notional": p.notional,
                "margin": p.margin, "stop": prior.get("stop", 0), "target": prior.get("target", 0),
                "opened_at": prior.get("opened_at", snapshot["timestamp"]), "entry_fee": prior.get("entry_fee", 0),
                "funding_paid": p.funding_paid, "status": "OPEN", "highest": prior.get("highest", p.highest),
                "lowest": prior.get("lowest", p.lowest), "bars_held": prior.get("bars_held", 0),
                "reserved_margin": p.margin, "contract_size": p.contract_size,
            }
            new[p.id] = data
        st["positions"] = new
        self.state.save(st)
        return snapshot

    @staticmethod
    def _position_summary(p):
        return {"id": p.id, "symbol": p.symbol, "side": p.side, "qty": p.qty, "notional": p.notional,
                "margin": p.margin, "entry": p.entry, "mark": p.highest if p.highest else p.entry,
                "funding_paid": p.funding_paid, "contract_size": p.contract_size}

    def _bump(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1

    @staticmethod
    def _is_reduce_only(order):
        info = order.get("info") or {}
        return bool(order.get("reduceOnly") or info.get("reduceOnly") or str(info.get("reduceOnly")).lower() == "true")

    def _mark(self, symbol):
        fn = getattr(self.adapter, "ticker", None)
        if not callable(fn):
            return None
        try:
            last = (fn(symbol) or {}).get("last")
            return float(last) if last else None
        except Exception:
            return None

    def _find_by_client_id(self, cid, symbol=None):
        try:
            orders = self.adapter.fetch_open_orders() or []
        except Exception:
            return None
        for o in orders:
            if str(o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderId") or "") == cid:
                return o
        return None

    def submit(self, signal, equity=None, positions=None, pending_reserved=None, returns=None):
        """Thread-safe SIZING -> RISK -> CORRELATION -> ORDER transaction."""
        with self._lock:
            return self._submit_unlocked(signal, equity, positions, pending_reserved, returns)

    def _submit_unlocked(self, signal, equity=None, positions=None, pending_reserved=None, returns=None):
        """SIZING -> RISK -> CORRELATION -> ORDER. Caller holds self._lock."""
        st, risk = self._risk_state()
        if risk.get("halted_reason"):
            return {"status": "REJECTED", "stage": "RISK", "reason": f"halted:{risk['halted_reason']}"}
        for rec in st.get("orders", {}).values():
            if rec.get("symbol") == signal.symbol and rec.get("exchange") == signal.exchange \
                    and rec.get("status") not in TERMINAL and rec.get("status") != "FILLED_PROTECTION_FAILED":
                return {"status": "REJECTED", "stage": "RISK", "reason": "duplicate_open_order"}
        # SIZING / maker re-pricing (no exchange write yet)
        try:
            fitted, pinfo = self.exec.prepare(signal)
        except OrderSkipped as exc:
            self._bump(f"sizing_skip:{exc.reason}")
            return {"status": "REJECTED", "stage": "SIZING", "reason": exc.reason, "info": exc.info}
        except Exception as exc:
            return {"status": "REJECTED", "stage": "SIZING", "reason": f"order_validation_or_exchange_error:{exc}"}
        has_state_api = all(hasattr(self.adapter, name) for name in ("fetch_balance", "fetch_positions", "fetch_open_orders", "fetch_my_trades"))
        if (equity is None or positions is None or pending_reserved is None) and has_state_api:
            snapshot = self.refresh_risk_state()
            equity = snapshot["equity"] if equity is None else equity
            positions = snapshot["positions"] if positions is None else positions
            pending_reserved = snapshot["pending_reserved"] if pending_reserved is None else pending_reserved
        else:
            equity = self.cfg.reference_equity if equity is None else equity
            positions = () if positions is None else positions
            pending_reserved = 0.0 if pending_reserved is None else pending_reserved
        st, risk = self._risk_state()
        for p in positions:
            if getattr(p, "status", "OPEN") == "OPEN" and str(p.symbol) == signal.symbol:
                return {"status": "REJECTED", "stage": "RISK", "reason": "already_open_symbol"}
        decision = self.risk.can_enter(
            equity, positions, pending_reserved, fitted.notional,
            daily_loss=float(risk.get("daily_loss", 0)), weekly_loss=float(risk.get("weekly_loss", 0)),
            peak_equity=float(risk.get("peak_equity", equity)),
        )
        if not decision.allowed:
            return {"status": "REJECTED", "stage": "RISK", "reason": decision.reason.split(":", 1)[0], "detail": decision.reason}
        if returns:
            res = self.portfolio.evaluate(fitted.symbol, returns, positions, candidate_side=fitted.side)
            if res["blocked"]:
                return {"status": "REJECTED", "stage": "CORRELATION", "reason": "correlation_limit",
                        "detail": f"{res['symbol']}:{res['corr']:.3f}"}
        # ORDER
        ensure = getattr(self.adapter, "ensure_leverage", None)
        if callable(ensure):
            try:
                ensure(fitted.symbol, self.cfg.leverage, "cross")
            except Exception as exc:
                log.error("cross/leverage setup failed for %s; entry blocked: %s", fitted.symbol, exc)
                return {"status": "REJECTED", "stage": "ACCOUNT_MODE", "reason": "cross_or_leverage_setup_failed", "detail": str(exc)}
        cid = "ph" + uuid4().hex[:26]
        try:
            order = self.exec.send_entry(fitted, cid)
        except Exception as exc:
            order = self._find_by_client_id(cid, fitted.symbol)
            if order is None:
                return {"status": "REJECTED", "stage": "ORDER", "reason": f"order_validation_or_exchange_error:{exc}"}
            log.warning("entry %s resolved by client id after error: %s", cid, exc)
        if not order:
            return {"status": "REJECTED", "stage": "ORDER", "reason": "exchange_rejected_order"}
        rec = {
            "id": str(uuid4()), "exchange_order_id": order.get("id") if isinstance(order, dict) else None,
            "client_order_id": cid, "exchange": signal.exchange, "symbol": signal.symbol, "side": signal.side,
            "status": "SUBMITTED", "signal": fitted.__dict__, "original_entry": signal.entry,
            "entry_price": fitted.entry, "submitted_at": time.time(), "requotes": 0,
            "protective_orders": [], "protected_amount": 0.0,
        }
        st.setdefault("orders", {})[rec["id"]] = rec
        risk["peak_equity"] = max(float(risk.get("peak_equity", equity)), equity)
        st["risk"] = risk
        self.state.save(st)
        return rec

    def _signal_from_record(self, sd):
        return Signal(sd["exchange"], sd["symbol"], sd["side"], sd["score"], sd["entry"], sd["stop"], sd["target"],
                       sd["notional"], sd["margin"], sd["created_at"], sd.get("qty", 0), sd.get("reasons", []), sd.get("contract_size", 1.0))

    def _cancel_protective(self, rec):
        """Cancel protective legs. Failures are logged, flagged and retried - never swallowed."""
        failed = 0
        for item in rec.get("protective_orders", []):
            order = item.get("order") or {}
            oid = order.get("id") if isinstance(order, dict) else None
            if oid and not item.get("cancelled"):
                try:
                    self.exec.cancel(oid, rec["symbol"])
                    item["cancelled"] = True
                    item.pop("cancel_error", None)
                except Exception as exc:
                    msg = str(exc)
                    if "not found" in msg.lower() or "does not exist" in msg.lower() or "unknown order" in msg.lower():
                        item["cancelled"] = True      # already gone is a successful cancel
                        continue
                    item["cancel_error"] = msg
                    failed += 1
                    log.error("protective cancel FAILED %s %s: %s", rec["symbol"], oid, exc)
        rec["cancel_failed"] = failed > 0
        return failed

    def _emergency_close(self, rec, sig, qty):
        pos = Position(id=rec["id"], exchange=sig.exchange, symbol=sig.symbol, side=sig.side,
                       entry=rec.get("average") or sig.entry, qty=qty, notional=sig.notional,
                       margin=sig.margin, stop=sig.stop, target=sig.target, opened_at=sig.created_at,
                       contract_size=sig.contract_size)
        try:
            rec["emergency_close"] = self.exec.market_close(pos)
            rec.pop("emergency_close_error", None)
            return True
        except Exception as exc:
            rec["emergency_close_error"] = str(exc)
            log.error("EMERGENCY CLOSE FAILED %s %s: %s", sig.exchange, sig.symbol, exc)
            return False

    def _protect_new_fills(self, rec, sig, filled):
        protected = float(rec.get("protected_amount", 0))
        delta = max(0.0, filled - protected)
        if delta <= 0:
            return True
        additions = self.exec.protective_orders(sig, delta, self._mark(sig.symbol))
        rec["protective_orders"].extend(additions)
        ok = bool(additions) and all(x.get("status") == "SUBMITTED" for x in additions)
        if ok:
            rec["protected_amount"] = protected + delta
            return True
        # fail-safe: remove any leg that did go through, then flatten what was filled
        self._cancel_protective(rec)
        closed = self._emergency_close(rec, sig, filled)
        rec["status"] = "EMERGENCY_CLOSED" if closed else "FILLED_PROTECTION_FAILED"
        rec["protective_ok"] = False
        return False

    def reconcile_order(self, local_id):
        st = self.state.load()
        rec = st.get("orders", {}).get(local_id)
        if not rec:
            return None
        if rec.get("status") in TERMINAL:
            return rec
        sig = self._signal_from_record(rec["signal"])
        if rec.get("status") == "FILLED_PROTECTION_FAILED":      # retry the flatten until it works
            filled = float(rec.get("filled") or 0)
            if filled > 0 and self._emergency_close(rec, sig, filled):
                self._cancel_protective(rec)
                rec["status"] = "EMERGENCY_CLOSED"
            st["orders"][local_id] = rec
            self.state.save(st)
            return rec
        if rec.get("exchange_order_id"):
            remote = self.exec.fetch(rec["exchange_order_id"], rec["symbol"])
            status = str(remote.get("status") or "unknown").lower()
            rec["exchange_status"] = status
            rec["filled"] = float(remote.get("filled") or 0)
            rec["average"] = remote.get("average")
            if rec["filled"] > 0 and not self._protect_new_fills(rec, sig, rec["filled"]):
                st["orders"][local_id] = rec
                self.state.save(st)
                return rec
            if status in {"closed", "filled"} and rec["filled"] > 0:
                items = rec["protective_orders"]
                rec["protective_ok"] = bool(items) and len(items) % 2 == 0 and all(x.get("status") == "SUBMITTED" for x in items)
                rec["status"] = "FILLED" if rec["protective_ok"] else "FILLED_PROTECTION_FAILED"
            elif status in {"canceled", "cancelled", "rejected", "expired"}:
                if rec["filled"] > 0:      # partially filled then cancelled: keep the protected remainder
                    rec["status"] = "FILLED"
                    rec["partial_final"] = True
                    items = rec["protective_orders"]
                    rec["protective_ok"] = bool(items) and all(x.get("status") == "SUBMITTED" for x in items)
                else:
                    rec["status"] = status.upper()
            elif status in OPEN_REMOTE:
                self._handle_resting_entry(rec, sig)
            st["orders"][local_id] = rec
            self.state.save(st)
        return rec

    def _handle_resting_entry(self, rec, sig):
        """Entry still resting: after maker_timeout either keep (price unchanged), requote, or give up."""
        age = time.time() - float(rec.get("submitted_at") or time.time())
        if age < self.cfg.maker_timeout_sec:
            return
        used = int(rec.get("requotes", 0))
        old_price = float(rec.get("entry_price") or sig.entry)
        new_price, _ = self.exec.maker_price(sig)
        move_bps = abs(new_price - old_price) / old_price * 10000 if old_price else 0.0
        chase_bps = (new_price - rec.get("original_entry", sig.entry)) / rec.get("original_entry", sig.entry) * 10000
        if sig.side == "SHORT":
            chase_bps = -chase_bps
        if used >= self.cfg.max_requotes:
            self._cancel_entry(rec, sig, "maker_timeout")
            return
        if move_bps < self.cfg.requote_bps:
            rec["requotes"] = used + 1
            rec["submitted_at"] = time.time()          # still best price on the book: keep queue position
            return
        if chase_bps > self.cfg.max_chase_bps:
            self._cancel_entry(rec, sig, "chase_limit")
            return
        if not self._cancel_entry(rec, sig, None):
            return
        if float(rec.get("filled") or 0) > 0:          # partially filled during cancel: protected above, stop here
            return
        shift = new_price - sig.entry
        new_sig = replace_signal(sig, new_price, shift)
        try:
            order, fitted = self.exec.place_entry(new_sig, "ph" + uuid4().hex[:26])
        except Exception as exc:
            rec["status"] = "EXPIRED"
            rec["expire_reason"] = f"requote_failed:{exc}"
            return
        rec.update({"exchange_order_id": order.get("id"), "signal": fitted.__dict__, "entry_price": fitted.entry,
                    "submitted_at": time.time(), "requotes": used + 1, "status": "SUBMITTED", "filled": 0.0})
        rec["protected_amount"] = 0.0
        rec["protective_orders"] = []

    def _cancel_entry(self, rec, sig, expire_reason):
        """Cancel resting entry and VERIFY with the exchange. Returns True when it is gone."""
        try:
            self.exec.cancel(rec["exchange_order_id"], rec["symbol"])
        except Exception as exc:
            log.warning("entry cancel raised %s; verifying state", exc)
        try:
            remote = self.exec.fetch(rec["exchange_order_id"], rec["symbol"])
        except Exception as exc:
            rec["cancel_unverified"] = str(exc)
            return False
        status = str(remote.get("status") or "").lower()
        rec["filled"] = float(remote.get("filled") or 0)
        rec["average"] = remote.get("average")
        if status in {"canceled", "cancelled", "expired", "closed", "filled", "rejected"}:
            rec.pop("cancel_unverified", None)
            if rec["filled"] > 0:
                self._protect_new_fills(rec, sig, rec["filled"])
                if rec.get("status") not in TERMINAL and rec.get("status") != "FILLED_PROTECTION_FAILED":
                    rec["status"] = "FILLED"
                    rec["partial_final"] = status != "closed" and status != "filled"
                    rec["protective_ok"] = all(x.get("status") == "SUBMITTED" for x in rec["protective_orders"]) and bool(rec["protective_orders"])
            elif expire_reason:
                rec["status"] = "EXPIRED"
                rec["expire_reason"] = expire_reason
            return True
        rec["cancel_unverified"] = f"status={status}"
        return False

    def clear_halt(self):
        st, risk = self._risk_state()
        for k in ("halted_reason", "halted_at", "kill_complete"):
            risk.pop(k, None)
        st["risk"] = risk
        self.state.save(st)

    def enforce_kill_switch(self, snapshot):
        """Order of operations: (1) cancel NEW-entry orders and verify, (2) close positions
        reduce-only, (3) cancel leftover protective legs. Retries on later cycles until flat."""
        st, risk = self._risk_state()
        peak = float(risk.get("peak_equity", snapshot["equity"]))
        dd = (peak - snapshot["equity"]) / peak if peak > 0 else 1.0
        reasons = []
        if snapshot["daily_loss"] <= -self.cfg.daily_loss_limit_usd:
            reasons.append("daily_loss_kill_switch")
        if snapshot["weekly_loss"] <= -self.cfg.weekly_loss_limit_usd:
            reasons.append("weekly_loss_kill_switch")
        if dd >= self.cfg.max_drawdown_pct:
            reasons.append("max_drawdown_kill_switch")
        halted = risk.get("halted_reason")
        if not reasons and not halted:
            return []
        if halted and risk.get("kill_complete") and not snapshot["positions"]:
            return []
        if not halted:
            risk["halted_reason"] = ",".join(reasons)
            risk["halted_at"] = snapshot["timestamp"]
            st["risk"] = risk
            self.state.save(st)      # persist the halt first: no new entries even if later steps fail
        results = []
        # (1) cancel entry orders (reduce-only protective legs stay for now), then verify
        entry_orders = [o for o in snapshot.get("open_orders", []) if not self._is_reduce_only(o)]
        for o in entry_orders:
            try:
                self.exec.cancel(o.get("id"), o.get("symbol"))
                results.append({"symbol": o.get("symbol"), "status": "ENTRY_CANCEL_SENT", "id": o.get("id")})
            except Exception as exc:
                results.append({"symbol": o.get("symbol"), "status": "ENTRY_CANCEL_FAILED", "id": o.get("id"), "error": str(exc)})
        unverified = []
        if entry_orders:
            try:
                still = {str(o.get("id")) for o in (self.adapter.fetch_open_orders() or [])}
                unverified = [o for o in entry_orders if str(o.get("id")) in still]
            except Exception as exc:
                unverified = entry_orders
                results.append({"status": "ENTRY_CANCEL_VERIFY_FAILED", "error": str(exc)})
            for o in unverified:
                results.append({"symbol": o.get("symbol"), "status": "ENTRY_CANCEL_UNVERIFIED", "id": o.get("id")})
        # (2) close positions
        close_failed = 0
        for p in snapshot["positions"]:
            try:
                results.append({"symbol": p.symbol, "status": "CLOSE_SUBMITTED", "order": self.exec.market_close(p)})
            except Exception as exc:
                close_failed += 1
                results.append({"symbol": p.symbol, "status": "CLOSE_FAILED", "error": str(exc)})
        # (3) leftover reduce-only/protective legs of closed symbols
        if snapshot["positions"] and not close_failed:
            symbols = {p.symbol for p in snapshot["positions"]}
            for o in snapshot.get("open_orders", []):
                if self._is_reduce_only(o) and o.get("symbol") in symbols:
                    try:
                        self.exec.cancel(o.get("id"), o.get("symbol"))
                    except Exception as exc:
                        results.append({"symbol": o.get("symbol"), "status": "PROTECTIVE_CANCEL_FAILED", "error": str(exc)})
        st, risk = self._risk_state()
        risk["kill_complete"] = bool(not unverified and not close_failed)
        st["risk"] = risk
        self.state.save(st)
        return results

    def reconcile_all(self):
        snapshot = self.refresh_risk_state()
        kill = self.enforce_kill_switch(snapshot)
        st = self.state.load()
        out = list(kill)
        for local_id in list(st.get("orders", {})):
            try:
                out.append(self.reconcile_order(local_id))
            except Exception as exc:
                out.append({"id": local_id, "status": "RECONCILE_ERROR", "error": str(exc)})
        return out

    def hard_loss_close(self, position):
        return self.exec.market_close(position)


def replace_signal(sig, new_entry, shift):
    from dataclasses import replace
    return replace(sig, entry=new_entry, stop=sig.stop + shift, target=sig.target + shift)
