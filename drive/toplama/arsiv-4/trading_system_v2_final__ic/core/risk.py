# Risk Manager (25 USDT Risk, Position Netting, Dynamic Stops)
class RiskManager:
    def __init__(self, leverage=10, initial_margin=50):
        self.leverage = leverage
        self.margin = initial_margin
