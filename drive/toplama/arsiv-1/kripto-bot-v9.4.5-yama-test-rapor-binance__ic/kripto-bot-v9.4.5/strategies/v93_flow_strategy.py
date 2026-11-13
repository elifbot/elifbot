"""Kripto Bot v9.3.0 — Kanonik Çoklu- Katman Akış, Lider Rejim & Dalga Çıkış Stratejisi.

Canlı motor (`UnifiedEngine` + `GlobalMarketRegimeAnchor` + `RegimeStateMachine` +
`TenAgentMutualAuditCouncil` + `FlowTrendExitManager`) ile OOS Walk-Forward ve Ablasyon
testleri için ortak karar bileşenlerini kullanır; mum ve tick yürütmesi eşdeğer değildir:

  1. Gerçek `taker_buy_quote` / agresif alıcı-satıcı emir akışı (`compute_candle_orderflow`),
  2. Nedensel `5m -> 15m / 1h` çoklu zaman dilimi (`causal_mtf_from_5m`),
  3. Küresel `BTC+ETH` lider rejim çapası + evren yönlü piyasa genişliği (`GlobalMarketRegimeAnchor`),
  4. 10-Ajan 3-Turlu Çapraz Müzakere Konseyi (`TenAgentMutualAuditCouncil`),
  5. 4-Aşamalı Dinamik Dalga Kâr Koruma & Ters Akış Çıkışı (`FlowTrendExitManager`).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.flow_exit_manager import FlowTrendExitManager
from src.global_market_regime import (
    GlobalMarketRegimeAnchor,
    causal_mtf_from_5m,
    compute_candle_orderflow,
)
from src.indicators import Indicators, indicator_score
from src.pdf_core_confluence import compute_pdf_core_confluence
from src.regime_state_machine import RegimeStateMachine
from src.ten_agent_debate import TenAgentMutualAuditCouncil
from strategies.base import SignalResult, StrategyBase


def _fast_supertrend_last(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 10, mult: float = 3.0
) -> tuple[int, float]:
    """Son mumun Supertrend yönünü (+1 / -1) ve ATR değerini saf NumPy ile ~0.08ms'de hesaplar."""
    n = len(close)
    if n < 3:
        return 1, 0.0
    prev_c = np.empty(n, dtype=float)
    prev_c[0] = close[0]
    prev_c[1:] = close[:-1]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
    atr = np.empty(n, dtype=float)
    alpha = 1.0 / float(period)
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]
    atr_warmup = atr.copy()
    if n > period:
        atr_warmup[: period - 1] = 0.0
    hl2 = (high + low) * 0.5
    bu = hl2 + mult * atr_warmup
    bl = hl2 - mult * atr_warmup

    fu = bu[0]
    fl = bl[0]
    d = 1
    for i in range(1, n):
        fu = bu[i] if (bu[i] < fu or close[i - 1] > fu) else fu
        fl = bl[i] if (bl[i] > fl or close[i - 1] < fl) else fl
        if d == 1:
            d = -1 if close[i] < fl else 1
        else:
            d = 1 if close[i] > fu else -1
    return int(d), float(atr[-1])


def _ema_last(arr: np.ndarray, span: int) -> float:
    if len(arr) == 0:
        return 0.0
    alpha = 2.0 / (span + 1.0)
    val = float(arr[0])
    for x in arr[1:]:
        val = alpha * float(x) + (1.0 - alpha) * val
    return val


def _rsi_last(close: np.ndarray, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    diff = np.diff(close)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    alpha = 1.0 / float(period)
    ag = float(gains[0])
    al = float(losses[0])
    for i in range(1, len(gains)):
        ag = alpha * float(gains[i]) + (1.0 - alpha) * ag
        al = alpha * float(losses[i]) + (1.0 - alpha) * al
    if al <= 1e-12:
        return 100.0 if ag > 0 else 50.0
    rs = ag / al
    return float(100.0 - (100.0 / (1.0 + rs)))


class CausalMarketPanel:
    """Çoklu sembol OOS / Walk-Forward testlerinde `t` anına kadar olan (`open_time <= t`)
    BTC, ETH ve evren kesit getirilerini sıfır gelecek sızıntısı (no lookahead) ile sunar."""

    def __init__(self, symbol_frames: dict[str, pd.DataFrame]) -> None:
        self.frames: dict[str, pd.DataFrame] = {}
        self._ts_arrays: dict[str, np.ndarray] = {}
        self._close_arrays: dict[str, np.ndarray] = {}
        self._leader_cache: dict[tuple[str, int], pd.DataFrame] = {}
        self._returns_cache: dict[int, list[float]] = {}
        self.feature_cache: dict[tuple, Any] = {}
        self.global_anchor = GlobalMarketRegimeAnchor()
        self.global_cache: dict[int, dict] = {}
        self._mtf_cache: dict[tuple[str, int], dict[str, Any]] = {}
        for sym, df in symbol_frames.items():
            key = sym.upper().replace("/", "").replace(":USDT", "")
            ordered = df.sort_values("open_time").reset_index(drop=True)
            self.frames[key] = ordered
            self._ts_arrays[key] = ordered["open_time"].to_numpy(dtype=np.int64)
            self._close_arrays[key] = ordered["close"].to_numpy(dtype=float)

    def slice_up_to(self, symbol: str, decision_ts: int, max_bars: int = 240) -> pd.DataFrame | None:
        key = symbol.upper().replace("/", "").replace(":USDT", "")
        df = self.frames.get(key)
        if df is None or df.empty:
            return None
        cache_key = (key, int(decision_ts))
        if key in ("BTCUSDT", "ETHUSDT") and cache_key in self._leader_cache:
            return self._leader_cache[cache_key]
        ts_arr = self._ts_arrays[key]
        idx = int(np.searchsorted(ts_arr, int(decision_ts), side="right"))
        if idx <= 0:
            return None
        start = max(0, idx - max_bars)
        out = df.iloc[start:idx]
        if key in ("BTCUSDT", "ETHUSDT"):
            if len(self._leader_cache) > 4096:
                self._leader_cache.clear()
            self._leader_cache[cache_key] = out
        return out

    def causal_mtf_cached(self, symbol: str, history: pd.DataFrame, decision_ts: int) -> dict[str, Any]:
        key = (symbol.upper(), int(decision_ts))
        cached = self._mtf_cache.get(key)
        if cached is not None:
            return cached
        res = causal_mtf_from_5m(history)
        if len(self._mtf_cache) > 8192:
            self._mtf_cache.clear()
        self._mtf_cache[key] = res
        return res

    def cross_sectional_returns_15m(self, decision_ts: int) -> list[float]:
        ts_i = int(decision_ts)
        cached = self._returns_cache.get(ts_i)
        if cached is not None:
            return cached
        rets: list[float] = []
        for key, ts_arr in self._ts_arrays.items():
            idx = int(np.searchsorted(ts_arr, ts_i, side="right"))
            if idx < 4:
                continue
            closes = self._close_arrays[key]
            c_now = float(closes[idx - 1])
            c_prev = float(closes[idx - 4])
            if c_prev > 0:
                rets.append((c_now - c_prev) / c_prev * 100.0)
        if len(self._returns_cache) > 4096:
            self._returns_cache.clear()
        self._returns_cache[ts_i] = rets
        return rets


class V93CanonicalFlowStrategy(StrategyBase):
    """v9.3.0 kanonik sinyal + lider rejim + 10-ajan + dinamik dalga çıkış stratejisi."""

    NAME = "v93_canonical_flow"
    MIN_ROWS = 55
    USES_DYNAMIC_FLOW_EXIT = True
    CANONICAL_MARGIN_USDT = 50.0
    HARD_STOP_PCT = 8.0  # $50 marj x 10x ($500 notional) -> -$40 (%80 marj) acil likidasyon-önü sert stop

    # Ablasyon bayrakları (LOO bileşen katkı analizi için):
    #   disabled_family in {None, "TREND_IND", "VOLUME_FLOW", "LEADER_BREADTH_REGIME", "TEN_AGENT_AUDIT"}
    def __init__(
        self,
        *,
        symbol: str = "BTCUSDT",
        market_panel: CausalMarketPanel | None = None,
        disabled_family: str | None = None,
        entry_score_th: float = 20.0,
        min_flow_aligned: float = 11.0,
        min_rvol: float = 0.85,
        cooldown_bars: int = 3,
    ) -> None:
        super().__init__()
        self.symbol = symbol.upper().replace("/", "").replace(":USDT", "")
        self.market_panel = market_panel
        self.disabled_family = disabled_family
        self.entry_score_th = float(entry_score_th)
        self.min_flow_aligned = float(min_flow_aligned)
        self.min_rvol = float(min_rvol)
        self.cooldown_bars = int(cooldown_bars)

        self.global_anchor = market_panel.global_anchor if market_panel is not None else GlobalMarketRegimeAnchor()
        self.regime_sm = RegimeStateMachine()
        self.ten_agent = TenAgentMutualAuditCouncil(
            min_consensus_votes=7,
            min_expected_gross_fee_mult=2.6,
        )
        self.exit_mgr = FlowTrendExitManager()
        self._last_exit_ts: int = -10**15
        self._last_exit_was_loss: bool = False

    def _update_global_context(self, decision_ts: int, fallback_df: pd.DataFrame):
        if self.disabled_family == "LEADER_BREADTH_REGIME":
            return None
        if self.market_panel is not None:
            if decision_ts in self.market_panel.global_cache:
                snap, leaders, breadth = self.market_panel.global_cache[decision_ts]
                self.global_anchor.leaders = leaders.copy()
                self.global_anchor.breadth = breadth.copy()
                return snap
            btc_df = self.market_panel.slice_up_to("BTCUSDT", decision_ts, max_bars=240)
            eth_df = self.market_panel.slice_up_to("ETHUSDT", decision_ts, max_bars=240)
            if btc_df is not None and len(btc_df) >= 30:
                self.global_anchor.update_leader("BTC/USDT", btc_df, now_ms=decision_ts)
            if eth_df is not None and len(eth_df) >= 30:
                self.global_anchor.update_leader("ETH/USDT", eth_df, now_ms=decision_ts)
            rets = self.market_panel.cross_sectional_returns_15m(decision_ts)
        else:
            if self.symbol in ("BTCUSDT", "ETHUSDT") and len(fallback_df) >= 30:
                lbl = "BTC/USDT" if self.symbol == "BTCUSDT" else "ETH/USDT"
                self.global_anchor.update_leader(lbl, fallback_df.tail(240), now_ms=decision_ts)
            rets = []
        self.global_anchor.update_directional_breadth_from_returns(rets)
        snapshot = self.global_anchor.snapshot()
        if self.market_panel is not None:
            self.market_panel.global_cache[decision_ts] = (snapshot, self.global_anchor.leaders.copy(), self.global_anchor.breadth.copy())
        return snapshot

    def _compute_fast_screen(self, history: pd.DataFrame) -> dict[str, Any]:
        """Her mumda ~0.4ms içinde ön eleme özelliklerini hesaplar; aday sinyal yoksa ağır
        hacim-profili/VWAP hesabına girmeden mumu atlar."""
        tail = history.tail(120)
        cache_key = ("screen", self.symbol, int(tail["open_time"].iloc[0]), int(tail["open_time"].iloc[-1]))
        cache = self.market_panel.feature_cache if self.market_panel is not None else {}
        if cache_key in cache:
            return cache[cache_key]
        close_arr = tail["close"].to_numpy(dtype=float)
        high_arr = tail["high"].to_numpy(dtype=float)
        low_arr = tail["low"].to_numpy(dtype=float)

        st_dir, atr_val = _fast_supertrend_last(high_arr, low_arr, close_arr, 10, 3.0)
        price = float(close_arr[-1])
        atr_pct = (atr_val / price * 100.0) if price > 0 else 0.0
        ema9 = _ema_last(close_arr[-45:], 9)
        ema21 = _ema_last(close_arr[-80:], 21)
        ema50 = _ema_last(close_arr, 50)
        rsi_val = _rsi_last(close_arr[-60:], 14)

        flow = compute_candle_orderflow(tail)
        core = compute_pdf_core_confluence(tail)
        core["vwap_atr_z"] = core["vwap20_z"]

        # Hızlı trend ivme tahmini (-100..+100):
        fast_ind = 0.0
        if price > ema9 > ema21:
            fast_ind += 22.0
        elif price < ema9 < ema21:
            fast_ind -= 22.0
        fast_ind += 10.0 if price > ema50 else -10.0
        fast_ind += 14.0 * float(st_dir)
        fast_ind += max(-18.0, min(18.0, (rsi_val - 50.0) * 0.75))

        result = {
            "tail": tail,
            "price": price,
            "st_dir": st_dir,
            "atr_pct": atr_pct,
            "ema9": ema9,
            "ema21": ema21,
            "ema50": ema50,
            "rsi": rsi_val,
            "fast_ind": fast_ind,
            "flow": flow,
            "core": core,
        }

        cache[cache_key] = result
        return result

    def _compute_full_features(self, history: pd.DataFrame, decision_ts: int, screen: dict[str, Any] | None = None) -> dict[str, Any]:
        s = screen if screen is not None else self._compute_fast_screen(history)
        tail = s["tail"]
        cache = self.market_panel.feature_cache if self.market_panel is not None else {}
        key = ("indicator", self.symbol, int(tail["open_time"].iloc[0]), decision_ts)
        if key not in cache:
            cache[key] = indicator_score(tail)
        ind = cache[key]
        if self.market_panel is not None:
            mtf = self.market_panel.causal_mtf_cached(self.symbol, history, decision_ts)
        else:
            mtf = causal_mtf_from_5m(history)

        ind_sc = 0.0 if self.disabled_family == "TREND_IND" else float(ind["score"])
        flow = s["flow"]
        flow_sc = 0.0 if self.disabled_family == "VOLUME_FLOW" else float(flow["score"])
        core = s["core"]

        if self.disabled_family == "TREND_IND":
            combined = flow_sc
        elif self.disabled_family == "VOLUME_FLOW":
            combined = ind_sc
        else:
            combined = 0.56 * ind_sc + 0.44 * flow_sc

        return {
            "ind": ind,
            "ind_score": ind_sc,
            "flow": flow,
            "flow_score": flow_sc,
            "combined_score": combined,
            "core": core,
            "mtf": mtf,
            "st_dir": int(s["st_dir"]),
            "rsi": float(s["rsi"]),
            "atr_pct": float(s["atr_pct"]),
            "ema20": float(s["ema21"]),
            "ema50": float(s["ema50"]),
        }

    def evaluate(self, history: pd.DataFrame) -> SignalResult:
        if len(history) < 55:
            return self._hold("filtered", history)

        last = history.iloc[-1]
        decision_ts = int(last["open_time"])
        price = float(last["close"])
        if price <= 0:
            return self._hold("filtered", history)

        # Çıkış sonrası soğuma (zarar sonrası intikam işlemini önlemek için daha uzun bekleme)
        eff_cd = self.cooldown_bars + (2 if self._last_exit_was_loss else 0)
        if decision_ts - self._last_exit_ts < eff_cd * 300_000:
            return self._hold("filtered", history)

        screen = self._compute_fast_screen(history)
        flow_pre = 0.0 if self.disabled_family == "VOLUME_FLOW" else float(screen["flow"]["score"])
        ind_pre = 0.0 if self.disabled_family == "TREND_IND" else float(screen["fast_ind"])
        comb_pre = (
            flow_pre
            if self.disabled_family == "TREND_IND"
            else (ind_pre if self.disabled_family == "VOLUME_FLOW" else 0.55 * ind_pre + 0.45 * flow_pre)
        )

        # Ön eleme: Yeterli ivme yoksa ve tepe aşırı uzaması yoksa ağır indikatör hesabını atla
        vwap_z_pre = float(screen["core"]["vwap_atr_z"])
        maybe_div_short = (
            vwap_z_pre >= 1.25
            and screen["rsi"] >= 58.0
            and price > screen["ema50"]
            and float(screen["flow"]["score"]) <= -6.0
        )
        if abs(comb_pre) < 12.0 and not maybe_div_short:
            return self._hold("filtered", history)

        f = self._compute_full_features(history, decision_ts, screen=screen)
        global_ctx = self._update_global_context(decision_ts, history)

        core = f["core"]
        flow = f["flow"]
        mtf = f["mtf"]
        chop = float(core["choppiness_14"])
        rvol = float(flow["rvol"]) if self.disabled_family != "VOLUME_FLOW" else 1.15
        vwap_z = float(core["vwap_atr_z"])

        # Aday yön ve playbook belirleme
        cand_side: str | None = None
        playbook = "MOMENTUM_BREAKOUT"

        if f["combined_score"] >= self.entry_score_th:
            cand_side = "LONG"
        elif f["combined_score"] <= -self.entry_score_th:
            cand_side = "SHORT"
        elif self.disabled_family != "VOLUME_FLOW" and maybe_div_short:
            if global_ctx is None or global_ctx["global_bias"] != "GLOBAL_BULLISH":
                div = self.regime_sm.detect_bearish_volume_divergence(
                    history.tail(30),
                    price=price,
                    ema20=f["ema20"],
                    rvol=float(flow["rvol"]),
                    rvol_warmed=True,
                    spike_ret_2s=-0.05,
                    flow_snap=flow,
                )
                if div.get("triggered"):
                    cand_side = "SHORT"
                    playbook = "VOLUME_DIVERGENCE_SHORT"

        if cand_side is None:
            return self._hold("filtered", history)

        dir_sign = 1.0 if cand_side == "LONG" else -1.0
        flow_aligned = f["flow_score"] * dir_sign
        ind_aligned = f["ind_score"] * dir_sign

        # Katman 1: Nedensel Çoklu Zaman Dilimi (15m + 1h) uyumu
        mtf_dir = str(mtf["trend"])
        if cand_side == "LONG":
            mtf_aligned = mtf_dir == "BULLISH" or (
                mtf_dir == "MIXED" and (1 if mtf["tf_1h"]["trend"] == "UP" else -1 if mtf["tf_1h"]["trend"] == "DOWN" else 0) > 0 and f["st_dir"] > 0
            )
        else:
            mtf_aligned = mtf_dir == "BEARISH" or (
                mtf_dir == "MIXED" and (1 if mtf["tf_1h"]["trend"] == "UP" else -1 if mtf["tf_1h"]["trend"] == "DOWN" else 0) < 0 and f["st_dir"] < 0
            )

        if self.disabled_family != "TREND_IND":
            st_ok = f["st_dir"] == int(dir_sign)
            rsi_ok = (46.0 <= f["rsi"] <= 74.0) if cand_side == "LONG" else (26.0 <= f["rsi"] <= 56.0 or playbook == "VOLUME_DIVERGENCE_SHORT")
            not_chasing = (vwap_z <= 2.30) if cand_side == "LONG" else (vwap_z >= -2.30)
            if not (st_ok and rsi_ok and not_chasing and mtf_aligned):
                return self._hold("filtered", history)
            if ind_aligned < 8.0 and playbook != "VOLUME_DIVERGENCE_SHORT":
                return self._hold("filtered", history)

        # Katman 2: Gerçek Taker Buy/Sell Hacim & Emir Akışı Kapısı
        if self.disabled_family != "VOLUME_FLOW":
            if playbook != "VOLUME_DIVERGENCE_SHORT":
                if flow_aligned < self.min_flow_aligned or rvol < self.min_rvol:
                    return self._hold("filtered", history)
                if float(flow["cvd_60s"]) * dir_sign <= 0:
                    return self._hold("filtered", history)

        # Katman 3: Küresel BTC+ETH Lider Rejim + Evren Genişliği + Yerel Makro Kapısı
        if self.disabled_family != "LEADER_BREADTH_REGIME":
            macro_info = self.regime_sm.evaluate_macro_regime(
                self.symbol, history,
                adx=float(f["ind"].get("adx", 22.0)),
                choppiness_14=chop, vwap_atr_z=vwap_z,
                rvol=rvol, rvol_warmed=True, mtf_trend=mtf_dir,
            )
            if bool(macro_info["hard_blocked"]):
                return self._hold("macro_block", history)
            if str(macro_info["macro_regime"]) == "BEARISH_CASCADE" and cand_side != "SHORT":
                return self._hold("filtered", history)

            dist_ok, _ = self.regime_sm.check_bearish_distribution_gate(
                side=cand_side, macro_info=macro_info, mtf_trend=mtf_dir,
                flow_score=f["flow_score"], vwap_atr_z=vwap_z
            )
            if not dist_ok:
                return self._hold("filtered", history)

            if global_ctx is not None:
                g_dec = self.global_anchor.evaluate_global_alignment(
                    self.symbol, cand_side,
                    coin_ret_1h_pct=(price / float(history["close"].iloc[-13]) - 1) * 100,
                    flow_score=f["flow_score"], rvol=rvol,
                    mtf_aligned=mtf_aligned, vwap_atr_z=vwap_z, playbook=playbook,
                )
                if not g_dec["allowed"]:
                    return self._hold("leader_block", history)
        else:
            if chop >= 60.5 or f["atr_pct"] < 0.16:
                return self._hold("filtered", history)

        # Katman 4: 10-Ajan 3-Turlu Çapraz Müzakere & Maliyet-Üstü Beklenti Denetimi
        if self.disabled_family != "TEN_AGENT_AUDIT":
            audit_ctx: dict[str, Any] = {
                "symbol": self.symbol,
                "side": cand_side,
                "ind_score": f["ind_score"],
                "flow_score": f["flow_score"],
                "combined_score": f["combined_score"],
                "rvol": max(rvol, 0.9),
                "atr_pct": f["atr_pct"],
                "spread_pct": 0.015,
                "roundtrip_fee_pct": 0.07,
                "choppiness_14": chop,
                "mtf_aligned": mtf_aligned,
                "vwap_atr_z": vwap_z,
                "spot_perp_basis_bps": 3.0,
                "funding_adverse_near": False,
                "playbook": playbook,
            }
            if global_ctx is not None:
                audit_ctx["global_leader_score"] = float(global_ctx["leader_score"])
                audit_ctx["directional_breadth"] = float(global_ctx["breadth"]["net_score"])
            audit = self.ten_agent.evaluate_entry(audit_ctx)
            if not bool(audit["approved"]):
                return self._hold("filtered", history)

        return SignalResult(signal=cand_side, strategy_name=self.NAME,
                            regime=playbook, data_timestamp=decision_ts,
                            notes=[f"score={f['combined_score']:+.1f}"])

    def evaluate_exit(
        self,
        history: pd.DataFrame,
        pos: Any,
        *,
        price: float,
        now_ms: int,
        fee_rate: float = 0.00035,
    ) -> dict[str, Any]:
        """Açık pozisyonda `FlowTrendExitManager` + `TenAgentMutualAuditCouncil` çıkış denetimi."""
        if len(history) < 30:
            return {"should_exit": False}

        s = self._compute_fast_screen(history)
        flow = s["flow"]
        ind_sc = float(s["fast_ind"])
        flow_sc = float(flow["score"])
        comb_sc = 0.56 * ind_sc + 0.44 * flow_sc

        gross_pnl = float(pos.unrealised_pnl(price))
        mfe_usdt = max(float(getattr(pos, "mfe_usdt", 0.0)), gross_pnl)
        notional = float(pos.entry_price) * float(pos.qty_base)
        roundtrip_fee = max(0.30, notional * float(fee_rate) * 2.0)
        age_sec = max(0.0, (int(now_ms) - int(pos.opened_at)) / 1000.0)

        flow_dec = self.exit_mgr.evaluate_open_position(
            side=pos.side,
            age_sec=age_sec,
            gross_pnl_usdt=gross_pnl,
            mfe_usdt=mfe_usdt,
            roundtrip_fee_usdt=roundtrip_fee,
            flow_score=flow_sc,
            ind_score=ind_sc,
            combined_score=comb_sc,
            flow_snap=flow,
            supertrend_dir=int(s["st_dir"]),
            rsi=float(s["rsi"]),
        )
        if bool(flow_dec.get("should_exit", False)):
            self._last_exit_ts = int(now_ms)
            self._last_exit_was_loss = (gross_pnl - roundtrip_fee) < 0.0
            return flow_dec

        if self.disabled_family != "TEN_AGENT_AUDIT":
            ag_dec = self.ten_agent.audit_open_position(
                {
                    "symbol": self.symbol,
                    "side": pos.side,
                    "flow_score": flow_sc,
                    "ind_score": ind_sc,
                    "combined_score": comb_sc,
                    "buy_usdt": float(flow["buy_usdt"]),
                    "sell_usdt": float(flow["sell_usdt"]),
                    "cvd_60s": float(flow["cvd_60s"]),
                    "gross_pnl_usdt": gross_pnl,
                    "mfe_usdt": mfe_usdt,
                    "age_sec": age_sec,
                    "st_dir": int(s["st_dir"]),
                }
            )
            if bool(ag_dec.get("should_exit", False)):
                self._last_exit_ts = int(now_ms)
                self._last_exit_was_loss = (gross_pnl - roundtrip_fee) < 0.0
                return {
                    "should_exit": True,
                    "exit_kind": "TEN_AGENT_FLOW_REVERSAL",
                    "reason": str(ag_dec.get("reason", "10_AJAN_CIKIS")),
                }

        return {"should_exit": False}
