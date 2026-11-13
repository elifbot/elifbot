"""src/flow_exit_manager.py — v9.3 İndikatör + Para Akışı Takip Eden 4-Kademeli Dinamik Dalga Koruma ve Çıkış Motoru.

Temel Mantık:
  - LONG pozisyon: Para girişi ve indikatör ivmesi sürdüğü sürece pozisyon KORUNUR;
    satış baskısına ve indikatör dönüşüne geçtiği en uygun noktada kapatılır.
  - SHORT pozisyon: Satış baskısı (para çıkışı) sürdüğü sürece pozisyon KORUNUR;
    satış bitip alışa ve indikatör dönüşüne geçtiği noktada kapatılır.
  - Sabit küçük TP veya 135sn kör zaman kesici YOKTUR; acil güvenlik stopu
    $50 marjın %80'i (-$40.00 / 10x'te %8.0 fiyat mesafesi) olarak korunur.
  - v9.3 Yükseltmeleri:
    1) Net Başabaş Kalkanı (`mfe_usdt >= $1.55` sonrası akım ters dönerse komisyon-üstü net kâr kilidi),
    2) 3 Kademeli İlerleyen Dalga Kilidi (`$2.20 -> %66`, `$4.50 -> %72`, `$8.00 -> %78`),
    3) Aktif Fazda Ters Sinyal + Karşı Akım Çıkışı (`ACTIVE_SIGNAL_REVERSAL`, yalnız DRAIN değil canlıda da aktif).
"""
from __future__ import annotations

from typing import Any


class FlowTrendExitManager:
    """Açık pozisyonları indikatör + para akışı + kademeli dalga kilidi + 10-ajan teftişiyle yönetir."""

    def __init__(
        self,
        *,
        min_reversal_profit_usdt: float = 1.10,
        breakeven_shield_mfe_usdt: float = 1.55,
        wave_ratchet_min_mfe_usdt: float = 2.20,
        wave_ratchet_keep_ratio: float = 0.66,
        mid_wave_mfe_usdt: float = 4.50,
        mid_wave_keep_ratio: float = 0.72,
        big_wave_mfe_usdt: float = 8.00,
        big_wave_keep_ratio: float = 0.78,
        thesis_invalidation_min_age_sec: float = 90.0,
    ) -> None:
        self.min_reversal_profit_usdt = float(min_reversal_profit_usdt)
        self.breakeven_shield_mfe_usdt = float(breakeven_shield_mfe_usdt)
        self.wave_ratchet_min_mfe_usdt = float(wave_ratchet_min_mfe_usdt)
        self.wave_ratchet_keep_ratio = float(wave_ratchet_keep_ratio)
        self.mid_wave_mfe_usdt = float(mid_wave_mfe_usdt)
        self.mid_wave_keep_ratio = float(mid_wave_keep_ratio)
        self.big_wave_mfe_usdt = float(big_wave_mfe_usdt)
        self.big_wave_keep_ratio = float(big_wave_keep_ratio)
        self.thesis_invalidation_min_age_sec = float(thesis_invalidation_min_age_sec)

    def evaluate_open_position(
        self,
        *,
        side: str,
        gross_pnl_usdt: float,
        mfe_usdt: float,
        roundtrip_fee_usdt: float,
        age_sec: float,
        ind_score: float,
        flow_score: float,
        combined_score: float,
        flow_snap: dict[str, Any],
        supertrend_dir: int | None = None,
        rsi: float | None = None,
        ten_agent_audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Pozisyonun tutulmaya devam mı edeceğine yoksa dönüş/kilit noktasında kapatılacağına karar verir."""
        side_u = str(side or "LONG").upper()
        direction = 1.0 if side_u == "LONG" else -1.0

        flow_aligned = float(flow_score) * direction
        ind_aligned = float(ind_score) * direction
        comb_aligned = float(combined_score) * direction

        buy_usdt = float(flow_snap.get("buy_usdt", 0.0) or 0.0)
        sell_usdt = float(flow_snap.get("sell_usdt", 0.0) or 0.0)
        cvd = float(flow_snap.get("cvd_60s", 0.0) or 0.0)
        cvd_aligned = cvd * direction

        fav_vol = buy_usdt if side_u == "LONG" else sell_usdt
        opp_vol = sell_usdt if side_u == "LONG" else buy_usdt
        total_vol = fav_vol + opp_vol
        opp_ratio = (opp_vol / max(fav_vol, 1.0)) if total_vol >= 400.0 else 1.0

        st_flipped = (
            (side_u == "LONG" and supertrend_dir == -1)
            or (side_u == "SHORT" and supertrend_dir == 1)
        )
        min_net_meaningful = max(self.min_reversal_profit_usdt, roundtrip_fee_usdt * 3.2)

        # 1) 10-Ajan Çapraz Teftiş Çıkış Uzlaşısı
        if ten_agent_audit and bool(ten_agent_audit.get("should_exit", False)):
            return {
                "should_exit": True,
                "exit_kind": "TEN_AGENT_FLOW_REVERSAL",
                "reason": str(ten_agent_audit.get("reason") or "10_AJAN_AKIM_BITTI_CIKIS"),
            }

        # 2) Anlamlı Kârdayken Akım + İndikatör Dönüşü ("satışa geçene kadar LONG / satış bitene kadar SHORT")
        if gross_pnl_usdt >= min_net_meaningful:
            rsi_exhausted = (
                (side_u == "LONG" and rsi is not None and rsi < 46.0 and ind_aligned < 0)
                or (side_u == "SHORT" and rsi is not None and rsi > 54.0 and ind_aligned > 0)
            )
            flow_reversed = (
                flow_aligned <= -12.0
                or (opp_ratio >= 1.45 and cvd_aligned < 0 and flow_aligned < -4.0)
            )
            ind_reversed = comb_aligned <= -10.0 or st_flipped or rsi_exhausted

            if flow_reversed and (ind_reversed or gross_pnl_usdt >= min_net_meaningful * 1.5):
                lbl = (
                    "PARA GİRİŞİ BİTTİ / SATIŞA GEÇTİ (LONG KÂR AL)"
                    if side_u == "LONG"
                    else "SATIŞ BASKISI BİTTİ / ALIŞA GEÇTİ (SHORT KÂR AL)"
                )
                return {
                    "should_exit": True,
                    "exit_kind": "FLOW_REVERSAL_PROFIT",
                    "reason": (
                        f"{lbl}: brüt=${gross_pnl_usdt:+.2f}, akış={flow_score:+.1f}, "
                        f"skor={combined_score:+.1f}"
                    ),
                }

        # 3) 3-Kademeli Büyük Dalga Kâr Koruma Kilidi (Akım Zayıfladığında Kârın %66-%78'ini Koru)
        if mfe_usdt >= self.wave_ratchet_min_mfe_usdt:
            if mfe_usdt >= self.big_wave_mfe_usdt:
                keep = self.big_wave_keep_ratio
                min_hold_flow = 10.0
            elif mfe_usdt >= self.mid_wave_mfe_usdt:
                keep = self.mid_wave_keep_ratio
                min_hold_flow = 8.0
            else:
                keep = self.wave_ratchet_keep_ratio
                min_hold_flow = 6.0

            floor_usdt = max(roundtrip_fee_usdt * 2.5, mfe_usdt * keep)
            if gross_pnl_usdt >= 0.0 and gross_pnl_usdt <= floor_usdt and flow_aligned < min_hold_flow:
                return {
                    "should_exit": True,
                    "exit_kind": "WAVE_PROFIT_GUARD",
                    "reason": (
                        f"DALGA KÂR KORUMASI: zirve=${mfe_usdt:+.2f} -> korunan=${gross_pnl_usdt:+.2f} "
                        f"(akış ivmesi yavaşladı: {flow_score:+.1f})"
                    ),
                }

        # 4) Net Başabaş Kalkanı (`mfe >= $1.55` görmüş dalganın komisyon-üstü kârdan zarara dönmesini önler)
        if mfe_usdt >= self.breakeven_shield_mfe_usdt:
            be_floor = max(roundtrip_fee_usdt + 0.20, 0.55)
            if (
                gross_pnl_usdt >= -0.25
                and gross_pnl_usdt <= be_floor
                and flow_aligned <= -6.0
                and (ind_aligned <= 0.0 or st_flipped)
            ):
                return {
                    "should_exit": True,
                    "exit_kind": "NET_BREAKEVEN_SHIELD",
                    "reason": (
                        f"NET BAŞABAŞ KALKANI: zirve=${mfe_usdt:+.2f} -> korunan=${gross_pnl_usdt:+.2f} "
                        f"(karşı akış={flow_score:+.1f})"
                    ),
                }

        # 5) Aktif Ters Sinyal & Yapısal Tez İptali (-$40 acil stopa gitmeden teyitli yapısal dönüşte çıkış;
        #    tek mumluk normal -%0.25 geri çekilmelerde whipsaw olmaması için en az 10dk / Supertrend kırılımı şarttır)
        if age_sec >= max(self.thesis_invalidation_min_age_sec, 600.0) and gross_pnl_usdt <= -2.50:
            strong_signal_flip = (
                st_flipped
                and comb_aligned <= -24.0
                and flow_aligned <= -16.0
            )
            deep_flow_flip = (
                gross_pnl_usdt <= -4.00
                and comb_aligned <= -30.0
                and flow_aligned <= -24.0
                and opp_ratio >= 1.50
            )
            if strong_signal_flip or deep_flow_flip:
                return {
                    "should_exit": True,
                    "exit_kind": "ACTIVE_SIGNAL_REVERSAL" if strong_signal_flip else "THESIS_INVALIDATED",
                    "reason": (
                        f"TERS SİNYAL & KARŞI AKIM DOĞAL ÇIKIŞ: skor={combined_score:+.1f}, "
                        f"akış={flow_score:+.1f}, anlık=${gross_pnl_usdt:+.2f}"
                    ),
                }

        return {
            "should_exit": False,
            "exit_kind": "HOLD_WAVE",
            "reason": (
                "LONG para girişi/trend korunuyor"
                if side_u == "LONG"
                else "SHORT satış baskısı/trend korunuyor"
            ),
        }
