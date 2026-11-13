import numpy as np

class RiskManager:
    def __init__(self, max_beta_exposure=3.0, max_btc_shock_loss_pct=0.05):
        self.max_beta_exposure = max_beta_exposure
        self.max_btc_shock_loss_pct = max_btc_shock_loss_pct
        self.positions = {} # symbol: position_size
        self.betas = {} # symbol: beta_value

    def calculate_beta(self, symbol, btc_returns, asset_returns):
        if len(btc_returns) < 12 or len(asset_returns) < 12:
            return 1.0
        covariance = np.cov(asset_returns, btc_returns)[0][1]
        variance = np.var(btc_returns)
        self.betas[symbol] = covariance / variance if variance != 0 else 1.0
        return self.betas[symbol]

    def check_net_beta_exposure(self, symbol, new_size, direction):
        current_beta_exposure = sum(self.positions.get(s, 0) * self.betas.get(s, 1.0) for s in self.positions)
        asset_beta = self.betas.get(symbol, 1.0)
        additional_exposure = new_size * asset_beta * (1 if direction == "LONG" else -1)
        
        if abs(current_beta_exposure + additional_exposure) > self.max_beta_exposure:
            return False
        return True

    def btc_shock_stres_test(self, total_equity, btc_shock_pct=-0.03):
        estimated_loss = 0.0
        for symbol, size in self.positions.items():
            beta = self.betas.get(symbol, 1.0)
            estimated_loss += size * (beta * btc_shock_pct)
        if abs(estimated_loss) / total_equity > self.max_btc_shock_loss_pct:
            return False
        return True
