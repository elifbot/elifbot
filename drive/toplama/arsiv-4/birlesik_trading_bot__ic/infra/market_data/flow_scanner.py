# infra/market_data/flow_scanner.py
import ccxt

class VolumeFlowScanner:
    def __init__(self, exchange_client):
        self.client = exchange_client

    def get_hottest_markets(self, limit=5) -> list:
        """
        Borsadaki tüm vadeli pariteleri tarar. 
        Para girişi (Hacim Anomalisi + Fiyat Momentumu) bazlı en sıcak olanları sıralar.
        """
        try:
            tickers = self.client.fetch_tickers()
            candidates = []
            for symbol, data in tickers.items():
                if not (symbol.endswith(':USDT') or symbol.endswith('/USDT') or symbol.endswith('-USDT-SWAP')):
                    continue
                
                v24h = float(data.get('quoteVolume', 0) or 0)
                change_pct = float(data.get('percentage', 0) or 0)
                
                if v24h < 5000000: # Config'deki alt limit
                    continue
                
                # Para Giriş Çıkış Skor Algoritması (Hacim anomalisi x Değişim yüzdesi gücü)
                momentum_score = abs(change_pct) * v24h
                
                candidates.append({
                    "symbol": symbol,
                    "volume_24h": v24h,
                    "change_pct": change_pct,
                    "score": momentum_score,
                    "direction": "LONG" if change_pct >= 0 else "SHORT"
                })
            
            candidates.sort(key=lambda x: x['score'], reverse=True)
            return candidates[:limit]
        except Exception as e:
            print(f"[Hata] Para akışı taranamadı: {str(e)}")
            return []
