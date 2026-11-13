import time
import config
from exchange_adapter import PaperTradingExchange, BinanceFuturesExchange, OKXFuturesExchange
from strategy import StrategyEngine
from risk_manager import RiskManager

class FuturesBot:
    def __init__():
        pass

def get_exchange_instance():
    if config.MODE == "PAPER":
        print(">>> SİSTEM PAPER TRADING (SANAL SİMÜLASYON) MODUNDA BAŞLATILDI <<<")
        return PaperTradingExchange(initial_balance=10000.0)
    elif config.MODE == "BINANCE":
        print(">>> BINANCE FUTURES CANLI API MODU <<<")
        return BinanceFuturesExchange(config.BINANCE_API_KEY, config.BINANCE_SECRET_KEY)
    elif config.MODE == "OKX":
        print(">>> OKX FUTURES CANLI API MODU <<<")
        return OKXFuturesExchange(config.OKX_API_KEY, config.OKX_SECRET_KEY, config.OKX_PASSPHRASE)
    else:
        raise ValueError("Geçersiz TRADING_MODE konfigürasyonu!")

def main():
    exchange = get_exchange_instance()
    strategy = StrategyEngine()
    risk_mgr = RiskManager()

    # Simüle edilmiş canlı fiyat akışı (Test amaçlı)
    simulated_market_prices = [65000.0, 65100.0, 65250.0, 65400.0, 65300.0, 64200.0]
    symbol = "BTCUSDT"
    price_history = []

    print("\n--- FUTURES BOT TEST DÖNGÜSÜ BAŞLIYOR ---\n")
    exchange.set_leverage(symbol, config.DEFAULT_LEVERAGE)

    for price in simulated_market_prices:
        price_history.append(price)
        print(f"\n[PİYASA FİYATI]: {symbol} = {price} USDT")

        # 1. Mevcut pozisyon için risk / çıkış kontrolü
        position = exchange.get_position(symbol)
        if position:
            exit_reason = risk_mgr.check_exit_conditions(position, price)
            if exit_reason:
                print(f"[RİSK MOTORU TETİKLENDİ]: {exit_reason} -> Pozisyon Kapatılıyor!")
                close_side = "SELL" if position["side"] == "BUY" else "BUY"
                exchange.create_order(symbol, close_side, "MARKET", position["quantity"], price)
                continue

        # 2. Strateji değerlendirmesi
        signal = strategy.evaluate_market(price_history)
        print(f"[STRATEJİ SİNYALİ]: {signal}")

        if signal == "BUY_LONG" and not position:
            exchange.create_order(symbol, "BUY", "MARKET", quantity=0.1, price=price)
        elif signal == "SELL_SHORT" and not position:
            exchange.create_order(symbol, "SELL", "MARKET", quantity=0.1, price=price)

        time.sleep(0.5)

    print("\n--- TEST DÖNGÜSÜ TAMAMLANTI ---")

if __name__ == "__main__":
    main()
