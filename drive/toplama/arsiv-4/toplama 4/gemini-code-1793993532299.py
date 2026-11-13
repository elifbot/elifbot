import time
import logging
import pandas as pd
import numpy as np

# =====================================================================
# 1. LOGGING VE KONFİGÜRASYON (config.py)
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot_activity.log"),
        logging.StreamHandler()
    ]
)

class Config:
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "1h"
    LEVERAGE = 1
    RISK_PER_TRADE = 0.02   # Sermayenin %2'si kadar risk
    RSI_PERIOD = 14
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    SMA_FAST = 20
    SMA_SLOW = 50
    POLL_INTERVAL = 60     # Saniye cinsinden döngü süresi

# =====================================================================
# 2. İNDİKATÖR MODÜLÜ (indicators.py)
# =====================================================================
class TechnicalIndicators:
    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # Hareketli Ortalamalar (SMA)
        df['sma_fast'] = df['close'].rolling(window=Config.SMA_FAST).mean()
        df['sma_slow'] = df['close'].rolling(window=Config.SMA_SLOW).mean()
        
        # RSI Hesabı
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=Config.RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=Config.RSI_PERIOD).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR (Average True Range - Stop Loss Hesabı İçin)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        return df

# =====================================================================
# 3. RİSK VE POZİSYON YÖNETİMİ (risk.py & sizing.py)
# =====================================================================
class RiskManager:
    def __init__(self, total_balance: float):
        self.total_balance = total_balance

    def calculate_position_size(self, current_price: float, atr: float) -> float:
        """Kasa yönetimi prensiplerine göre pozisyon büyüklüğünü hesaplar."""
        risk_amount = self.total_balance * Config.RISK_PER_TRADE
        stop_loss_distance = atr * 1.5  # ATR'nin 1.5 katı kadar stop mesafesi
        
        if stop_loss_distance == 0 or np.isnan(stop_loss_distance):
            return 0.0
            
        units = risk_amount / stop_loss_distance
        return round(units, 4)

# =====================================================================
# 4. STRATEJİ MODÜLÜ (strategy.py)
# =====================================================================
class TradingStrategy:
    @staticmethod
    def check_signals(df: pd.DataFrame) -> str:
        """
        Grafik verilerini inceleyerek BUY, SELL veya HOLD kararı üretir.
        """
        if len(df) < Config.SMA_SLOW:
            return "HOLD"
            
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # Golden Cross & Death Cross Kriterleri
        golden_cross = (prev_row['sma_fast'] <= prev_row['sma_slow']) and (last_row['sma_fast'] > last_row['sma_slow'])
        death_cross = (prev_row['sma_fast'] >= prev_row['sma_slow']) and (last_row['sma_fast'] < last_row['sma_slow'])
        
        # RSI Aşırı Alım / Aşırı Satım
        rsi_oversold = last_row['rsi'] < Config.RSI_OVERSOLD
        rsi_overbought = last_row['rsi'] > Config.RSI_OVERBOUGHT
        
        # Sinyal Üretimi
        if golden_cross or (rsi_oversold and last_row['close'] > last_row['sma_fast']):
            return "BUY"
        elif death_cross or (rsi_overbought and last_row['close'] < last_row['sma_fast']):
            return "SELL"
            
        return "HOLD"

# =====================================================================
# 5. BORSA / PAPER TRADING MODÜLÜ (exchanges.py)
# =====================================================================
class MockExchange:
    """Canlı borsa mantığını taklit eden simülasyon sınıfı."""
    def __init__(self):
        self.balance = 10000.0  # 10,000 USDT Test Bakiyesi
        self.position = 0.0

    def fetch_ohlcv(self) -> pd.DataFrame:
        """Test amaçlı dinamik mum verisi üretir."""
        dates = pd.date_range(end=pd.Timestamp.now(), periods=100, freq="1h")
        np.random.seed(int(time.time()) % 1000)
        close_prices = 50000 + np.cumsum(np.random.randn(100) * 150)
        
        df = pd.DataFrame({
            "timestamp": dates,
            "open": close_prices - 50,
            "high": close_prices + 100,
            "low": close_prices - 100,
            "close": close_prices,
            "volume": np.random.randint(10, 500, size=100)
        })
        return df

    def execute_order(self, action: str, amount: float, price: float):
        if action == "BUY" and self.position == 0:
            self.position = amount
            cost = amount * price
            self.balance -= cost
            logging.info(f"🟢 [ALIM GERÇEKLEŞTİ] Miktar: {amount} {Config.SYMBOL} | Fiyat: ${price:.2f} | Kalan Bakiye: ${self.balance:.2f}")
        elif action == "SELL" and self.position > 0:
            revenue = self.position * price
            self.balance += revenue
            logging.info(f"🔴 [SATIM GERÇEKLEŞTİ] Miktar: {self.position} {Config.SYMBOL} | Fiyat: ${price:.2f} | Yeni Bakiye: ${self.balance:.2f}")
            self.position = 0.0

# =====================================================================
# 6. CANLI ÇALIŞTIRICI & EVENT LOOP (main.py / live_runner.py)
# =====================================================================
class TradingBot:
    def __init__(self):
        self.exchange = MockExchange()
        self.risk_manager = RiskManager(self.exchange.balance)
        
    def run_step(self):
        logging.info("⏳ Piyasa verileri çekiliyor ve analiz ediliyor...")
        
        # 1. Veri Çek
        df = self.exchange.fetch_ohlcv()
        
        # 2. İndikatörleri Hesapla
        df = TechnicalIndicators.add_indicators(df)
        
        # 3. Sinyal Üret
        signal = TradingStrategy.check_signals(df)
        last_price = df.iloc[-1]['close']
        last_atr = df.iloc[-1]['atr']
        
        logging.info(f"📊 Fiyat: ${last_price:.2f} | RSI: {df.iloc[-1]['rsi']:.1f} | Sinyal: {signal}")
        
        # 4. Emir İletim Mantığı
        if signal == "BUY" and self.exchange.position == 0:
            size = self.risk_manager.calculate_position_size(last_price, last_atr)
            if size > 0:
                self.exchange.execute_order("BUY", size, last_price)
        elif signal == "SELL" and self.exchange.position > 0:
            self.exchange.execute_order("SELL", self.exchange.position, last_price)

    def start(self, loop=False):
        logging.info("🚀 Algoritmik Trading Botu Başlatıldı.")
        if loop:
            try:
                while True:
                    self.run_step()
                    time.sleep(Config.POLL_INTERVAL)
            except KeyboardInterrupt:
                logging.info("🛑 Bot durduruldu.")
        else:
            # Tek tur çalıştırma (Test için)
            self.run_step()

if __name__ == "__main__":
    bot = TradingBot()
    bot.start(loop=False)  # Sürekli canlı döngü için loop=True yapabilirsiniz.