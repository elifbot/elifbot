class RiskManager:
    """
    Strict 25 USDT fixed loss allocation per trade.
    Nominal position: 500 USDT ($50 margin x 10x leverage).
    """
    def __init__(self, initial_balance=1000.0, margin_per_trade=50.0, leverage=10.0, max_risk_per_trade=25.0):
        self.balance = initial_balance
        self.margin = margin_per_trade
        self.leverage = leverage
        self.nominal_position = margin_per_trade * leverage # 500 USDT
        self.max_risk_per_trade = max_risk_per_trade

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        # Distance to stop loss based on 25 USDT max loss
        # Loss = (entry_price - stop_price) * position_size = 25 USDT
        price_delta_pct = self.max_risk_per_trade / self.nominal_position # 25 / 500 = 5%
        
        if side == "LONG":
            return entry_price * (1.0 - price_delta_pct)
        else:
            return entry_price * (1.0 + price_delta_pct)

    def can_open_position(self, current_open_positions: int) -> bool:
        required_margin = self.margin
        available_margin = self.balance - (current_open_positions * self.margin)
        return available_margin >= required_margin
