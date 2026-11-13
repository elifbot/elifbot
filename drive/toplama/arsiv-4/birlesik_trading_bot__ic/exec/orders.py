# exec/orders.py
class SimulationOrderLifecycle:
    def __init__(self):
        self.active_positions = {}
        self.entry_margin = 50.0
        self.leverage = 10
        self.max_loss_usd = 25.0
        self.trailing_pct = 0.01

    def manage_positions(self, current_tickers):
        """
        Açık tüm pozisyonları simülasyon üzerinden anlık inceler ve yönetir.
        25$ sert zarar kes kuralı ve %1 Trailing Stop'u yürütür.
        """
        closed_positions = []
        for symbol, pos in list(self.active_positions.items()):
            if symbol not in current_tickers:
                continue
            
            # Canlı fiyat güncellemesi
            current_price = float(current_tickers[symbol].get('last' or 'close', pos['entry_price']))
            pos['current_price'] = current_price
            pos_size_usd = self.entry_margin * self.leverage
            
            if pos['side'] == 'LONG':
                pnl = (current_price - pos['entry_price']) / pos['entry_price'] * pos_size_usd
                # 1. 25$ Sabit Zarar Kontrolü
                if pnl <= -self.max_loss_usd:
                    print(f"[ACİL STOP] {symbol} LONG Pozisyonu 25$ net zararla kapatıldı. (Maker/Post-Only)")
                    closed_positions.append(symbol)
                    continue
                # 2. %1 Trailing Stop Güncellemesi ve Kontrolü
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                trailing_stop = pos['highest_price'] * (1.0 - self.trailing_pct)
                if current_price <= trailing_stop and current_price > pos['entry_price']:
                    print(f"[İZ SÜREN STOP] {symbol} LONG Kar realizasyonu ile %1 stop seviyesinden kapatıldı!")
                    closed_positions.append(symbol)
                    
            elif pos['side'] == 'SHORT':
                pnl = (pos['entry_price'] - current_price) / pos['entry_price'] * pos_size_usd
                if pnl <= -self.max_loss_usd:
                    print(f"[ACİL STOP] {symbol} SHORT Pozisyonu 25$ net zararla kapatıldı. (Maker/Post-Only)")
                    closed_positions.append(symbol)
                    continue
                if current_price < pos['lowest_price']:
                    pos['lowest_price'] = current_price
                trailing_stop = pos['lowest_price'] * (1.0 + self.trailing_pct)
                if current_price >= trailing_stop and current_price < pos['entry_price']:
                    print(f"[İZ SÜREN STOP] {symbol} SHORT Kar realizasyonu ile %1 stop seviyesinden kapatıldı!")
                    closed_positions.append(symbol)
                    
        for sym in closed_positions:
            del self.active_positions[sym]

    def open_position(self, symbol, side, price):
        if symbol in self.active_positions:
            return
        self.active_positions[symbol] = {
            'symbol': symbol,
            'side': side,
            'entry_price': price,
            'current_price': price,
            'highest_price': price,
            'lowest_price': price
        }
        print(f"[POZİSYON AÇILDI] {symbol} | Yön: {side} | Giriş: {price}$ | Marjin: 50$ | Kaldıraç: 10x (POST-ONLY/MAKER)")
