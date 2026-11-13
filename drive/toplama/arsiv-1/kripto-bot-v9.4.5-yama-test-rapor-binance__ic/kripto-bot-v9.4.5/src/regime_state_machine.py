"""Kripto Bot v9.1 — Histerezisli Rejim Durum Makinesi, Ayı/Yatay Dağıtım Kapısı ve Hacim Uyumsuzluğu.

v9.1 Yükseltmeleri:
  1. Sinyal Öncesi Tam Piyasa Rejimi Sorgusu (`evaluate_macro_regime`):
     - `CRASH_RISK_OFF` (sert çöküş / şok) ve `CHOPPY_RANGE` (testere / gürültülü yatay) piyasalarda
       sinyalleri %100 engeller; eski `MOMENTUM_FLOW_OVERRIDE` istisnası tamamen kaldırılmıştır.
  2. Ayı Trendi & Yatay Dağıtım Düşen Hacim Filtresi (`check_bearish_distribution_gate`):
     - Piyasa hacimleri azalırken rejim `BEARISH_TREND` veya `YATAY_DAGITIM` ise tüm `LONG` sinyalleri
       %100 engellenir; yalnızca `SHORT` yönlü işlemlere izin verilir.
  3. Hacim Uyumsuzluğu (`detect_bearish_volume_divergence`):
     - Fiyat yerel zirveyi test ederken / yeni tepe denerken hacim dibe vurduğunda, `SpikeDetector`
       ve `MoneyFlow` filtrelerinden geçirerek agresif `SHORT` (`VOLUME_DIVERGENCE_SHORT`) tetikler.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

import pandas as pd


VALID_REGIMES = ("SIKISMA", "BREAKOUT", "TREND", "RANGE")


@dataclass
class SymbolRegimeState:
    confirmed_regime: str = "RANGE"
    previous_regime: str = "RANGE"
    pending_regime: str | None = None
    pending_count: int = 0
    last_bar_id: int | None = None
    bars_in_regime: int = 0
    transition: str = "NONE"


class RegimeStateMachine:
    """Sembol bazlı histerezisli rejim makinesi, düşen-hacim ayı kapısı ve hacim uyumsuzluğu motoru."""

    def __init__(
        self,
        *,
        min_confirm_bars: int = 2,
        adx_enter: float = 22.0,
        adx_exit: float = 18.0,
        breadth_min_ratio: float = 0.35,
        fade_min_vwap_z: float = 1.65,
        choppy_choppiness_min: float = 61.8,
        crash_5m_pct: float = -1.8,
        crash_1h_pct: float = -3.5,
        volume_decline_ratio_max: float = 0.94,
        block_long_in_bearish_distribution: bool = True,
    ) -> None:
        self.min_confirm_bars = max(1, int(min_confirm_bars))
        self.adx_enter = float(adx_enter)
        self.adx_exit = float(adx_exit)
        self.breadth_min_ratio = float(breadth_min_ratio)
        self.fade_min_vwap_z = float(fade_min_vwap_z)
        self.choppy_choppiness_min = float(choppy_choppiness_min)
        self.crash_5m_pct = float(crash_5m_pct)
        self.crash_1h_pct = float(crash_1h_pct)
        self.volume_decline_ratio_max = float(volume_decline_ratio_max)
        self.block_long_in_bearish_distribution = bool(block_long_in_bearish_distribution)
        self._states: dict[str, SymbolRegimeState] = {}
        self.stats = {
            "evaluations": 0,
            "transitions": 0,
            "squeeze_breakouts": 0,
            "whipsaws_suppressed": 0,
            "fade_blocked_low_breadth": 0,
            "choppy_hard_blocks": 0,
            "crash_hard_blocks": 0,
            "bearish_distribution_long_blocks": 0,
            "volume_divergence_shorts": 0,
        }

    def state_for(self, symbol: str) -> SymbolRegimeState:
        st = self._states.get(symbol)
        if st is None:
            st = SymbolRegimeState()
            self._states[symbol] = st
        return st

    def classify_raw_with_hysteresis(
        self,
        symbol: str,
        *,
        raw_regime: str,
        adx: float,
        squeeze_on: bool = False,
        breakout_dir: int = 0,
    ) -> str:
        st = self.state_for(symbol)
        cur = st.confirmed_regime
        raw_up = str(raw_regime or "RANGE").upper()
        if raw_up not in VALID_REGIMES:
            raw_up = "RANGE"

        if squeeze_on or raw_up == "SIKISMA":
            return "SIKISMA"
        if breakout_dir != 0 or raw_up == "BREAKOUT":
            return "BREAKOUT"

        adx_val = float(adx or 0.0)
        if cur == "TREND":
            return "TREND" if adx_val >= self.adx_exit else "RANGE"
        if adx_val >= self.adx_enter:
            return "TREND"
        return "RANGE"

    def update(
        self,
        symbol: str,
        *,
        raw_regime: str,
        adx: float = 0.0,
        bar_id: int | None = None,
        rvol: float = 1.0,
        squeeze_on: bool = False,
        breakout_dir: int = 0,
    ) -> dict[str, Any]:
        self.stats["evaluations"] += 1
        st = self.state_for(symbol)
        candidate = self.classify_raw_with_hysteresis(
            symbol,
            raw_regime=raw_regime,
            adx=adx,
            squeeze_on=squeeze_on,
            breakout_dir=breakout_dir,
        )

        is_new_bar = bar_id is None or st.last_bar_id != int(bar_id)
        if bar_id is not None:
            st.last_bar_id = int(bar_id)

        if st.bars_in_regime == 0:
            st.confirmed_regime = candidate
            st.previous_regime = candidate
            st.bars_in_regime = 1
            st.transition = "INITIAL"
            return self._snapshot(st, candidate)

        if not is_new_bar:
            return self._snapshot(st, candidate)

        if candidate == st.confirmed_regime:
            if st.pending_regime is not None:
                self.stats["whipsaws_suppressed"] += 1
            st.pending_regime = None
            st.pending_count = 0
            st.bars_in_regime += 1
            st.transition = "NONE"
            return self._snapshot(st, candidate)

        needed = self.min_confirm_bars
        if st.confirmed_regime == "SIKISMA" and candidate == "BREAKOUT" and float(rvol) >= 1.8:
            needed = 1

        if st.pending_regime == candidate:
            st.pending_count += 1
        else:
            if st.pending_regime is not None:
                self.stats["whipsaws_suppressed"] += 1
            st.pending_regime = candidate
            st.pending_count = 1

        if st.pending_count >= needed:
            prev = st.confirmed_regime
            st.previous_regime = prev
            st.confirmed_regime = candidate
            st.pending_regime = None
            st.pending_count = 0
            st.bars_in_regime = 1
            self.stats["transitions"] += 1
            if prev == "SIKISMA" and candidate in ("BREAKOUT", "TREND"):
                st.transition = "SQUEEZE_BREAKOUT"
                self.stats["squeeze_breakouts"] += 1
            else:
                st.transition = f"{prev}_TO_{candidate}"
        else:
            st.bars_in_regime += 1

        return self._snapshot(st, candidate)

    def evaluate_macro_regime(
        self,
        symbol: str,
        ohlcv_5m: pd.DataFrame,
        *,
        adx: float,
        choppiness_14: float,
        vwap_atr_z: float,
        rvol: float,
        rvol_warmed: bool,
        mtf_trend: str = "NEUTRAL",
    ) -> dict[str, Any]:
        """Her sinyalden ÖNCE piyasa rejimini (`Trend`, `Yatay`, `Çöküş`, `Ayı`, `Yatay Dağıtım`) sorgular."""
        st = self.state_for(symbol)
        base_regime = st.confirmed_regime
        closes = ohlcv_5m["close"].astype(float)
        vols = ohlcv_5m["volume"].astype(float) if "volume" in ohlcv_5m.columns else pd.Series([1.0])

        cur_px = float(closes.iloc[-1])
        px_5m_ago = float(closes.iloc[-2]) if len(closes) >= 2 else cur_px
        px_1h_ago = float(closes.iloc[-13]) if len(closes) >= 13 else float(closes.iloc[0])
        ret_5m_pct = ((cur_px - px_5m_ago) / px_5m_ago * 100.0) if px_5m_ago > 0 else 0.0
        ret_1h_pct = ((cur_px - px_1h_ago) / px_1h_ago * 100.0) if px_1h_ago > 0 else 0.0

        ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])

        # Kapanmış mumlarda hacim trendi (son 3 kapalı mum ortalaması vs önceki 20 mum medyanı)
        vol_ratio_5m = 1.0
        if len(vols) >= 12:
            closed_vols = [float(v) for v in vols.iloc[:-1] if float(v) > 0]
            if len(closed_vols) >= 10:
                recent_v = statistics.mean(closed_vols[-3:])
                base_v = statistics.median(closed_vols[-23:-3] or closed_vols[:-3])
                if base_v > 0:
                    vol_ratio_5m = recent_v / base_v

        volume_declining = (vol_ratio_5m <= self.volume_decline_ratio_max) or (
            rvol_warmed and float(rvol) <= self.volume_decline_ratio_max
        )

        # 1) Ani Çöküş (`CRASH_RISK_OFF`) vs Kontrollü 1s Ayı Şelalesi (`BEARISH_CASCADE`)
        if ret_5m_pct <= self.crash_5m_pct or (
            ret_1h_pct <= self.crash_1h_pct and float(vwap_atr_z) <= -2.25
        ):
            self.stats["crash_hard_blocks"] += 1
            return {
                "macro_regime": "CRASH_RISK_OFF",
                "hard_blocked": True,
                "volume_declining": volume_declining,
                "vol_ratio_5m": round(vol_ratio_5m, 4),
                "ret_5m_pct": round(ret_5m_pct, 3),
                "ret_1h_pct": round(ret_1h_pct, 3),
                "ema20": ema20,
                "ema50": ema50,
                "reason": f"cokus_rejimi_engeli(5m={ret_5m_pct:+.2f}%,1h={ret_1h_pct:+.2f}%)",
            }

        if ret_1h_pct <= self.crash_1h_pct and float(vwap_atr_z) > -2.25:
            return {
                "macro_regime": "BEARISH_CASCADE",
                "hard_blocked": False,
                "volume_declining": volume_declining,
                "vol_ratio_5m": round(vol_ratio_5m, 4),
                "ret_5m_pct": round(ret_5m_pct, 3),
                "ret_1h_pct": round(ret_1h_pct, 3),
                "ema20": ema20,
                "ema50": ema50,
                "reason": f"kontrollu_ayi_selalesi(1h={ret_1h_pct:+.2f}%,z={vwap_atr_z:+.2f})",
            }

        # 2) Testere / Gürültülü Yatay (`CHOPPY_RANGE`) -> %100 Sinyal Engeli
        is_choppy = (
            base_regime == "RANGE"
            and float(choppiness_14) >= self.choppy_choppiness_min
            and float(adx) < 19.5
            and abs(float(vwap_atr_z)) < self.fade_min_vwap_z
        )
        if is_choppy:
            self.stats["choppy_hard_blocks"] += 1
            return {
                "macro_regime": "CHOPPY_RANGE",
                "hard_blocked": True,
                "volume_declining": volume_declining,
                "vol_ratio_5m": round(vol_ratio_5m, 4),
                "ret_5m_pct": round(ret_5m_pct, 3),
                "ret_1h_pct": round(ret_1h_pct, 3),
                "ema20": ema20,
                "ema50": ema50,
                "reason": f"yatay_testere_engeli(chop={choppiness_14:.1f},adx={adx:.1f})",
            }

        # 3) Ayı Trendi (`BEARISH_TREND`) ve Yatay Dağıtım (`YATAY_DAGITIM`) Tespiti
        mtf_up = str(mtf_trend or "NEUTRAL").upper()
        is_bearish_structure = (ema20 < ema50 and (mtf_up == "BEARISH" or ret_1h_pct <= -0.15)) or (
            base_regime == "TREND" and ema20 < ema50
        )
        is_horizontal_distribution = (
            not is_bearish_structure
            and base_regime in ("RANGE", "SIKISMA")
            and volume_declining
            and (mtf_up == "BEARISH" or ema20 <= ema50 * 1.0015 or float(vwap_atr_z) >= 0.30)
        )

        if is_bearish_structure:
            macro = "BEARISH_TREND"
        elif is_horizontal_distribution:
            macro = "YATAY_DAGITIM"
        elif base_regime == "BREAKOUT" or st.transition == "SQUEEZE_BREAKOUT":
            macro = "SQUEEZE_BREAKOUT"
        elif ema20 > ema50 and base_regime == "TREND":
            macro = "BULLISH_TREND"
        else:
            macro = base_regime

        return {
            "macro_regime": macro,
            "hard_blocked": False,
            "volume_declining": volume_declining,
            "vol_ratio_5m": round(vol_ratio_5m, 4),
            "ret_5m_pct": round(ret_5m_pct, 3),
            "ret_1h_pct": round(ret_1h_pct, 3),
            "ema20": ema20,
            "ema50": ema50,
            "reason": "ok",
        }

    def check_bearish_distribution_gate(
        self,
        *,
        side: str,
        macro_info: dict[str, Any],
        mtf_trend: str = "NEUTRAL",
        flow_score: float = -15.0,
        vwap_atr_z: float = 0.0,
    ) -> tuple[bool, str]:
        """Piyasa hacimleri azalırken veya üst zaman dilimi düşüşteyken `BEARISH_TREND`,
        `YATAY_DAGITIM` ve `BEARISH_CASCADE` rejimlerinde `LONG` sinyallerini engeller;
        kontrollü şelalede aşırı satım olmayan trend `SHORT` fırsatlarına izin verir."""
        macro = str(macro_info.get("macro_regime") or "")
        vol_declining = bool(macro_info.get("volume_declining", False))
        mtf_up = str(mtf_trend or "NEUTRAL").upper()

        if macro == "BEARISH_CASCADE":
            if side == "LONG":
                self.stats["bearish_distribution_long_blocks"] += 1
                return False, f"kontrollu_selale_long_engeli(1h={macro_info.get('ret_1h_pct', 0.0):+.2f}%)"
            if side == "SHORT":
                if float(vwap_atr_z) <= -2.25:
                    return False, f"selale_dip_short_kovalama_engeli(z={vwap_atr_z:+.2f})"
                if float(flow_score) > -8.0:
                    return False, f"selale_short_satis_akisi_zayif(flow={flow_score:+.1f})"
            return True, "ok"

        if not self.block_long_in_bearish_distribution or side != "LONG":
            return True, "ok"

        if vol_declining and macro in ("BEARISH_TREND", "YATAY_DAGITIM"):
            self.stats["bearish_distribution_long_blocks"] += 1
            return (
                False,
                f"dusen_hacim_{macro.lower()}_long_engeli(vol_oran={macro_info.get('vol_ratio_5m', 1.0):.2f})",
            )
        if macro == "BEARISH_TREND" and mtf_up == "BEARISH":
            self.stats["bearish_distribution_long_blocks"] += 1
            return False, "ayi_trendi_ust_zaman_uyumlu_long_engeli"
        return True, "ok"

    def detect_bearish_volume_divergence(
        self,
        ohlcv_5m: pd.DataFrame,
        *,
        price: float,
        ema20: float,
        rvol: float,
        rvol_warmed: bool,
        spike_ret_2s: float,
        flow_snap: dict[str, Any],
        cfg_div: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fiyat yeni zirve / tepe testi yaparken hacim dibe vurduğunda `Spike` + `MoneyFlow`
        onayıyla agresif `SHORT` (`VOLUME_DIVERGENCE_SHORT`) sinyali üretir."""
        c = cfg_div or {}
        if not bool(c.get("aktif", True)) or len(ohlcv_5m) < 16:
            return {"triggered": False}

        lookback = max(8, int(c.get("pencere_mum", 14)))
        tol_pct = float(c.get("tepe_yakinlik_tolerans_yuzde", 0.38))
        vol_exh_max = float(c.get("hacim_tukenme_orani_ust", 0.72))
        max_rvol_exh = float(c.get("maks_rvol_tukenme", 0.88))
        max_flow_short = float(c.get("maks_akis_skoru_short", -2.5))

        window = ohlcv_5m.iloc[-(lookback + 1) : -1]
        cur_bar = ohlcv_5m.iloc[-1]
        highs = window["high"].astype(float).to_numpy()
        vols = window["volume"].astype(float).to_numpy()
        if len(highs) == 0:
            return {"triggered": False}

        peak_idx = int(highs.argmax())
        swing_high = float(highs[peak_idx])
        peak_vol = float(vols[peak_idx]) if vols[peak_idx] > 0 else float(vols.mean() or 1.0)
        cur_test_high = max(float(price), float(cur_bar["high"]))

        # 1) Fiyat zirve testi (swing tepesine <= %tol yakın veya üstünü süpürmüş ve EMA20 üzerinde)
        near_top = swing_high > 0 and cur_test_high >= swing_high * (1.0 - tol_pct / 100.0)
        above_mean = float(price) >= float(ema20) * 0.999
        if not (near_top and above_mean):
            return {"triggered": False}

        # 2) Hacim dibe vuruşu (son kapalı mum / güncel hacim tepe hacminin <= %72'si veya RVOL <= 0.88)
        last_closed_vol = float(window["volume"].iloc[-1])
        vol_ratio_vs_peak = (last_closed_vol / peak_vol) if peak_vol > 0 else 1.0
        vol_bottomed = (vol_ratio_vs_peak <= vol_exh_max) or (
            rvol_warmed and float(rvol) <= max_rvol_exh
        )
        if not vol_bottomed:
            return {"triggered": False}

        # 3) Spike + MoneyFlow doğrulaması (yukarı hacimli spike yok, satıcı baskısı / alıcı tükenmesi var)
        if float(spike_ret_2s) > 0.15 or (rvol_warmed and float(rvol) > 1.15):
            return {"triggered": False}

        flow_score = float(flow_snap.get("score", 0.0))
        buy_u = float(flow_snap.get("buy_usdt", 0.0))
        sell_u = float(flow_snap.get("sell_usdt", 0.0))
        seller_edge = (flow_score <= max_flow_short) or (sell_u > 0 and sell_u >= buy_u * 1.08)
        if not seller_edge:
            return {"triggered": False}

        self.stats["volume_divergence_shorts"] += 1
        return {
            "triggered": True,
            "side": "SHORT",
            "playbook": "VOLUME_DIVERGENCE_SHORT",
            "swing_high": max(swing_high, cur_test_high),
            "vol_ratio_vs_peak": round(vol_ratio_vs_peak, 4),
            "flow_score": round(flow_score, 2),
            "reason": (
                f"hacim_uyumsuzlugu_short(tepe={swing_high:.6g},vol_oran={vol_ratio_vs_peak:.2f},"
                f"rvol={rvol:.2f},flow={flow_score:+.1f})"
            ),
        }

    def select_strategy_playbook(
        self,
        symbol: str,
        *,
        side: str,
        vwap_atr_z: float,
        breadth_ratio: float,
        rvol: float,
        flow_score: float,
        rvol_warmed: bool = True,
        net_breadth_score: float = 0.0,
    ) -> dict[str, Any]:
        """v9.3 Katı Strateji Seçici (`MOMENTUM_FLOW_OVERRIDE` arka kapısı kapalı, yönlü genişlik duyarlı)."""
        st = self.state_for(symbol)
        regime = st.confirmed_regime
        if side not in ("LONG", "SHORT"):
            return {"allowed": True, "playbook": "WAIT", "regime": regime, "reason": "bekle"}

        is_counter_vwap_fade = (side == "LONG" and vwap_atr_z <= -self.fade_min_vwap_z) or (
            side == "SHORT" and vwap_atr_z >= self.fade_min_vwap_z
        )

        if is_counter_vwap_fade or regime == "RANGE":
            if float(breadth_ratio) < self.breadth_min_ratio:
                self.stats["fade_blocked_low_breadth"] += 1
                return {
                    "allowed": False,
                    "playbook": "BREADTH_FADE",
                    "regime": regime,
                    "transition": st.transition,
                    "reason": (
                        f"genislik_kapisi_kapali(genislik={breadth_ratio:.1%} < "
                        f"esik={self.breadth_min_ratio:.1%})"
                    ),
                }
            if side == "LONG" and float(net_breadth_score) <= -0.35:
                return {
                    "allowed": False,
                    "playbook": "BREADTH_FADE",
                    "regime": regime,
                    "transition": st.transition,
                    "reason": f"agir_satis_selalesinde_long_fade_engeli(net={net_breadth_score:+.2f})",
                }
            if side == "SHORT" and float(net_breadth_score) >= 0.35:
                return {
                    "allowed": False,
                    "playbook": "BREADTH_FADE",
                    "regime": regime,
                    "transition": st.transition,
                    "reason": f"agir_alis_rallisinde_short_fade_engeli(net={net_breadth_score:+.2f})",
                }
            if regime == "RANGE" and not is_counter_vwap_fade:
                return {
                    "allowed": False,
                    "playbook": "RANGE_NOISE_BLOCK",
                    "regime": regime,
                    "transition": st.transition,
                    "reason": f"yatay_rejimde_vwap_uzamasi_yok(z={vwap_atr_z:+.2f})",
                }
            return {
                "allowed": True,
                "playbook": "BREADTH_FADE",
                "regime": regime,
                "transition": st.transition,
                "reason": f"genislik_onayli_fade(genislik={breadth_ratio:.1%},z={vwap_atr_z:+.2f})",
            }

        if regime == "SIKISMA":
            strong_prebreak = abs(float(flow_score)) >= 38.0 and (float(rvol) >= 1.40 or not rvol_warmed)
            if not strong_prebreak:
                return {
                    "allowed": False,
                    "playbook": "SQUEEZE_WAIT",
                    "regime": regime,
                    "transition": st.transition,
                    "reason": "sikisma_icinde_kirilim_bekleniyor",
                }

        return {
            "allowed": True,
            "playbook": "MOMENTUM_BREAKOUT",
            "regime": regime,
            "transition": st.transition,
            "reason": f"onayli_momentum(rejim={regime},gecis={st.transition})",
        }

    @staticmethod
    def _snapshot(st: SymbolRegimeState, candidate: str) -> dict[str, Any]:
        return {
            "regime": st.confirmed_regime,
            "confirmed_regime": st.confirmed_regime,
            "previous_regime": st.previous_regime,
            "candidate_regime": candidate,
            "pending_regime": st.pending_regime,
            "pending_count": st.pending_count,
            "bars_in_regime": st.bars_in_regime,
            "transition": st.transition,
        }
