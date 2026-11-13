# -*- coding: utf-8 -*-
"""ACARBOT FINAL v2.0 - Order Lifecycle Engine with Cross/Isolated Margin and Tracking Guards."""

import time
import math

class DynamicOrderLifecycle:
    def __init__(self, settings):
        self.settings = settings
        self.balance = 10000.0  # Sanal Başlangıç Bakiyesi
        self.initial_balance = 10000.0
        self.positions = {}     # Active tracking registry
        self.trade_history = []
        self.cooldown_registry = {} # Token re-entry cooldown map
        
        # Session Metrics
        self.peak_equity = 10000.0
        self.dip_equity = 10000.0
        self.max_concurrent_positions = 0
        self.max_used_margin_pct = 0.0
        self.min_free_collateral = 10000.0
        
        # Filter Performance Tracker ("Açılsaydı ne olurdu" engine)
        self.shadow_trades = []

    def get_account_state(self):
        """Calculates portfolio equity, free collateral, and maintenance margin for Cross/Isolated modes."""
        total_pnl = 0.0
        allocated_margin = 0.0
        total_maintenance_margin = 0.0

        for symbol, pos in self.positions.items():
            size_units = pos['size_units']
            curr_price = pos['current_price']
            entry_price = pos['entry_price']
            
            # Position gross PnL
            if pos['side'] == 'long':
                pnl = (curr_price - entry_price) * size_units
            else:
                pnl = (entry_price - curr_price) * size_units
            
            total_pnl += pnl
            allocated_margin += pos['margin']
            # Maintenance Margin Estimate (0.5% standard maint threshold)
            total_maintenance_margin += (size_units * curr_price) * 0.005

        equity = self.balance + total_pnl
        
        # Track Peak/Dip Metrics
        if equity > self.peak_equity: self.peak_equity = equity
        if equity < self.dip_equity: self.dip_equity = equity
        
        if self.settings["DEFAULT_MARGIN_MODE"] == "CROSS":
            free_collateral = self.balance + total_pnl - allocated_margin
        else:
            free_collateral = self.balance - allocated_margin # Isolated separation

        if free_collateral < self.min_free_collateral:
            self.min_free_collateral = free_collateral

        used_margin_pct = (allocated_margin / equity) * 100 if equity > 0 else 0.0
        if used_margin_pct > self.max_used_margin_pct:
            self.max_used_margin_pct = used_margin_pct

        return {
            "equity": equity,
            "free_collateral": free_collateral,
            "allocated_margin": allocated_margin,
            "total_maintenance_margin": total_maintenance_margin,
            "total_pnl": total_pnl
        }

    def check_portfolio_drawdown(self) -> bool:
        """Auto-deactivation logic if peak-to-trough drawdown threshold is breached."""
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.get_account_state()["equity"]) / self.peak_equity
            if drawdown >= self.settings["MOTOR_MAX_DRAWDOWN_PERCENT"]:
                return True
        return False

    def can_open_position(self, symbol, side, beta, all_ticker_data) -> bool:
        """Performs precise rate-limiting, cooldown verification, and beta stress shock testing."""
        current_time = time.time()
        
        # 1. Cooldown Protection Check (15 Minutes)
        if symbol in self.cooldown_registry:
            if current_time < self.cooldown_registry[symbol]:
                return False

        # 2. Rate Limiting Check
        recent_entries = [t for t in self.trade_history if current_time - t.get('timestamp', 0) < 60]
        if len(recent_entries) >= self.settings["ENTRY_RATE_LIMIT_PER_MINUTE"]:
            return False

        # 3. Calculate Beta Weighted Aggregates
        state = self.get_account_state()
        current_beta_exposure = 0.0
        for s, pos in self.positions.items():
            direction_mult = 1 if pos['side'] == 'long' else -1
            current_beta_exposure += (pos['margin'] * self.settings["LEVERAGE"]) * pos['beta'] * direction_mult

        new_direction_mult = 1 if side == 'long' else -1
        prospective_beta_exposure = current_beta_exposure + (self.settings["ENTRY_MARGIN_USD"] * self.settings["LEVERAGE"]) * beta * new_direction_mult

        if abs(prospective_beta_exposure) > (state['equity'] * self.settings["MAX_BETA_WEIGHTED_EXPOSURE"]):
            return False

        # 4. BTC -3% Shock Stress Test Simulation
        # Estimate the downside impact across beta values
        btc_shock = self.settings["BTC_SHOCK_THRESHOLD_PERCENT"]
        estimated_shock_loss = 0.0
        for s, pos in self.positions.items():
            pos_side_mult = 1 if pos['side'] == 'long' else -1
            estimated_shock_loss += (pos['margin'] * self.settings["LEVERAGE"]) * pos['beta'] * btc_shock * pos_side_mult
        
        # Add prospective position to shock evaluation
        estimated_shock_loss += (self.settings["ENTRY_MARGIN_USD"] * self.settings["LEVERAGE"]) * beta * btc_shock * new_direction_mult
        
        if abs(estimated_shock_loss) > (state['equity'] * self.settings["BTC_SHOCK_MAX_EQUITY_LOSS_PERCENT"]):
            return False

        return True

    def log_shadow_performance(self, symbol, side, reason, entry_price):
        """Simulates and tracks filtered trades to audit if NewsGuard or SweepGuard preserved alpha."""
        self.shadow_trades.append({
            "symbol": symbol,
            "side": side,
            "filter_reason": reason,
            "entry_price": entry_price,
            "timestamp": time.time()
        })

    def open_position_simulated(self, symbol, side, entry_price, beta):
        """Opens a simulated execution position applying proper leverage, margin bookkeeping and fees."""
        state = self.get_account_state()
        margin_req = self.settings["ENTRY_MARGIN_USD"]
        
        if state["free_collateral"] < margin_req:
            return False

        size_usd = margin_req * self.settings["LEVERAGE"]
        size_units = size_usd / entry_price
        
        # Apply commission and simulated slippage
        fee_rate = self.settings["MAKER_FEE_RATE"] if self.settings["POST_ONLY_EXECUTION"] else self.settings["TAKER_FEE_RATE"]
        total_entry_drag = (size_usd * fee_rate) + (size_usd * self.settings["SIMULATED_SLIPPAGE_RATE"])
        
        self.balance -= total_entry_drag

        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "current_price": entry_price,
            "highest_price": entry_price,
            "lowest_price": entry_price,
            "margin": margin_req,
            "size_units": size_units,
            "beta": beta,
            "timestamp": time.time()
        }
        
        if len(self.positions) > self.max_concurrent_positions:
            self.max_concurrent_positions = len(self.positions)

        print(f"[EMİR AÇILDI] {symbol} {side.upper()} | Kaldıraç: {self.settings['LEVERAGE']}x | Sürtünme Maliyeti: {total_entry_drag:.2f}$")
        return True

    def manage_positions(self, all_tickers):
        """Reviews all positions across the master ticker feed to process stop loss or trailing stop triggers."""
        state = self.get_account_state()
        
        # System account-wide Cross liquidation safety check
        if self.settings["DEFAULT_MARGIN_MODE"] == "CROSS":
            if state["equity"] <= state["total_maintenance_margin"]:
                print("[KAPSAMLI LİKİDASYON] Hesap özkaynağı bakım marjının altına düştü! Tüm pozisyonlar tasfiye ediliyor.")
                self.liquidate_all_positions()
                return

        symbols_to_close = []

        for symbol, pos in list(self.positions.items()):
            ticker = all_tickers.get(symbol)
            if not ticker or ticker.get('last') is None:
                continue # Skip if temporary data disruption occurs to wait for secondary source heartbeat
                
            curr_price = float(ticker['last'])
            pos['current_price'] = curr_price
            
            # Recalculate dynamic returns
            entry_price = pos['entry_price']
            size_units = pos['size_units']
            size_usd = pos['margin'] * self.settings["LEVERAGE"]
            
            if pos['side'] == 'long':
                gross_pnl = (curr_price - entry_price) * size_units
                if curr_price > pos['highest_price']:
                    pos['highest_price'] = curr_price
                
                # Check Hard Stop Limit ($25 loss target)
                if gross_pnl <= -self.settings["HARD_STOP_LOSS_USD"]:
                    symbols_to_close.append((symbol, "Sabit Stop Kes", gross_pnl))
                    continue
                    
                # Trailing Stop Verification (%1 distance threshold)
                trailing_trigger = pos['highest_price'] * (1 - self.settings["TRAILING_STOP_PERCENT"])
                if curr_price <= trailing_trigger and curr_price > entry_price:
                    symbols_to_close.append((symbol, "Takip Eden Stop Kilit", gross_pnl))

            elif pos['side'] == 'short':
                gross_pnl = (entry_price - curr_price) * size_units
                if curr_price < pos['lowest_price']:
                    pos['lowest_price'] = curr_price
                    
                # Check Hard Stop Limit ($25 loss target)
                if gross_pnl <= -self.settings["HARD_STOP_LOSS_USD"]:
                    symbols_to_close.append((symbol, "Sabit Stop Kes", gross_pnl))
                    continue
                    
                # Trailing Stop Verification (%1 distance threshold)
                trailing_trigger = pos['lowest_price'] * (1 + self.settings["TRAILING_STOP_PERCENT"])
                if curr_price >= trailing_trigger and curr_price < entry_price:
                    symbols_to_close.append((symbol, "Takip Eden Stop Kilit", gross_pnl))

        for symbol, reason, gross_pnl in symbols_to_close:
            self.close_position_simulated(symbol, reason, gross_pnl)

    def close_position_simulated(self, symbol, reason, gross_pnl):
        """Closes a target position, logs accurate performance metrics, and applies re-entry cooldown safeguards."""
        pos = self.positions.pop(symbol)
        size_usd = pos['margin'] * self.settings["LEVERAGE"]
        
        # Apply exit fee metrics
        fee_rate = self.settings["MAKER_FEE_RATE"] if self.settings["POST_ONLY_EXECUTION"] else self.settings["TAKER_FEE_RATE"]
        exit_drag = size_usd * fee_rate
        
        net_pnl = gross_pnl - exit_drag
        self.balance += gross_pnl - exit_drag # Update vault bakiye
        
        # Set exact Cooldown trigger if exit was initiated by a Hard Stop Loss event
        if reason == "Sabit Stop Kes":
            self.cooldown_registry[symbol] = time.time() + (self.settings["RE_ENTRY_COOLDOWN_MINUTES"] * 60)

        trade_record = {
            "symbol": symbol,
            "side": pos['side'],
            "entry_price": pos['entry_price'],
            "exit_price": pos['current_price'],
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "reason": reason,
            "timestamp": time.time()
        }
        self.trade_history.append(trade_record)
        print(f"[POZİSYON KAPANDI] {symbol} Nedeni: {reason} | Net PnL: {net_pnl:.2f}$")

    def liquidate_all_positions(self):
        """Emergency portfolio liquidation execution under margin stress scenarios."""
        for symbol in list(self.positions.keys()):
            self.close_position_simulated(symbol, "CROSS Hesap Tasfiyesi", -self.settings["HARD_STOP_LOSS_USD"])

    def generate_session_report(self):
        """Renders comprehensive analytical session report summarizing system efficacy metrics."""
        state = self.get_account_state()
        print("\n" + "="*50)
        print("     ACARBOT FINAL v2.0 - OPERASYONEL RAPORU")
        print("="*50)
        print(f"Başlangıç Bakiyesi: {self.initial_balance:.2f}$")
        print(f"Mevcut Özkaynak (Equity): {state['equity']:.2f}$")
        print(f"Toplam Gerçekleşen İşlem: {len(self.trade_history)}")
        print(f"Eşzamanlı En Yüksek Pozisyon: {self.max_concurrent_positions}")
        print(f"Maksimum Marjin Kullanım %: {self.max_used_margin_pct:.2f}%")
        print(f"En Düşük Serbest Teminat: {self.min_free_collateral:.2f}$")
        print(f"Equity Tepe Noktası: {self.peak_equity:.2f}$")
        print(f"Equity Dip Noktası: {self.dip_equity:.2f}$")
        print(f"Engellenen Gölge Sinyal Sayısı: {len(self.shadow_trades)}")
        print("="*50 + "\n")
