# exec/orders.py
from core.config import POSITION_RULES

class SimulationOrderLifecycle:
    def __init__(self):
        self.active_positions = {}

    def manage_positions(self, current_live_prices):
        """
        Açık olan tüm sanal pozisyonları 25$ zarar kes ve %1 trailing stop kurallarına göre yönetir.
        """
        symbols_to_close = []
        
        for symbol, pos in self.active_positions.items():
            if symbol not in current_live_prices:
                continue
                
            current_price = current_live_prices[symbol]
            entry_price = pos['entry_price']
            side = pos['side']
            position_size_usd = POSITION_RULES["ENTRY_MARGIN_USD"] * POSITION_RULES["LEVERAGE"] # 50$ * 10x = 500$
            
            if side == 'LONG':
                # PnL Hesaplama
                pnl_usd = ((current_price - entry_price) / entry_price) * position_size_usd
                
                # 1. Katı Kural: 25$ Zarar Kes
                if pnl_usd <= -POSITION_RULES["HARD_STOP_LOSS_USD"]:
                    print(f"🛑 [SABİT ZARAR KES] {symbol} LONG pozisyonu 25$ zararla acil kapatıldı!")
                    symbols_to_close.append(symbol)
                    continue
                
                # 2. İz Süren Stop Güncelleme (%1)
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                trailing_stop_level = pos['highest_price'] * (1 - POSITION_RULES["TRAILING_STOP_PERCENT"])
                if current_price <= trailing_stop_level and current_price > entry_price:
                    realized_pnl = ((trailing_stop_level - entry_price) / entry_price) * position_size_usd
                    print(f"💰 [İZ SÜREN STOP] {symbol} LONG kar kilitlenerek kapatıldı. Kar: {realized_pnl:.2f}$")
                    symbols_to_close.append(symbol)
                    
            elif side == 'SHORT':
                pnl_usd = ((entry_price - current_price) / entry_price) * position_size_usd
                
                if pnl_usd <= -POSITION_RULES["HARD_STOP_LOSS_USD"]:
                    print(f"🛑 [SABİT ZARAR KES] {symbol} SHORT pozisyonu 25$ zararla acil kapatıldı!")
                    symbols_to_close.append(symbol)
                    continue
                
                if current_price < pos['lowest_price']:
                    pos['lowest_price'] = current_price
                    
                trailing_stop_level = pos['lowest_price'] * (1 + POSITION_RULES["TRAILING_STOP_PERCENT"])
                if current_price >= trailing_stop_level and current_price < entry_price:
                    realized_pnl = ((entry_price - trailing_stop_level) / entry_price) * position_size_usd
                    print(f"💰 [İZ SÜREN STOP] {symbol} SHORT kar kilitlenerek kapatıldı. Kar: {realized_pnl:.2f}$")
                    symbols_to_close.append(symbol)

        for sym in symbols_to_close:
            if sym in self.active_positions:
                del self.active_positions[sym]

    def open_position(self, symbol, side, current_price):
        if symbol in self.active_positions:
            return
        
        # Post-Only / Maker mantığında komisyon avantajlı giriş simülasyonu
        self.active_positions[symbol] = {
            'side': side,
            'entry_price': current_price,
            'highest_price': current_price,
            'lowest_price': current_price
        }
        print(f"🚀 [POZİSYON AÇILDI] {symbol} | Yön: {side} | Giriş: {current_price}$ | Marjin: 50$ | Kaldıraç: 10x (POST-ONLY Maker)")
