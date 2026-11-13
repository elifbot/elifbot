# infra/market_data/flow_scanner.py

class VolumeFlowScanner:
    def __init__(self, ccxt_client):
        self.client = ccxt_client

    def get_all_tickers_safely(self) -> dict:
        """
        Tüm paritelerin verilerini çeker, tekil hata durumlarını izole eder.
        """
        try:
            return self.client.fetch_tickers()
        except Exception as e:
            print(f"[HATA] Canlı veri tickers çekilemedi: {str(e)}")
            return {}

    def get_hottest_markets(self, tickers: dict, limit=5) -> list:
        candidates = []
        for symbol, data in tickers.items():
            try:
                if not symbol.endswith(':USDT') and not symbol.endswith('/USDT'):
                    continue
                
                # Bozuk veya eksik veri koruması
                quote_volume = data.get('quoteVolume')
                last_price = data.get('last')
                percentage = data.get('percentage')
                
                v24h = float(quote_volume) if quote_volume is not None else 0.0
                price = float(last_price) if last_price is not None else 0.0
                change_pct = float(percentage) if percentage is not None else 0.0

                if v24h < 1000000.0 or price <= 0.0:
                    continue

                momentum_score = abs(change_pct) * v24h
                candidates.append({
                    "symbol": symbol,
                    "volume_24h": v24h,
                    "change_pct": change_pct,
                    "score": momentum_score,
                    "price": price
                })
            except Exception:
                continue

        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:limit]
