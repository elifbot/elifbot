# exec/orders.py
class SimulationOrderLifecycle:
    def __init__(self):
        self.entry_margin = 50.0
        self.leverage = 10
        self.max_loss_usd = 25.0
        self.trailing_pct = 0.01

    def track_positions(self, active_positions, current_prices):
        closed_positions = []
        for symbol, pos in list(active_positions.items()):
            current_price = current_prices[symbol]
            entry_price = pos['entry_price']
            side = pos['side']
            position_size_usd = self.entry_margin * self.leverage
            
            if side == 'long':
                pnl_usd = (current_price - entry_price) / entry_price * position_size_usd
                pos['pnl_usd'] = pnl_usd
                
                # 1. 25$ Sabit Zarar Durdurma (Hard Stop)
                if pnl_usd <= -self.max_loss_usd:
                    pos['close_reason'] = "25$ Sabit Zarar Durdurma (Stop-Loss)"
                    closed_positions.append(symbol)
                    continue
                
                # 2. İz Süren Stop Güncelleme (%1)
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                trailing_stop_level = pos['highest_price'] * (1.0 - self.trailing_pct)
                if current_price <= trailing_stop_level and current_price > entry_price:
                    pos['close_reason'] = "Fiyatın %1 Altına Düşen İz Süren Stop (Kâr Al)"
                    closed_positions.append(symbol)
                    
            elif side == 'short':
                pnl_usd = (entry_price - current_price) / entry_price * position_size_usd
                pos['pnl_usd'] = pnl_usd
                
                # 1. 25$ Sabit Zarar Durdurma
                if pnl_usd <= -self.max_loss_usd:
                    pos['close_reason'] = "25$ Sabit Zarar Durdurma (Stop-Loss)"
                    closed_positions.append(symbol)
                    continue
                
                # 2. İz Süren Stop Güncelleme (%1)
                if current_price < pos['lowest_price']:
                    pos['lowest_price'] = current_price
                
                trailing_stop_level = pos['lowest_price'] * (1.0 + self.trailing_pct)
                if current_price >= trailing_stop_level and current_price < entry_price:
                    pos['close_reason'] = "Fiyatın %1 Üstüne Çıkan İz Süren Stop (Kâr Al)"
                    closed_positions.append(symbol)
                    
        return closed_positions