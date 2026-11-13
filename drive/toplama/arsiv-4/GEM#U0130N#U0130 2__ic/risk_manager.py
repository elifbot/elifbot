# Risk ve Sermaye Yönetimi

class RiskManager:
    def __init__(self, stop_loss_pct=0.015, take_profit_pct=0.03):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def check_exit_conditions(self, position: dict, current_price: float) -> str:
        """Pozisyonda Stop-Loss veya Take-Profit tetiklendi mi kontrol eder."""
        if not position:
            return None

        entry_price = position["entry_price"]
        side = position["side"]

        if side == "BUY":
            price_change = (current_price - entry_price) / entry_price
        else:
            price_change = (entry_price - current_price) / entry_price

        if price_change <= -self.stop_loss_pct:
            return "STOP_LOSS"
        elif price_change >= self.take_profit_pct:
            return "TAKE_PROFIT"

        return None
