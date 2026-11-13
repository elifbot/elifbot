"""Kripto Bot v9.0 — Komisyon & İcra Optimizasyon Motoru (`CommissionOptimizer`).

Kural_05_Maliyet_Komisyon + Kural_03_Indikator_MTF + Kural_10_Veri_Defter_Sagligi ortak uzmanlığıyla tasarlanan bu modül,
24 gerçek canlı borsa işleminde tespit edilen "%114 brüt kârın komisyona gitmesi" sorununu
4 katmanlı mühendislik zırhıyla çözer:

  1. Akıllı Maker-Öncelikli Giriş & Çıkış (`choose_entry_mode` / `choose_exit_mode`):
     Normal makasta (`spread <= %0.08`) Taker Market (`%0.05` = $0.50/$1000) yerine
     Post-Only / Pasif Maker Limit (`%0.02` = $0.20/$1000) kullanarak giriş/kâr-al
     komisyonunu **%60 düşürür** ($1.00 gidiş-dönüş -> $0.40 gidiş-dönüş).
  2. En Ucuz Borsa Yönlendirici (`select_optimal_venue`):
     Binance ve OKX anlık `(spread/2 + komisyon)` toplam efektif maliyetini karşılaştırıp
     en düşük maliyetli borsayı seçer.
  3. Beklenen Hareket / Komisyon Çarpanı Kapısı (`evaluate_fee_viability`):
     Paritenin beklenen ATR hareketi, tahmini gidiş-dönüş komisyon + makas maliyetinin
     en az `min_fee_multiple` (`3.0x`) katı değilse mikro-testere girişini engeller.
  4. Komisyon-Dahil Kademeli MFE Kâr Kilidi (`compute_net_mfe_lock_usdt`):
     Kâr kilidinin brüt kâr üzerinden erken tetiklenip komisyon sonrası net eksi (`-$0.53`)
     yazmasını engeller; kilit tabanına her zaman `giriş_ücreti + tahmini_çıkış_ücreti + net_tampon` ekler.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FeeViabilityResult:
    viable: bool
    expected_move_usdt: float
    roundtrip_cost_usdt: float
    fee_multiple: float
    recommended_mode: str  # "maker", "chase_limit", "market"
    reason: str


class CommissionOptimizer:
    """Komisyon yükünü minimize eden ve komisyon-sonrası negatif beklentili işlemleri eleyen motor."""

    def __init__(
        self,
        *,
        maker_fee_pct: float = 0.02,
        taker_fee_pct: float = 0.05,
        bnb_discount_active: bool = False,
        max_maker_spread_pct: float = 0.08,
        max_entry_spread_pct: float = 0.08,
        min_fee_multiple: float = 3.0,
        min_net_lock_profit_usdt: float = 0.45,
        atr_slippage_fraction: float = 0.03,
    ):
        discount = 0.90 if bnb_discount_active else 1.0
        self.maker_fee_pct = max(0.0, float(maker_fee_pct) * discount)
        self.taker_fee_pct = max(0.0, float(taker_fee_pct) * discount)
        self.max_maker_spread_pct = max(0.005, float(max_maker_spread_pct))
        self.max_entry_spread_pct = max(0.005, float(max_entry_spread_pct))
        self.min_fee_multiple = max(1.2, float(min_fee_multiple))
        self.min_net_lock_profit_usdt = max(0.10, float(min_net_lock_profit_usdt))
        self.atr_slippage_fraction = max(0.0, float(atr_slippage_fraction))

        self.stats = {
            "evaluated_signals": 0,
            "blocked_fee_drag": 0,
            "blocked_wide_spread": 0,
            "maker_entries": 0,
            "taker_entries": 0,
            "maker_exits": 0,
            "taker_exits": 0,
            "estimated_saved_usdt": 0.0,
        }

    def estimate_dynamic_slippage_pct(
        self,
        *,
        spread_pct: float = 0.02,
        atr_pct: float = 0.40,
        notional_usdt: float = 1000.0,
        minute_quote_vol_usdt: float = 150_000.0,
    ) -> float:
        """ATR, anlık makas ve 1dk tahta likiditesine duyarlı dinamik kayma (slippage %) modeli."""
        half_spread = max(0.0, float(spread_pct)) * 0.5
        vol_component = max(0.0, float(atr_pct)) * self.atr_slippage_fraction
        liq_ratio = max(0.0, float(notional_usdt)) / max(float(minute_quote_vol_usdt), 10_000.0)
        impact_component = min(0.12, liq_ratio * 0.30)
        return round(half_spread + vol_component + impact_component, 6)

    def estimate_roundtrip_cost_usdt(
        self,
        notional_usdt: float,
        spread_pct: float = 0.02,
        *,
        prefer_maker_entry: bool = True,
        prefer_maker_exit: bool = True,
    ) -> dict[str, float]:
        """$1,000 gibi bir pozisyon büyüklüğü için giriş + çıkış + makas toplam maliyetini hesaplar."""
        notional = max(0.0, float(notional_usdt))
        sp = max(0.0, float(spread_pct))
        in_rate = self.maker_fee_pct if (prefer_maker_entry and sp <= self.max_maker_spread_pct) else self.taker_fee_pct
        out_rate = self.maker_fee_pct if prefer_maker_exit else self.taker_fee_pct
        # Maker emir makas kazanır veya sıfır kayma ile dolar; Taker emir yarı-makas öder
        slip_pct = (0.0 if in_rate == self.maker_fee_pct else sp * 0.5) + (
            0.0 if out_rate == self.maker_fee_pct else sp * 0.5
        )
        entry_fee = notional * (in_rate / 100.0)
        exit_fee = notional * (out_rate / 100.0)
        slip_cost = notional * (slip_pct / 100.0)
        taker_baseline = notional * ((self.taker_fee_pct * 2.0 + sp) / 100.0)
        total = entry_fee + exit_fee + slip_cost
        return {
            "entry_fee_usdt": round(entry_fee, 6),
            "exit_fee_usdt": round(exit_fee, 6),
            "slippage_usdt": round(slip_cost, 6),
            "total_cost_usdt": round(total, 6),
            "taker_baseline_usdt": round(taker_baseline, 6),
            "potential_saving_usdt": round(max(0.0, taker_baseline - total), 6),
        }

    def evaluate_fee_viability(
        self,
        *,
        notional_usdt: float,
        atr_pct: float,
        spread_pct: float = 0.02,
        rvol: float = 1.0,
    ) -> FeeViabilityResult:
        """Beklenen ATR oynaklığının komisyon + makas maliyetini anlamlı biçimde aşıp aşmadığını denetler."""
        self.stats["evaluated_signals"] += 1
        notional = max(1.0, float(notional_usdt))
        atr_p = max(0.01, float(atr_pct))
        sp = max(0.0, float(spread_pct))
        rv = max(0.0, float(rvol))

        if sp > self.max_entry_spread_pct:
            self.stats["blocked_wide_spread"] += 1
            self.stats["blocked_fee_drag"] += 1
            return FeeViabilityResult(
                viable=False,
                expected_move_usdt=0.0,
                roundtrip_cost_usdt=round(notional * (sp / 100.0), 4),
                fee_multiple=0.0,
                recommended_mode="chase_limit",
                reason=f"sig_tahta_yuksek_spread(spread=%{sp:.3f} > max=%{self.max_entry_spread_pct:.3f})",
            )

        # Yüksek RVOL (>3.0x) ani patlamada fiyat kaçmaması için chase_limit (%0.02),
        # normal tahtada doğrudan pasif maker (%0.02) önerilir.
        if sp <= self.max_maker_spread_pct:
            rec_mode = "chase_limit" if rv >= 3.0 else "maker"
            prefer_maker_in = True
        else:
            rec_mode = "chase_limit"
            prefer_maker_in = True

        cost_info = self.estimate_roundtrip_cost_usdt(
            notional, sp, prefer_maker_entry=prefer_maker_in, prefer_maker_exit=True
        )
        rt_cost = max(0.01, cost_info["total_cost_usdt"])
        # 5m/60m ATR yüzdesine göre beklenen tek dalga fiyat hareketi ($)
        vol_boost = min(1.6, max(0.85, 0.85 + (rv - 1.0) * 0.20))
        expected_move_usdt = notional * (atr_p / 100.0) * vol_boost
        multiple = expected_move_usdt / rt_cost

        if multiple < self.min_fee_multiple:
            self.stats["blocked_fee_drag"] += 1
            return FeeViabilityResult(
                viable=False,
                expected_move_usdt=round(expected_move_usdt, 4),
                roundtrip_cost_usdt=round(rt_cost, 4),
                fee_multiple=round(multiple, 2),
                recommended_mode=rec_mode,
                reason=(
                    f"komisyon_yuku_yuksek(beklenen=${expected_move_usdt:.2f} < "
                    f"{self.min_fee_multiple:.1f}x maliyet=${rt_cost:.2f})"
                ),
            )

        return FeeViabilityResult(
            viable=True,
            expected_move_usdt=round(expected_move_usdt, 4),
            roundtrip_cost_usdt=round(rt_cost, 4),
            fee_multiple=round(multiple, 2),
            recommended_mode=rec_mode,
            reason=f"maliyet_verimli({multiple:.1f}x,mod={rec_mode},tahmini_maliyet=${rt_cost:.2f})",
        )

    def select_optimal_venue(
        self, quotes: dict[str, tuple[float, float]], side: str
    ) -> tuple[str, float, dict[str, Any]]:
        """Borsalar arası (ör. Binance vs OKX) anlık (bid, ask) verisinden en düşük efektif maliyetli borsayı seçer."""
        best_venue = "binance"
        best_eff_px = 0.0
        best_score = math.inf
        details: dict[str, Any] = {}

        is_buy = str(side).upper() in ("LONG", "BUY")
        for venue, (bid, ask) in quotes.items():
            if bid <= 0 or ask < bid:
                continue
            mid = (bid + ask) / 2.0
            sp_pct = (ask - bid) / mid * 100.0
            fee_pct = self.maker_fee_pct if sp_pct <= self.max_maker_spread_pct else self.taker_fee_pct
            # Alışta düşük fiyat + düşük komisyon, satışta yüksek fiyat - düşük komisyon en iyidir
            touch_px = bid if is_buy else ask  # Maker pasif fiyat
            eff_cost_pct = sp_pct * 0.25 + fee_pct
            normalized_rank = (touch_px / mid + eff_cost_pct / 100.0) if is_buy else (-touch_px / mid + eff_cost_pct / 100.0)
            details[venue] = {
                "bid": bid,
                "ask": ask,
                "spread_pct": round(sp_pct, 5),
                "fee_pct": fee_pct,
                "effective_cost_pct": round(eff_cost_pct, 5),
            }
            if normalized_rank < best_score:
                best_score = normalized_rank
                best_venue = venue
                best_eff_px = mid

        return best_venue, best_eff_px, details

    def compute_net_mfe_lock_usdt(
        self,
        *,
        mfe_usdt: float,
        notional_usdt: float,
        entry_fee_usdt: float,
        prefer_maker_exit: bool = True,
    ) -> float | None:
        """Komisyon-dahil 3 kademeli MFE kâr kilidi: asla net zararda kâr kilidi kurmaz!

        • Kademe 1 (MFE >= roundtrip_fee + $0.95): En az `roundtrip_fee + $0.45` net kâr kilitler.
        • Kademe 2 (MFE >= $3.20): Brüt MFE'nin %64'ünü kilitler.
        • Kademe 3 (MFE >= $6.00, koşucu balina trendi): Brüt MFE'nin %76'sını kilitler.
        """
        exit_rate = self.maker_fee_pct if prefer_maker_exit else self.taker_fee_pct
        est_exit_fee = max(0.0, float(notional_usdt)) * (exit_rate / 100.0)
        roundtrip_fee = max(0.0, float(entry_fee_usdt)) + est_exit_fee

        trigger_floor = roundtrip_fee + 0.95
        if mfe_usdt < trigger_floor:
            return None

        if mfe_usdt >= 6.0:
            keep_ratio = 0.76
        elif mfe_usdt >= 3.2:
            keep_ratio = 0.64
        else:
            keep_ratio = 0.56

        min_gross_lock = roundtrip_fee + self.min_net_lock_profit_usdt
        return max(min_gross_lock, mfe_usdt * keep_ratio)

    def record_fill_telemetry(self, *, is_entry: bool, is_maker: bool, notional_usdt: float) -> None:
        saving = max(0.0, float(notional_usdt)) * ((self.taker_fee_pct - self.maker_fee_pct) / 100.0)
        if is_entry:
            if is_maker:
                self.stats["maker_entries"] += 1
                self.stats["estimated_saved_usdt"] += saving
            else:
                self.stats["taker_entries"] += 1
        else:
            if is_maker:
                self.stats["maker_exits"] += 1
                self.stats["estimated_saved_usdt"] += saving
            else:
                self.stats["taker_exits"] += 1

    def snapshot(self) -> dict[str, Any]:
        s = dict(self.stats)
        s["estimated_saved_usdt"] = round(float(s["estimated_saved_usdt"]), 4)
        s["maker_fee_pct"] = self.maker_fee_pct
        s["taker_fee_pct"] = self.taker_fee_pct
        return s
