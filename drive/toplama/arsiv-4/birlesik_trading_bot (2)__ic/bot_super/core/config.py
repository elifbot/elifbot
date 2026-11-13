# core/config.py

POSITION_RULES = {
    "MAX_OPEN_POSITIONS": float('inf'), # Sınırsız pozisyon kuralı!
    "ENTRY_MARGIN_USD": 50.0,           # İşlem başına 50$ marjin
    "LEVERAGE": 10,                     # Sabit 10x kaldıraç
    "HARD_STOP_LOSS_USD": 25.0,         # 25$ Net zarar kes
    "TRAILING_STOP_PERCENT": 0.01,       # %1 İz süren stop tetikleyicisi
    "POST_ONLY_EXECUTION": True         # Her zaman komisyon dostu MAKER emri kullan
}

SYSTEM_BOT_SETTINGS = {
    "SCAN_INTERVAL_SECONDS": 10,       
    "MIN_VOLUME_THRESHOLD": 1000000,   
    "SIMULATION_MODE": True             # API olmadığı için Simülasyon (Paper) modu açık!
}