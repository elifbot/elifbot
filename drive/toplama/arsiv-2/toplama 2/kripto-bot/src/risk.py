"""Risk yönetimi — kullanıcının kesin kuralları + Kayma (Slippage) Filtresi + Dinamik Kaldıraç:

  1) STOP-LOSS %5: giriş fiyatından %5 ters hareket = pozisyon kapatılır.
  2) KÂR KİLİDİ: kâr %10'u geçerse stop-loss +%5 kâr seviyesine çekilir.
     Yani en kötü ihtimalle %5 kârla çıkılır.
  3) TRAILING: zirveden %5 geri dönüş olursa kapatılır (kârı maksimize eder,
     botun "gidebildiği noktayı" kendisi bulmasını sağlar).
  4) %10 KASA + DİNAMİK KALDIRAÇ (20x → 10x → 5x):
     - Normal/sakin piyasada: 20x kaldıraç
     - Yüksek oynaklıkta (ATR %1.5+): 10x kaldıraç
     - Aşırı oynaklıkta (ATR %3.0+) veya VETO yaklaşımında: 5x kaldıraç
  5) MAKSİMUM KAYMA FİLTRESİ (Max Slippage Tolerance = %0.30):
     Fiyat emir seviyesinden %0.3'ten fazla uzaklaşmışsa market emri iptal edilir
     ve "Chase Order" (fiyatı takip eden limit emir) mantığına geçilir.
  6) ARTIDA OLDUKÇA SINIRSIZ POZİSYON EKLEME (Unlimited Pyramiding).
  7) TERSTE KALAN POZİSYONU ÇAPRAZ KURTARMA (İkili Kapama / Pair Rescue).
  8) Günlük devre kesici: günlük toplam zarar limiti aşılırsa bot durur.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Position:
    symbol: str
    side: str                     # "LONG" veya "SHORT"
    entry: float                  # ağırlıklı ortalama giriş fiyatı
    qty: float                    # toplam miktar (baz para birimi)
    stop: float                   # güncel stop fiyatı
    peak: float = 0.0             # LONG: görülen en yüksek | SHORT: görülen en düşük
    locked_profit: bool = False   # +%10 sonrası stop kara çekildi mi?
    opened_at: str = ""
    leverage: int = 20            # Kaldıraç (20x baz, dinamik 10x / 5x)
    margin_usdt: float = 0.0      # Kasanın %10'u ile ayrılan toplam marj ($)
    layers: int = 1               # Kaç kademe ekleme yapıldı (sınırsız pyramiding)
    last_add_price: float = 0.0   # Son ekleme yapılan fiyat

    def __post_init__(self):
        if not self.opened_at:
            self.opened_at = datetime.now(timezone.utc).isoformat()
        if not self.peak:
            self.peak = self.entry
        if not self.last_add_price:
            self.last_add_price = self.entry
        if self.margin_usdt <= 0 and self.entry > 0 and self.qty > 0:
            lev = max(1, int(self.leverage or 20))
            self.margin_usdt = round((self.entry * self.qty) / lev, 2)

    def add_layer(
        self,
        add_price: float,
        add_qty: float,
        add_margin_usdt: float = 0.0,
        stop_loss_pct: float = 5.0,
    ):
        """Artıdaki pozisyona yeni kademe ekler (Sınırsız Pyramiding)."""
        if add_qty <= 0 or add_price <= 0:
            return
        old_notional = self.entry * self.qty
        new_notional = add_price * add_qty
        total_qty = self.qty + add_qty
        self.entry = (old_notional + new_notional) / total_qty
        self.qty = total_qty
        if add_margin_usdt <= 0:
            add_margin_usdt = new_notional / max(1, self.leverage)
        self.margin_usdt = round(self.margin_usdt + add_margin_usdt, 2)
        self.layers += 1
        self.last_add_price = add_price

        if self.side == "LONG":
            cand_stop = self.entry * (1.0 - stop_loss_pct / 100.0)
            self.stop = max(self.stop, cand_stop)
            self.peak = max(self.peak, add_price)
        else:
            cand_stop = self.entry * (1.0 + stop_loss_pct / 100.0)
            self.stop = min(self.stop, cand_stop)
            self.peak = min(self.peak, add_price)


class RiskManager:
    def __init__(
        self,
        stop_loss_pct: float = 5.0,
        lock_trigger_pct: float = 10.0,
        lock_level_pct: float = 5.0,
        trail_pct: float = 5.0,
        risk_per_trade_pct: float = 1.0,
        max_positions: int = 3,
        daily_max_loss_pct: float = 5.0,
        capital_pct_per_entry: float = 10.0,
        leverage: int = 20,
        unlimited_pyramiding: bool = True,
        pyramid_min_profit_pct: float = 0.25,
        pair_rescue_enabled: bool = True,
        rescue_min_loser_pct: float = 0.5,
        rescue_min_net_margin_pct: float = -2.0,
        rescue_max_net_margin_pct: float = 6.0,
        max_slippage_pct: float = 0.30,
        dynamic_leverage_enabled: bool = True,
        atr_high_volatility_pct: float = 1.5,
        atr_extreme_volatility_pct: float = 3.0,
        max_layers: int = 6,
        hard_max_positions: int = 6,
        max_same_side_positions: int = 4,
        max_total_margin_pct: float = 60.0,
        weekly_max_loss_pct: float = 12.0,
        liq_stop_buffer: float = 0.70,
        maintenance_margin_pct: float = 0.5,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.lock_trigger_pct = lock_trigger_pct
        self.lock_level_pct = lock_level_pct
        self.trail_pct = trail_pct
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_positions = max_positions
        self.daily_max_loss_pct = daily_max_loss_pct

        self.capital_pct_per_entry = capital_pct_per_entry
        self.leverage = leverage
        self.unlimited_pyramiding = unlimited_pyramiding
        self.pyramid_min_profit_pct = pyramid_min_profit_pct
        self.pair_rescue_enabled = pair_rescue_enabled
        self.rescue_min_loser_pct = rescue_min_loser_pct
        self.rescue_min_net_margin_pct = rescue_min_net_margin_pct
        self.rescue_max_net_margin_pct = rescue_max_net_margin_pct

        # A) Maksimum Kayma Toleransı (%0.30)
        self.max_slippage_pct = max_slippage_pct

        # B) Dinamik Kaldıraç Ayarları (20x -> 10x -> 5x)
        self.dynamic_leverage_enabled = dynamic_leverage_enabled
        self.atr_high_volatility_pct = atr_high_volatility_pct
        self.atr_extreme_volatility_pct = atr_extreme_volatility_pct

        # C) Sert üst sınırlar (sınırsız ekleme artık güvenli bir tavanla çalışır)
        self.max_layers = max_layers                    # tek pozisyonda en fazla kademe
        self.hard_max_positions = hard_max_positions    # artıda sınırsız olsa bile mutlak tavan
        self.max_same_side_positions = max_same_side_positions  # aynı yönde en fazla pozisyon (korelasyon riski)
        self.max_total_margin_pct = max_total_margin_pct        # toplam marj / bakiye (%)
        self.weekly_max_loss_pct = weekly_max_loss_pct          # haftalık zarar limiti (bakiyenin %'si)
        self.liq_stop_buffer = liq_stop_buffer          # stop, likidasyon mesafesinin en çok bu oranında
        self.maintenance_margin_pct = maintenance_margin_pct

        self._daily_pnl_pct = 0.0
        self._day = datetime.now(timezone.utc).date()
        self._weekly_pnl_pct = 0.0
        self._week = datetime.now(timezone.utc).isocalendar()[:2]

    def _reset_day_if_needed(self):
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day, self._daily_pnl_pct = today, 0.0

    @property
    def daily_pnl_pct(self) -> float:
        self._reset_day_if_needed()
        return self._daily_pnl_pct

    def effective_stop_pct(self, leverage: int | None = None) -> float:
        """Likidasyon-bilinçli stop mesafesi (fiyat %).

        20x'te likidasyon ~%4.5 civarındadır; %5 stop likidasyondan SONRA kalır ve
        hiç çalışmaz. Bu yüzden stop mesafesi, likidasyon mesafesinin
        `liq_stop_buffer` (varsayılan %70) katını asla aşmaz.
        """
        lev = max(1, int(leverage or self.leverage or 1))
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(self.stop_loss_pct, liq_dist * self.liq_stop_buffer), 4)

    def initial_stop(self, side: str, entry: float, leverage: int | None = None) -> float:
        """Kural 1: ilk stop-loss girişten %5 uzakta — yüksek kaldıraçta likidasyon-bilinçli daraltılır."""
        pct = self.effective_stop_pct(leverage) if leverage else self.stop_loss_pct
        if side == "LONG":
            return entry * (1 - pct / 100)
        return entry * (1 + pct / 100)

    # -- C) Portföy seviyesi sert limitler ------------------------------------
    def equity_pnl_pct(self, pnl_usdt: float, balance_usdt: float) -> float:
        """Kapanan işlemin K/Z'sini HESAP bakiyesine oranla (%) verir (fiyat % değil)."""
        if balance_usdt <= 0:
            return 0.0
        return pnl_usdt / balance_usdt * 100.0

    def margin_cap_ok(self, used_margin_usdt: float, add_margin_usdt: float, balance_usdt: float) -> tuple[bool, str]:
        if balance_usdt <= 0:
            return False, "bakiye okunamadı"
        pct = (used_margin_usdt + add_margin_usdt) / balance_usdt * 100.0
        if pct > self.max_total_margin_pct:
            return False, f"toplam marj tavanı aşılır (%{pct:.1f} > %{self.max_total_margin_pct:g})"
        return True, "OK"

    def position_size(self, balance_usdt: float, entry: float, stop: float) -> float:
        """Stop mesafesine göre miktar: stop olursa kayıp = kasanın %risk_per_trade_pct'si."""
        risk_usdt = balance_usdt * self.risk_per_trade_pct / 100
        dist = abs(entry - stop)
        if dist <= 0 or entry <= 0:
            return 0.0
        return risk_usdt / dist

    # -- A) Maksimum İzin Verilen Kayma (Slippage) Filtresi --------------------
    def check_slippage(
        self, expected_price: float, execution_price: float, max_slip_pct: float | None = None
    ) -> tuple[bool, float, str]:
        """Emir fiyatı ile anlık gerçekleşme fiyatı arasındaki kaymayı denetler.

        Eğer kayma > %0.30 ise (False, slip_pct, 'CHASE_ORDER') döner;
        böylece bot market emrini iptal edip 'Chase Order' (fiyatı takip eden limit) moduna geçer.
        """
        tol = max_slip_pct if max_slip_pct is not None else self.max_slippage_pct
        if expected_price <= 0 or execution_price <= 0:
            return False, 0.0, "geçersiz fiyat"
        slip_pct = abs(execution_price - expected_price) / expected_price * 100.0
        if slip_pct > tol:
            return (
                False,
                round(slip_pct, 4),
                f"KAYMA LİMİTİ AŞILDI (%{slip_pct:.3f} > maks %{tol:.2f}) → Chase Order moduna geçiliyor",
            )
        return True, round(slip_pct, 4), "OK"

    # -- B) Dinamik Kaldıraç ve Volatilite Sarmalı (20x → 10x → 5x) ------------
    def compute_dynamic_leverage(
        self,
        price: float,
        atr: float | None = None,
        veto_approaching: bool = False,
        fear_greed: float = 50.0,
    ) -> tuple[int, str]:
        """Piyasa oynaklığına (ATR) ve haber/veto riskine göre kaldıracı 20x / 10x / 5x ayarlar."""
        base_lev = int(self.leverage or 20)
        if not self.dynamic_leverage_enabled or price <= 0:
            return base_lev, f"sabit {base_lev}x"

        atr_pct = (float(atr) / price * 100.0) if (atr and atr > 0) else 0.0

        # 1) Aşırı oynaklık (ATR >= %3.0) veya VETO yaklaşımı / aşırı panik → 5x
        if (
            atr_pct >= self.atr_extreme_volatility_pct
            or veto_approaching
            or fear_greed <= 20.0
        ):
            lev = min(base_lev, 5)
            why = (
                f"VETO/panik yaklaşımı (FG={fear_greed:.0f}) → {lev}x"
                if (veto_approaching or fear_greed <= 20.0)
                else f"aşırı oynaklık (ATR %{atr_pct:.2f} >= %{self.atr_extreme_volatility_pct}) → {lev}x"
            )
            return lev, why

        # 2) Yüksek oynaklık (ATR >= %1.5) veya gergin psikoloji → 10x
        if (
            atr_pct >= self.atr_high_volatility_pct
            or fear_greed <= 28.0
            or fear_greed >= 82.0
        ):
            lev = min(base_lev, 10)
            why = (
                f"yüksek oynaklık (ATR %{atr_pct:.2f}) → {lev}x"
                if atr_pct >= self.atr_high_volatility_pct
                else f"psikolojik uç bölge (FG={fear_greed:.0f}) → {lev}x"
            )
            return lev, why

        # 3) Sakin piyasa ve normal koşul → Tam 20x
        return base_lev, f"sakin piyasa (ATR %{atr_pct:.2f}) → {base_lev}x"

    def leveraged_entry_size(
        self,
        balance_usdt: float,
        entry: float,
        capital_pct: float | None = None,
        leverage: int | None = None,
    ) -> tuple[float, dict]:
        """Kasanın her zaman %10'u ile giriş + aktif kaldıraç (20x / dinamik 10x / 5x)."""
        cap_pct = capital_pct if capital_pct is not None else self.capital_pct_per_entry
        lev = int(leverage if leverage is not None else self.leverage)
        if balance_usdt <= 0 or entry <= 0 or cap_pct <= 0 or lev <= 0:
            return 0.0, {"kaynak": "kasa_%10_20x", "neden": "bakiye/fiyat geçersiz"}
        margin_usdt = balance_usdt * (cap_pct / 100.0)
        notional_usdt = margin_usdt * lev
        qty = notional_usdt / entry
        return qty, {
            "kaynak": f"kasa_%{cap_pct:g}_{lev}x",
            "margin_usdt": round(margin_usdt, 2),
            "notional": round(notional_usdt, 2),
            "leverage": lev,
            "capital_pct": cap_pct,
            "risk_pct": cap_pct,
        }

    def profit_pct(self, pos: Position, price: float) -> float:
        """Spot fiyat değişim yüzdesi (%)."""
        if pos.side == "LONG":
            return (price - pos.entry) / pos.entry * 100
        return (pos.entry - price) / pos.entry * 100

    def roe_pct(self, pos: Position, price: float) -> float:
        """Kaldıraçlı marj getiri yüzdesi (ROE % = fiyat_pnl_% × kaldıraç)."""
        return self.profit_pct(pos, price) * max(1, int(getattr(pos, "leverage", 20)))

    def pnl_usdt(self, pos: Position, price: float) -> float:
        """Dolar bazında net gerçekleşmemiş K/Z ($)."""
        if pos.side == "LONG":
            return (price - pos.entry) * pos.qty
        return (pos.entry - price) * pos.qty

    def can_open(
        self,
        open_count: int,
        all_in_profit: bool = False,
        side: str | None = None,
        open_sides: list[str] | None = None,
    ) -> tuple[bool, str]:
        self._reset_day_if_needed()
        self._reset_week_if_needed()
        if self._daily_pnl_pct <= -self.daily_max_loss_pct:
            return False, f"Günlük zarar limiti (%{self.daily_max_loss_pct}) doldu, bot durdu."
        if self._weekly_pnl_pct <= -self.weekly_max_loss_pct:
            return False, f"Haftalık zarar limiti (%{self.weekly_max_loss_pct}) doldu, hafta sonuna kadar yeni giriş yok."
        if open_count >= self.hard_max_positions:
            return False, f"Mutlak pozisyon tavanı ({self.hard_max_positions}) dolu."
        if side and open_sides:
            same = sum(1 for x in open_sides if x == side)
            if same >= self.max_same_side_positions:
                return False, f"Aynı yönde ({side}) en fazla {self.max_same_side_positions} pozisyon (korelasyon riski)."
        if self.unlimited_pyramiding and all_in_profit and open_count > 0:
            return True, "OK (tüm açık pozisyonlar artıda → ekleme izni, sert tavan içinde)"
        if open_count >= self.max_positions:
            return False, f"Maksimum pozisyon ({self.max_positions}) dolu."
        return True, "OK"

    def can_add_to_winner(self, pos: Position, price: float) -> tuple[bool, str]:
        """Aynı semboldeki açık pozisyon artıdaysa sınırsız kademe eklenebilir mi?"""
        if not self.unlimited_pyramiding:
            return False, "sınırsız ekleme kapalı"
        if pos.layers >= self.max_layers:
            return False, f"kademe tavanı ({self.max_layers}) doldu"
        pnl = self.profit_pct(pos, price)
        if pnl <= 0:
            return False, f"pozisyon henüz artıda değil (%{pnl:+.2f})"
        ref_px = pos.last_add_price if pos.last_add_price > 0 else pos.entry
        if pos.side == "LONG":
            step_pct = (price - ref_px) / ref_px * 100.0
        else:
            step_pct = (ref_px - price) / ref_px * 100.0
        if step_pct < self.pyramid_min_profit_pct and pnl < self.pyramid_min_profit_pct:
            return False, f"ekleme adımı küçük (%{step_pct:+.2f} < %{self.pyramid_min_profit_pct})"
        return (
            True,
            f"artıda (%{pnl:+.2f}, ROE %{self.roe_pct(pos, price):+.1f}) → {pos.layers + 1}. kademe ekleniyor",
        )

    def find_pair_rescue(
        self, positions: dict[str, Position], prices: dict[str, float]
    ) -> dict | None:
        """Kural: Biri artıda biri ekside (terste) ise ufak zarar ya da kârla ikisini kapat."""
        if not self.pair_rescue_enabled or len(positions) < 2:
            return None

        winners: list[tuple[Position, float, float, float]] = []
        losers: list[tuple[Position, float, float, float]] = []

        for sym, pos in positions.items():
            px = prices.get(sym)
            if not px or px <= 0:
                continue
            pct = self.profit_pct(pos, px)
            usd = self.pnl_usdt(pos, px)
            if pct > 0.05 and usd > 0:
                winners.append((pos, px, pct, usd))
            elif pct <= -self.rescue_min_loser_pct and usd < 0:
                losers.append((pos, px, pct, usd))

        if not winners or not losers:
            return None

        losers.sort(key=lambda x: x[3])
        winners.sort(key=lambda x: x[3], reverse=True)

        for l_pos, l_px, l_pct, l_usd in losers:
            for w_pos, w_px, w_pct, w_usd in winners:
                if l_pos.symbol == w_pos.symbol:
                    continue
                net_usd = w_usd + l_usd
                l_margin = (
                    l_pos.margin_usdt
                    if l_pos.margin_usdt > 0
                    else (l_pos.entry * l_pos.qty) / max(1, l_pos.leverage)
                )
                w_margin = (
                    w_pos.margin_usdt
                    if w_pos.margin_usdt > 0
                    else (w_pos.entry * w_pos.qty) / max(1, w_pos.leverage)
                )
                tot_margin = max(1.0, l_margin + w_margin)
                net_margin_pct = (net_usd / tot_margin) * 100.0

                covers_loss = w_usd >= abs(l_usd) * 0.75
                in_band = (
                    self.rescue_min_net_margin_pct
                    <= net_margin_pct
                    <= self.rescue_max_net_margin_pct
                )
                small_profit_rescue = net_usd >= 0 and covers_loss

                if covers_loss and (in_band or small_profit_rescue):
                    durum = "UFAK KÂRLA" if net_usd >= 0 else "UFAK ZARARLA"
                    return {
                        "action": "pair_close",
                        "winner_symbol": w_pos.symbol,
                        "winner_price": w_px,
                        "winner_pnl_pct": round(w_pct, 2),
                        "winner_pnl_usdt": round(w_usd, 2),
                        "loser_symbol": l_pos.symbol,
                        "loser_price": l_px,
                        "loser_pnl_pct": round(l_pct, 2),
                        "loser_pnl_usdt": round(l_usd, 2),
                        "net_pnl_usdt": round(net_usd, 2),
                        "net_margin_pct": round(net_margin_pct, 2),
                        "reason": (
                            f"ÇAPRAZ KURTARMA ({durum} İKİLİ KAPAMA): "
                            f"{w_pos.symbol} (+${w_usd:.2f} / %{w_pct:+.2f}) + "
                            f"{l_pos.symbol} (-${abs(l_usd):.2f} / %{l_pct:+.2f}) → "
                            f"Net: ${net_usd:+.2f} (marjın %{net_margin_pct:+.2f}'si)"
                        ),
                    }
        return None

    def _reset_week_if_needed(self):
        wk = datetime.now(timezone.utc).isocalendar()[:2]
        if wk != self._week:
            self._week, self._weekly_pnl_pct = wk, 0.0

    @property
    def weekly_pnl_pct(self) -> float:
        self._reset_week_if_needed()
        return self._weekly_pnl_pct

    def register_close(self, pnl_pct: float):
        self._reset_day_if_needed()
        self._reset_week_if_needed()
        self._daily_pnl_pct += pnl_pct
        self._weekly_pnl_pct += pnl_pct

    def update(self, pos: Position, price: float) -> dict:
        """Stop seviyesini günceller, kapatılması gerekiyorsa söyler."""
        pnl = self.profit_pct(pos, price)
        roe = self.roe_pct(pos, price)
        usd = self.pnl_usdt(pos, price)

        if pos.side == "LONG":
            pos.peak = max(pos.peak, price)
            if pnl >= self.lock_trigger_pct:
                lock_stop = pos.entry * (1 + self.lock_level_pct / 100)
                if lock_stop > pos.stop:
                    pos.stop = lock_stop
                    pos.locked_profit = True
            trail_stop = pos.peak * (1 - self.trail_pct / 100)
            if trail_stop > pos.stop and pnl > 0:
                pos.stop = trail_stop
            if price <= pos.stop:
                reason = (
                    "KÂR KİLİDİ STOPU"
                    if pos.locked_profit and pnl > 0
                    else "TRAILING STOP"
                    if pnl > 0
                    else "STOP-LOSS %5"
                )
                return {
                    "action": "close",
                    "reason": reason,
                    "stop": pos.stop,
                    "pnl_pct": pnl,
                    "roe_pct": roe,
                    "pnl_usdt": usd,
                    "locked": pos.locked_profit,
                }
        else:  # SHORT
            pos.peak = min(pos.peak if pos.peak else price, price)
            if pnl >= self.lock_trigger_pct:
                lock_stop = pos.entry * (1 - self.lock_level_pct / 100)
                if lock_stop < pos.stop:
                    pos.stop = lock_stop
                    pos.locked_profit = True
            trail_stop = pos.peak * (1 + self.trail_pct / 100)
            if trail_stop < pos.stop and pnl > 0:
                pos.stop = trail_stop
            if price >= pos.stop:
                reason = (
                    "KÂR KİLİDİ STOPU"
                    if pos.locked_profit and pnl > 0
                    else "TRAILING STOP"
                    if pnl > 0
                    else "STOP-LOSS %5"
                )
                return {
                    "action": "close",
                    "reason": reason,
                    "stop": pos.stop,
                    "pnl_pct": pnl,
                    "roe_pct": roe,
                    "pnl_usdt": usd,
                    "locked": pos.locked_profit,
                }

        return {
            "action": "hold",
            "reason": "pozisyon sürüyor",
            "stop": pos.stop,
            "pnl_pct": pnl,
            "roe_pct": roe,
            "pnl_usdt": usd,
            "locked": pos.locked_profit,
        }
