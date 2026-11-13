# app/main.py
import time
from core.config import SYSTEM_BOT_SETTINGS, NEWS_TRADING_SETTINGS
from infra.market_data.flow_scanner import VolumeFlowScanner
from safety.news_guard import NewsGuard
from app.executor import UnifiedHighSpeedExecutor

class MockCCXTClient:
    def fetch_tickers(self):
        # Gerçek API entegrasyonu sağlandığında CCXT kütüphanesine bağlanacak örnek veri simülatörü
        return {
            "BTC/USDT:USDT": {"quoteVolume": 45000000, "percentage": 2.5, "last": 96500.0},
            "ETH/USDT:USDT": {"quoteVolume": 32000000, "percentage": -1.8, "last": 3450.0},
            "SOL/USDT:USDT": {"quoteVolume": 15000000, "percentage": 5.4, "last": 242.0},
            "XRP/USDT:USDT": {"quoteVolume": 8000000, "percentage": -0.5, "last": 1.15},
            "DOGE/USDT:USDT": {"quoteVolume": 12000000, "percentage": 12.1, "last": 0.42}
        }
    def set_leverage(self, leverage, symbol): pass
    def set_margin_mode(self, mode, symbol): pass

def main():
    print("====================================================")
    print("  BİRLEŞİK LİKİDİTE VE PARA AKIŞI VADELİ İŞLEM BOTU  ")
    print("====================================================")
    
    config = {
        "SYSTEM_BOT_SETTINGS": SYSTEM_BOT_SETTINGS,
        "NEWS_TRADING_SETTINGS": NEWS_TRADING_SETTINGS
    }
    
    # İstemci ve modüllerin ayağa kaldırılması
    client = MockCCXTClient() 
    scanner = VolumeFlowScanner(client, SYSTEM_BOT_SETTINGS)
    news = NewsGuard(NEWS_TRADING_SETTINGS)
    
    executor = UnifiedHighSpeedExecutor(client, scanner, news, config)
    
    # Sürekli Yıldırım Döngü
    try:
        while True:
            executor.run_cycle()
            time.sleep(SYSTEM_BOT_SETTINGS["SCAN_INTERVAL_SECONDS"])
    except KeyboardInterrupt:
        print("\n[Sistem] Bot kullanıcı tarafından güvenli bir şekilde kapatıldı.")

if __name__ == "__main__":
    main()
