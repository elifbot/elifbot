"""
config.py — Merkezi konfigürasyon.

PAPER-ONLY araştırma botu. Gerçek emir gönderilmez, kimlik doğrulamalı hiçbir
uç nokta çağrılmaz, API anahtarı okunmaz.

Her sabit bir simülasyon varsayımıdır; canlı piyasa koşullarıyla birebir
eşleşme iddiası YOKTUR.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# GÜVENLİK SINIRLARI (değiştirilmemeli)
# ---------------------------------------------------------------------------
# Yalnızca bu iki host ve bu altı public path'e GET yapılabilir.
#   Binance: yalnızca /fapi (USDⓈ-M VADELİ). Spot /api/v3 KULLANILMAZ.
#   OKX:     yalnızca SWAP (vadeli) uç noktaları.
ALLOWED_HOSTS: frozenset[str] = frozenset({"fapi.binance.com", "www.okx.com"})
ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/fapi/v1/klines",
        "/fapi/v1/exchangeInfo",
        "/api/v5/market/candles",
        "/api/v5/market/tickers",      # hacim sıralaması için (public, auth yok)
        "/api/v5/public/instruments",
        "/fapi/v1/ticker/24hr",        # Binance vadeli hacim taraması (public)
    }
)

# Yalnızca paper/replay modu desteklenir. live/testnet -> sys.exit(1)
SUPPORTED_MODES: tuple[str, ...] = ("paper", "replay")
REJECTED_MODES: tuple[str, ...] = ("live", "testnet")

# ---------------------------------------------------------------------------
# BORSALAR / SEMBOLLER — (exchange, symbol) tuple'ları; asla birleştirilmez
# ---------------------------------------------------------------------------
EXCHANGE_SYMBOL_PAIRS: list[tuple[str, str]] = [
    ("binance", "BTCUSDT"),
    ("binance", "ETHUSDT"),
    ("okx", "BTC-USDT-SWAP"),
    ("okx", "ETH-USDT-SWAP"),
]

# ---------------------------------------------------------------------------
# ZAMAN / OTURUM
# ASSUMPTION: 1m mumlar, 60 sn yoklama; araştırma varsayılanıdır.
# ---------------------------------------------------------------------------
TIMEFRAME = "1m"
TIMEFRAME_MS = 60_000
CANDLE_LIMIT = 300            # EMA200 + pay için >= 200 kapalı mum gerekir
POLL_INTERVAL_SEC = 60
SESSION_DURATION_MIN = 60
SESSION_NO_ENTRY_MINUTES = 7  # son 7 dakikada yeni giriş yok

# ---------------------------------------------------------------------------
# HESAP / RİSK
# ASSUMPTION: başlangıç bakiyesi 1000 USDT, taker komisyonu %0.05.
# ---------------------------------------------------------------------------
STARTING_BALANCE_USDT = 1_000.0
BALANCE_FLOOR_USDT = 100.0     # bu eşiğin altına düşecek pozisyon açılamaz
DEFAULT_LEVERAGE = 10
MAX_LEVERAGE = 20
TAKER_FEE_RATE = 0.0005        # tek yön, notional üzerinden; market giriş/çıkış
MAKER_FEE_RATE = 0.0002        # tek yön; yalnızca dolan limit/maker girişi

MAX_OPEN_POSITIONS = 40        # toplam açık pozisyon tavanı
                               # 7 gün kanıtı: 6 slot → 10x'te eksi, 40 slot → +%13,9
MAX_SAME_DIRECTION = 40        # aynı yönde açık pozisyon tavanı
                               # tasfiye zinciri TEK yönlüdür; 4 onu öldürür
MAX_UTILISATION = 0.95         # kullanılan marj / başlangıç bakiyesi (40 × 25$ = %100)

DAILY_LOSS_LIMIT_PCT = 0.05    # günlük -%5 -> yeni pozisyon yok
STALE_PRICE_FACTOR = 2.0       # fiyat 2 * poll_interval'dan eskiyse bayat

MIN_TRADES_FOR_SHARPE = 30     # altında Sharpe hesaplanmaz

# ---------------------------------------------------------------------------
# GÖSTERGELER
# ---------------------------------------------------------------------------
EMA_PERIODS: tuple[int, ...] = (5, 8, 10, 13, 21, 34, 50, 100, 200)
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0
ATR_PERIOD = 14
ADX_PERIOD = 14
SUPERTREND_PERIOD = 10
SUPERTREND_MULT = 3.0
STOCH_RSI_PERIOD = 14
STOCH_RSI_K = 3
STOCH_RSI_D = 3

# Sinyal eşikleri — ASSUMPTION: kalibre edilmemiş başlangıç değerleri.
ADX_TREND_THRESHOLD = 20.0
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
VOLUME_ZSCORE_THRESHOLD = 1.5
SQUEEZE_LOOKBACK = 20

# ---------------------------------------------------------------------------
# DOSYA YOLLARI
# ---------------------------------------------------------------------------
TRADE_LOG_PATH = "trades.csv"
REPORT_PATH = "pnl_report.txt"
LOG_DIR = "logs"

# ---------------------------------------------------------------------------
# HACİM ODAKLI TARAMA
# ---------------------------------------------------------------------------
SCAN_ENABLED_DEFAULT = False
SCAN_UNIVERSE_LIMIT = 40        # USD hacme göre ilk N aday (ticker'dan)
SCAN_FETCH_TOP = 12             # mum verisi çekilecek en fazla sembol
SCAN_PICK_TOP = 3               # işlem için seçilecek en fazla sembol
SCAN_MIN_USD_VOLUME = 2_000_000.0
SCAN_LOOKBACK_BARS = 60         # rvol / z-skor penceresi
SCAN_K_BARS = 5                 # "ani hareket" fiyat penceresi (5 mum)
# NOT: Eşikler 2026-10-27 canlı gözlemle kalibre edildi. İlk değerler
# (0.6% / 2.5x) 6 adayın HİÇBİRİNİ yakalamadı: HUMA rvol=7.1 ama ret=-0.53,
# GRVT ret=-3.08 ama rvol=1.7. Eşikler aşağı çekildi.
SCAN_RET_THRESHOLD_PCT = 0.35   # ani sayılmak için min |%| hareket (5 mumda)
SCAN_RVOL_THRESHOLD = 2.0       # ani sayılmak için min hacim çarpanı

# ---------------------------------------------------------------------------
# SADECE KALDIRAÇLI KRİPTO VADELİ İŞLEM
# ---------------------------------------------------------------------------
# Spot işlem YOKTUR. Her iki borsada da yalnızca perpetual vadeli kontratlar
# taranır ve işlem görür.
FUTURES_ONLY = True
LEVERAGE_ENABLED = True

# Binance: contractType PERPETUAL + quoteAsset USDT + status TRADING şartı.
BINANCE_CONTRACT_TYPES = ("PERPETUAL",)
BINANCE_QUOTE_ASSET = "USDT"

# OKX: yalnızca '-USDT-SWAP'. Hisse/emtia/pre-IPO kontratları, spot paritesi
# olmadığı için "saf kripto" filtresiyle elenir (ABD hisse verisi kullanılmaz).
OKX_REQUIRE_SPOT_PAIR = True
