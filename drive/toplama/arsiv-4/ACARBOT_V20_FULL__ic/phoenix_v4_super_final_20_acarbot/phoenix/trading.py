from uuid import uuid4
import datetime
import time
from .risk import RiskManager
from .exchange_execution import ExchangeExecutor
from .state import StateStore
from .models import Position, Signal
from .portfolio import PortfolioRisk


class TradingService:
    """Authenticated execution service; exchange state is authoritative after sync/restart."""
    def __init__(self, adapter, cfg, state_path="state.json"):
        self.adapter = adapter
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self.state = StateStore(state_path)
        self.exec = ExchangeExecutor(adapter, cfg)
        self.portfolio = PortfolioRisk(cfg.correlation_limit, cfg.correlation_window)

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

    def submit(self, signal, equity=None, positions=None, pending_reserved=None, returns=None):
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
        if returns:
            blocked, symbol, corr = self.portfolio.correlated(signal.symbol, returns, positions)
            if blocked:
                return {"status": "REJECTED", "reason": f"correlation_limit:{symbol}:{corr:.3f}"}
        decision = self.risk.can_enter(
            equity, positions, pending_reserved, signal.notional,
            daily_loss=float(risk.get("daily_loss", 0)), weekly_loss=float(risk.get("weekly_loss", 0)),
            peak_equity=float(risk.get("peak_equity", equity)),
        )
        if not decision.allowed:
            return {"status": "REJECTED", "reason": decision.reason}
        try:
            order = self.exec.enter_post_only(signal)
        except Exception as exc:
            return {"status": "REJECTED", "reason": f"order_validation_or_exchange_error:{exc}"}
        if not order:
            return {"status": "REJECTED", "reason": "exchange_rejected_order"}
        rec = {
            "id": str(uuid4()), "exchange_order_id": order.get("id") if isinstance(order, dict) else None,
            "exchange": signal.exchange, "symbol": signal.symbol, "side": signal.side, "status": "SUBMITTED",
            "signal": signal.__dict__, "protective_orders": [], "protected_amount": 0.0,
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
        for item in rec.get("protective_orders", []):
            order = item.get("order") or {}
            oid = order.get("id") if isinstance(order, dict) else None
            if not oid:
                continue
            try:
                self.exec.cancel(oid, rec["symbol"])
                try:
                    remote = self.exec.fetch(oid, rec["symbol"])
                    status = str(remote.get("status") or "").lower()
                    item["cancel_verified"] = status in {"canceled", "cancelled", "closed", "rejected", "expired"}
                    item["exchange_status_after_cancel"] = status
                    if not item["cancel_verified"]:
                        item["cancel_error"] = f"exchange order still active after cancel: {status or 'unknown'}"
                except Exception as verify_exc:
                    item["cancel_verified"] = False
                    item["cancel_verify_error"] = str(verify_exc)
            except Exception as exc:
                item["cancel_error"] = str(exc)

    def reconcile_order(self, local_id):
        st = self.state.load()
        rec = st.get("orders", {}).get(local_id)
        if not rec:
            return None
        if rec.get("exchange_order_id"):
            remote = self.exec.fetch(rec["exchange_order_id"], rec["symbol"])
            status = str(remote.get("status") or "unknown").lower()
            rec["exchange_status"] = status
            rec["filled"] = float(remote.get("filled") or 0)
            rec["average"] = remote.get("average")
            if status in {"closed", "filled"} and rec["filled"] > 0:
                sig = self._signal_from_record(rec["signal"])
                protected = float(rec.get("protected_amount", 0))
                delta = max(0.0, rec["filled"] - protected)
                if delta > 0:
                    additions = self.exec.protective_orders(sig, delta)
                    rec["protective_orders"].extend(additions)
                    rec["protected_amount"] = protected + delta
                submitted_kinds = {
                    x.get("kind") for x in rec.get("protective_orders", [])
                    if x.get("status") == "SUBMITTED"
                }
                rec["protective_ok"] = (
                    {"stopLoss", "takeProfit"} <= submitted_kinds
                    and rec["protected_amount"] + 1e-12 >= rec["filled"]
                )
                rec["status"] = "FILLED" if rec["protective_ok"] else "FILLED_PROTECTION_FAILED"
                if not rec["protective_ok"]:
                    self._cancel_protective(rec)
                    try:
                        rec["emergency_close"] = self.exec.market_close(Position(
                            id=local_id, exchange=sig.exchange, symbol=sig.symbol, side=sig.side,
                            entry=rec.get("average") or sig.entry, qty=rec["filled"], notional=sig.notional,
                            margin=sig.margin, stop=sig.stop, target=sig.target, opened_at=sig.created_at,
                            contract_size=sig.contract_size
                        ))
                    except Exception as exc:
                        rec["emergency_close_error"] = str(exc)
            elif status in {"canceled", "cancelled", "rejected", "expired"}:
                rec["status"] = status.upper()
            st["orders"][local_id] = rec
            self.state.save(st)
        return rec

    def enforce_kill_switch(self, snapshot):
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
        if not reasons or risk.get("halted_reason"):
            return []
        results = []
        for order in snapshot.get("open_orders", []):
            info = order.get("info") or {}
            reduce_only = bool(order.get("reduceOnly") or info.get("reduceOnly"))
            if reduce_only:
                continue
            oid = order.get("id")
            symbol = order.get("symbol")
            if not oid or not symbol:
                continue
            try:
                self.exec.cancel(oid, symbol)
                results.append({"symbol": symbol, "status": "PENDING_CANCEL_SUBMITTED", "order_id": oid})
            except Exception as exc:
                results.append({"symbol": symbol, "status": "PENDING_CANCEL_FAILED", "order_id": oid, "error": str(exc)})
        for p in snapshot["positions"]:
            try:
                results.append({"symbol": p.symbol, "status": "CLOSE_SUBMITTED", "order": self.exec.market_close(p)})
            except Exception as exc:
                results.append({"symbol": p.symbol, "status": "CLOSE_FAILED", "error": str(exc)})
        risk["halted_reason"] = ",".join(reasons)
        risk["halted_at"] = snapshot["timestamp"]
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
