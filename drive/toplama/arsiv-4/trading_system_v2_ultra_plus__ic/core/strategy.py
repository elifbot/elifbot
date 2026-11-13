import pandas as pd
from core.indicators import TechnicalIndicators
from core.liquidation import LiquidationClusterDetector

class StrategyEngine:
    """
    Combines 15m signal trigger with 1h and 4h trend filters,
    Funding Rate guard, and Stop-Hunt Liquidation Cluster detection.
    """
    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.liq_detector = LiquidationClusterDetector()

    def validate_htf_trend(self, df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> str:
        ema20_1h = self.indicators.calculate_ema(df_1h, 20).iloc[-1]
        ema50_1h = self.indicators.calculate_ema(df_1h, 50).iloc[-1]
        ema200_1h = self.indicators.calculate_ema(df_1h, 200).iloc[-1]
        
        ema20_4h = self.indicators.calculate_ema(df_4h, 20).iloc[-1]
        ema50_4h = self.indicators.calculate_ema(df_4h, 50).iloc[-1]

        if ema20_1h > ema50_1h > ema200_1h and ema20_4h > ema50_4h:
            return "BULLISH"
        elif ema20_1h < ema50_1h < ema200_1h and ema20_4h < ema50_4h:
            return "BEARISH"
        return "NEUTRAL"

    def generate_signal(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame, df_4h: pd.DataFrame, funding_rate: float, orderbook: dict = None):
        htf_trend = self.validate_htf_trend(df_1h, df_4h)
        
        # Check Stop-Hunt Liquidation Cluster
        if orderbook and self.liq_detector.is_stop_hunt_imminent(orderbook):
            return {"action": "HOLD", "reason": "STOP_HUNT_RISK_DETECTED"}

        # Funding rate guard: Skip LONG if funding rate > 0.03%
        if funding_rate > 0.0003 and htf_trend == "BULLISH":
            return {"action": "HOLD", "reason": "HIGH_POSITIVE_FUNDING_RATE"}
        
        if htf_trend == "BULLISH":
            return {"action": "BUY_LONG", "reason": "HTF_ALIGNED_BULLISH"}
        elif htf_trend == "BEARISH":
            return {"action": "SELL_SHORT", "reason": "HTF_ALIGNED_BEARISH"}
        
        return {"action": "HOLD", "reason": "NO_HTF_ALIGNMENT"}
