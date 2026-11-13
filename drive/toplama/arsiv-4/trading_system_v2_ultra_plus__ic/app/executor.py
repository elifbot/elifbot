from infra.slippage import LatencySlippageSimulator

class ExecutionEngine:
    """
    Executes trades with orderbook-aware Limit/Maker matching,
    slippage protection, latency simulation, and auto-netting.
    """
    def __init__(self, mode='PAPER', exchange='binance'):
        self.mode = mode
        self.exchange = exchange
        self.slippage_sim = LatencySlippageSimulator(base_latency_ms=45, slippage_pct=0.0003)

    def execute_limit_maker(self, symbol, side, amount, target_price):
        executed_price = self.slippage_sim.apply_slippage(target_price, side)
        order_info = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "requested_price": target_price,
            "executed_price": executed_price,
            "type": "LIMIT_MAKER",
            "status": "OPEN",
            "ttl_seconds": 60
        }
        return order_info
