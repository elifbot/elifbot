import random

class LatencySlippageSimulator:
    """
    Models execution latency and market orderbook slippage.
    """
    def __init__(self, base_latency_ms=50, slippage_pct=0.0004):
        self.base_latency = base_latency_ms
        self.slippage_pct = slippage_pct

    def apply_slippage(self, price: float, side: str) -> float:
        random_factor = random.uniform(0.5, 1.5)
        impact = price * (self.slippage_pct * random_factor)
        if side == "LONG":
            return price + impact # Suffer negative slippage on entry
        else:
            return price - impact
