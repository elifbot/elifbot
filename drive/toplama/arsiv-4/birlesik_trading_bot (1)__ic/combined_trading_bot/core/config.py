# core/config.py

SYSTEM_BOT_SETTINGS = {
    "SCAN_INTERVAL_SECONDS": 10,       # Para girişlerini her 10 saniyede bir yıldırım hızıyla tara
    "DEFAULT_LEVERAGE": 5,             # Otomatik ayarlanacak kaldıraç büyüklüğü
    "MAX_OPEN_POSITIONS": 5,           # Aynı anda en fazla kaç farklı sıcak coinde işlemde olsun
    "MIN_VOLUME_THRESHOLD": 5000000,   # Son 24 saatte en az 5 Milyon $ hacmi olmayan coinlere dokunma
    
    # Komisyon Optimizasyonu
    "USE_MARKET_MAKER_POST_ONLY": True, # Komisyonu azaltmak için yapıcı (Maker) emir kullanımı
    "EMERGENCY_SLIPPAGE_PCT": 0.05,     # Piyasa yapıcı emir gerçekleşmezse kayma toleransı
}

NEWS_TRADING_SETTINGS = {
    "enabled": True,                   # Haber bazlı destekleyici katman açık mı?
    "sentiment_long_threshold": 0.3,   # Haber skoru bu değerin üstündeyse Long'u destekler
    "sentiment_short_threshold": -0.3, # Haber skoru bu değerin altındaysa Short'u destekler
}
