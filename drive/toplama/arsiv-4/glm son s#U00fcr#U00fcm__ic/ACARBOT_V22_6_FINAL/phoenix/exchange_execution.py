"""CCXT execution layer: maker entries, exchange-aware params, protective SL/TP, safe close.

V22 changes
-----------
* Entry price is moved to the MAKER side of a fresh book (LONG bid+tick, SHORT ask-tick),
  never crossing the spread. The old entry (= ask for LONG) is a taker price and a
  post-only order there is rejected by the exchange.
* Per-exchange order params:  Binance {"postOnly": True, "timeInForce": "GTX"} (+positionSide
  in hedge mode); OKX {"tdMode": "cross", "postOnly": True} (+posSide in long/short mode).
* Pre-order sizing via ``sizing.fit_order`` (precision, min amount/notional, bump-or-skip).
* Protective orders validate direction first (LONG: stop < entry < target; SHORT mirrored)
  and against the live mark; an invalid trigger is rejected fail-safe (never sent).
* Orders are NOT blindly retried (duplicate-order risk); a client order id is attached so a
  timeout can be resolved by looking the order up instead of re-sending it.
"""
from __future__ import annotations
import logging
import time
from dataclasses import replace

from .risk import RiskManager
from .sizing import fit_order, meta_from_dict, MarketMeta

log = logging.getLogger("phoenix.exec")


class OrderSkipped(Exception):
    """Business-level refusal before any exchange call (sizing/validation)."""

    def __init__(self, reason: str, info=None):
        super().__init__(reason)
        self.reason = reason
        self.info = info or {}


def validate_protective(side: str, entry: float, stop: float, target: float, mark: float | None = None):
    """Return (ok, reason). side is the POSITION side (LONG/SHORT).

    ``target`` <= 0 means "no exchange-side take profit" (indicator mode): only the stop is validated.
    """
    if min(entry, stop) <= 0 or target < 0:
        return False, "non_positive_price"
    has_tp = target > 0
    if side == "LONG":
        if not (stop < entry and (not has_tp or entry < target)):
            return False, "long_requires_stop<entry<target"
        if mark and not (stop < mark and (not has_tp or mark < target)):
            return False, "long_trigger_would_fire_immediately"
    elif side == "SHORT":
        if not (entry < stop and (not has_tp or target < entry)):
            return False, "short_requires_target<entry<stop"
        if mark and not (mark < stop and (not has_tp or target < mark)):
            return False, "short_trigger_would_fire_immediately"
    else:
        return False, "unknown_side"
    return True, "ok"


def validate_stop_amendment(side: str, stop: float, mark: float | None = None):
    """V22.6: validation for a REPLACEMENT stop (breakeven/trail). Unlike the initial protective
    stop, a trailed stop sits BEYOND entry in profit (LONG: entry < stop < mark), so the only
    hard requirements are a positive trigger on the right side of the live mark."""
    if stop <= 0:
        return False, "non_positive_price"
    if side == "LONG":
        if mark and not stop < mark:
            return False, "long_trigger_would_fire_immediately"
    elif side == "SHORT":
        if mark and not mark < stop:
            return False, "short_trigger_would_fire_immediately"
    else:
        return False, "unknown_side"
    return True, "ok"


class ExchangeExecutor:
    def __init__(self, adapter, cfg):
        self.adapter = adapter
        self.cfg = cfg
        self.risk = RiskManager(cfg)

    # ---- helpers --------------------------------------------------------------
    @property
    def exchange(self) -> str:
        return str(getattr(self.adapter, "exchange_id", "")).upper()

    def _meta(self, symbol) -> MarketMeta | None:
        fn = getattr(self.adapter, "market_meta", None)
        if callable(fn):
            try:
                return meta_from_dict(fn(symbol))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("market_meta failed for %s: %s", symbol, exc)
        if hasattr(self.adapter, "market"):
            try:
                m = self.adapter.market(symbol) or {}
                limits = m.get("limits") or {}
                return MarketMeta(float((limits.get("amount") or {}).get("min") or 0),
                                  float((limits.get("cost") or {}).get("min") or 0),
                                  0.0, 0.0, float(m.get("contractSize") or 1.0))
            except Exception:
                return None
        return None

    def _market_limits(self, symbol):
        m = self._meta(symbol)
        return (m.min_amount, m.min_cost) if m else (0.0, 0.0)

    def position_params(self, position_side: str, closing: bool) -> dict:
        """Exchange-specific hedge/one-way routing for entry (closing=False) or exit orders."""
        ex = self.exchange
        params = {}
        if ex == "BINANCE":
            if self.cfg.binance_pos_mode == "hedge":
                params["positionSide"] = position_side.upper()   # reduceOnly is invalid in hedge mode
            elif closing:
                params["reduceOnly"] = True
        elif ex == "OKX":
            params["tdMode"] = self.cfg.okx_td_mode
            if self.cfg.okx_pos_mode == "long_short":
                params["posSide"] = position_side.lower()
            elif closing:
                params["reduceOnly"] = True
        else:
            if closing:
                params["reduceOnly"] = True
        return params

    def entry_params(self, signal) -> dict:
        params = self.position_params(signal.side, closing=False)
        if self.exchange == "BINANCE":
            params.update({"postOnly": True, "timeInForce": "GTX"})
        else:
            params["postOnly"] = True
        return params

    def maker_price(self, signal):
        """Price on the passive side of the live book; falls back to signal.entry without a book."""
        book_fn = getattr(self.adapter, "order_book", None)
        tick_fn = getattr(self.adapter, "price_tick", None)
        if not callable(book_fn):
            return signal.entry, {"source": "signal_entry"}
        try:
            book = book_fn(signal.symbol, 5)
            bid = float((book.get("bids") or [[0]])[0][0])
            ask = float((book.get("asks") or [[0]])[0][0])
        except Exception as exc:
            return signal.entry, {"source": "signal_entry", "book_error": str(exc)}
        if bid <= 0 or ask <= 0 or ask <= bid:
            return signal.entry, {"source": "signal_entry", "book": "invalid"}
        tick = float(tick_fn(signal.symbol) or 0) if callable(tick_fn) else 0.0
        if tick <= 0:
            tick = max(ask - bid, 0.0) or signal.entry * 1e-6
        if signal.side == "LONG":
            price = min(bid + tick, ask - tick)
            if price < bid:
                price = bid
        else:
            price = max(ask - tick, bid + tick)
            if price > ask:
                price = ask
        return price, {"source": "book", "bid": bid, "ask": ask, "tick": tick}

    # ---- entry ----------------------------------------------------------------
    def prepare(self, signal):
        """Fit + re-price the signal for a maker entry. Raises OrderSkipped on refusal."""
        if signal.qty <= 0 or signal.entry <= 0 or signal.notional <= 0:
            raise OrderSkipped("invalid_signal")
        price, pinfo = self.maker_price(signal)
        shifted = replace(signal, entry=price,
                          stop=signal.stop + (price - signal.entry), target=(signal.target + (price - signal.entry)) if signal.target > 0 else 0.0)
        price_prec = getattr(self.adapter, "price_to_precision", None)
        if callable(price_prec):
            shifted = replace(shifted, entry=price_prec(signal.symbol, shifted.entry))
        meta = self._meta(signal.symbol)
        if meta is not None:
            fitted, reason, info = fit_order(shifted, meta, self.risk, self.cfg)
            if fitted is None:
                raise OrderSkipped(reason, info)
            shifted = fitted
        amount = self.adapter.amount_to_precision(shifted.symbol, shifted.qty)
        if amount <= 0:
            raise OrderSkipped("zero_qty_after_rounding", {"qty": shifted.qty})
        if abs(amount - shifted.qty) > 1e-12:
            shifted = replace(shifted, qty=amount)
        ok, why = validate_protective(shifted.side, shifted.entry, shifted.stop, shifted.target)
        if not ok:
            raise OrderSkipped(f"protective_invalid:{why}")
        return shifted, pinfo

    def send_entry(self, fitted, client_id: str | None = None):
        """Send an already fitted entry. One attempt only; timeouts are resolved by lookup."""
        params = self.entry_params(fitted)
        if client_id:
            params["clientOrderId"] = client_id
        side = "buy" if fitted.side == "LONG" else "sell"
        return self.adapter.create_order(fitted.symbol, "limit", side, fitted.qty, fitted.entry, params)

    def place_entry(self, signal, client_id: str | None = None):
        """Return (order, fitted_signal)."""
        fitted, _pinfo = self.prepare(signal)
        return self.send_entry(fitted, client_id), fitted

    def enter_post_only(self, signal):
        """Backward-compatible wrapper: returns only the order."""
        order, _ = self.place_entry(signal)
        return order

    # ---- misc order ops -------------------------------------------------------
    def cancel(self, order_id, symbol):
        return self.adapter.cancel_order(order_id, symbol)

    def fetch(self, order_id, symbol):
        return self.adapter.fetch_order(order_id, symbol)

    def market_close(self, position):
        side = "sell" if position.side == "LONG" else "buy"
        amount = self.adapter.amount_to_precision(position.symbol, position.qty)
        if amount <= 0:
            raise ValueError("invalid close amount")
        params = self.position_params(position.side, closing=True)
        if not params:
            params = {"reduceOnly": True}
        return self.adapter.create_order(position.symbol, "market", side, amount, None, params)

    # ---- protection -----------------------------------------------------------
    def stop_only(self, signal, filled_amount, mark: float | None = None):
        """V22.6: send ONLY the stopLoss leg (used to re-arm a trailed/breakeven stop in LIVE).
        Validated as a stop AMENDMENT (a trailed stop may sit above entry for a LONG), fail-safe
        like protective_orders; returns a one-item list."""
        if filled_amount <= 0:
            return []
        ok, why = validate_stop_amendment(signal.side, signal.stop, mark)
        if not ok:
            log.error("stop replacement refused for %s %s: %s", signal.exchange, signal.symbol, why)
            return [{"status": "REJECTED", "kind": "stopLoss", "error": f"invalid_protective:{why}"}]
        side = "sell" if signal.side == "LONG" else "buy"
        amount = self.adapter.amount_to_precision(signal.symbol, filled_amount)
        if amount <= 0:
            return []
        base = self.position_params(signal.side, closing=True)
        if self.exchange == "BINANCE":
            return [self._send(signal, "stopLoss", "STOP_MARKET", side, amount,
                               {**base, "stopPrice": signal.stop, "workingType": "MARK_PRICE"})]
        if self.exchange == "OKX":
            res = self._send(signal, "stopLoss", "market", side, amount, {**base, "stopLossPrice": signal.stop})
            if res.get("status") != "SUBMITTED":
                res2 = self._send(signal, "stopLoss", "conditional", side, amount,
                                  {**base, "slTriggerPx": signal.stop, "slOrdPx": "-1"})
                if res2.get("status") == "SUBMITTED":
                    res = res2
                else:
                    res["fallback_error"] = res2.get("error")
            return [res]
        return [self._send(signal, "stopLoss", "market", side, amount, {**base, "stopLossPrice": signal.stop})]

    def protective_orders(self, signal, filled_amount, mark: float | None = None):
        """Place reduce-only SL + TP for ``filled_amount``. Invalid levels are rejected, not sent."""
        if filled_amount <= 0:
            return []
        ok, why = validate_protective(signal.side, signal.entry, signal.stop, signal.target, mark)
        if not ok:
            log.error("protective orders refused for %s %s: %s", signal.exchange, signal.symbol, why)
            return [{"status": "REJECTED", "kind": "stopLoss", "error": f"invalid_protective:{why}"},
                    {"status": "REJECTED", "kind": "takeProfit", "error": f"invalid_protective:{why}"}]
        side = "sell" if signal.side == "LONG" else "buy"
        amount = self.adapter.amount_to_precision(signal.symbol, filled_amount)
        if amount <= 0:
            return []
        base = self.position_params(signal.side, closing=True)
        out = []
        if self.exchange == "BINANCE":
            specs = [
                ("stopLoss", "STOP_MARKET", {"stopPrice": signal.stop, "workingType": "MARK_PRICE"}),
                ("takeProfit", "TAKE_PROFIT_MARKET", {"stopPrice": signal.target, "workingType": "MARK_PRICE"}),
            ]
            if not signal.target or signal.target <= 0:
                specs = specs[:1]
            for kind, order_type, extra in specs:
                out.append(self._send(signal, kind, order_type, side, amount, {**base, **extra}))
        elif self.exchange == "OKX":
            # Preferred: ccxt unified trigger params. Fallback: raw OKX algo fields.
            specs = [
                ("stopLoss", {"stopLossPrice": signal.stop}, {"slTriggerPx": signal.stop, "slOrdPx": "-1"}),
                ("takeProfit", {"takeProfitPrice": signal.target}, {"tpTriggerPx": signal.target, "tpOrdPx": "-1"}),
            ]
            if not signal.target or signal.target <= 0:
                specs = specs[:1]
            for kind, unified, raw in specs:
                res = self._send(signal, kind, "market", side, amount, {**base, **unified})
                if res.get("status") != "SUBMITTED":
                    res2 = self._send(signal, kind, "conditional", side, amount, {**base, **raw})
                    if res2.get("status") == "SUBMITTED":
                        res = res2
                    else:
                        res["fallback_error"] = res2.get("error")
                out.append(res)
        else:
            specs = [
                ("stopLoss", {"stopLossPrice": signal.stop}),
                ("takeProfit", {"takeProfitPrice": signal.target}),
            ]
            if not signal.target or signal.target <= 0:
                specs = specs[:1]
            for kind, extra in specs:
                out.append(self._send(signal, kind, "market", side, amount, {**base, **extra}))
        return out

    def _send(self, signal, kind, order_type, side, amount, params):
        try:
            result = self.adapter.create_order(signal.symbol, order_type, side, amount, None, params)
            return {"status": "SUBMITTED", "kind": kind, "order": result}
        except Exception as exc:
            return {"status": "REJECTED", "kind": kind, "error": str(exc)}
