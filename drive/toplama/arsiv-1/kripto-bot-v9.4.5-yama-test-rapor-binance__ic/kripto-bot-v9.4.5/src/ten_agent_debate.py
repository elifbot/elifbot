"""src/ten_agent_debate.py — 10 Kantitatif Ajanlı 3-Turlu Çapraz Teftiş ve Müzakere Konseyi.

Tasarım İlkeleri (Kullanıcı Madde 2 & Denetim Madde 2.g / 3.10):
  1. Dürüst Adlandırma: Sahte dış model pazarlama etiketleri ("Opus 5 SWE-bench %97" vb.)
     KULLANILMAZ. 10 ajan, aynı tam görevi farklı risk/ufuk hassasiyetleriyle yürüten
     otonom kantitatif denetçilerdir (`Mufettis_01` .. `Mufettis_10`). İsteğe bağlı canlı
     LLM API hakemi ayrı ve açık biçimde etiketlenir.
  2. Tek Görev Bölüşümü DEĞİL, Tam Görev Çapraz Teftişi:
     10 ajanın tamamı her aday girişi VE her açık pozisyonu uçtan uca aynı 6 boyutta inceler:
       (a) Beklenen brüt hareket / gidiş-dönüş ücret + makas katsayısı (ücret öncesi kenar),
       (b) Canlı para akışı (`flow_score`, alış/satış hacmi, `CVD`),
       (c) Teknik yapı ve momentum (`ind_score`, EMA/Supertrend/BOS),
       (d) Çoklu zaman dilimi (`15m/1h`) ve testere (`Choppiness_14`) rejimi,
       (e) İcra kalitesi (makas, spot-perp baz farkı, funding yakınlığı),
       (f) Aşırı uzama / tepe-dip tuzağı riski.
  3. 3 Turlu Birbirini Teftiş (Peer Cross-Examination):
     - Tur 1: 10 ajan bağımsız tam değerlendirme ve tespit ettiği kusurları (`flaws`) üretir.
     - Tur 2: Her ajan diğer 9 ajanın tespit ettiği kusurları ve güçlü kanıtları teftiş eder;
       haklı itirazlar karşısında puanını revize eder ve teftiş diyalog kaydı üretir.
     - Tur 3: Revize oylar birleştirilir; kapalı işlemlerin brüt/net sonucuna göre konsey
       minimum kenar/ücret eşiğini dinamik sıkılaştırır.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InspectorProfile:
    agent_id: str
    role_note: str
    w_edge_cost: float
    w_flow: float
    w_tech: float
    w_regime: float
    w_exec: float
    skepticism: float  # Akran itirazlarına duyarlılık (0.8 - 1.35)


TEN_INSPECTORS: tuple[InspectorProfile, ...] = (
    InspectorProfile("Mufettis_01", "Dengeli Tam-Gorev Denetcisi", 0.24, 0.24, 0.22, 0.16, 0.14, 1.00),
    InspectorProfile("Mufettis_02", "Brut-Kenar ve Komisyon Denetcisi", 0.34, 0.20, 0.18, 0.14, 0.14, 1.20),
    InspectorProfile("Mufettis_03", "Canli Para Akisi ve CVD Denetcisi", 0.20, 0.34, 0.20, 0.14, 0.12, 0.95),
    InspectorProfile("Mufettis_04", "Trend ve Piyasa Yapisi Denetcisi", 0.20, 0.20, 0.32, 0.18, 0.10, 1.00),
    InspectorProfile("Mufettis_05", "Emir Defteri Makas ve Baz Denetcisi", 0.24, 0.18, 0.16, 0.14, 0.28, 1.15),
    InspectorProfile("Mufettis_06", "Ters Secilim ve Maker Kuyruk Denetcisi", 0.26, 0.22, 0.16, 0.14, 0.22, 1.18),
    InspectorProfile("Mufettis_07", "Coklu Zaman Dilimi Uyum Denetcisi", 0.18, 0.20, 0.22, 0.28, 0.12, 1.08),
    InspectorProfile("Mufettis_08", "Testere ve Tuzak Engelleyici Denetci", 0.22, 0.20, 0.18, 0.26, 0.14, 1.22),
    InspectorProfile("Mufettis_09", "Dalga Surdurulebilirlik Denetcisi", 0.22, 0.28, 0.24, 0.16, 0.10, 0.90),
    InspectorProfile("Mufettis_10", "Karsi-Tez Basmufettisi", 0.28, 0.22, 0.18, 0.18, 0.14, 1.30),
)


class TenAgentMutualAuditCouncil:
    """10 kantitatif ajanın aynı görevi 3 turda birbirini teftiş ederek yürüttüğü konsey."""

    MODE_LABEL = "TEN_AGENT_3ROUND_MUTUAL_AUDIT"

    def __init__(
        self,
        *,
        min_consensus_votes: int = 7,
        min_expected_gross_fee_mult: float = 3.5,
        max_dialogue_history: int = 60,
    ) -> None:
        self.min_consensus_votes = max(5, min(10, int(min_consensus_votes)))
        self.base_min_gross_fee_mult = max(2.0, float(min_expected_gross_fee_mult))
        self.dynamic_min_gross_fee_mult = self.base_min_gross_fee_mult
        self.recent_outcomes: deque[dict[str, float]] = deque(maxlen=40)
        self.dialogue_log: deque[dict[str, Any]] = deque(maxlen=max(15, int(max_dialogue_history)))
        self.audit_stats = {
            "entry_audits": 0,
            "entry_approved": 0,
            "entry_rejected": 0,
            "peer_downgrades": 0,
            "peer_upgrades": 0,
            "position_audits": 0,
            "position_hold_decisions": 0,
            "position_exit_decisions": 0,
        }

    def record_closed_trade_outcome(self, gross_usdt: float, fee_usdt: float, net_usdt: float) -> None:
        """Kapalı işlemleri izleyerek ücret/kenar eşiğini kendi kendine sıkılaştırır veya normale çeker."""
        self.recent_outcomes.append(
            {"gross": float(gross_usdt), "fee": float(fee_usdt), "net": float(net_usdt)}
        )
        if len(self.recent_outcomes) >= 4:
            avg_net = sum(x["net"] for x in self.recent_outcomes) / len(self.recent_outcomes)
            avg_fee = sum(x["fee"] for x in self.recent_outcomes) / len(self.recent_outcomes)
            if avg_net < 0 and avg_fee > 0:
                self.dynamic_min_gross_fee_mult = min(
                    5.5, self.base_min_gross_fee_mult + 0.75
                )
            elif avg_net > avg_fee * 0.5:
                self.dynamic_min_gross_fee_mult = max(
                    self.base_min_gross_fee_mult, self.dynamic_min_gross_fee_mult - 0.25
                )

    def evaluate_entry(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Aday giriş sinyalini 10 ajanla 3 turda çapraz teftiş eder."""
        self.audit_stats["entry_audits"] += 1
        symbol = str(ctx.get("symbol", ""))
        side = str(ctx.get("side", "BEKLE")).upper()
        if side not in ("LONG", "SHORT"):
            return {
                "approved": False,
                "consensus_votes": 0,
                "final_score": 0.0,
                "reason": "aktif_yon_sinyali_yok",
                "mode": self.MODE_LABEL,
                "round1_votes": {},
                "round2_votes": {},
                "dialogues": [],
            }

        direction = 1.0 if side == "LONG" else -1.0
        ind_aligned = float(ctx.get("ind_score", 0.0)) * direction
        flow_aligned = float(ctx.get("flow_score", 0.0)) * direction
        combined_aligned = float(ctx.get("combined_score", 0.0)) * direction
        atr_pct = max(0.03, float(ctx.get("atr_pct", 0.35)))
        spread_pct = max(0.0005, float(ctx.get("spread_pct", 0.02)))
        roundtrip_fee_pct = max(0.04, float(ctx.get("roundtrip_fee_pct", 0.045)))
        total_friction_pct = roundtrip_fee_pct + spread_pct
        # Beklenen tipik dalga yakalama mesafesi (~1.35 * 5m ATR%)
        expected_wave_pct = atr_pct * 1.35
        gross_to_cost_mult = expected_wave_pct / max(total_friction_pct, 1e-6)

        chop = float(ctx.get("choppiness_14", 50.0))
        rvol = float(ctx.get("rvol", 1.0))
        vwap_z = float(ctx.get("vwap_atr_z", 0.0))
        mtf_aligned = bool(ctx.get("mtf_aligned", True))
        basis_bps = abs(float(ctx.get("spot_perp_basis_bps", 0.0)))
        funding_adverse_near = bool(ctx.get("funding_adverse_near", False))
        playbook = str(ctx.get("playbook", "MOMENTUM_BREAKOUT"))
        has_macro = "global_leader_score" in ctx
        leader_aligned = float(ctx.get("global_leader_score", 0.0)) * direction if has_macro else 0.0
        breadth_aligned = float(ctx.get("directional_breadth", 0.0)) * direction if has_macro else 0.0

        # --- TUR 1: 10 Ajanın Tam Görev Üzerinden Bağımsız Değerlendirmesi ---
        r1_scores: dict[str, float] = {}
        r1_flaws: dict[str, list[str]] = {}
        r1_strengths: dict[str, list[str]] = {}

        # Boyut alt puanları (0..100)
        s_edge = max(0.0, min(100.0, (gross_to_cost_mult / self.dynamic_min_gross_fee_mult) * 65.0))
        if gross_to_cost_mult < self.dynamic_min_gross_fee_mult:
            s_edge = max(10.0, s_edge - 22.0)

        if playbook == "VOLUME_DIVERGENCE_SHORT":
            s_flow = max(25.0, min(95.0, 58.0 + max(-15.0, flow_aligned) * 0.8))
        else:
            s_flow = max(0.0, min(100.0, 50.0 + flow_aligned * 1.05 + (rvol - 1.0) * 10.0))

        s_tech = max(0.0, min(100.0, 46.0 + ind_aligned * 0.95 + combined_aligned * 0.35))
        macro_bonus = 0.0
        if has_macro:
            macro_bonus = max(-20.0, min(12.0, leader_aligned * 0.16 + breadth_aligned * 14.0))
        s_reg = max(
            0.0,
            min(100.0, (82.0 if mtf_aligned else 34.0) - max(0.0, chop - 54.0) * 2.4 + macro_bonus),
        )
        s_exec = max(
            0.0,
            min(
                100.0,
                88.0 - spread_pct * 380.0 - max(0.0, basis_bps - 8.0) * 1.6 - (25.0 if funding_adverse_near else 0.0),
            ),
        )

        overextended = (side == "LONG" and vwap_z > 2.9) or (side == "SHORT" and vwap_z < -2.9)

        for ag in TEN_INSPECTORS:
            raw = (
                ag.w_edge_cost * s_edge
                + ag.w_flow * s_flow
                + ag.w_tech * s_tech
                + ag.w_regime * s_reg
                + ag.w_exec * s_exec
            )
            flaws: list[str] = []
            strengths: list[str] = []
            if gross_to_cost_mult < self.dynamic_min_gross_fee_mult:
                flaws.append(f"brut_kenar_dusuk({gross_to_cost_mult:.1f}x<{self.dynamic_min_gross_fee_mult:.1f}x)")
            elif gross_to_cost_mult >= self.dynamic_min_gross_fee_mult * 1.4:
                strengths.append(f"guclu_brut_kenar({gross_to_cost_mult:.1f}x_maliyet)")

            if flow_aligned < -6.0 and playbook != "VOLUME_DIVERGENCE_SHORT":
                flaws.append(f"ters_para_akisi({flow_aligned:+.1f})")
            elif flow_aligned >= 18.0:
                strengths.append(f"guclu_akim_destegi({flow_aligned:+.1f})")

            if not mtf_aligned and playbook != "VOLUME_DIVERGENCE_SHORT":
                flaws.append("ust_zaman_dilimi_uyumsuz")
            if chop >= 59.5:
                flaws.append(f"yuksek_choppiness({chop:.1f})")
            if spread_pct > 0.06:
                flaws.append(f"acik_makas(%{spread_pct:.3f})")
            if basis_bps > 20.0:
                flaws.append(f"yuksek_spot_perp_baz({basis_bps:.1f}bps)")
            if funding_adverse_near:
                flaws.append("funding_uzlasmasina_yakin_ters_oran")
            if overextended and playbook != "VOLUME_DIVERGENCE_SHORT":
                flaws.append(f"vwap_asiri_uzama(z={vwap_z:+.2f})")
            if has_macro:
                if leader_aligned < -15.0:
                    flaws.append(f"ters_lider_rejimi({leader_aligned:+.1f})")
                elif leader_aligned >= 15.0 and breadth_aligned >= 0.12:
                    strengths.append("lider_ve_genislik_onayi")
            if combined_aligned >= 28.0 and ind_aligned >= 18.0:
                strengths.append(f"yuksek_bilesik_ivme({combined_aligned:+.1f})")

            if overextended and playbook != "VOLUME_DIVERGENCE_SHORT":
                raw -= 14.0 * ag.skepticism
            r1_scores[ag.agent_id] = round(max(0.0, min(100.0, raw)), 2)
            r1_flaws[ag.agent_id] = flaws
            r1_strengths[ag.agent_id] = strengths

        # --- TUR 2: Çapraz Teftiş & Akran Müzakeresi (Her Ajan Diğer 9 Ajanı Denetler) ---
        r2_scores: dict[str, float] = {}
        dialogues: list[str] = []

        for ag in TEN_INSPECTORS:
            my_r1 = r1_scores[ag.agent_id]
            peer_flaw_counts: dict[str, int] = {}
            peer_strength_counts: dict[str, int] = {}
            peer_avg = sum(v for k, v in r1_scores.items() if k != ag.agent_id) / 9.0

            for other_id, fl_list in r1_flaws.items():
                if other_id == ag.agent_id:
                    continue
                for fl in fl_list:
                    peer_flaw_counts[fl] = peer_flaw_counts.get(fl, 0) + 1
            for other_id, st_list in r1_strengths.items():
                if other_id == ag.agent_id:
                    continue
                for st in st_list:
                    peer_strength_counts[st] = peer_strength_counts.get(st, 0) + 1

            confirmed_flaws = [f for f, cnt in peer_flaw_counts.items() if cnt >= 3]
            confirmed_strengths = [s for s, cnt in peer_strength_counts.items() if cnt >= 5]

            adj = 0.0
            if confirmed_flaws:
                penalty = sum(5.2 for _ in confirmed_flaws) * ag.skepticism
                adj -= penalty
            if confirmed_strengths and not confirmed_flaws:
                adj += min(8.0, len(confirmed_strengths) * 3.5)

            # Akran ortalamasından aşırı kopuk iyimserliği dengele
            if my_r1 - peer_avg > 10.0 and confirmed_flaws:
                adj -= (my_r1 - peer_avg) * 0.35

            new_sc = round(max(0.0, min(100.0, my_r1 + adj)), 2)
            r2_scores[ag.agent_id] = new_sc

            if new_sc <= my_r1 - 4.0 and len(dialogues) < 4:
                self.audit_stats["peer_downgrades"] += 1
                dialogues.append(
                    f"[Tur-2 Teftiş] {ag.agent_id}: Akranların '{confirmed_flaws[0]}' "
                    f"itirazını doğruladı ({my_r1:.0f} -> {new_sc:.0f})."
                )
            elif new_sc >= my_r1 + 3.0 and len(dialogues) < 4:
                self.audit_stats["peer_upgrades"] += 1
                dialogues.append(
                    f"[Tur-2 Teftiş] {ag.agent_id}: 9 akranın '{confirmed_strengths[0]}' "
                    f"kanıtıyla güven artırdı ({my_r1:.0f} -> {new_sc:.0f})."
                )

        # --- TUR 3: Ortak Müfettiş Uzlaşısı ---
        approvals = sum(1 for sc in r2_scores.values() if sc >= 55.0)
        final_score = round(sum(r2_scores.values()) / len(r2_scores), 2)
        hard_cost_veto = gross_to_cost_mult < (self.dynamic_min_gross_fee_mult * 0.80)

        approved = (
            approvals >= self.min_consensus_votes
            and final_score >= 55.0
            and not hard_cost_veto
        )
        if approved:
            self.audit_stats["entry_approved"] += 1
            reason = (
                f"10_ajan_onay({approvals}/10, skor={final_score:.1f}, "
                f"kenar/maliyet={gross_to_cost_mult:.1f}x)"
            )
        else:
            self.audit_stats["entry_rejected"] += 1
            top_flaw = next(iter(r1_flaws["Mufettis_02"] or r1_flaws["Mufettis_10"] or ["uzlasi_yetersiz"]))
            reason = (
                f"10_ajan_red({approvals}/10<{self.min_consensus_votes}, "
                f"skor={final_score:.1f}, neden={top_flaw})"
            )

        if not dialogues:
            dialogues.append(
                f"[Tur-3 Uzlaşı] {symbol} {side}: {approvals}/10 onay, "
                f"revize skor={final_score:.1f}, beklenen_kenar={gross_to_cost_mult:.1f}x maliyet."
            )

        self.dialogue_log.append(
            {
                "kind": "ENTRY_AUDIT",
                "symbol": symbol,
                "side": side,
                "approved": approved,
                "votes": f"{approvals}/10",
                "score": final_score,
                "gross_cost_mult": round(gross_to_cost_mult, 2),
                "messages": dialogues[:3],
            }
        )
        return {
            "approved": approved,
            "consensus_votes": approvals,
            "final_score": final_score,
            "expected_gross_to_cost_mult": round(gross_to_cost_mult, 2),
            "reason": reason,
            "mode": self.MODE_LABEL,
            "round1_votes": r1_scores,
            "round2_votes": r2_scores,
            "dialogues": dialogues,
        }

    def audit_open_position(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Açık pozisyonu 10 ajanla çapraz teftiş eder: Akım devam ediyorsa KORU, bittiyse ÇIK!"""
        self.audit_stats["position_audits"] += 1
        symbol = str(ctx.get("symbol", ""))
        side = str(ctx.get("side", "LONG")).upper()
        direction = 1.0 if side == "LONG" else -1.0

        flow_score = float(ctx.get("flow_score", 0.0))
        ind_score = float(ctx.get("ind_score", 0.0))
        combined_score = float(ctx.get("combined_score", 0.0))
        buy_usdt = float(ctx.get("buy_usdt", 0.0))
        sell_usdt = float(ctx.get("sell_usdt", 0.0))
        cvd = float(ctx.get("cvd_60s", 0.0))
        gross_pnl_usdt = float(ctx.get("gross_pnl_usdt", 0.0))
        mfe_usdt = float(ctx.get("mfe_usdt", 0.0))
        age_sec = float(ctx.get("age_sec", 0.0))

        flow_with_us = flow_score * direction
        ind_with_us = ind_score * direction
        comb_with_us = combined_score * direction
        cvd_with_us = cvd * direction

        fav_vol = buy_usdt if side == "LONG" else sell_usdt
        opp_vol = sell_usdt if side == "LONG" else buy_usdt
        opp_dominance = (opp_vol / max(fav_vol, 1.0)) if (opp_vol + fav_vol) > 500.0 else 1.0

        st_dir = ctx.get("st_dir")
        st_flipped = (st_dir is not None and float(st_dir) * direction < 0)

        exit_votes_r1: dict[str, bool] = {}
        reasons_found: list[str] = []

        for ag in TEN_INSPECTORS:
            want_exit = False
            # Kârdayken hem para akışı hem yapısal ivme gerçekten karşı tarafa döndüyse (dalgaları erken boğmadan)
            if gross_pnl_usdt >= 2.00:
                if (
                    flow_with_us <= -16.0 * (2.0 - ag.skepticism)
                    and ind_with_us <= -10.0
                    and opp_dominance >= 1.40
                ):
                    want_exit = True
                    if "kar_akim_tersine_dondu" not in reasons_found:
                        reasons_found.append("kar_akim_tersine_dondu")
                elif comb_with_us <= -22.0 and cvd_with_us <= 0 and ind_with_us <= -12.0:
                    want_exit = True
                    if "indikator_ve_cvd_donusu" not in reasons_found:
                        reasons_found.append("indikator_ve_cvd_donusu")
            # Zarardayken (en az 10dk / 2 adet 5dk mum nefes süresi sonrası) tam yapısal + Supertrend + akış çöküşü varsa
            elif age_sec >= 600.0 and gross_pnl_usdt <= -3.50:
                if (
                    comb_with_us <= -30.0
                    and flow_with_us <= -22.0
                    and ind_with_us <= -18.0
                    and opp_dominance >= 1.55
                    and (st_dir is None or st_flipped)
                ):
                    want_exit = True
                    if "tam_karsi_akim_tez_iptali" not in reasons_found:
                        reasons_found.append("tam_karsi_akim_tez_iptali")

            exit_votes_r1[ag.agent_id] = want_exit

        # Tur 2 Akran Teftişi: Eğer para girişi/satışı hâlâ pozisyon lehine güçlüyse erken çıkışı veto et!
        strong_continuation = flow_with_us >= 8.0 or (opp_dominance < 0.85 and ind_with_us > 0.0)
        exit_votes_r2: dict[str, bool] = {}
        for ag in TEN_INSPECTORS:
            v = exit_votes_r1[ag.agent_id]
            if v and strong_continuation and gross_pnl_usdt < 8.0:
                # Akranlar para akışının bitmediğini kanıtladı -> pozisyonu koru!
                v = False
            exit_votes_r2[ag.agent_id] = v

        exit_count = sum(1 for v in exit_votes_r2.values() if v)
        should_exit = exit_count >= 7

        if should_exit:
            self.audit_stats["position_exit_decisions"] += 1
            msg = (
                f"[Pozisyon Teftişi] {symbol} {side}: {exit_count}/10 ajan akım dönüşünü doğruladı "
                f"({', '.join(reasons_found) or 'akim_bitti'}) -> ÇIKIŞ."
            )
            self.dialogue_log.append(
                {
                    "kind": "POSITION_EXIT_AUDIT",
                    "symbol": symbol,
                    "side": side,
                    "approved": True,
                    "votes": f"{exit_count}/10 ÇIKIŞ",
                    "score": round(gross_pnl_usdt, 2),
                    "messages": [msg],
                }
            )
        else:
            self.audit_stats["position_hold_decisions"] += 1

        return {
            "should_exit": should_exit,
            "exit_votes": exit_count,
            "hold_votes": 10 - exit_count,
            "strong_continuation": strong_continuation,
            "mfe_usdt": mfe_usdt,
            "reason": (
                f"10_AJAN_AKIM_BITTI_CIKIS ({exit_count}/10: {', '.join(reasons_found)})"
                if should_exit
                else f"10_AJAN_POZISYONU_KORU ({10 - exit_count}/10 akım devam ediyor)"
            ),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.MODE_LABEL,
            "min_consensus_votes": self.min_consensus_votes,
            "dynamic_min_gross_fee_mult": round(self.dynamic_min_gross_fee_mult, 2),
            "stats": dict(self.audit_stats),
            "recent_dialogues": list(self.dialogue_log)[-12:],
        }
