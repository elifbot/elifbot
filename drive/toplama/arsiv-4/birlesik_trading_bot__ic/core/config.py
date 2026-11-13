# core/config.py

SYSTEM_BOT_SETTINGS = {
    "SCAN_INTERVAL_SECONDS": 10,
    "MIN_VOLUME_THRESHOLD": 5000000,
    "SIMULATION_MODE": True
}

POSITION_RULES = {
    "MAX_OPEN_POSITIONS": float('inf'), # Sınırsız pozisyon açma kuralı
    "ENTRY_MARGIN_USD": 50.0,           # Sabit 50$ Giriş
    "LEVERAGE": 10,                     # Sabit 10x Kaldıraç
    "HARD_STOP_LOSS_USD": 25.0,         # 25$ Net Zarar Kes
    "TRAILING_STOP_PERCENT": 0.01,       # %1 İz Süren Stop
    "POST_ONLY_EXECUTION": True         # Düşük komisyon dostu MAKER emir tipi
}

NEWS_TRADING_SETTINGS = {
    "enabled": True,
    "sentiment_long_threshold": 0.5,
    "sentiment_short_threshold": -0.5
}
