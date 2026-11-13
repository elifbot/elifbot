# -*- coding: utf-8 -*-
import time
import ccxt
from ACARBOT_FINAL_v2.0.core.config import POSITION_RULES
from ACARBOT_FINAL_v2.0.infra.market_data.flow_scanner import VolumeFlowScanner
from ACARBOT_FINAL_v2.0.safety.news_guard import NewsGuard
from ACARBOT_FINAL_v2.0.app.executor import HighSpeedExecutor

class MockCCXTClient:
    """Canlı veri akışını simüle eden güvenli ve hatasız Mock İstemci"""
    def fetch_tickers(self):
        return {
            "SOL/USDT": {"quoteVolume": 15000000.0, "last": 185.5, "percentage": 2.1},
            "ETH/USDT": {"quoteVolume": 45000000.0, "last": 2645.0, "percentage": -0.5},
            "BTC/USDT": {"quoteVolume": 95000000.0, "last": 68200.0, "percentage": 0.8},
            "RENDER/USDT": {"quoteVolume": 8000000.0, "last": 7.85, "percentage": 3.4},
            "AVAX/USDT": {"quoteVolume": 12000000.0, "last": 28.4, "percentage": -2.2}
        }

def main():
    print("[BAŞLIYOR] ACARBOT FINAL v2.0 - Tam Entegrasyon Modu")
    client = MockCCXTClient()
    scanner = VolumeFlowScanner(client)
    news = NewsGuard(POSITION_RULES)
    executor = HighSpeedExecutor(client, news, scanner)

    # 15 dakikalık test döngüsü simülasyonu
    for i in range(3):
        print(f"\n--- Döngü T{i+1} ---")
        executor.run_cycle()
        time.sleep(1)

    print("\n==================================================")
    print("[OTURUM RAPORU]")
    print(f"Başlangıç Bakiyesi: {POSITION_RULES['STARTING_BALANCE']}$")
    print(f"Bitiş Bakiyesi: {executor.balance:.2f}$")
    print(f"Tepe Hesap Değeri (Peak Equity): {executor.peak_equity:.2f}$")
    print(f"Dip Hesap Değeri (Dip Equity): {executor.dip_equity:.2f}$")
    print(f"Toplam Kaydedilen Gölge İşlem (Shadow Trade): {len(executor.shadow_trades)}")
    print("==================================================")

if __name__ == '__main__':
    main()
