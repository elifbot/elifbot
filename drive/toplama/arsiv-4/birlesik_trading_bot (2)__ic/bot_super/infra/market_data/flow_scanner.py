# infra/market_data/flow_scanner.py
import random

class VolumeFlowScanner:
    def __init__(self):
        # Gerçek simülasyon için OKX/Binance vadeli çiftlerini taklit ediyoruz
        self.mock_symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "AVAX/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT"]

    def get_hottest_markets(self, limit=5) -> list:
        candidates = []
        for symbol in self.mock_symbols:
            v24h = random.uniform(5000000, 150000000)
            change_pct = random.uniform(-8.0, 8.0)
            # Para giriş skoru = Değişim şiddeti * Hacim
            momentum_score = abs(change_pct) * v24h
            candidates.append({
                "symbol": symbol,
                "volume_24h": v24h,
                "change_pct": change_pct,
                "score": momentum_score
            })
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:limit]