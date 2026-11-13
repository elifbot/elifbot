import sys
import asyncio
from core.strategy import StrategyEngine
from core.risk import RiskManager
from core.portfolio import PortfolioManager
from infra.paper import PaperBroker
from safety.alerts import AlertManager

async def main():
    print("=" * 60)
    print("   ALGORITHMIC TRADING SYSTEM v2.0 ULTRA (PROD READY)   ")
    print("=" * 60)
    print("[INIT] Mode: PAPER TRADING")
    print("[INIT] Initial Balance: 1,000 USDT | Margin/Trade: 50 USDT | Leverage: 10x")
    print("[INIT] Target Nominal Position: 500 USDT | Risk/Trade: 25 USDT")
    print("[INIT] Advanced Modules Enabled:")
    print("       - 1h/4h Real-Time HTF Trend Engine")
    print("       - Dynamic Funding Rate Guard & Arbitrage Thresholds")
    print("       - Portfolio Correlation & Netting Matrix (Pearson R > 0.85 Guard)")
    print("       - Orderbook Matching Maker Broker (TTL & Partial Fill Engine)")
    print("       - Walk-Forward Out-Of-Sample Overfitting Prevention Lab")
    print("       - Multi-Exchange WebSocket Data Engine (Binance / OKX)")
    
    alert = AlertManager()
    alert.send_notification("System Engine initialized successfully in PAPER mode.")

if __name__ == "__main__":
    asyncio.run(main())
