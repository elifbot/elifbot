# exec/orders.py
import time

class DynamicOrderLifecycle:
    def __init__(self, config):
        self.config = config
        self.active_positions = {} # {symbol: position_dict}
        self.closed_cooldowns = {} # {symbol: timestamp}
        self.balance = 10000.0     # Sanal başlangıç bakiyesi
        self.trade_history = []    # İşlem kaydı jurnali

    def open_position(self, symbol, side, current_price):
        current_time = time.time()
        # 10 saniyelik aynı yönde hemen açılmama (cooldown) koruması
        if symbol in self.closed_cooldowns:
            if current_time - self.closed_cooldowns[symbol] < 12:
                return

        margin = self.config["ENTRY_MARGIN_USD"]
        leverage = self.config["LEVERAGE"]
        
        # Simüle Maker emri maliyet hesabı
        slippage = current_price * self.config["SLIPPAGE_PCT"]
        execution_price = current_price + slippage if side == 'long' else current_price - slippage
        
        position_size_usd = margin * leverage
        size_in_tokens = position_size_usd / execution_price
        fee = position_size_usd * self.config["MAKER_FEE"]
        
        if self.balance < margin + fee:
            print(f"[BAKİYE YETERSİZ] {symbol} için işlem açılamadı.")
            return

        self.balance -= (margin + fee)
        
        self.active_positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_price": execution_price,
            "current_price": execution_price,
            "highest_price": execution_price if side == 'long' else float('inf'),
            "lowest_price": execution_price if side == 'short' else float('-inf'),
            "margin": margin,
            "size_usd": position_size_usd,
            "tokens": size_in_tokens,
            "opened_at": current_time,
            "trailing_activated": False
        }
        print(f"[POZİSYON AÇILDI] {symbol} {side.upper()} | Fiyat: {execution_price:.4f} | Marjin: {margin}$ | Bakiye: {self.balance:.2f}$")

    def manage_positions(self, all_tickers: dict):
        """
        İlk 5'ten bağımsız olarak TÜM aktif pozisyonları tarar ve yönetir.
        """
        symbols_to_close = []
        current_time = time.time()

        for symbol, pos in list(self.active_positions.items()):
            ticker_data = all_tickers.get(symbol)
            if not ticker_data or ticker_data.get('last') is None:
                continue

            current_price = float(ticker_data['last'])
            pos['current_price'] = current_price
            
            entry_price = pos['entry_price']
            size_usd = pos['size_usd']
            side = pos['side']
            hard_stop_usd = self.config["HARD_STOP_LOSS_USD"]
            trailing_pct = self.config["TRAILING_STOP_PERCENT"]

            if side == 'long':
                # Gerçek PnL Hesabı
                gross_pnl = (current_price - entry_price) / entry_price * size_usd
                
                # Sabit 25$ stop kontrolü
                if gross_pnl <= -hard_stop_usd:
                    self.close_position(symbol, current_price, f"Sabit Stop Kes (Gerçek Zarar: {gross_pnl:.2f}$)")
                    continue

                # Trailing stop mantığı düzeltmesi: Her kâr artışında tetiklenir
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                # Kar realizasyonu veya trailing stop kontrolü
                trailing_stop_level = pos['highest_price'] * (1.0 - trailing_pct)
                if current_price <= trailing_stop_level and current_price > entry_price:
                    self.close_position(symbol, current_price, "İz Süren Stop (Kar Kilitlendi)")
                    continue

            elif side == 'short':
                gross_pnl = (entry_price - current_price) / entry_price * size_usd
                
                if gross_pnl <= -hard_stop_usd:
                    self.close_position(symbol, current_price, f"Sabit Stop Kes (Gerçek Zarar: {gross_pnl:.2f}$)")
                    continue

                if current_price < pos['highest_price']: # Kısa işlemde highest_price taban fiyatı tutar
                    pos['highest_price'] = current_price
                
                trailing_stop_level = pos['highest_price'] * (1.0 + trailing_pct)
                if current_price >= trailing_stop_level and current_price < entry_price:
                    self.close_position(symbol, current_price, "İz Süren Stop (Kar Kilitlendi)")
                    continue

    def close_position(self, symbol, current_price, reason):
        pos = self.active_positions.pop(symbol)
        side = pos['side']
        entry_price = pos['entry_price']
        size_usd = pos['size_usd']
        margin = pos['margin']

        # Kapanış kayması ve komisyonu hesabı
        slippage = current_price * self.config["SLIPPAGE_PCT"]
        exit_price = current_price - slippage if side == 'long' else current_price + slippage
        
        if side == 'long':
            realized_pnl = (exit_price - entry_price) / entry_price * size_usd
        else:
            realized_pnl = (entry_price - exit_price) / entry_price * size_usd
            
        fee = size_usd * self.config["MAKER_FEE"]
        net_return = margin + realized_pnl - fee
        self.balance += net_return
        
        self.closed_cooldowns[symbol] = time.time()
        
        trade_log = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": realized_pnl,
            "net_pnl": realized_pnl - fee,
            "reason": reason,
            "balance_after": self.balance
        }
        self.trade_history.append(trade_log)
        
        print(f"[POZİSYON KAPANDI] {symbol} | Neden: {reason} | Çıkış Fiyatı: {exit_price:.4f} | Net PnL: {realized_pnl - fee:.2f}$ | Güncel Bakiye: {self.balance:.2f}$")
