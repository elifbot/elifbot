from pydantic import BaseModel
from typing import Dict, Any

class RiskConfig(BaseModel):
    max_beta_exposure: float = 3.0
    max_signals_per_minute: int = 5
    btc_shock_threshold_pct: float = -0.03
    max_equity_loss_tolerance: float = 0.05
    reduce_only_stop: bool = True

class BotConfig(BaseModel):
    version: str = "1.2-final"
    env: str = "live"
    risk: RiskConfig = RiskConfig()
