# infra/market_data/flow_scanner.py
import numpy as np

class VolumeFlowScanner:
    def __init__(self, ccxt_client, system_settings):
        self.client = ccxt_client
        self.settings = system_settings

    def get_hottest_markets(self, limit=10) -> list:
        """
        1. ÖNCELİK: Piyasadaki tüm aktif vadeli paritelerin anlık para giriş/çıkış ve 
        momentum ivmesini tarar, en sıcak olan pariteleri tespit eder.
        """
        try:
            tickers = self.client.fetch_tickers()
            candidates = []
            min_vol = self.settings.get("MIN_VOLUME_THRESHOLD", 5000000)

            for symbol, data in tickers.items():
                if not (symbol.endswith(':USDT') or symbol.endswith('/USDT') or symbol.endswith(':USDC')):
                    continue
                
                v24h = float(data.get('quoteVolume', 0))
                change_pct = float(data.get('percentage', 0))
                last_price = float(data.get('last', 0))

                if v24h < min_vol: 
                    continue

                # Para akışı gücü formülü (Hacim ve Fiyat Momentum Değişimi)
                flow_score = abs(change_pct) * v24h
                direction = "LONG" if change_pct >= 0 else "SHORT"

                candidates.append({
                    "symbol": symbol,
                    "volume_24h": v24h,
                    "change_pct": change_pct,
                    "last_price": last_price,
                    "flow_score": flow_score,
                    "primary_direction": direction
                })

            # Para giriş hızı ve yoğunluğuna göre azalan sırada sırala
            candidates.sort(key=lambda x: x['flow_score'], reverse=True)
            return candidates[:limit]

        except Exception as e:
            print(f"[HATA] Para akış taraması başarısız: {str(e)}")
            return []
