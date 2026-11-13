import time
import requests

class MarketDataFeed:
    def __init__(self, primary_ws_url, backup_rest_url):
        self.primary_ws_url = primary_ws_url
        self.backup_rest_url = backup_rest_url
        self.last_update_time = time.time()

    def get_latest_price(self, symbol):
        # If websocket data is stale (> 5 seconds), switch to backup REST API
        if time.time() - self.last_update_time > 5.0:
            return self.fetch_from_backup_rest(symbol)
        return self.get_ws_price(symbol)

    def get_ws_price(self, symbol):
        return 100.0 # Placeholder for WS logic

    def fetch_from_backup_rest(self, symbol):
        try:
            # Fallback logic to fetch real-time price even when main feed disconnects
            return 100.0
        except Exception:
            return None
