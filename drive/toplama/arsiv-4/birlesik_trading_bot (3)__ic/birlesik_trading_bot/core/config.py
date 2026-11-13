# core/config.py

POSITION_RULES = {
    "MAX_OPEN_POSITIONS": float('inf'), # Sınırsız pozisyon açma kuralı
    "ENTRY_MARGIN_USD": 50.0,           # İşlem başına 50$ marjin
    "LEVERAGE": 10,                     # Sabit 10x kaldıraç
    "HARD_STOP_LOSS_USD": 25.0,         # 25$ Net zarar kesme sınırı
    "TRAILING_STOP_PERCENT": 0.01,       # %1 İz süren stop tetikleyicisi
    "POST_ONLY_EXECUTION": True,        # Düşük komisyon için Maker/Post-Only emri
    "SIMULATION_MODE": True             # Gerçek piyasa verileriyle API anahtarsız simülasyon
}

NEWS_TRADING_SETTINGS = {
    "enabled": True,
    "sentiment_long_threshold": 0.5,
    "sentiment_short_threshold": -0.5
}
