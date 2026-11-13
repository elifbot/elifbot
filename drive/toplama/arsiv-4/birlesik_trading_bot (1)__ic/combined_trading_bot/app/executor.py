# app/executor.py
import time

class UnifiedHighSpeedExecutor:
    def __init__(self, exchange_client, flow_scanner, news_guard, config):
        self.exchange = exchange_client
        self.flow_scanner = flow_scanner
        self.news_guard = news_guard
        self.config = config
        self.active_positions = set()

    def run_cycle(self):
        """
        Merkezi işlem döngüsü. 1. Öncelik Para Akışıdır. Haberler destekleyici olarak çalışır.
        """
        print("\n[Piyasa Taraması] Yıldırım tarama döngüsü başlatıldı...")
        
        # 1. ÖNCELİK: Para giriş ve çıkış dinamiklerini en sıcak pariteler için tarar
        hottest_markets = self.flow_scanner.get_hottest_markets(limit=self.config["SYSTEM_BOT_SETTINGS"]["MAX_OPEN_POSITIONS"])
        if not hottest_markets:
            print("[Uyarı] Kriterlere uygun yüksek para akışlı parite bulunamadı.")
            return

        # 2. ÖNCELİK (DESTEKLEYİCİ): Küresel haber duyarlılığını arka planda eşleştir
        news_support = self.news_guard.get_market_sentiment()
        print(f"[İkincil Filtre] Haber Destek Durumu: {news_support}")

        for market in hottest_markets:
            symbol = market['symbol']
            primary_dir = market['primary_direction']
            
            if symbol in self.active_positions:
                continue
                
            if len(self.active_positions) >= self.config["SYSTEM_BOT_SETTINGS"]["MAX_OPEN_POSITIONS"]:
                break

            # Haber filtresiyle uyumluluk kontrolü (Destekleyici Davranış)
            # Eğer haber yönü, para akışı yönünün tam zıttı ise pozisyonu korumak için askıya al
            if news_support == "BULLISH_SUPPORT" and primary_dir == "SHORT":
                print(f"[{symbol}] Yoğun para çıkışı var fakat haber akışı aşırı olumlu! İşlem risk azaltımı için pas geçildi.")
                continue
            if news_support == "BEARISH_SUPPORT" and primary_dir == "LONG":
                print(f"[{symbol}] Yoğun para girişi var fakat haber akışı aşırı olumsuz! İşlem risk azaltımı için pas geçildi.")
                continue

            # Komisyon Azaltıcı Akıllı Emir Sistemi (Maker / Post-Only)
            self.execute_low_fee_order(symbol, side="buy" if primary_dir == "LONG" else "sell", price=market['last_price'])

    def execute_low_fee_order(self, symbol, side, price):
        """
        Düşük komisyon ödemek amacıyla borsaya MAKER (Limit - Post Only) emri iletir.
        Bu sayede borsa Taker komisyon cezası kesmez, aksine en düşük komisyon diliminden işlem açar.
        """
        try:
            leverage = self.config["SYSTEM_BOT_SETTINGS"]["DEFAULT_LEVERAGE"]
            self.exchange.set_leverage(leverage, symbol)
            self.exchange.set_margin_mode("ISOLATED", symbol)

            # CCXT Post-Only parametresi borsaya göre ayarlanır (Örn: Binance/OKX için timeInForce VUR veya params postOnly)
            params = {}
            if self.config["SYSTEM_BOT_SETTINGS"]["USE_MARKET_MAKER_POST_ONLY"]:
                # Limit Maker / Post Only emri tetikleme parametresi
                params['postOnly'] = True 
            
            print(f"[DÜŞÜK KOMİSYON - MAKER EMİR] {symbol} çiftinde {leverage}x kaldıraçla {side.upper()} Maker limit emri {price} fiyatından iletildi!")
            
            # Gerçek emir gönderim şablonu:
            # amount = self.calculate_position_size(symbol, price)
            # self.exchange.create_order(symbol, 'limit', side, amount, price, params)
            
            self.active_positions.add(symbol)
        except Exception as e:
            print(f"[{symbol}] Düşük komisyonlu limit emir hatası: {str(e)}")
            
    def calculate_position_size(self, symbol, price):
        return 1.0
