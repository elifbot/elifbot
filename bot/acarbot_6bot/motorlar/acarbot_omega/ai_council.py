# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — 20-Denetçili Yapay Zeka & Kantitatif Çapraz Teftiş Konseyi (ai_council.py)
==========================================================================================
Birleştirilen Miras:
  - AI-OmniStudio v1.0.1 (council.py): 20 Denetçili 3-Turlu Çapraz Teftiş + Tek Üye Sert Vetosu
    + Dürüst Mod Etiketlemesi ('LIVE_LLM_HYBRID' vs 'RULE_BASED_QUANT_20') + Fail-Closed
  - Gmail AI-Hub (ai_hub.py & ai_hub_nvidia.py): Çoklu model yönlendirici (GitHub Models,
    NVIDIA NIM, OpenAI, DeepSeek, Anthropic, Gemini, Ollama)
  - ACARBOT v5.5 Zarar Analizi: Edge-vs-Cost (Beklenen Brüt Hareket / Toplam Sürtünme Maliyeti) Vetosu
  - Online SGD Öğrenici: Kapanan her işlemden gerçek zamanlı ağırlık kalibrasyonu
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from .config import OmegaConfig
from .contracts import CostBreakdown
from .microstructure import OmegaFeatureSnapshot


@dataclass(frozen=True)
class CouncilVerdict:
    approved: bool
    side: int
    trigger_kind: str
    approval_score: float             # [0.0 .. 1.0]
    expected_gross_move_usd: float
    edge_to_cost_ratio: float
    mode: Literal["RULE_BASED_QUANT_20", "LIVE_LLM_HYBRID", "INSUFFICIENT_QUORUM"]
    veto_reasons: List[str] = field(default_factory=list)
    auditor_votes_for: int = 0
    auditor_total: int = 20


class OmegaAICouncil:
    """
    20 bağımsız kantitatif ve mikroyapı denetçi profilini 3 turda koşturur;
    isteğe bağlı olarak canlı MultiModelRouter LLM konseyiyle birleştirir.
    """

    def __init__(self, cfg: OmegaConfig) -> None:
        self.cfg = cfg
        # Online SGD Öğrenen Faktör Ağırlıkları (Başlangıçta dengeli, her kapanan işlemde kendini kalibre eder)
        self.learned_weights: Dict[str, float] = {
            "vol_shock": 0.25,
            "orderflow": 0.25,
            "velocity": 0.20,
            "confluence": 0.15,
            "edge_cost": 0.15,
        }
        self.bias: float = 0.0
        self.learning_rate: float = 0.025
        self.samples_learned: int = 0

    def detect_candidate_direction(self, snap: OmegaFeatureSnapshot) -> tuple[int, str]:
        """Hacim Patlaması (LONG/SHORT) veya Hacim Çöküşü (Tükeniş Dönüşü LONG/SHORT) adayını belirler."""
        # 1) HACİM PATLAMASI + YUKARI KIRILIM -> LONG ADAYI
        if (
            snap.vol_mult >= self.cfg.vol_explosion_mult
            and snap.burst_usd >= self.cfg.min_burst_usd
            and (snap.ret_burst_pct >= self.cfg.min_velocity_pct or snap.ret_30s_pct >= self.cfg.min_velocity_pct * 1.35)
            and snap.orderflow_bias >= self.cfg.min_orderflow_bias
        ):
            return 1, f"OMEGA_HACIM_PATLAMASI_LONG ({snap.vol_mult:.1f}x | +{max(snap.ret_burst_pct, snap.ret_30s_pct):.2f}%)"

        # 2) HACİM PATLAMASI + AŞAĞI ÇÖKÜŞ -> SHORT ADAYI
        if (
            snap.vol_mult >= self.cfg.vol_explosion_mult
            and snap.burst_usd >= self.cfg.min_burst_usd
            and (snap.ret_burst_pct <= -self.cfg.min_velocity_pct or snap.ret_30s_pct <= -self.cfg.min_velocity_pct * 1.35)
            and snap.orderflow_bias <= -self.cfg.min_orderflow_bias
        ):
            return -1, f"OMEGA_COKUS_PATLAMASI_SHORT ({snap.vol_mult:.1f}x | {min(snap.ret_burst_pct, snap.ret_30s_pct):.2f}%)"

        # 3) HACİM ÇÖKÜŞÜ (Climax Sonrası Hacim Kuruması + Ters Dönüş)
        if (
            snap.peak_burst_mult_60s >= self.cfg.vol_explosion_mult * 1.15
            and 1.0 <= snap.secs_since_peak_burst <= 60.0
            and snap.vol_mult <= snap.peak_burst_mult_60s * self.cfg.vol_collapse_ratio
        ):
            if (
                snap.peak_burst_move_60s >= self.cfg.min_velocity_pct * 1.75
                and snap.ret_burst_pct <= -0.14
                and snap.orderflow_bias <= -0.14
            ):
                return -1, f"OMEGA_HACIM_COKUSU_SHORT ({snap.peak_burst_mult_60s:.1f}x->{snap.vol_mult:.1f}x)"
            if (
                snap.peak_burst_move_60s <= -self.cfg.min_velocity_pct * 1.75
                and snap.ret_burst_pct >= 0.14
                and snap.orderflow_bias >= 0.14
            ):
                return 1, f"OMEGA_HACIM_COKUSU_LONG ({snap.peak_burst_mult_60s:.1f}x->{snap.vol_mult:.1f}x)"

        return 0, ""

    def estimate_expected_gross_move_usd(
        self, snap: OmegaFeatureSnapshot, side: int, notional_usd: float
    ) -> float:
        """ATR%, anlık patlama ivmesi ve hacim çarpanından muhafazakâr beklenen brüt hareket ($) tahmini."""
        vel_mag = max(abs(snap.ret_burst_pct), abs(snap.ret_30s_pct) * 0.85, abs(snap.peak_burst_move_60s) * 0.55)
        vol_boost = min(2.2, 0.85 + math.log1p(max(0.0, snap.vol_mult)) * 0.45)
        flow_boost = 0.80 + 0.40 * max(0.0, snap.orderflow_bias * side)
        est_move_pct = max(vel_mag * 0.90, snap.atr_pct * 0.75) * vol_boost * flow_boost
        return round(notional_usd * (est_move_pct / 100.0), 3)

    def evaluate(
        self,
        snap: OmegaFeatureSnapshot,
        side: int,
        trigger_kind: str,
        costs: CostBreakdown,
        notional_usd: float,
    ) -> CouncilVerdict:
        vetoes: List[str] = []
        expected_gross = self.estimate_expected_gross_move_usd(snap, side, notional_usd)
        total_friction = max(0.05, costs.total_friction_usd)
        edge_ratio = expected_gross / total_friction

        # ==========================================================
        # TUR 1 & TUR 2: SERT MİKROYAPI VE MALİYET VETOLARI (FAIL-CLOSED)
        # ==========================================================
        if edge_ratio < self.cfg.min_edge_to_cost_ratio:
            vetoes.append(f"EDGE_VS_COST_VETO ({edge_ratio:.2f}x < {self.cfg.min_edge_to_cost_ratio:.2f}x)")

        # Bull / Bear Trap (Üst veya alt dev fitil tuzağı) vetosu
        is_collapse_reversal = "HACIM_COKUSU" in trigger_kind
        if not is_collapse_reversal:
            if side > 0 and snap.range_pos < 0.42:
                vetoes.append(f"BULL_TRAP_FITIL_VETO (range_pos={snap.range_pos:.2f})")
            elif side < 0 and snap.range_pos > 0.58:
                vetoes.append(f"BEAR_TRAP_FITIL_VETO (range_pos={snap.range_pos:.2f})")

        # Testere (Choppiness) vetosu — eğer olağanüstü (>5x) kırılım hacmi yoksa testerede girme!
        if snap.choppiness_index > self.cfg.max_choppiness_index and snap.vol_mult < (self.cfg.vol_explosion_mult * 1.8):
            vetoes.append(f"TESTERE_CHOP_VETO (chop={snap.choppiness_index:.1f})")

        # Aşırı geniş makas (spread) vetosu
        if snap.spread_bps is not None and snap.spread_bps > 22.0:
            vetoes.append(f"ASIRI_MAKAS_VETO ({snap.spread_bps:.1f} bps)")

        # Aşırı ters fonlama vetosu (>%0.35 / 8 saat kalabalık yön)
        if snap.funding_rate is not None and (snap.funding_rate * side) > 0.0035:
            vetoes.append(f"KALABALIK_FONLAMA_VETO (funding={snap.funding_rate:.4%})")

        # ==========================================================
        # 20 KANTİTATİF DENETÇİ PROFİLİ OYLAMASI
        # ==========================================================
        dir_flow = snap.orderflow_bias * side
        dir_vel = (snap.ret_burst_pct if not is_collapse_reversal else -snap.peak_burst_move_60s * 0.5) * side
        dir_conf = snap.technical_confluence * side
        dir_vwap = snap.vwap_dev_pct * side
        dir_deriv = (snap.derivatives_composite * side) if snap.derivatives_composite is not None else None

        auditor_checks = [
            edge_ratio >= self.cfg.min_edge_to_cost_ratio,                        # 1. Maliyet Baş-Denetçisi
            edge_ratio >= self.cfg.min_edge_to_cost_ratio * 1.25,                 # 2. Sıkı Sürtünme Denetçisi
            snap.vol_mult >= self.cfg.vol_explosion_mult or is_collapse_reversal, # 3. Hacim Şoku Denetçisi
            snap.burst_usd >= self.cfg.min_burst_usd or is_collapse_reversal,     # 4. Dolar Likidite Denetçisi
            snap.quote_vol_24h >= self.cfg.min_24h_vol_usd,                       # 5. Derinlik Taban Denetçisi
            dir_flow >= self.cfg.min_orderflow_bias,                              # 6. CVD Akış Denetçisi
            dir_flow >= 0.25,                                                     # 7. Agresif Taker Baskı Denetçisi
            abs(snap.ret_burst_pct) >= self.cfg.min_velocity_pct * 0.75,          # 8. Anlık Hız Denetçisi
            (snap.ret_30s_pct * side) >= 0.0 or is_collapse_reversal,             # 9. 30sn Momentum Tutarlılığı
            (snap.range_pos >= 0.52 if side > 0 else snap.range_pos <= 0.48),     # 10. Mum Kapanış Gücü Denetçisi
            snap.choppiness_index <= self.cfg.max_choppiness_index,               # 11. Testere Filtre Denetçisi
            snap.regime != "RANGE" or snap.vol_mult >= 3.5,                       # 12. Rejim Uyum Denetçisi
            dir_conf >= -0.15,                                                    # 13. 10-İndikatör Konfluans Denetçisi
            dir_conf >= 0.16,                                                     # 14. Güçlü Trend Konfluans Denetçisi
            (25.0 <= snap.rsi_14 <= 84.0) if side > 0 else (16.0 <= snap.rsi_14 <= 75.0),  # 15. RSI Tükenme Koruması
            abs(dir_vwap) <= 4.5,                                                 # 16. Aşırı VWAP Kopma Koruması
            snap.atr_pct <= 6.0,                                                  # 17. Anormal Volatilite Koruması
            (snap.spread_bps is None or snap.spread_bps <= 12.0),                 # 18. Emir Defteri Makas Denetçisi
            (dir_deriv is None or dir_deriv >= -0.05),                            # 19. OI / Defter Dengesi Denetçisi
            self._sgd_probability(snap, side, edge_ratio) >= 0.50,                # 20. Online SGD Öğrenen Model
        ]

        votes_for = sum(1 for v in auditor_checks if v)
        quant_score = votes_for / 20.0
        sgd_prob = self._sgd_probability(snap, side, edge_ratio)
        blended_score = round(0.75 * quant_score + 0.25 * sgd_prob, 4)

        mode: Literal["RULE_BASED_QUANT_20", "LIVE_LLM_HYBRID", "INSUFFICIENT_QUORUM"] = "RULE_BASED_QUANT_20"

        # Tur 3: İsteğe bağlı Canlı LLM Konseyi Teyidi
        if self.cfg.enable_live_llm_council and not vetoes:
            llm_ok, llm_adj = self._optional_live_llm_check(snap, side, edge_ratio)
            if llm_ok:
                mode = "LIVE_LLM_HYBRID"
                blended_score = round(0.70 * blended_score + 0.30 * llm_adj, 4)
            elif self.cfg.fail_closed_on_llm_error:
                vetoes.append("INSUFFICIENT_LLM_QUORUM")
                mode = "INSUFFICIENT_QUORUM"

        approved = (len(vetoes) == 0) and (blended_score >= self.cfg.council_min_approval_score)
        return CouncilVerdict(
            approved=approved,
            side=side,
            trigger_kind=trigger_kind,
            approval_score=blended_score,
            expected_gross_move_usd=expected_gross,
            edge_to_cost_ratio=round(edge_ratio, 2),
            mode=mode,
            veto_reasons=vetoes,
            auditor_votes_for=votes_for,
            auditor_total=20,
        )

    def _sgd_probability(self, snap: OmegaFeatureSnapshot, side: int, edge_ratio: float) -> float:
        x_vol = min(1.5, snap.vol_mult / 5.0)
        x_flow = max(-1.0, min(1.0, snap.orderflow_bias * side))
        x_vel = max(-1.0, min(1.5, (snap.ret_burst_pct * side) / 0.6))
        x_conf = max(-1.0, min(1.0, snap.technical_confluence * side))
        x_edge = min(1.5, (edge_ratio - 1.0) / 3.0)
        z = (
            self.bias
            + self.learned_weights["vol_shock"] * x_vol
            + self.learned_weights["orderflow"] * x_flow
            + self.learned_weights["velocity"] * x_vel
            + self.learned_weights["confluence"] * x_conf
            + self.learned_weights["edge_cost"] * x_edge
        )
        z = max(-12.0, min(12.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def learn_from_closed_trade(
        self,
        entry_snap: Optional[OmegaFeatureSnapshot],
        side: int,
        edge_ratio: float,
        net_pnl_usd: float,
    ) -> None:
        """Kapanan her işlemden Online Lojistik SGD ile ağırlıkları günceller."""
        if entry_snap is None:
            return
        target = 1.0 if net_pnl_usd > 0 else 0.0
        pred = self._sgd_probability(entry_snap, side, edge_ratio)
        err = target - pred

        feats = {
            "vol_shock": min(1.5, entry_snap.vol_mult / 5.0),
            "orderflow": max(-1.0, min(1.0, entry_snap.orderflow_bias * side)),
            "velocity": max(-1.0, min(1.5, (entry_snap.ret_burst_pct * side) / 0.6)),
            "confluence": max(-1.0, min(1.0, entry_snap.technical_confluence * side)),
            "edge_cost": min(1.5, (edge_ratio - 1.0) / 3.0),
        }
        for k, v in feats.items():
            self.learned_weights[k] = max(-2.0, min(3.0, self.learned_weights[k] + self.learning_rate * err * v))
        self.bias = max(-1.5, min(1.5, self.bias + self.learning_rate * err * 0.5))
        self.samples_learned += 1

    def _optional_live_llm_check(
        self, snap: OmegaFeatureSnapshot, side: int, edge_ratio: float
    ) -> tuple[bool, float]:
        try:
            from ai_models import MultiModelRouter

            router = MultiModelRouter()
            if not router.available_providers():
                return False, 0.5
            side_str = "LONG" if side > 0 else "SHORT"
            prompt = (
                f"Parite: {snap.exchange}:{snap.symbol} Yön: {side_str} | "
                f"Hacim: {snap.vol_mult}x (${snap.burst_usd:.0f}) | Hız: {snap.ret_burst_pct}% | "
                f"CVD: {snap.orderflow_bias} | Edge/Maliyet: {edge_ratio:.2f}x | Chop: {snap.choppiness_index}. "
                "Yalnızca 0.0 ile 1.0 arasında tek bir onay skoru yaz."
            )
            resp = router.ask(prompt=prompt, system="Kısa sayısal risk denetçisisin.", max_tokens=16)
            if not resp:
                return False, 0.5
            import re

            m = re.search(r"0\.\d+|1\.0", resp)
            if not m:
                return False, 0.5
            return True, float(m.group(0))
        except Exception:
            return False, 0.5
