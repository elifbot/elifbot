import time
from abc import ABC, abstractmethod

class BaseExchange(ABC):
    """Tüm borsa entegrasyonları için soyut sınıf."""
    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int):
        pass

    @abstractmethod
    def create_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None):
        pass

    @abstractmethod
    def get_position(self, symbol: str):
        pass


class PaperTradingExchange(BaseExchange):
    """API anahtarı olmadan test çalıştırmayı sağlayan Sanal/Paper Trading Motoru."""
    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.positions = {}
        self.orders_history = []
        self.leverage = 10

    def set_leverage(self, symbol: str, leverage: int):
        self.leverage = leverage
        print(f"[PAPER TRADING] {symbol} kaldıraç oranı: {leverage}x")

    def create_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        order = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "price": price,
            "leverage": self.leverage,
            "timestamp": timestamp
        }

        if symbol not in self.positions:
            self.positions[symbol] = {
                "side": side,
                "entry_price": price,
                "quantity": quantity,
                "leverage": self.leverage
            }
            print(f"[PAPER TRADING EMİR AÇILDI]: {side} {quantity} {symbol} @ {price} USDT")
        else:
            current_pos = self.positions[symbol]
            if current_pos["side"] != side:
                entry = current_pos["entry_price"]
                pnl = (price - entry) * quantity if current_pos["side"] == "BUY" else (entry - price) * quantity
                self.balance += pnl
                print(f"[PAPER TRADING POZİSYON KAPANDI]: {symbol} | PnL: {pnl:.2f} USDT | Güncel Bakiye: {self.balance:.2f} USDT")
                del self.positions[symbol]
            else:
                print(f"[PAPER TRADING] Mevcut pozisyona ekleme yapıldı.")

        self.orders_history.append(order)
        return {"status": "FILLED", "order": order}

    def get_position(self, symbol: str):
        return self.positions.get(symbol, None)


class BinanceFuturesExchange(BaseExchange):
    """Binance Futures Canlı API Adaptör Şablonu."""
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        # Burada ccxt.binanceusdm veya python-binance istemcisi başlatılır

    def set_leverage(self, symbol: str, leverage: int):
        print(f"[BINANCE API] {symbol} kaldıracı {leverage}x ayarlanıyor...")

    def create_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None):
        print(f"[BINANCE API EMİR] {side} {quantity} {symbol}")

    def get_position(self, symbol: str):
        return None


class OKXFuturesExchange(BaseExchange):
    """OKX Futures Canlı API Adaptör Şablonu."""
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    def set_leverage(self, symbol: str, leverage: int):
        print(f"[OKX API] {symbol} kaldıracı {leverage}x ayarlanıyor...")

    def create_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None):
        print(f"[OKX API EMİR] {side} {quantity} {symbol}")

    def get_position(self, symbol: str):
        return None
