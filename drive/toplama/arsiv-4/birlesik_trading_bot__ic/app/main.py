# app/main.py
import time
import ccxt
from core.config import SYSTEM_BOT_SETTINGS, POSITION_RULES
from infra.market_data.flow_scanner import VolumeFlowScanner
from safety.news_guard import NewsGuard
from exec.orders import SimulationOrderLifecycle

def main():
    print("=============================================================")
    print("  BİRLEŞİK TRADING BOT - CANLI PİYASA SİMÜLASYONU BAŞLADI  ")
    print("  Kural: Sınırsız Pozisyon | 50$ Marjin | 10x Kaldıraç       ")
    print("  Risk: 25$ Sabit Stop | %1 Kar İz Süren Trailing Stop       ")
    print("  Mod: Canlı Veri / Public API (Şifresiz Bağlantı)           ")
    print("=============================================================")
    
    # Canlı Binance Vadeli İşlemler Public İstemcisi
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    scanner = VolumeFlowScanner(exchange)
    guard = NewsGuard()
    engine = SimulationOrderLifecycle()

    while True:
        try:
            # 1. Pozisyonları Canlı Ticker'lar İle Yönet
            tickers = exchange.fetch_tickers()
            engine.manage_positions(tickers)
            
            # 2. Destekleyici Makro Haber Yönünü Al
            news_dir = guard.get_market_direction()
            
            # 3. 1. Öncelik: En Sıcak Para Giriş Çıkışı Olan Coinleri Bul
            hottest_markets = scanner.get_hottest_markets(limit=5)
            
            for market in hottest_markets:
                symbol = market['symbol']
                flow_dir = market['direction']
                current_price = tickers[symbol]['last']
                
                # Haber filtresiyle uyum kontrolü veya nötr ise direkt giriş
                if news_dir != "NEUTRAL" and news_dir != flow_dir:
                    # Çelişki varsa temkinli davran, pozisyonu pas geç
                    continue
                
                # Sınırsız pozisyon açma mantığıyla işleme dahil et
                engine.open_position(symbol, flow_dir, current_price)
                
            time.sleep(SYSTEM_BOT_SETTINGS["SCAN_INTERVAL_SECONDS"])
        except KeyboardInterrupt:
            print("\n[Sistem] Bot kullanıcı tarafından durduruldu.")
            break
        except Exception as e:
            print(f"[Döngü Hatası] Veri çekilemedi, 10s sonra tekrar denenecek: {str(e)}")
            time.sleep(10)

if __name__ == "__main__":
    main()
