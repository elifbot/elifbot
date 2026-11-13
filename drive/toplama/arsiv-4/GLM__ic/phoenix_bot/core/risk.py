"""Risk motoru: pozisyon boyutlandırma, ATR+swing stop planı, kaldıraç merdiveni,
TP1/TP2 R-planı, günlük/haftalık limitler, funding/OI vetoları.

AcarBot'un risk.py'sinden uyarlanan çekirdek ilkeler:
- sabit risk yüzdesi ile boyutlandırma (qty = sermaye×risk% / stop mesafesi)
- stop likidasyona sığmıyorsa kaldıracı otomatik düşür (merdiven)
- stop mesafesi tavanı (max_stop_pct) aşılırsa işlemi reddet
"""


class RiskManager:
    def __init__(self, rc: dict):
        self.rc = rc

    # ---------- işlem izinleri ----------
    def can_open(self, n_positions: int, n_same_side: int, day_loss_pct: float,
                 week_loss_pct: float):
        if n_positions >= self.rc['max_positions']:
            return False, 'max pozisyon sayısı'
        if n_same_side >= self.rc['max_same_side']:
            return False, f"aynı yön limiti ({self.rc['max_same_side']})"
        if day_loss_pct <= -self.rc['max_daily_loss_pct']:
            return False, f"günlük zarar limiti ({day_loss_pct:.1f}%)"
        if week_loss_pct <= -self.rc['max_weekly_loss_pct']:
            return False, f"haftalık zarar limiti ({week_loss_pct:.1f}%)"
        return True, 'ok'

    def funding_ok(self, side: int, funding):
        """Ekstrem fundingde ödeyen tarafa giriş yok."""
        if funding is None:
            return True, 'ok'
        thr = float(self.rc.get('funding_filter_pct', 0)) / 100.0
        if thr <= 0:
            return True, 'ok'
        if side > 0 and funding > thr:
            return False, f"funding yüksek, long pahalı ({funding*100:.3f}%)"
        if side < 0 and funding < -thr:
            return False, f"funding yüksek, short pahalı ({funding*100:.3f}%)"
        return True, 'ok'

    def oi_ok(self, side: int, delta_pct):
        """OI çöküşü (herkes kapatıyor) veya kaos → giriş yok."""
        if delta_pct is None or not self.rc.get('oi_filter', True):
            return True, 'ok'
        if delta_pct <= self.rc['oi_min_delta_pct']:
            return False, f"OI çöküşü ({delta_pct:.1f}%)"
        if abs(delta_pct) >= self.rc['oi_max_abs_pct']:
            return False, f"OI kaosu ({delta_pct:+.1f}%)"
        return True, 'ok'

    # ---------- boyutlandırma ----------
    def position_size(self, equity: float, entry: float, sl: float,
                      leverage: float) -> float:
        dist = abs(entry - sl)
        if dist <= 0 or equity <= 0 or entry <= 0:
            return 0.0
        qty = equity * float(self.rc['risk_per_trade_pct']) / 100.0 / dist
        return min(qty, equity * leverage / entry)   # notional tavanı

    # ---------- stop planı + kaldıraç merdiveni ----------
    def plan(self, price: float, side: int, atrv: float, swing_low=None,
             swing_high=None, base_lev=5):
        """Döndürür: (sl, leverage) veya None (ret).
        Stop = ATR×çarpan ile swing yapısal seviyesi arasından DAHA GENİŞ olanı
        (daha güvenli mesafe); tavanı aşarsa işlem reddedilir."""
        rc = self.rc
        if atrv <= 0 or price <= 0:
            return None
        if side > 0:
            atr_stop = price - rc['sl_atr_mult'] * atrv
            sl = atr_stop
            if swing_low is not None and swing_low > 0:
                swing_stop = swing_low - rc.get('swing_buffer_atr', 0.2) * atrv
                sl = min(atr_stop, swing_stop)
        else:
            atr_stop = price + rc['sl_atr_mult'] * atrv
            sl = atr_stop
            if swing_high is not None and swing_high > 0:
                swing_stop = swing_high + rc.get('swing_buffer_atr', 0.2) * atrv
                sl = max(atr_stop, swing_stop)
        dist_pct = abs(price - sl) / price * 100
        if dist_pct > rc['max_stop_pct']:
            return None                    # stop çok geniş → işlem reddi
        lev = self.safe_leverage(price, sl, base_lev)
        return sl, lev

    def safe_leverage(self, price: float, sl: float, base: int) -> int:
        """Likidasyon mesafesi stop×1.4'ten küçük olmayacak şekilde kaldıraç seçer."""
        dist = abs(price - sl) / price
        if dist <= 0:
            return 1
        safe = int(1.0 / (dist * 1.4))
        return max(1, min(int(base), int(self.rc.get('max_leverage', 20)), safe))

    # ---------- TP / kilit yardımcıları ----------
    def tp_prices(self, entry: float, side: int, risk0: float):
        rc = self.rc
        tp1 = entry + side * rc['tp1_r'] * risk0
        tp2 = entry + side * rc['tp2_r'] * risk0
        return tp1, tp2

    def lock_stop(self, entry: float, side: int, risk0: float, mfe_r: float,
                  cur_sl: float) -> float:
        """MFE (maksimum kârlı hareket) kilit merdiveni."""
        for trig, lock in (self.rc.get('profit_lock') or []):
            if mfe_r >= trig:
                cand = entry + side * lock * risk0
                cur_sl = max(cur_sl, cand) if side > 0 else min(cur_sl, cand)
        return cur_sl
