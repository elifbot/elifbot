import numpy as np
from typing import Dict, List

class RiskManager:
    def __init__(self, config):
        self.config = config
        self.active_positions = {} # symbol: nominal_value
        
    def calculate_btc_beta(self, symbol_returns: List[float], btc_returns: List[float]) -> float:
        """Son 1-2 saatin 5 dakikalık getirilerinden BTC betası hesaplar."""
        if len(symbol_returns) < 12 or len(btc_returns) < 12:
            return 1.0 # Güvenli varsayılan değer
        covariance = np.cov(symbol_returns, btc_returns)[0][1]
        btc_variance = np.var(btc_returns)
        return covariance / btc_variance if btc_variance != 0 else 1.0

    def check_beta_exposure_limit(self, current_positions: Dict[str, float], betas: Dict[str, float]) -> bool:
        net_beta_exposure = sum(pos * betas.get(sym, 1.0) for sym, pos in current_positions.items())
        return abs(net_beta_exposure) <= self.config.risk.max_beta_exposure

    def run_btc_shock_test(self, current_positions: Dict[str, float], betas: Dict[str, float], equity: float) -> bool:
        """BTC %3 düşerse portföyün uğrayacağı kaybı simüle eder."""
        simulated_shock = self.config.risk.btc_shock_threshold_pct
        simulated_loss = 0.0
        for sym, nominal in current_positions.items():
            beta = betas.get(sym, 1.0)
            sym_expected_move = simulated_shock * beta
            simulated_loss += nominal * sym_expected_move
            
        max_allowed_loss = equity * self.config.risk.max_equity_loss_tolerance
        return abs(simulated_loss) <= max_allowed_loss
