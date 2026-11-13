# app/main.py
import time
from core.config import POSITION_RULES
from safety.news_guard import NewsGuard
from infra.market_data.flow_scanner import VolumeFlowScanner
from exec.orders import DynamicOrderLifecycle
from app.executor import HighSpeedExecutor

class MockCCXTClient:
    """
    Canlı simülasyon için CCXT public veri motorunu taklit eden veya bağlayan istemci sınıfı.
    """
    def fetch_tickers(self):
        # Gerçek modda ccxt.binance().fetch_tickers() çağrılır. 
        # Test/Simülasyon için örnek canlı akış taklidi:
        import random
        return {
            "BTC/USDT:USDT": {"quoteVolume": 50000000, "last": 68000 + random.uniform(-200, 200), "percentage": 1.5},
            "ETH/USDT:USDT": {"quoteVolume": 25000000, "last": 2600 + random.uniform(-15, 15), "percentage": -0.8},
            "SOL/USDT:USDT": {"quoteVolume": 35000000, "last": 185 + random.uniform(-2, 2), "percentage": 3.2},
            "AVAX/USDT:USDT": {"quoteVolume": 12000000, "last": 28.5 + random.uniform(-0.5, 0.5), "percentage": -2.5},
            "RENDER/USDT:USDT": {"quoteVolume": 8000000, "last": 4.8 + random.uniform(-0.1, 0.1), "percentage": 4.1},
            "LINK/USDT:USDT": {"quoteVolume": 5000000, "last": 14.2 + random.uniform(-0.3, 0.3), "percentage": 0.5}
        }

if __name__ == "__main__":
    print("[SİSTEM] Profesyonel Birleşik Trading Bot Başlatılıyor...")
    
    # Bağımlılıkların enjeksiyonu
    client = MockCCXTClient()
    config = POSITION_RULES
    
    news_guard = NewsGuard(config)
    flow_scanner = VolumeFlowScanner(client)
    order_lifecycle = DynamicOrderLifecycle(config)
    
    executor = HighSpeedExecutor(client, news_guard, flow_scanner, order_lifecycle, config)
    
    print("[SİSTEM] Canlı Simülasyon Aktif. Modüller bağlandı. Döngü başlıyor...")
    
    # 15 dakikalık testi simüle eden örnek döngü (Kullanıcı dilediğinde kesintisiz çalıştırır)
    for _ in range(5): 
        executor.run_cycle()
        time.sleep(1)
