# -*- coding: utf-8 -*-
"""ACARBOT FINAL v2.0 - Central Verified Configuration Matrix."""

import math

SYSTEM_BOT_SETTINGS = {
    "VERSION": "2.0-Production",
    "SCAN_INTERVAL_SECONDS": 10,
    "DEFAULT_MARGIN_MODE": "ISOLATED",  # Supported: "ISOLATED", "CROSS"
    "MAX_OPEN_POSITIONS": float('inf'), # Explicitly unlimited slots based on capital
    "ENTRY_MARGIN_USD": 50.0,
    "LEVERAGE": 10,
    "HARD_STOP_LOSS_USD": 25.0,
    "TRAILING_STOP_PERCENT": 0.01,
    
    # Advanced Fee & Slippage Parameters
    "MAKER_FEE_RATE": 0.0002,          # %0.02 Maker Fee
    "TAKER_FEE_RATE": 0.0005,          # %0.05 Taker Fee
    "SIMULATED_SLIPPAGE_RATE": 0.0005,   # %0.05 Slippage on Market fills
    "POST_ONLY_EXECUTION": True,       # Force passive limit maker routing
    
    # High-Priority Risk and Cooldown Mitigations
    "RE_ENTRY_COOLDOWN_MINUTES": 15,    # 15 minutes strict token cooldown after stop-loss
    "ENTRY_RATE_LIMIT_PER_MINUTE": 3,   # Max N position entries per minute
    "MAX_BETA_WEIGHTED_EXPOSURE": 5.0,  # Max beta-weighted aggregate risk limit
    "BTC_SHOCK_THRESHOLD_PERCENT": -0.03, # -3% BTC drop trigger
    "BTC_SHOCK_MAX_EQUITY_LOSS_PERCENT": 0.15, # Max 15% equity loss budget under stress
    
    # Safety Guards
    "MIN_VOLUME_24H_USD": 5000000.0,
    "MIN_ORDERBOOK_DEPTH_USD": 50000.0, # Minimum depth within 1% to prevent slippage crashes
    "MAX_FUNDING_RATE_THRESHOLD": 0.0037, # 0.37% threshold to inhibit toxic carry positions
    "TIME_SYNC_MAX_DELTA_SECONDS": 2.0,
    
    # Engine Deactivation Parameters
    "MOTOR_MAX_DRAWDOWN_PERCENT": 0.20 # 20% Peak-to-Trough drawdown auto shutoff
}

def validate_config(settings):
    """Validates structural constraints on system parameters."""
    if settings["ENTRY_MARGIN_USD"] <= 0:
        raise ValueError("ENTRY_MARGIN_USD must be positive.")
    if settings["LEVERAGE"] <= 0 or settings["LEVERAGE"] > 125:
        raise ValueError("LEVERAGE bounds exceeded [1-125].")
    if settings["HARD_STOP_LOSS_USD"] > settings["ENTRY_MARGIN_USD"]:
        raise ValueError("Stop loss cannot exceed entry margin size.")
    if settings["DEFAULT_MARGIN_MODE"] not in ["ISOLATED", "CROSS"]:
        raise ValueError("Invalid default margin mode configuration.")
    return True

validate_config(SYSTEM_BOT_SETTINGS)
