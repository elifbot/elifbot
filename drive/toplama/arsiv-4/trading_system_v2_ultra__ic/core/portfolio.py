import pandas as pd
import numpy as np

class PortfolioManager:
    """
    Calculates pairwise Pearson correlations and limits exposure to highly correlated pairs (R > 0.85).
    Tracks Net Directional Delta (Long vs Short Nominal Balance).
    """
    def __init__(self, max_correlation_threshold=0.85):
        self.max_corr = max_correlation_threshold

    def is_correlation_safe(self, symbol: str, price_matrix: pd.DataFrame, active_symbols: list) -> bool:
        if not active_symbols or symbol not in price_matrix.columns:
            return True
            
        corr_matrix = price_matrix.corr()
        for active in active_symbols:
            if active in corr_matrix.columns:
                corr_val = corr_matrix.loc[symbol, active]
                if abs(corr_val) > self.max_corr:
                    return False
        return True

    def calculate_net_exposure(self, active_positions: list) -> dict:
        total_long = sum(p['nominal'] for p in active_positions if p['side'] == 'LONG')
        total_short = sum(p['nominal'] for p in active_positions if p['side'] == 'SHORT')
        return {
            "total_long_usd": total_long,
            "total_short_usd": total_short,
            "net_directional_delta": total_long - total_short
        }
