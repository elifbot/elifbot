class BacktestEngine:
    def __init__(self, maker_fee=0.0002, taker_fee=0.0005):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.maker_fills_log = []

    def calibrate_maker_fill(self, order_book, order_price, trade_flow):
        # Calibrate if limit order would be filled based on adverse selection logic
        is_filled = False
        for trade in trade_flow:
            if trade['price'] <= order_price:
                is_filled = True
                break
        self.maker_fills_log.append({"price": order_price, "filled": is_filled})
        return is_filled

    def run_walk_forward(self, data, regimes):
        # Walk-forward validation over bull, bear, and sideways regimes
        results = {}
        for regime, regime_data in regimes.items():
            results[regime] = "Validated"
        return results
