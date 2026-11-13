# -*- coding: utf-8 -*-
import math

POSITION_RULES = {
    "MAX_OPEN_POSITIONS": float('inf'),
    "ENTRY_MARGIN_USD": 50.0,
    "LEVERAGE": 10,
    "HARD_STOP_LOSS_USD": 25.0,
    "TRAILING_STOP_PERCENT": 0.01,
    "POST_ONLY_EXECUTION": True,
    "MARGIN_MODE": "cross",  # cross veya isolated
    "STARTING_BALANCE": 1000.0,  # 1000$ başlangıç bakiyesi (beta tavanı için kritik)
    "MAX_DRAWDOWN_LIMIT": 0.15,  # Başlangıç bakiyesinden -%15 drawdown koruması
    "RATE_LIMIT_PER_MIN": 3,     # Dakikada maksimum 3 giriş
    "COOLDOWN_MINUTES": 15,      # Stop sonrası 15 dakika yeniden giriş engeli
    "MAX_FUNDING_RATE_THRESHOLD": 0.003,
    "TIME_SYNC_MAX_DELTA_SECONDS": 5,
    "TAKER_FEE": 0.0005,
    "MAKER_FEE": 0.0002,
    "SLIPPAGE_TAKER": 0.0005,
    "SLIPPAGE_MAKER": 0.0000
}
