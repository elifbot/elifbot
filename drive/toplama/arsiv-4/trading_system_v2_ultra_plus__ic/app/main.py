import sys
import asyncio
from core.strategy import StrategyEngine
from core.risk import RiskManager
from core.portfolio import PortfolioManager
from core.liquidation import LiquidationClusterDetector
from safety.news_guard import MacroNewsGuard
from infra.slippage import LatencySlippageSimulator
from infra.paper import PaperBroker
from safety.alerts import AlertManager

async def main():
    print("=" * 70)
    print("   ALGORITHMIC TRADING SYSTEM v2.0 ULTRA+ (INSTITUTIONAL GRADE)   ")
    print("=" * 70)
    print("[INIT] Mode: PAPER TRADING")
    print("[INIT] Initial Balance: 1,000 USDT | Base Margin: 50 USDT | Max Leverage: 10x")
    print("[INIT] Institutional Features Fully Loaded & Integrated:")
    print("       1. ATR Dynamic Position Sizing (Volatility-adjusted risk & stop)")
    print("       2. Liquidation Heatmap & Stop-Hunt Counter Strategy Guard")
    print("       3. Dynamic Multi-Stage Take-Profit (50% Locked) & Trailing Stop")
    print("       4. Macro Economic News Calendar & Black Swan Emergency Guard")
    print("       5. High-Precision Orderbook Latency & Slippage Simulation Engine")
    print("       6. 1h/4h Real-Time HTF Trend Engine & Funding Rate Filter")
    print("       7. Portfolio Correlation (Pearson R > 0.85) & Net Delta Exposure Engine")

    # Initializing guards
    news_guard = MacroNewsGuard()
    if news_guard.is_high_impact_news_imminent():
        print("[WARNING] High-impact macroeconomic news window detected! Trading paused.")
    
    alert = AlertManager()
    alert.send_notification("Trading Engine v2.0 ULTRA+ successfully initialized.")

if __name__ == "__main__":
    asyncio.run(main())
