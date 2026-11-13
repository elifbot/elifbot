"""CCXT execution adapter with exchange-aware protective order handling."""

class ExchangeExecutor:
    def __init__(self, adapter, cfg):
        self.adapter = adapter
        self.cfg = cfg

    def _market_limits(self, symbol):
        market = self.adapter.market(symbol) if hasattr(self.adapter, "market") else {}
        limits = market.get("limits") or {}
        return float((limits.get("amount") or {}).get("min") or 0), float((limits.get("cost") or {}).get("min") or 0)

    def enter_post_only(self, signal):
        side = "buy" if signal.side == "LONG" else "sell"
        if signal.qty <= 0 or signal.entry <= 0 or signal.notional <= 0:
            raise ValueError("invalid order amount/price/notional")
        amount = self.adapter.amount_to_precision(signal.symbol, signal.qty)
        price = self.adapter.price_to_precision(signal.symbol, signal.entry)
        if amount <= 0 or price <= 0:
            return None
        min_amount, min_cost = self._market_limits(signal.symbol)
        if min_amount and amount < min_amount:
            raise ValueError(f"amount below exchange minimum: {amount} < {min_amount}")
        if min_cost and abs(amount * price * signal.contract_size) < min_cost:
            raise ValueError(f"notional below exchange minimum: {abs(amount * price * signal.contract_size)} < {min_cost}")
        return self.adapter.create_order(signal.symbol, "limit", side, amount, price, {"postOnly": True})

    def cancel(self, order_id, symbol):
        return self.adapter.cancel_order(order_id, symbol)

    def fetch(self, order_id, symbol):
        return self.adapter.fetch_order(order_id, symbol)

    def market_close(self, position):
        side = "sell" if position.side == "LONG" else "buy"
        amount = self.adapter.amount_to_precision(position.symbol, position.qty)
        if amount <= 0:
            raise ValueError("invalid close amount")
        params = {"reduceOnly": True}
        return self.adapter.create_order(position.symbol, "market", side, amount, None, params)

    def protective_orders(self, signal, filled_amount):
        if filled_amount <= 0:
            return []
        if signal.entry <= 0 or signal.stop <= 0 or signal.target <= 0:
            raise ValueError("invalid protective trigger: non-positive price")
        if signal.side == "LONG" and not (signal.stop < signal.entry < signal.target):
            raise ValueError("invalid LONG protective trigger ordering")
        if signal.side == "SHORT" and not (signal.target < signal.entry < signal.stop):
            raise ValueError("invalid SHORT protective trigger ordering")
        side = "sell" if signal.side == "LONG" else "buy"
        exchange = getattr(self.adapter, "exchange_id", "").upper()
        amount = self.adapter.amount_to_precision(signal.symbol, filled_amount)
        if amount <= 0:
            return []
        out = []
        if exchange == "BINANCE":
            specs = [
                ("stopLoss", "STOP_MARKET", signal.stop, {"stopPrice": signal.stop, "reduceOnly": True, "workingType": "MARK_PRICE"}),
                ("takeProfit", "TAKE_PROFIT_MARKET", signal.target, {"stopPrice": signal.target, "reduceOnly": True, "workingType": "MARK_PRICE"}),
            ]
        elif exchange == "OKX":
            specs = [
                ("stopLoss", "conditional", signal.stop, {"tdMode": "cross", "reduceOnly": True, "slTriggerPx": signal.stop, "slOrdPx": "-1"}),
                ("takeProfit", "conditional", signal.target, {"tdMode": "cross", "reduceOnly": True, "tpTriggerPx": signal.target, "tpOrdPx": "-1"}),
            ]
        else:
            specs = [
                ("stopLoss", "market", signal.stop, {"reduceOnly": True, "stopLossPrice": signal.stop}),
                ("takeProfit", "market", signal.target, {"reduceOnly": True, "takeProfitPrice": signal.target}),
            ]
        for kind, order_type, trigger, params in specs:
            if trigger <= 0:
                continue
            try:
                result = self.adapter.create_order(signal.symbol, order_type, side, amount, None, params)
                out.append({"status": "SUBMITTED", "kind": kind, "order": result})
            except Exception as exc:
                out.append({"status": "REJECTED", "kind": kind, "error": str(exc)})
        return out
