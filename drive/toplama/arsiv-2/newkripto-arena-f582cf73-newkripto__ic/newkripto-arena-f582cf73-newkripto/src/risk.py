"""Risk yönetimi — sabit marj stopu, trailing ve portföy güvenlik sınırları.

Aktif yapılandırma: 50 USDT marj × 10x ve marjın %80'i (40 USDT) fiyat K/Z
başlangıç stopu. Stop, 10x tahmini likidasyon mesafesinin önünde üretilir.
Sabit TP yerine trailing/kâr kilidi kullanılır; Executor ayrıca doğrulanmış
order-flow dönüşleriyle kâr koşusunu kapatır.

Eski fiyat-yüzde, ATR/swing ve dinamik kaldıraç modları test ve karşılaştırma
için korunur. Ücret, funding ve kayma net gerçekleşen zararı değiştirebilir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


def position_limits_for_mode(cfg: dict, mode: str) -> dict[str, int]:
    """Paper deneyindeki geniş limitleri gerçek/testnet hesabından ayırır."""
    limits = {
        "max_positions": int(cfg.get("max_pozisyon", 3)),
        "hard_max_positions": int(cfg.get("mutlak_max_pozisyon", 6)),
        "max_same_side_positions": int(cfg.get("ayni_yon_max_pozisyon", 4)),
    }
    if str(mode).lower() == "paper" and cfg.get("paper_genis_pozisyon_limiti", False):
        paper_max = int(cfg.get("paper_max_pozisyon", 1000))
        paper_same_side = int(cfg.get("paper_ayni_yon_max_pozisyon", paper_max))
        return {
            "max_positions": paper_max,
            "hard_max_positions": paper_max,
            "max_same_side_positions": min(paper_max, paper_same_side),
        }
    return limits


@dataclass
class Position:
    symbol: str
    side: str
    entry: float
    qty: float
    stop: float
    peak: float = 0.0
    locked_profit: bool = False
    opened_at: str = ""
    leverage: int = 20
    margin_usdt: float = 0.0      # Kasanın %10'u ile ayrılan toplam marj ($)
    layers: int = 1               # Kaç kademe ekleme yapıldı (sınırsız pyramiding)
    last_add_price: float = 0.0   # Son ekleme yapılan fiyat
    exchange: str = ""            # Pozisyonun açıldığı borsa (failover'da değişmez)
    # Gerçekleşen giriş ücreti/funding ve tahmini çıkış ücreti net başabaş
    # muhasebesi için pozisyonla taşınır. Varsayılan kapalı mod ana stratejiyi
    # değiştirmez; Shadow Lab net-exit varyantı bu alanları etkinleştirir.
    entry_fee_usdt: float = 0.0
    exit_fee_pct: float = 0.0
    funding_usdt: float = 0.0
    net_breakeven_enabled: bool = False
    net_profit_buffer_usdt: float = 0.0
    mfe_usdt: float = 0.0
    mae_usdt: float = 0.0

    def __post_init__(self):
        if not self.opened_at:
            self.opened_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if self.peak == 0.0:
            self.peak = float(self.entry)
        if self.last_add_price == 0.0:
            self.last_add_price = float(self.entry)

    def add_layer(
        self,
        add_price: float,
        add_qty: float,
        add_margin_usdt: float = 0.0,
        stop_loss_pct: float = 5.0,
    ) -> None:
        if add_qty <= 0 or add_price <= 0:
            return
        total_qty = self.qty + add_qty
        self.entry = (self.entry * self.qty + add_price * add_qty) / total_qty
        self.qty = total_qty
        self.margin_usdt += float(add_margin_usdt)
        self.layers += 1
        self.last_add_price = float(add_price)
        if self.side == "LONG":
            new_stop = self.entry * (1 - stop_loss_pct / 100.0)
            self.stop = max(self.stop, new_stop)
            self.peak = max(self.peak, add_price)
        else:
            new_stop = self.entry * (1 + stop_loss_pct / 100.0)
            self.stop = min(self.stop, new_stop)
            self.peak = min(self.peak, add_price)


class RiskManager:
    def __init__(
        self,
        stop_loss_pct: float = 5.0,
        stop_model: str = "fiyat_yuzde",
        margin_stop_fraction: float = 0.80,
        margin_stop_liq_buffer: float = 0.85,
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
        margin_mode: str = "isolated",
        cross_max_margin_pct: float = 95.0,
        cross_min_free_usdt: float = 50.0,
        early_lock_trigger_pct: float = 0.0,
        early_lock_level_pct: float = 0.12,
        state_store=None,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.stop_model = str(stop_model or "fiyat_yuzde").strip().lower()
        self.margin_stop_fraction = float(margin_stop_fraction)
        self.margin_stop_liq_buffer = float(margin_stop_liq_buffer)
        self.lock_trigger_pct = lock_trigger_pct
        self.lock_level_pct = lock_level_pct
        self.trail_pct = trail_pct
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_positions = int(max_positions)
        self.daily_max_loss_pct = daily_max_loss_pct
        self.capital_pct_per_entry = capital_pct_per_entry
        self.leverage = int(leverage)
        self.unlimited_pyramiding = bool(unlimited_pyramiding)
        self.pyramid_min_profit_pct = float(pyramid_min_profit_pct)
        self.pair_rescue_enabled = bool(pair_rescue_enabled)
        self.rescue_min_loser_pct = float(rescue_min_loser_pct)
        self.max_slippage_pct = float(max_slippage_pct)
        self.dynamic_leverage_enabled = bool(dynamic_leverage_enabled)
        self.atr_high_volatility_pct = float(atr_high_volatility_pct)
        self.atr_extreme_volatility_pct = float(atr_extreme_volatility_pct)
        self.max_layers = int(max_layers)
        self.hard_max_positions = int(hard_max_positions)
        self.max_same_side_positions = int(max_same_side_positions)
        self.max_total_margin_pct = float(max_total_margin_pct)
        self.weekly_max_loss_pct = float(weekly_max_loss_pct)
        self.liq_stop_buffer = float(liq_stop_buffer)
        self.maintenance_margin_pct = float(maintenance_margin_pct)
        self.margin_mode = str(margin_mode or "isolated").strip().lower()
        self.cross_max_margin_pct = float(cross_max_margin_pct)
        self.cross_min_free_usdt = float(cross_min_free_usdt)
        self.early_lock_trigger_pct = max(0.0, float(early_lock_trigger_pct or 0.0))
        self.early_lock_level_pct = max(0.0, float(early_lock_level_pct or 0.0))

        self._daily_pnl_pct = 0.0
        self._day = datetime.now(timezone.utc).date()
        self._weekly_pnl_pct = 0.0
        self._week = datetime.now(timezone.utc).isocalendar()[:2]
        self.state_store = state_store
        self._restore_state()

    def _restore_state(self) -> None:
        """Zarar limitlerini yeniden başlatma sonrasında da korur."""
        if self.state_store is None or not hasattr(self.state_store, "get_meta"):
            return
        saved = self.state_store.get_meta("risk_limits", {}) or {}
        if not isinstance(saved, dict):
            return
        today = datetime.now(timezone.utc).date().isoformat()
        week = datetime.now(timezone.utc).isocalendar()[:2]
        if saved.get("day") == today:
            value = float(saved.get("daily_pnl_pct", 0.0))
            if math.isfinite(value):
                self._daily_pnl_pct = value
        if tuple(saved.get("week", ())) == tuple(week):
            value = float(saved.get("weekly_pnl_pct", 0.0))
            if math.isfinite(value):
                self._weekly_pnl_pct = value

    def _sync_state(self) -> None:
        if self.state_store is None or not hasattr(self.state_store, "set_meta"):
            return
        self.state_store.set_meta(
            "risk_limits",
            {
                "day": self._day.isoformat(),
                "week": list(self._week),
                "daily_pnl_pct": self._daily_pnl_pct,
                "weekly_pnl_pct": self._weekly_pnl_pct,
            },
        )

    def _reset_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._daily_pnl_pct = 0.0

    def _reset_week_if_needed(self) -> None:
        week = datetime.now(timezone.utc).isocalendar()[:2]
        if week != self._week:
            self._week = week
            self._weekly_pnl_pct = 0.0

    @property
    def daily_pnl_pct(self) -> float:
        self._reset_day_if_needed()
        return self._daily_pnl_pct

    @property
    def weekly_pnl_pct(self) -> float:
        self._reset_week_if_needed()
        return self._weekly_pnl_pct

    def liquidation_stop_pct(self, leverage: int | None = None) -> float:
        """Verilen kaldıraçta stop için izin verilen en geniş fiyat mesafesi."""
        lev = max(1, int(leverage or self.leverage or 1))
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(liq_dist * self.liq_stop_buffer, 4)

    def margin_stop_pct(self, leverage: int | None = None) -> float:
        """Marjın yapılandırılan payını riske eden fiyat mesafesi.

        10x ve %80 için istenen mesafe %8'dir (50 USDT marj → 40 USDT).
        Yalnız bu modele özel %85 likidasyon tamponu uygulanır; eski %70
        tamponu stopu istenmeden %6.65'e düşürmez.
        """
        lev = max(1, int(leverage or self.leverage or 1))
        requested = (100.0 / lev) * self.margin_stop_fraction
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(requested, liq_dist * self.margin_stop_liq_buffer), 4)

    def effective_stop_pct(self, leverage: int | None = None) -> float:
        """Seçilen marj veya fiyat-yüzde modelinin likidasyon bilinçli stopu."""
        lev = max(1, int(leverage or self.leverage or 1))
        if self.stop_model in {"marj", "margin"}:
            return self.margin_stop_pct(lev)
        return round(min(self.stop_loss_pct, self.liquidation_stop_pct(lev)), 4)

    def initial_stop(self, side: str, entry: float, leverage: int | None = None) -> float:
        """Marj-risk veya eski fiyat-yüzde modeline göre başlangıç stopu."""
        if self.stop_model in {"marj", "margin"}:
            pct = self.margin_stop_pct(leverage)
        else:
            pct = self.effective_stop_pct(leverage) if leverage else self.stop_loss_pct
        if side == "LONG":
            return entry * (1 - pct / 100)
        return entry * (1 + pct / 100)

    def stop_reason(self) -> str:
        """Log ve Telegram için aktif stop modelinin doğru etiketi."""
        if self.stop_model in {"marj", "margin"}:
            return f"STOP-LOSS (marjın %{self.margin_stop_fraction * 100:g})"
        return f"STOP-LOSS (%{self.stop_loss_pct:g})"

    def close_stop_reason(self, pos: Position) -> str:
        """Başlangıç stopu ile trailing/başabaş-kâr stopunu ayırır."""
        if pos.locked_profit:
            return "KÂR KİLİDİ STOPU"
        if (pos.side == "LONG" and pos.stop >= pos.entry) or (
            pos.side == "SHORT" and pos.stop <= pos.entry
        ):
            return "TRAILING STOP"
        return self.stop_reason()

    def atr_structure_plan(
        self,
        side: str,
        entry: float,
        atr: float,
        leverage: int,
        swing_low: float | None = None,
        swing_high: float | None = None,
        atr_mult: float = 1.5,
        structure_buffer_atr: float = 0.20,
        max_stop_pct: float = 12.0,
    ) -> dict:
        """ATR + swing yapısına göre stop ve uyumlu kaldıraç üretir."""
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side LONG veya SHORT olmalı")
        entry, atr = float(entry), float(atr)
        if entry <= 0 or not math.isfinite(entry) or atr <= 0 or not math.isfinite(atr):
            return {"accepted": False, "reason": "ATR/fiyat geçersiz"}

        direction = 1.0 if side == "LONG" else -1.0
        atr_stop = entry - direction * atr * float(atr_mult)
        stop = atr_stop
        source = "ATR"
        if side == "LONG" and swing_low is not None and 0 < float(swing_low) < entry:
            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
            if structure_stop > 0 and structure_stop < stop:
                stop, source = structure_stop, "ATR+SWING"
        elif side == "SHORT" and swing_high is not None and float(swing_high) > entry:
            structure_stop = float(swing_high) + atr * float(structure_buffer_atr)
            if structure_stop > stop:
                stop, source = structure_stop, "ATR+SWING"

        risk_distance = abs(entry - stop)
        stop_pct = risk_distance / entry * 100.0
        if stop <= 0 or risk_distance <= 0 or not math.isfinite(stop_pct):
            return {"accepted": False, "reason": "Geçerli ATR/swing stopu üretilemedi"}
        if stop_pct > float(max_stop_pct):
            return {
                "accepted": False,
                "reason": f"ATR/swing stop %{stop_pct:.2f} > maksimum %{float(max_stop_pct):.2f}",
            }

        requested_leverage = max(1, int(leverage))
        candidates = sorted(
            {requested_leverage, 10, 5, 3, 2, 1}, reverse=True
        )
        selected = next(
            (
                lev for lev in candidates
                if lev <= requested_leverage and stop_pct <= self.liquidation_stop_pct(lev)
            ),
            None,
        )
        if selected is None:
            return {
                "accepted": False,
                "reason": f"ATR/swing stop %{stop_pct:.2f}, 1x likidasyon tamponuna bile sığmıyor",
            }
        return {
            "accepted": True,
            "side": side,
            "entry": entry,
            "stop": float(stop),
            "risk_distance": float(risk_distance),
            "stop_pct": float(stop_pct),
            "leverage": int(selected),
            "requested_leverage": requested_leverage,
            "leverage_reduced": selected < requested_leverage,
            "atr": atr,
            "source": source,
            "reason": (
                f"{source} stop %{stop_pct:.2f}"
                + (
                    f"; kaldıraç {requested_leverage}x→{selected}x"
                    if selected < requested_leverage
                    else ""
                )
            ),
        }

    # -- Dinamik Kaldıraç & Hesaplamalar --------------------------------------
    def compute_dynamic_leverage(
        self,
        price: float,
        atr: float | None = None,
        veto_approaching: bool = False,
        fear_greed: float = 50.0,
    ) -> tuple[int, str]:
        base = max(1, int(self.leverage))
        if not self.dynamic_leverage_enabled:
            return base, f"sabit {base}x"
        if veto_approaching or fear_greed <= 18 or fear_greed >= 88:
            lev = min(base, 5)
            return lev, f"kriz/veto koruması ({lev}x)"
        if atr is not None and price > 0:
            atr_pct = float(atr) / float(price) * 100.0
            if atr_pct >= self.atr_extreme_volatility_pct:
                lev = min(base, 5)
                return lev, f"aşırı oynaklık ATR %{atr_pct:.2f} ({lev}x)"
            if atr_pct >= self.atr_high_volatility_pct:
                lev = min(base, 10)
                return lev, f"yüksek oynaklık ATR %{atr_pct:.2f} ({lev}x)"
        return base, f"normal piyasa ({base}x)"

    def position_size(self, balance_usdt: float, entry: float, stop: float) -> float:
        """Risk-bazlı pozisyon miktarı (coin adedi)."""
        dist = abs(float(entry) - float(stop))
        if balance_usdt <= 0 or entry <= 0 or dist <= 0:
            return 0.0
        risk_usdt = float(balance_usdt) * (self.risk_per_trade_pct / 100.0)
        return risk_usdt / dist

    def leveraged_entry_size(
        self,
        balance_usdt: float,
        entry: float,
        capital_pct: float | None = None,
        leverage: int | None = None,
    ) -> tuple[float, dict]:
        """Kasa yüzdesi × kaldıraç ile marj, büyüklük ve miktar hesabı."""
        cap = float(capital_pct if capital_pct is not None else self.capital_pct_per_entry)
        lev = max(1, int(leverage if leverage is not None else self.leverage))
        if balance_usdt <= 0 or entry <= 0 or cap <= 0:
            return 0.0, {"margin_usdt": 0.0, "notional_usdt": 0.0, "leverage": lev}
        margin_usdt = float(balance_usdt) * (cap / 100.0)
        notional_usdt = margin_usdt * lev
        qty = notional_usdt / float(entry)
        return qty, {
            "margin_usdt": margin_usdt,
            "notional_usdt": notional_usdt,
            "leverage": lev,
        }

    def profit_pct(self, pos: Position, price: float) -> float:
        if pos.entry <= 0:
            return 0.0
        if pos.side == "LONG":
            return (price - pos.entry) / pos.entry * 100.0
        return (pos.entry - price) / pos.entry * 100.0

    def roe_pct(self, pos: Position, price: float) -> float:
        return self.profit_pct(pos, price) * max(1, int(pos.leverage))

    def pnl_usdt(self, pos: Position, price: float) -> float:
        if pos.side == "LONG":
            return (price - pos.entry) * pos.qty
        return (pos.entry - price) * pos.qty

    # -- C) Portföy seviyesi sert limitler ------------------------------------
    def equity_pnl_pct(self, pnl_usdt: float, balance_usdt: float) -> float:
        """Kapanan işlemin K/Z'sini HESAP bakiyesine oranla (%) verir (fiyat % değil)."""
        if balance_usdt <= 0:
            return 0.0
        return float(pnl_usdt) / float(balance_usdt) * 100.0

    def margin_cap_ok(
        self, used_margin_usdt: float, add_margin_usdt: float, balance_usdt: float
    ) -> tuple[bool, str]:
        if balance_usdt <= 0:
            return False, "bakiye sıfır veya negatif"
        total = float(used_margin_usdt) + float(add_margin_usdt)
        pct = total / float(balance_usdt) * 100.0
        if pct > self.max_total_margin_pct:
            return (
                False,
                f"toplam marj tavanı aşıldı (%{pct:.1f} > %{self.max_total_margin_pct:.1f})",
            )
        return True, "OK"

    def cross_pool_ok(
        self,
        active_margin_usdt: float,
        add_margin_usdt: float,
        equity_usdt: float,
        total_notional_usdt: float = 0.0,
    ) -> tuple[bool, str]:
        """Çapraz (Cross) ortak Futures kasa havuzu kontrolü (Bakiye + Açık K/Z)."""
        if equity_usdt <= 0:
            return False, "ortak özsermaye sıfır veya negatif"
        maint_usdt = max(0.0, float(total_notional_usdt)) * (
            self.maintenance_margin_pct / 100.0
        )
        if equity_usdt <= maint_usdt + self.cross_min_free_usdt:
            return (
                False,
                f"çapraz kasa sürdürme teminatı tamponu sınırda "
                f"(özsermaye=${equity_usdt:.2f}, sürdürme=${maint_usdt:.2f})",
            )
        total_active = max(0.0, float(active_margin_usdt)) + max(0.0, float(add_margin_usdt))
        pct = total_active / float(equity_usdt) * 100.0
        if pct > self.cross_max_margin_pct:
            return (
                False,
                f"çapraz kasa teminat kapasitesi dolu (%{pct:.1f} > %{self.cross_max_margin_pct:.1f})",
            )
        return True, "OK"

    def can_open(
        self,
        open_count: int,
        *,
        all_in_profit: bool = False,
        side: str | None = None,
        open_sides: list[str] | None = None,
    ) -> tuple[bool, str]:
        self._reset_day_if_needed()
        self._reset_week_if_needed()
        if self._daily_pnl_pct <= -self.daily_max_loss_pct:
            return (
                False,
                f"günlük zarar limiti aşıldı (%{self._daily_pnl_pct:.2f} <= -%{self.daily_max_loss_pct:.2f})",
            )
        if self._weekly_pnl_pct <= -self.weekly_max_loss_pct:
            return (
                False,
                f"haftalık zarar limiti aşıldı (%{self._weekly_pnl_pct:.2f} <= -%{self.weekly_max_loss_pct:.2f})",
            )
        if open_count >= self.hard_max_positions:
            return (
                False,
                f"mutlak maksimum pozisyon sınırına ulaşıldı ({open_count}/{self.hard_max_positions})",
            )
        if open_count >= self.max_positions and not (self.unlimited_pyramiding and all_in_profit):
            return (
                False,
                f"maksimum açık pozisyon sınırına ulaşıldı ({open_count}/{self.max_positions})",
            )
        if side and open_sides is not None:
            same_side = sum(1 for s in open_sides if s == side)
            if same_side >= self.max_same_side_positions:
                return (
                    False,
                    f"aynı yönde ({side}) maksimum pozisyon sınırına ulaşıldı "
                    f"({same_side}/{self.max_same_side_positions})",
                )
        return True, "OK"

    def can_add_to_winner(self, pos: Position, price: float) -> tuple[bool, str]:
        if not self.unlimited_pyramiding:
            return False, "sınırsız kademe ekleme kapalı"
        if pos.layers >= self.max_layers:
            return False, f"maksimum kademe sınırına ulaşıldı ({pos.layers}/{self.max_layers})"
        pnl = self.profit_pct(pos, price)
        if pnl <= 0:
            return False, "pozisyon kârda değil"
        ref_px = pos.last_add_price if pos.last_add_price > 0 else pos.entry
        if pos.side == "LONG":
            step_pct = (price - ref_px) / ref_px * 100.0
        else:
            step_pct = (ref_px - price) / ref_px * 100.0
        # Son kademeden bu yana yeterli fiyat ilerlemesi ŞARTTIR. Toplam kârın
        # yüksek olması aynı fiyatta arka arkaya kademe açılmasına gerekçe olamaz.
        if step_pct < self.pyramid_min_profit_pct:
            return False, f"ekleme adımı küçük (%{step_pct:+.2f} < %{self.pyramid_min_profit_pct})"
        return (
            True,
            f"artıda kademe #{pos.layers + 1} (toplam %{pnl:+.2f}, son kademeden %{step_pct:+.2f})",
        )

    def find_pair_rescue(
        self, positions: dict[str, Position], prices: dict[str, float]
    ) -> dict | None:
        """Biri artıda biri ekside iki pozisyon birbirini netliyorsa ikili kapama önerir."""
        if not self.pair_rescue_enabled or len(positions) < 2:
            return None
        evaluated = []
        for sym, pos in positions.items():
            px = prices.get(sym)
            if px is None or px <= 0:
                continue
            pnl_pct = self.profit_pct(pos, px)
            pnl_usd = self.pnl_usdt(pos, px)
            evaluated.append((sym, pos, px, pnl_pct, pnl_usd))
        winners = [row for row in evaluated if row[4] > 0 and row[3] > 0]
        losers = [
            row for row in evaluated if row[4] < 0 and row[3] <= -self.rescue_min_loser_pct
        ]
        if not winners or not losers:
            return None
        winners.sort(key=lambda r: r[4], reverse=True)
        losers.sort(key=lambda r: r[4])
        w_sym, w_pos, w_px, w_pct, w_usd = winners[0]
        for l_sym, l_pos, l_px, l_pct, l_usd in losers:
            if l_sym == w_sym:
                continue
            combined_margin = max(1.0, (w_pos.margin_usdt or 50.0) + (l_pos.margin_usdt or 50.0))
            net_usd = w_usd + l_usd
            # Kazanan bacak zararı tamamen veya küçük bir kurtarma toleransıyla karşılıyorsa kapat
            if net_usd >= -0.02 * combined_margin:
                return {
                    "action": "pair_close",
                    "winner_symbol": w_sym,
                    "loser_symbol": l_sym,
                    "winner_price": w_px,
                    "loser_price": l_px,
                    "winner_pnl_pct": w_pct,
                    "loser_pnl_pct": l_pct,
                    "net_pnl_usdt": net_usd,
                    "reason": (
                        f"ÇAPRAZ KURTARMA: {w_sym} (+${w_usd:.2f}) ile "
                        f"{l_sym} (${l_usd:.2f}) net=${net_usd:+.2f} kapama"
                    ),
                }
        return None

    def register_close(self, pnl_pct: float) -> None:
        self._reset_day_if_needed()
        self._reset_week_if_needed()
        value = float(pnl_pct)
        if not math.isfinite(value):
            raise ValueError("PnL yüzdesi sonlu bir sayı olmalı")
        self._daily_pnl_pct += value
        self._weekly_pnl_pct += value
        self._sync_state()

    def net_breakeven_price(self, pos: Position) -> float:
        """Gerçek giriş ücreti + funding + tamponu kapsayan tahmini net başabaş."""
        qty = abs(float(pos.qty))
        if qty <= 0 or pos.entry <= 0:
            return float(pos.entry)
        exit_rate = max(0.0, min(0.99, float(pos.exit_fee_pct) / 100.0))
        entry_fee = float(getattr(pos, "entry_fee_usdt", 0.0))
        funding = float(getattr(pos, "funding_usdt", 0.0))
        buffer = float(getattr(pos, "net_profit_buffer_usdt", 0.0))
        if pos.side == "LONG":
            return (
                pos.entry * qty + entry_fee - funding + buffer
            ) / (qty * (1.0 - exit_rate))
        return (
            pos.entry * qty - entry_fee + funding - buffer
        ) / (qty * (1.0 + exit_rate))

    def update(self, pos: Position, price: float) -> dict:
        """MFE/MAE ve stopu günceller, kapatılması gerekiyorsa söyler."""
        pnl = self.profit_pct(pos, price)
        roe = self.roe_pct(pos, price)
        usd = self.pnl_usdt(pos, price)
        pos.mfe_usdt = max(float(getattr(pos, "mfe_usdt", 0.0)), usd)
        pos.mae_usdt = min(float(getattr(pos, "mae_usdt", 0.0)), usd)
        use_net_be = bool(getattr(pos, "net_breakeven_enabled", False))
        floor = self.net_breakeven_price(pos) if use_net_be else float(pos.entry)

        if pos.side == "LONG":
            pos.peak = max(pos.peak, price)
            if self.early_lock_trigger_pct > 0 and pnl >= self.early_lock_trigger_pct:
                early_stop = max(
                    floor, pos.entry * (1 + self.early_lock_level_pct / 100.0)
                )
                if early_stop > pos.stop:
                    pos.stop = early_stop
                    pos.locked_profit = True
            if pnl >= self.lock_trigger_pct:
                lock_stop = max(floor, pos.entry * (1 + self.lock_level_pct / 100))
                if lock_stop > pos.stop:
                    pos.stop = lock_stop
                    pos.locked_profit = True
            trail_stop = pos.peak * (1 - self.trail_pct / 100)
            if use_net_be:
                if pnl > 0 and trail_stop >= pos.entry:
                    candidate = max(trail_stop, floor)
                    if candidate > pos.stop:
                        pos.stop = candidate
            elif trail_stop > pos.stop and pnl > 0 and trail_stop >= pos.entry:
                pos.stop = trail_stop
            if price <= pos.stop:
                return {
                    "action": "close",
                    "reason": self.close_stop_reason(pos),
                    "stop": pos.stop,
                    "pnl_pct": pnl,
                    "roe_pct": roe,
                    "pnl_usdt": usd,
                }
        else:
            pos.peak = min(pos.peak, price)
            if self.early_lock_trigger_pct > 0 and pnl >= self.early_lock_trigger_pct:
                early_stop = min(
                    floor, pos.entry * (1 - self.early_lock_level_pct / 100.0)
                )
                if early_stop < pos.stop:
                    pos.stop = early_stop
                    pos.locked_profit = True
            if pnl >= self.lock_trigger_pct:
                lock_stop = min(floor, pos.entry * (1 - self.lock_level_pct / 100))
                if lock_stop < pos.stop:
                    pos.stop = lock_stop
                    pos.locked_profit = True
            trail_stop = pos.peak * (1 + self.trail_pct / 100)
            if use_net_be:
                if pnl > 0 and trail_stop <= pos.entry:
                    candidate = min(trail_stop, floor)
                    if candidate < pos.stop:
                        pos.stop = candidate
            elif trail_stop < pos.stop and pnl > 0 and trail_stop <= pos.entry:
                pos.stop = trail_stop
            if price >= pos.stop:
                return {
                    "action": "close",
                    "reason": self.close_stop_reason(pos),
                    "stop": pos.stop,
                    "pnl_pct": pnl,
                    "roe_pct": roe,
                    "pnl_usdt": usd,
                }

        return {
            "action": "hold",
            "stop": pos.stop,
            "pnl_pct": pnl,
            "roe_pct": roe,
            "pnl_usdt": usd,
            "locked": pos.locked_profit,
            "mfe_usdt": pos.mfe_usdt,
            "mae_usdt": pos.mae_usdt,
            "net_breakeven_price": floor if use_net_be else None,
        }
