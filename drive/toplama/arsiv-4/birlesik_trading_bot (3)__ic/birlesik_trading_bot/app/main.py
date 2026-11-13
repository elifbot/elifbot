# app/main.py
import time
import sys
import os

# Klasör yolunu ekleyelim
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.market_data.flow_scanner import VolumeFlowScanner
from safety.news_guard import NewsGuard
from exec.orders import SimulationOrderLifecycle
from core.config import POSITION_RULES

def main():
    print("="*60)
    print("🤖 BİRLEŞİK CANLI PİYASA SİMÜLASYON BOTU BAŞLATILDI 🤖")
    print("Kurallar: Sınırsız Pozisyon | 50$ Giriş | 10x Kaldıraç | 25$ Stop | %1 Trailing")
    print("="*60)

    scanner = VolumeFlowScanner()
    news = NewsGuard()
    lifecycle = SimulationOrderLifecycle()

    while True:
        try:
            # 1. Adım: Tüm pariteleri para akışına göre tara (1. ÖNCELİK)
            print("\n[TARAMA] Binance Vadeli İşlemler tahtası para akışı için taranıyor...")
            hottest_markets = scanner.get_hottest_markets(limit=5)
            
            # Canlı fiyatları güncellemek için harita oluştur
            live_prices = {m['symbol']: m['last_price'] for m in hottest_markets}
            
            # Mevcut açık pozisyonları güncelle ve stop kurallarını işlet
            lifecycle.manage_positions(live_prices)

            # 2. Adım: Destekleyici Haber Durumunu Kontrol Et
            news_direction = news.get_market_direction()
            
            # 3. Adım: Para Girişine Göre Sınırsız İşlem Tetikleme
            for coin in hottest_markets:
                symbol = coin['symbol']
                price = coin['last_price']
                change = coin['change_pct']
                
                # Eğer para girişi yukarı yönlüyse (Fiyat artıyor ve hacim deli gibiyse)
                if change > 0:
                    if news_direction == "SHORT": 
                        print(f"⚠️ [FREN] {symbol} için para girişi LONG ancak haber akışı ayı (SHORT). İşlem pas geçildi.")
                        continue
                    lifecycle.open_position(symbol, "LONG", price)
                
                # Eğer para çıkışı aşağı yönlüyse (Fiyat düşüyor ve devasa satış hacmi varsa)
                elif change < 0:
                    if news_direction == "LONG":
                        print(f"⚠️ [FREN] {symbol} için hacim SHORT ancak haber akışı boğa (LONG). İşlem pas geçildi.")
                        continue
                    lifecycle.open_position(symbol, "SHORT", price)

            print(f"[DURUM] Aktif Pozisyon Sayısı: {len(lifecycle.active_positions)}")
            time.sleep(10) # 10 saniyede bir yıldırım tarama döngüsü

        except KeyboardInterrupt:
            print("\n🤖 Bot kullanıcı tarafından durduruldu.")
            break
        except Exception as e:
            print(f"[DÖNGÜ HATASI] {str(e)}")
            time.sleep(10)

if __name__ == "__main__":
    main()
