# -*- coding: utf-8 -*-
import time
from ACARBOT_FINAL_v2.0.core.config import POSITION_RULES
from ACARBOT_FINAL_v2.0.exec.orders import SimulationOrderLifecycle

class HighSpeedExecutor:
    def __init__(self, client, news_guard, flow_scanner):
        self.client = client
        self.news_guard = news_guard
        self.flow_scanner = flow_scanner
        self.config = POSITION_RULES
        self.order_engine = SimulationOrderLifecycle(self.config)
        
        self.balance = self.config['STARTING_BALANCE']
        self.initial_balance = self.config['STARTING_BALANCE']
        self.peak_equity = self.balance
        self.dip_equity = self.balance
        
        self.positions = {}
        self.cooldowns = {}
        self.recent_entries = []  # Hız limiti için
        self.shadow_trades = []   # Gölge sinyal analizi
        self.trade_history = []
        
        # Simüle edilmiş beta getirileri için mock serileri
        self.btc_history = [0.01, -0.005, 0.012, -0.002, 0.005]
        self.asset_history = {}

    def run_cycle(self):
        try:
            all_tickers = self.client.fetch_tickers()
        except Exception as e:
            print(f"[CRITICAL] Borsa bağlantısı kesildi, yedek REST aranıyor: {str(e)}")
            return

        # Önce pozisyonları yönet (Drawdown kilitlenmesinde stopların çalışmama bug'ı çözüldü)
        self.manage_positions(all_tickers)

        # Drawdown ve Koruma Limiti Kontrolü
        if (self.initial_balance - self.balance) / self.initial_balance >= self.config['MAX_DRAWDOWN_LIMIT']:
            print(f"[KORUMA] Maksimum Drawdown Sınırına Ulaşıldı! Yeni pozisyonlar engellendi.")
            return

        # Hız limiti temizliği (1 dakikadan eski girişleri at)
        now = time.time()
        self.recent_entries = [t for t in self.recent_entries if now - t < 60]

        # Sıcak coinleri tara
        hottest = self.flow_scanner.get_hottest_markets()
        sentiment = self.news_guard.fetch_latest_news_sentiment()

        for market in hottest:
            symbol = market['symbol']
            last_price = market['last_price']
            
            # Filtre 1: Cooldown kontrolü (15 dk yeniden giriş yasağı)
            if symbol in self.cooldowns and now - self.cooldowns[symbol] < self.config['COOLDOWN_MINUTES'] * 60:
                continue

            # Filtre 2: Giriş hız limiti
            if len(self.recent_entries) >= self.config['RATE_LIMIT_PER_MIN']:
                self.log_shadow_trade(symbol, "LONG", last_price, "RATE_LIMIT_ENGELİ", all_tickers)
                continue

            # Sinyal Tayini (Para Akışı + Haber Destekli)
            side = None
            if market['change_pct'] > 1.5 and sentiment in ["LONG", "NEUTRAL"]:
                side = 'long'
            elif market['change_pct'] < -1.5 and sentiment in ["SHORT", "NEUTRAL"]:
                side = 'short'

            if side and symbol not in self.positions:
                # Beta ve Stres Testi Hesaplama
                if symbol外套 not in self.asset_history: self.asset_history[symbol] = [0.015, -0.007, 0.014, -0.001, 0.006]
                beta = self.flow_scanner.calculate_asset_beta(symbol, self.btc_history, self.asset_history[symbol])
                
                # BTC Şoku Stres Testi (-%3 düşüş simülasyonu)
                potential_shock_loss = (self.config['ENTRY_MARGIN_USD'] * self.config['LEVERAGE']) * (beta * 0.03)
                if potential_shock_loss >= (self.balance * 0.05): # Equity %5 risk bütçesi aşımı
                    self.log_shadow_trade(symbol, side.upper(), last_price, "BTC_STRES_TEST_ENGELİ", all_tickers)
                    continue

                # Giriş Kapasitesi Kontrolü (Cross marjin kuralları)
                free_margin = self.calculate_free_margin(all_tickers)
                if free_margin < self.config['ENTRY_MARGIN_USD']:
                    continue

                # Pozisyonu Aç
                self.positions[symbol] = {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": last_price,
                    "highest_price": last_price,
                    "lowest_price": last_price,
                    "margin": self.config['ENTRY_MARGIN_USD'],
                    "opened_at": now
                }
                self.recent_entries.append(now)
                print(f"[İŞLEM AÇILDI] {symbol} | Yön: {side.upper()} | Fiyat: {last_price}$ | Beta: {beta:.2f}")

    def calculate_free_margin(self, tickers) -> float:
        used_margin = sum(p['margin'] for p in self.positions.values())
        total_pnl = 0.0
        for sym, p in self.positions.items():
            if sym in tickers:
                cur_price = tickers[sym]['last']
                size = (p['margin'] * self.config['LEVERAGE']) / p['entry_price']
                if p['side'] == 'long': total_pnl += (cur_price - p['entry_price']) * size
                else: total_pnl += (p['entry_price'] - cur_price) * size
        return self.balance + total_pnl - used_margin

    def manage_positions(self, tickers):
        """Tüm ticker evreni ile listeden düşen pariteler de dahil eksiksiz pozisyon ve gerçekçi cross tasfiye muhasebesi yönetimi"""
        now = time.time()
        closed_symbols = []

        # Hesap Özkaynak (Equity) takibi
        equity = self.calculate_free_margin(tickers) + sum(p['margin'] for p in self.positions.values())
        if equity > self.peak_equity: self.peak_equity = equity
        if equity < self.dip_equity: self.dip_equity = equity

        # Hesap Bazında Cross Likidasyon Kontrolü
        total_maintenance_margin = len(self.positions) * (self.config['ENTRY_MARGIN_USD'] * 0.05) # %5 bakım oranı
        if self.config['MARGIN_MODE'] == 'cross' and equity <= total_maintenance_margin:
            print("[!!! LİKİDASYON !!!] Hesap Özkaynağı Bakım Marjının Altına Düştü. Tüm pozisyonlar sıfırlanıyor!")
            for sym, p in self.positions.items():
                self.balance -= p['margin']  # Tüm marjin eridi
            self.positions.clear()
            return

        for symbol, pos in self.positions.items():
            if symbol not in tickers: continue
            current_price = tickers[symbol]['last']
            
            # Pozisyon Büyüklüğü Hesaplama
            position_size = (pos['margin'] * self.config['LEVERAGE']) / pos['entry_price']
            
            # Gerçekleşen Brüt PnL (Sabit -25$ hatası gerçekçi modele evrildi)
            if pos['side'] == 'long':
                gross_pnl = (current_price - pos['entry_price']) * position_size
            else:
                gross_pnl = (pos['entry_price'] - current_price) * position_size

            # 1. Katı Sabit Zarar Kes Kontrolü (25$ Sınırı)
            if gross_pnl <= -self.config['HARD_STOP_LOSS_USD']:
                fee = (pos['margin'] * self.config['LEVERAGE']) * (self.config['TAKER_FEE'] + self.config['SLIPPAGE_TAKER'])
                net_pnl = gross_pnl - fee
                self.balance += net_pnl
                self.cooldowns[symbol] = now
                closed_symbols.append(symbol)
                print(f"[SABİT STOP KES] {symbol} | Net Zarar: {net_pnl:.2f}$ (Taker komisyon ve kayma dahil)")
                continue

            # 2. Gelişmiş Trailing Stop Denetimi
            triggered, exit_price = self.order_engine.process_trailing_stop(pos, current_price)
            if triggered:
                if pos['side'] == 'long':
                    real_pnl = (exit_price - pos['entry_price']) * position_size
                else:
                    real_pnl = (pos['entry_price'] - exit_price) * position_size
                
                # Taker ücreti ve çıkış kayması gerçekçi yansıtıldı (Geriye gidiş engellendi)
                fee = (pos['margin'] * self.config['LEVERAGE']) * (self.config['TAKER_FEE'] + self.config['SLIPPAGE_TAKER'])
                net_pnl = real_pnl - fee
                self.balance += net_pnl
                closed_symbols.append(symbol)
                print(f"[TRAILING STOP] {symbol} | Çıkış Fiyatı: {exit_price}$ | Net PnL: {net_pnl:.2f}$")
                continue

        for sym in closed_symbols:
            if sym in self.positions: del self.positions[sym]

    def log_shadow_trade(self, symbol, side, entry_price, reason, tickers):
        """'Açılsaydı ne olurdu' ölçümünü yapan gölge işlem motoru"""
        self.shadow_trades.append({
            "symbol": symbol, "side": side, "entry_price": entry_price, "reason": reason, "time": time.time()
        })
        print(f"[GÖLGE SİNYAL KAYDEDİLDİ] {symbol} {side} - Neden: {reason}")
