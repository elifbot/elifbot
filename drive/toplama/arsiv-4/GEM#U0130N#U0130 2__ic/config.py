# Risk ve Sistem Konfigürasyonu
import os

MODE = os.getenv("TRADING_MODE", "PAPER")  # "PAPER", "BINANCE", "OKX"

# Kaldıraç ve Risk Ayarları
DEFAULT_LEVERAGE = 10
MAX_RISK_PER_TRADE = 0.02  # Bakiye başına max %2 risk
TAKE_PROFIT_PCT = 0.03     # %3 Kar Al
STOP_LOSS_PCT = 0.015      # %1.5 Zarar Kes

# API Anahtarları (Canlı moda geçildiğinde .env dosyasından çekilecek)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
