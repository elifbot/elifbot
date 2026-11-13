import time

class MarketDataFeed:
    def __init__(self, primary_ws, backup_rest_client):
        self.primary_ws = primary_ws
        self.backup_rest_client = backup_rest_client
        self.last_update_time = time.time()
        
    def get_latest_price(self, symbol: str) -> float:
        """Websocket akışı kesildiğinde REST katmanından yedek fiyatı çeker."""
        if time.time() - self.last_update_time > 5.0: # 5 saniyeden uzun gecikme
            print(f"[Yedek Mod] {symbol} için REST API yedek katmanı tetiklendi.")
            return self.backup_rest_client.fetch_ticker(symbol)
        return self.primary_ws.get_price(symbol)
