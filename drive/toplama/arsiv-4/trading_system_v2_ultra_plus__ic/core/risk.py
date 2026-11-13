import pandas as pd
from core.indicators import TechnicalIndicators

class RiskManager:
    """
    Dynamic ATR-based Position Sizing and Multi-stage Risk Allocation.
    Adjusts margin & leverage based on market volatility.
    """
    def __init__(self, initial_balance=1000.0, base_margin=50.0, leverage=10.0, base_risk=25.0):
        self.balance = initial_balance
        self.base_margin = base_margin
        self.leverage = leverage
        self.nominal_position = base_margin * leverage # 500 USDT base
        self.base_risk = base_risk

    def calculate_atr_dynamic_sizing(self, df: pd.DataFrame, entry_price: float, side: str, atr_period=14, atr_multiplier=2.0):
        atr = TechnicalIndicators.calculate_atr(df, period=atr_period).iloc[-1]
        
        # Stop distance is dynamic based on volatility (ATR)
        stop_distance = atr * atr_multiplier
        
        if side == "LONG":
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance
            
        stop_pct = abs(entry_price - stop_price) / entry_price
        
        # Adjust position nominal size so max risk remains exactly base_risk (25 USDT)
        dynamic_nominal = self.base_risk / max(stop_pct, 0.01)
        dynamic_margin = min(dynamic_nominal / self.leverage, self.balance * 0.1) # Max 10% of total balance
        
        return {
            "stop_price": stop_price,
            "stop_pct": stop_pct,
            "dynamic_nominal": dynamic_nominal,
            "dynamic_margin": dynamic_margin
        }

    def can_open_position(self, current_open_positions: int) -> bool:
        required_margin = self.base_margin
        available_margin = self.balance - (current_open_positions * self.base_margin)
        return available_margin >= required_margin
