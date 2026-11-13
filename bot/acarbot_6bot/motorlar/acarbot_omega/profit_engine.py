# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — 5 Kademeli Otonom AI Kâr Motoru & Kesin -$20.00 Zarar Kes Kalkanı (profit_engine.py)
====================================================================================================
Kurallar:
  - Zarar Kes: Net -$20.00 sınırını (komisyon + kayma dahil) ASLA aşmaz!
  - Kâr Al (TP): Sabit bir tavanla kârı boğmaz; 5 kademeli otonom AI karar motoruyla yönetir:
      Kademe 1: Başabaş + Komisyon Üstü Kâr Kilidi (BE_SHIELD)
      Kademe 2: İvme & CVD Duyarlı Esnek İz Sürme (MOMENTUM_ADAPTIVE_TRAIL)
      Kademe 3: Parabolik Ralli Sıkı Kâr Mandalı (PARABOLIC_RATCHET_86%)
      Kademe 4: Anlık Hacim/CVD Karşı Duvarı Tükeniş Çıkışı (AI_CLIMAX_EXHAUSTION_TP)
      Kademe 5: Yatay Sönümlenme Kâr Hasadı (STAGNATION_HARVEST_TP — V20 Raporu Dersi)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from .config import OmegaConfig
from .contracts import ContractSpec
from .microstructure import OmegaFeatureSnapshot


@dataclass
class OmegaPosition:
    id: str
    exchange: str
    symbol: str
    segment: str
    kind: str
    base_asset: str
    side: int  # +1 LONG, -1 SHORT
    qty: float
    entry_price: float
    mark_price: float
    margin_usd: float
    leverage: int
    notional_usd: float
    hard_stop_price: float
    est_liquidation_price: float
    roundtrip_fee_usd: float
    dynamic_floor_pnl_usd: float
    opened_ts: float
    trigger_type: str
    council_score: float
    edge_to_cost_ratio: float
    peak_pnl_usd: float = 0.0
    net_pnl_usd: float = 0.0
    profit_stage: str = "KADEME_0_KORUMA (-20$ SL)"
    entry_snapshot: Optional[OmegaFeatureSnapshot] = None

    @property
    def side_label(self) -> str:
        return "LONG" if self.side > 0 else "SHORT"

    def to_public_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("entry_snapshot", None)
        d["side_label"] = self.side_label
        return d


@dataclass(frozen=True)
class ExitDecision:
    should_close: bool
    exit_price: float = 0.0
    final_net_pnl_usd: float = 0.0
    reason: str = ""


class AutonomousProfitEngine:
    """Her fiyat adımında -$20 kesin zarar kes ve 5 kademeli otonom AI kâr motorunu çalıştırır."""

    def __init__(self, cfg: OmegaConfig) -> None:
        self.cfg = cfg

    def evaluate_tick(
        self,
        pos: OmegaPosition,
        spec: ContractSpec,
        snap: OmegaFeatureSnapshot,
        now_ts: float,
    ) -> ExitDecision:
        px = snap.price
        pos.mark_price = px

        gross_pnl = spec.gross_pnl_usd(pos.side, pos.entry_price, px, pos.notional_usd)
        net_pnl = gross_pnl - pos.roundtrip_fee_usd
        pos.net_pnl_usd = round(net_pnl, 4)
        if net_pnl > pos.peak_pnl_usd:
            pos.peak_pnl_usd = round(net_pnl, 4)

        # ------------------------------------------------------------------
        # 0) KESİN -$20.00 ZARAR KES KALKANI (Asla -$20.00 altı kayba izin verme!)
        # ------------------------------------------------------------------
        hit_stop_px = (pos.side > 0 and px <= pos.hard_stop_price) or (
            pos.side < 0 and px >= pos.hard_stop_price
        )
        if net_pnl <= -self.cfg.hard_stop_loss_usd or hit_stop_px:
            capped = max(net_pnl, -self.cfg.hard_stop_loss_usd)
            return ExitDecision(
                should_close=True,
                exit_price=px,
                final_net_pnl_usd=round(capped, 4),
                reason="KESIN_ZARAR_KES_-10$",
            )

        flow_aligned = snap.orderflow_bias * pos.side
        vel_aligned = snap.ret_burst_pct * pos.side
        hold_sec = max(0.0, now_ts - pos.opened_ts)

        # ------------------------------------------------------------------
        # 1) KADEME 1 — Başabaş + Komisyon Üstü Kâr Kilidi (BE_SHIELD)
        # ------------------------------------------------------------------
        if pos.peak_pnl_usd >= self.cfg.be_trigger_usd and pos.dynamic_floor_pnl_usd < self.cfg.be_lock_usd:
            pos.dynamic_floor_pnl_usd = self.cfg.be_lock_usd
            pos.profit_stage = f"KADEME_1_BE_KILIDI (+${self.cfg.be_lock_usd:.2f})"

        # ------------------------------------------------------------------
        # 2 & 3) KADEME 2 & 3 — İvme Duyarlı İz Sürme & Parabolik Mandal
        # ------------------------------------------------------------------
        if pos.peak_pnl_usd >= self.cfg.trail_arm_usd:
            if pos.peak_pnl_usd >= self.cfg.parabolic_arm_usd:
                giveback = 0.14  # Zirve kârın %86'sını kilitle!
                lbl = "KADEME_3_PARABOLIK_MANDAL"
            elif flow_aligned >= 0.15 and vel_aligned >= 0.0:
                giveback = 0.28  # Hacim ve akış hâlâ bizden yana -> trendi boğma!
                lbl = "KADEME_2_ESNEK_TREND_SURUSU"
            else:
                giveback = 0.18  # Akış zayıfladı -> kilidi hızla sıkılaştır!
                lbl = "KADEME_2_SIKILASTIRILMIS_AI_KILIT"

            candidate_floor = round(pos.peak_pnl_usd * (1.0 - giveback), 2)
            if candidate_floor > pos.dynamic_floor_pnl_usd:
                pos.dynamic_floor_pnl_usd = candidate_floor
            pos.profit_stage = f"{lbl} (Taban +${pos.dynamic_floor_pnl_usd:.2f})"

        # ------------------------------------------------------------------
        # 4) KADEME 4 — Anlık Hacim & CVD Karşı Duvarı Tükeniş Çıkışı
        # ------------------------------------------------------------------
        if (
            net_pnl >= self.cfg.exhaustion_tp_min_usd
            and snap.vol_mult >= 2.1
            and flow_aligned <= -0.36
            and vel_aligned <= -0.16
        ):
            return ExitDecision(
                should_close=True,
                exit_price=px,
                final_net_pnl_usd=round(net_pnl, 4),
                reason="AI_TUKENIS_DUVARI_KAR_AL",
            )

        # ------------------------------------------------------------------
        # 5) KADEME 5 — Yatay Sönümlenme Kâr Hasadı (ACARBOT V20 Dersi)
        # ------------------------------------------------------------------
        if (
            hold_sec >= self.cfg.stagnation_hold_sec
            and net_pnl >= self.cfg.stagnation_min_pnl_usd
            and snap.vol_mult < 0.85
            and abs(snap.ret_30s_pct) < 0.05
            and flow_aligned <= 0.0
        ):
            return ExitDecision(
                should_close=True,
                exit_price=px,
                final_net_pnl_usd=round(net_pnl, 4),
                reason="AI_ZAMAN_SONUMLENME_KAR_HASADI",
            )

        # Dinamik kâr tabanı tetiklendiyse kârı realize et
        if pos.dynamic_floor_pnl_usd > -self.cfg.hard_stop_loss_usd and net_pnl <= pos.dynamic_floor_pnl_usd:
            reason = (
                "AI_PARABOLIK_KAR_AL"
                if pos.dynamic_floor_pnl_usd >= 15.0
                else ("AI_TRAILING_KAR_AL" if pos.dynamic_floor_pnl_usd >= 3.0 else "BE_KAR_KORUMA")
            )
            return ExitDecision(
                should_close=True,
                exit_price=px,
                final_net_pnl_usd=round(net_pnl, 4),
                reason=reason,
            )

        return ExitDecision(should_close=False)
