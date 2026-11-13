import numpy as np
import pandas as pd

class RiskManager:
    def __init__(self, max_net_exposure=5000, btc_shock_threshold=-0.03):
        self.max_net_exposure = max_net_exposure
        self.btc_shock_threshold = btc_shock_threshold
        self.positions = {}
        self.beta_cache = {}

    def calculate_beta(self, symbol_returns, btc_returns):
        """Calculates beta relative to BTC using 5-min intervals over the last 1-2 hours"""
        if len(symbol_returns) < 12 or len(btc_returns) < 12:
            return 1.0
        covariance = np.cov(symbol_returns, btc_returns)[0][1]
        variance = np.var(btc_returns)
        beta = covariance / variance if variance != 0 else 1.0
        return float(np.clip(beta, 0.5, 3.0))

    def btc_shock_stress_test(self, open_positions, next_symbol_beta):
        """Calculates portfolio equity drop if BTC drops by threshold"""
        estimated_loss = 0.0
        for symbol, pos in open_positions.items():
            beta = self.beta_cache.get(symbol, 1.0)
            exposure = pos['nominal_value'] * (1 if pos['side'] == 'LONG' else -1)
            estimated_loss += exposure * beta * self.btc_shock_threshold
        
        return estimated_loss

    def validate_exposure_with_beta(self, open_positions, pending_symbol, pending_beta, pending_exposure):
        net_beta_exposure = 0.0
        for symbol, pos in open_positions.items():
            beta = self.beta_cache.get(symbol, 1.0)
            side_mult = 1 if pos['side'] == 'LONG' else -1
            net_beta_exposure += pos['nominal_value'] * side_mult * beta
            
        net_beta_exposure += pending_exposure * pending_beta
        return abs(net_beta_exposure) <= self.max_net_exposure

################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################################
# End of File metadata ledger framework assembly
