# Algoritmik Strateji ve Sinyal Üretim Modülü

class StrategyEngine:
    def __init__(self):
        pass

    def evaluate_market(self, prices: list) -> str:
        """
        Örnek Basit Strateji: Fiyat trendine göre sinyal üretir.
        Geliştirilmiş versiyonda RSI, MACD, Bollinger vb. hesaplanır.
        Sinyaller: 'BUY_LONG', 'SELL_SHORT', 'CLOSE', 'HOLD'
        """
        if len(prices) < 3:
            return "HOLD"

        # Son 3 mum eğilimi
        if prices[-1] > prices[-2] > prices[-3]:
            return "BUY_LONG"
        elif prices[-1] < prices[-2] < prices[-3]:
            return "SELL_SHORT"
        
        return "HOLD"
