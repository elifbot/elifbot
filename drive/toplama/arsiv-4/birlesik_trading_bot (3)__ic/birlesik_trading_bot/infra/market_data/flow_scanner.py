# infra/market_data/flow_scanner.py
import ccxt

class VolumeFlowScanner:
    def __init__(self):
        # API anahtarı olmadan canlı public verileri çekmek için Binance Futures başlatılıyor
        self.exchange = ccxt.binance({'options': {'defaultType': 'future'}})

    def get_hottest_markets(self, limit=10) -> list:
        """
        Binance Futures üzerindeki TÜM coinleri tarar.
        Alfabetik sırayı çöpe atıp, en yüksek para girişi/hacim anomalisi olanları sıralar.
        """
        try:
            tickers = self.exchange.fetch_tickers()
            candidates = []

            for symbol, data in tickers.items():
                if not (symbol.endswith(':USDT') or symbol.endswith('/USDT')):
                    continue
                
                v24h = float(data.get('quoteVolume', 0)) # 24 saatlik toplam dolar hacmi
                change_pct = float(data.get('percentage', 0)) # 24s değişim %

                if v24h < 5000000: # Likiditesi 5M$ altı olan coinleri eliyoruz
                    continue

                # Para Giriş/Çıkış Güç Skoru
                momentum_score = abs(change_pct) * v24h

                candidates.append({
                    "symbol": symbol,
                    "volume_24h": v24h,
                    "change_pct": change_pct,
                    "score": momentum_score,
                    "last_price": float(data.get('last', 0))
                })

            # Skora göre büyükten küçüğe sıralama (Para giriş yönü)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            return candidates[:limit]

        except Exception as e:
            print(f"[HATA] Para akışı taranamadı: {str(e)}")
            return []
