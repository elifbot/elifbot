# -*- coding: utf-8 -*-
"""ACARBOT FINAL v2.0 - Master Pipeline Coordination Loop."""

import time

class HighSpeedExecutor:
    def __init__(self, flow_scanner, order_lifecycle, news_guard, settings):
        self.flow_scanner = flow_scanner
        self.order_lifecycle = order_lifecycle
        self.news_guard = news_guard
        self.settings = settings

    def run_cycle(self):
        """Executes a single atomic loop iteration processing scanning, stress testing, and tracking loops."""
        # 1. Early-exit safety check if account drawdown threshold is violated
        if self.order_lifecycle.check_portfolio_drawdown():
            print("[KRİTİK DURDURMA] Motor maksimum drawdown eşiğine ulaştı! Yeni işlem açma durduruldu.")
            return

        # 2. Extract complete ticker universe to guarantee persistent tracking regardless of top-5 status
        all_tickers = self.flow_scanner.fetch_unified_tickers()
        if not all_tickers:
            print("[UYARI] Borsa veri akışında kesinti saptandı. Mevcut pozisyonlar beklemeye alınıyor.")
            return

        # Update active position price states and check for stops
        self.order_lifecycle.manage_positions(all_tickers)

        # 3. Pull macro signal validation metric
        news_direction = self.news_guard.evaluate_global_sentiment()

        # 4. Scan for hot liquidity pools using flow models
        hottest_markets = self.flow_scanner.get_hottest_markets(self.settings, limit=5)
        
        for candidate in hottest_markets:
            symbol = candidate['symbol']
            price = candidate['price']
            beta = candidate['beta']
            change_pct = candidate['change_pct']

            if symbol in self.order_lifecycle.positions:
                continue # Prevent duplicate execution entry

            # Determine trading side vector based on quantitative parameter direction
            trade_side = "long" if change_pct >= 0 else "short"

            # 5. Apply multi-layered rate checks and stress shock tests
            if self.order_lifecycle.can_open_position(symbol, trade_side, beta, all_tickers):
                # Execute automated simulation position allocation
                self.order_lifecycle.open_position_simulated(symbol, trade_side, price, beta)
            else:
                # Track what would have happened if entry filters blocked it
                self.order_lifecycle.log_shadow_performance(symbol, trade_side, "Risk/Stress/Cooldown Filter Blocked", price)
