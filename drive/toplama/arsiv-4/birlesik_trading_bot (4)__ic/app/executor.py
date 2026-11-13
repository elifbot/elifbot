# app/executor.py
import time

class HighSpeedExecutor:
    def __init__(self, exchange_client, news_guard, flow_scanner, order_lifecycle, config):
        self.exchange = exchange_client
        self.news_guard = news_guard
        self.flow_scanner = flow_scanner
        self.orders = order_lifecycle
        self.config = config

    def run_cycle(self):
        # 1. Tüm Ticker verilerini güvenle çek (Bozuk veri korumalı)
        all_tickers = self.flow_scanner.get_all_tickers_safely()
        if not all_tickers:
            print("[UYARI] Ticker verisi boş geldi, döngü atlanıyor ancak mevcut pozisyonlar korunuyor.")
            return

        # 2. ÖNCE TÜM POZİSYONLARI YÖNET (Top 5'ten düşen pariteler de burada kesintisiz yönetilir)
        self.orders.manage_positions(all_tickers)

        # 3. Küresel Haber Filtresini Kontrol Et
        global_direction = self.news_guard.get_market_direction()

        # 4. En Sıcak İlk 5 Pazarı Sırala (Para Giriş ve Çıkışları)
        hottest_markets = self.flow_scanner.get_hottest_markets(all_tickers, limit=5)

        # 5. Yeni Pozisyon Açma Stratejisi
        for market in hottest_markets:
            symbol = market['symbol']
            current_price = market['price']
            
            # Sınırsız pozisyon kuralı gereği, eğer paritede açık işlem yoksa yön tayini yapılır
            if symbol not in self.orders.active_positions:
                # Para giriş yönü ile haber doğrulaması
                if market['change_pct'] > 0 and global_direction != "SHORT":
                    self.orders.open_position(symbol, "long", current_price)
                elif market['change_pct'] < 0 and global_direction != "LONG":
                    self.orders.open_position(symbol, "short", current_price)
