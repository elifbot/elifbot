"""Risk ve Sermaye Yönetimi Modülü"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, max_daily_loss_pct: float = 5.0, max_slippage_pct: float = 0.30):
        self.max_daily_loss_pct = float(max_daily_loss_pct)
        self.max_slippage_pct = float(max_slippage_pct)
        self.daily_loss = 0.0

    def check_slippage(self, expected_price: float, executed_price: float) -> bool:
        slippage = abs(executed_price - expected_price) / expected_price * 100.0
        if slippage > self.max_slippage_pct:
            logger.warning(f"Slippage sınırı aşıldı! Gerçekleşen: %{slippage:.2f}")
            return False
        return True

    def check_daily_limit(self, current_loss: float) -> bool:
        if current_loss >= self.max_daily_loss_pct:
            logger.error("Günlük maksimum zarar sınırına ulaşıldı! Acil Durum (Kill-Switch) devreye giriyor.")
            return False
        return True