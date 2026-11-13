import time
import logging
import sqlite3
import pandas as pd
import numpy as np

# Canlı borsa bağlantısı için (pip install ccxt pandas numpy)
try:
    import ccxt
except ImportError:
    ccxt = None

# =====================================================================
# 1. LOGGING VE KONFİGÜRASYON
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

class Config:
    # Borsa ve Parite Ayarları
    EXCHANGE_ID = "binance"          # binance, okx, bybit vb.
    API_KEY= "***REDACTED***"
    SECRET_KEY= "***REDACTED***"
    USE_TESTNET = True               # Gerçek para öncesi testnet kullanımı
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "1h"
    LIMIT = 100                      # Kaç adet mum çekilecek

    # Risk & Kasa Yönetimi
    TOTAL_BALANCE = 10000.0          # Mock / Manuel Bakiye (Borsadan çekilmezse)
    RISK_PER_TRADE = 0.02            # Her işlemde kasanın %2'si risk edilir
    STOP_LOSS_ATR_MULT = 1.5         # Stop-Loss için ATR çarpanı

    # Strateji Parametreleri
    RSI_PERIOD = 14
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    SMA_FAST = 20
    SMA_SLOW = 50

    # Sistem & Bildirim Ayarları
    POLL_INTERVAL = 60              # Döngü süresi (Saniye)
    MAX_RETRIES = 3                 # API hatasında yeniden deneme sayısı
    RETRY_DELAY = 5                 # Denemeler arası bekleme süresi (Saniye)
    TELEGRAM_BOT_TOKEN = ""         # Bildirimler için Telegram Bot Token
    TELEGRAM_CHAT_ID = ""           # Telegram Chat ID

# =====================================================================
# 2. VERİTABANI YÖNETİMİ (SQLite)
# =====================================================================
class DatabaseManager:
    def __init__(self, db_name="bot_data.db"):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    side TEXT,
                    amount REAL,
                    price REAL,
                    cost REAL,
                    status TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    level TEXT,
                    message TEXT
                )
            """)
            conn.commit()

    def log_trade(self, symbol: str, side: str, amount: float, price: float, status="CLOSED"):
        cost = amount * price
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (symbol, side, amount, price, cost, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (symbol, side, amount, price, cost, status))
            conn.commit()
        logging.info(f"💾 [DB KAYDI] İşlem kaydedildi: {side} {amount} {symbol} @ ${price:.2f}")

# =====================================================================
# 3. BİLDİRİM SERVİSİ (Telegram)
# =====================================================================
class NotificationManager:
    @staticmethod
    def send_telegram_msg(message: str):
        if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
            return
        
        try:
            import urllib.parse
            import urllib.request
            
            encoded_msg = urllib.parse.quote(message)
            url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage?chat_id={Config.TELEGRAM_CHAT_ID}&text={encoded_msg}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logging.error(f"⚠️ Telegram bildirimi gönderilemedi: {e}")

# =====================================================================
# 4. İNDİKATÖR KÜTÜPHANESİ
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
        
        # ATR (Average True Range)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        return df

# =====================================================================
# 5. RİSK VE POZİSYON BOYUTLANDIRMA
# =====================================================================
class RiskManager:
    def __init__(self, balance: float):
        self.balance = balance

    def update_balance(self, new_balance: float):
        self.balance = new_balance

    def calculate_position_size(self, current_price: float, atr: float) -> float:
        """Sermaye riskine ve ATR oynaklığına göre dinamik lot miktarı hesaplar."""
        risk_amount = self.balance * Config.RISK_PER_TRADE
        stop_loss_distance = atr * Config.STOP_LOSS_ATR_MULT
        
        if stop_loss_distance == 0 or np.isnan(stop_loss_distance):
            return 0.0
            
        units = risk_amount / stop_loss_distance
        return round(units, 4)

# =====================================================================
# 6. STRATEJİ VE SİNYAL ÜRETİCİ
# =====================================================================
class TradingStrategy:
    @staticmethod
    def check_signals(df: pd.DataFrame) -> str:
        if len(df) < Config.SMA_SLOW:
            return "HOLD"
            
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Kesişim Mantığı
        golden_cross = (prev['sma_fast'] <= prev['sma_slow']) and (last['sma_fast'] > last['sma_slow'])
        death_cross = (prev['sma_fast'] >= prev['sma_slow']) and (last['sma_fast'] < last['sma_slow'])
        
        rsi_oversold = last['rsi'] < Config.RSI_OVERSOLD
        rsi_overbought = last['rsi'] > Config.RSI_OVERBOUGHT
        
        if golden_cross or (rsi_oversold and last['close'] > last['sma_fast']):
            return "BUY"
        elif death_cross or (rsi_overbought and last['close'] < last['sma_fast']):
            return "SELL"
            
        return "HOLD"

# =====================================================================
# 7. BORSA KATMANI (CCXT / Mock Bağlantısı)
# =====================================================================
class ExchangeConnector:
    def __init__(self):
        self.is_live = False
        self.exchange = None
        self.position = 0.0
        self.mock_balance = Config.TOTAL_BALANCE

        if ccxt and Config.API_KEY != "YOUR_API_KEY_HERE":
            try:
                exchange_class = getattr(ccxt, Config.EXCHANGE_ID)
                self.exchange = exchange_class({
                    'apiKey': Config.API_KEY,
                    'secret': Config.SECRET_KEY,
                    'enableRateLimit': True,
                })
                if Config.USE_TESTNET:
                    self.exchange.set_sandbox_mode(True)
                self.is_live = True
                logging.info(f"⚡ {Config.EXCHANGE_ID.upper()} canlı borsa bağlantısı kuruldu.")
            except Exception as e:
                logging.error(f"❌ Borsa bağlantı hatası: {e}. Simülasyon moduna geçiliyor.")
                self.is_live = False

    def fetch_ohlcv(self) -> pd.DataFrame:
        """Hata yönetimi ve retry mekanizmalı mum verisi çekimi."""
        if self.is_live and self.exchange:
            for attempt in range(Config.MAX_RETRIES):
                try:
                    raw_candles = self.exchange.fetch_ohlcv(Config.SYMBOL, Config.TIMEFRAME, limit=Config.LIMIT)
                    df = pd.DataFrame(raw_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    return df
                except Exception as e:
                    logging.warning(f"⚠️ Veri çekme hatası (Deneme {attempt+1}/{Config.MAX_RETRIES}): {e}")
                    time.sleep(Config.RETRY_DELAY)
            logging.error("❌ Borsa verisi çekilemedi. Son çare simülasyon verisi kullanılıyor.")

        # Simülasyon Verisi (Mock)
        dates = pd.date_range(end=pd.Timestamp.now(), periods=Config.LIMIT, freq="1h")
        np.random.seed(int(time.time()) % 1000)
        close_prices = 50000 + np.cumsum(np.random.randn(Config.LIMIT) * 150)
        return pd.DataFrame({
            "timestamp": dates,
            "open": close_prices - 50,
            "high": close_prices + 100,
            "low": close_prices - 100,
            "close": close_prices,
            "volume": np.random.randint(10, 500, size=Config.LIMIT)
        })

    def get_balance((self)) -> float:
        if self.is_live and self.exchange:
            try:
                bal = self.exchange.fetch_balance()
                return float(bal['free'].get('USDT', 0.0))
            except Exception as e:
                logging.error(f"Bakiye okuma hatası: {e}")
        return self.mock_balance

    def execute_order(self, side: str, amount: float, price: float) -> bool:
        """Emir iletim mantığı (Gerçek borsa ya da Paper-Trading)."""
        if self.is_live and self.exchange:
            try:
                order_type = 'market'
                order = self.exchange.create_order(Config.SYMBOL, order_type, side.lower(), amount)
                logging.info(f"🌐 [CANLI EMİR] {side} {amount} {Config.