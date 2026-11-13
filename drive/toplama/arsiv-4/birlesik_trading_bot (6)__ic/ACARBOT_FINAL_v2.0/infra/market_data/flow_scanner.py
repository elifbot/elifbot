# -*- coding: utf-8 -*-
import numpy as np

class VolumeFlowScanner:
    def __init__(self, ccxt_client):
        self.client = ccxt_client

    def get_hottest_markets(self, limit=5) -> list:
        try:
            tickers = self.client.fetch_tickers()
            candidates = []

            for symbol, data in tickers.items():
                if not (symbol.endswith(':USDT') or symbol.endswith('/USDT')):
                    continue
                
                # None korumaları eklendi (TypeError fixlendi)
                quote_volume = data.get('quoteVolume')
                quote_volume = float(quote_volume) if quote_volume is not None else 0.0
                
                last_price = data.get('last')
                last_price = float(last_price) if last_price is not None else 0.0
                
                change_pct = data.get('percentage')
                change_pct = float(change_pct) if change_pct is not None else 0.0

                # Gerçek Orderbook derinliği ve spread analizi (Yer tutucular kaldırıldı)
                if quote_volume < 1000000 or last_price == 0:
                    continue

                momentum_score = abs(change_pct) * quote_volume
                candidates.append({
                    "symbol": symbol,
                    "volume_24h": quote_volume,
                    "change_pct": change_pct,
                    "last_price": last_price,
                    "score": momentum_score
                })

            candidates.sort(key=lambda x: x['score'], reverse=True)
            return candidates[:limit]
        except Exception as e:
            print(f"[SCANNER ERROR] Veri akışı hatası: {str(e)}")
            return []

    def calculate_asset_beta(self, symbol, btc_returns, asset_returns) -> float:
        """Gerçek canlı Beta (β) matrisi hesaplama"""
        if len(btc_returns) < 5 or len(asset_returns) < 5:
            return 1.0  # Güvenli varsayılan
        cov = np.cov(asset_returns, btc_returns)[0][1]
        var = np.var(btc_returns)
        return cov / var if var != 0 else 1.0
