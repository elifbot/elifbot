# core/config.py

POSITION_RULES = {
    "MAX_OPEN_POSITIONS": float('inf'), # Sınırsız pozisyon kuralı
    "ENTRY_MARGIN_USD": 50.0,           # İşlem başına 50$ marjin
    "LEVERAGE": 10,                     # Sabit 10x kaldıraç
    "HARD_STOP_LOSS_USD": 25.0,         # 25$ Net zarar kes
    "TRAILING_STOP_PERCENT": 0.01,       # %1 İz süren stop tetikleyicisi
    "POST_ONLY_EXECUTION": True,        # Maker emri simülasyonu aktif
    "MAKER_FEE": 0.0002,                # %0.02 Maker komisyonu
    "TAKER_FEE": 0.0005,                # %0.05 Taker komisyonu
    "SLIPPAGE_PCT": 0.0005              # %0.05 Kayma simülasyonu
}

NEWS_TRADING_SETTINGS = {
    "enabled": True,
    "sentiment_long_threshold": 0.5,
    "sentiment_short_threshold": -0.5,
    "scan_interval_minutes": 5
}
