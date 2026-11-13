"""Kripto Bot v9.2 — Tekil Kanonik Strateji, 10-Ajan Çapraz Teftiş, Akım-Takip Çıkışı ve Yürütme Motoru.

v9.2 Mimari Yükseltmeleri:
  1. Tek Kanonik Hat (`UnifiedTradingEngine`): Tüm saf kripto vadeli evren taraması, rejim,
     10-Ajan 3-turlu çapraz teftiş, pasif Maker kuyruk yürütmesi ve ACID SQLite defteri tek omurgadadır.
  2. 10-Ajan Karşılıklı Teftiş Konseyi (`TenAgentMutualAuditCouncil`): On bağımsız müfettiş ajan
     (`Mufettis_01`..`Mufettis_10`) aynı tam görev üzerinde 3 turda birbirlerinin tezlerini ve
     itirazlarını denetler (dış API gerektirmez, paper modda deterministik çalışır).
  3. Akım ve İndikatör Takipli Dinamik Çıkış (`FlowTrendExitManager`): LONG pozisyonda para girişi
     sürdükçe pozisyonu korur, satış başladığında çıkar; SHORT pozisyonda satış baskısı bitip alım
     başladığında çıkar. Kör 135sn zaman kesimi kaldırılmış, gölge (counterfactual) karşılaştırması eklenmiştir.
  4. Karşı-Olgu & Asimetri Analitiği (`CounterfactualTracker`): Engellenen her LONG/SHORT sinyalin
     5dk/15dk ileri getirisi ve gölge 135sn kesim farkı canlı ölçülür.
  5. Fonlama Uzlaşma Yakınlığı (`check_funding_settlement_proximity`), Spot-Perp Basis Kapısı ve
     Veri Gecikmesi / Defter Mutabakat Alarmları (`operational_health_snapshot`).
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any

import pandas as pd

from scanner.ind_aktif import kapali_mum_ekle, metrik
from scanner.universe import STOCK_LIKE_DENYLIST
from scanner.ws_scanner import SpikeDetector

from .commission_optimizer import CommissionOptimizer
from .counterfactual import CounterfactualTracker
from .edge_analytics import compute_edge_separation_report
from .flow_exit_manager import FlowTrendExitManager
from .futures_catalog import NON_CRYPTO_OR_PEGGED_BASES, canonical_underlying_asset
from .indicators import indicator_score, multi_timeframe_filter
from .global_market_regime import GlobalMarketRegimeAnchor, causal_mtf_from_5m
from .llm_referee import LiveLLMReferee
from .moneyflow import MoneyFlow
from .pdf_core_confluence import compute_pdf_core_confluence
from .quant_rule_council import QuantRuleCouncil
from .regime_state_machine import RegimeStateMachine
from .strategy import Strategy
from .ten_agent_debate import TenAgentMutualAuditCouncil
from .win_loss_analyzer import WinLossAnalyzer


ENGINE_VERSION = "9.4.0"
DEFAULT_BREADTH_FADE_THRESHOLD = 0.35
FUNDING_INTERVAL_SEC = 8 * 3600  # 00:00, 08:00, 16:00 UTC


def check_funding_settlement_proximity(
    side: str,
    funding_rate: float,
    now_ts: float | None = None,
    *,
    settlement_ts: float | None = None,
    guard_window_sec: float = 720.0,
    adverse_rate_threshold: float = 0.0002,
) -> dict[str, Any]:
    """8 saatlik fonlama uzlaşmasına yakınken aleyhte fonlama ödemesini önleyen kapı (Denetim 3.8).

    - `funding_rate > 0`: LONG öder, SHORT alır.
    - `funding_rate < 0`: SHORT öder, LONG alır.
    """
    now_s = float(now_ts if now_ts is not None else time.time())
    if settlement_ts is not None and settlement_ts >= now_s:
        sec_to_settle = float(settlement_ts - now_s)
    else:
        rem = now_s % FUNDING_INTERVAL_SEC
        sec_to_settle = float((FUNDING_INTERVAL_SEC - rem) % FUNDING_INTERVAL_SEC)

    u_side = str(side or "").upper()
    rate = float(funding_rate or 0.0)
    adverse_payment_bps = 0.0
    if u_side == "LONG" and rate > 0:
        adverse_payment_bps = rate * 10_000.0
    elif u_side == "SHORT" and rate < 0:
        adverse_payment_bps = abs(rate) * 10_000.0

    blocked = (
        u_side in ("LONG", "SHORT")
        and sec_to_settle <= guard_window_sec
        and (adverse_payment_bps / 10_000.0) >= adverse_rate_threshold
    )
    return {
        "allowed": not blocked,
        "sec_to_settlement": round(sec_to_settle, 1),
        "funding_rate": rate,
        "adverse_payment_bps": round(adverse_payment_bps, 3),
        "reason": (
            f"funding_uzlasma_yakin({sec_to_settle:.0f}s_kala_aleyhte_{adverse_payment_bps:.2f}bps)"
            if blocked
            else "funding_uygun"
        ),
    }


class UnifiedTradingEngine:
    """v9.2 Tekil Kanonik Sinyal, Rejim, 10-Ajan Çapraz Teftiş, Akım-Çıkış ve Yürütme Motoru."""

    def __init__(
        self,
        executor,
        *,
        mode: str = "hybrid_fusion",
        council: QuantRuleCouncil | None = None,
        ten_agent_council: TenAgentMutualAuditCouncil | None = None,
        flow_exit_manager: FlowTrendExitManager | None = None,
        counterfactual: CounterfactualTracker | None = None,
        detector: SpikeDetector | None = None,
        commission_optimizer: CommissionOptimizer | None = None,
        win_loss_analyzer: WinLossAnalyzer | None = None,
        regime_machine: RegimeStateMachine | None = None,
        llm_referee: LiveLLMReferee | None = None,
        breadth_fade_threshold: float = DEFAULT_BREADTH_FADE_THRESHOLD,
        require_vwap_warmup: bool = False,
        cfg: dict[str, Any] | None = None,
    ):
        if mode not in {"shadow_only", "confluence_gate", "hybrid_fusion"}:
            raise ValueError(f"Geçersiz motor modu: {mode}")
        self.version = ENGINE_VERSION
        self.cfg = cfg or {}
        self.executor = executor
        self.mode = mode
        self.breadth_fade_threshold = float(breadth_fade_threshold)
        self.require_vwap_warmup = bool(require_vwap_warmup)
        self.council = council if council is not None else QuantRuleCouncil()

        ten_cfg = self.cfg.get("on_ajan_konseyi", {}) if isinstance(self.cfg, dict) else {}
        self.ten_agent_enabled: bool = (
            ten_agent_council is not None or bool(ten_cfg.get("aktif", False))
        )
        self.ten_agent_council = (
            ten_agent_council
            if ten_agent_council is not None
            else TenAgentMutualAuditCouncil(
                min_consensus_votes=int(ten_cfg.get("min_onay_oyu", 7)),
                min_expected_gross_fee_mult=float(ten_cfg.get("min_brut_maliyet_kati", 3.5)),
            )
        )

        exit_cfg = self.cfg.get("cikis", {}) if isinstance(self.cfg, dict) else {}
        self.flow_exit_enabled: bool = (
            flow_exit_manager is not None or bool(exit_cfg.get("akim_takip_cikisi_aktif", False))
        )
        self.flow_exit_manager = (
            flow_exit_manager
            if flow_exit_manager is not None
            else FlowTrendExitManager(
                min_reversal_profit_usdt=float(exit_cfg.get("min_donus_kar_usdt", 1.10)),
            )
        )
        self.counterfactual = (
            counterfactual if counterfactual is not None else CounterfactualTracker()
        )

        self.global_anchor = GlobalMarketRegimeAnchor()
        self.detector = detector if detector is not None else SpikeDetector(baglam_aktif=True)
        self.detector.ind_aktif = True
        self.commission_optimizer = (
            commission_optimizer
            if commission_optimizer is not None
            else CommissionOptimizer(max_entry_spread_pct=0.08)
        )
        self.win_loss_analyzer = (
            win_loss_analyzer if win_loss_analyzer is not None else WinLossAnalyzer()
        )
        self.regime_machine = (
            regime_machine
            if regime_machine is not None
            else RegimeStateMachine(breadth_min_ratio=self.breadth_fade_threshold)
        )
        self.llm_referee = llm_referee if llm_referee is not None else LiveLLMReferee()
        self._last_processed_trade_id: int = 0
        self._last_breadth_update_ms: int = 0
        self._last_feed_ts: float = time.time()
        self.spot_perp_basis_bps: dict[str, float] = {}
        self.max_spot_perp_basis_bps: float = float(
            (self.cfg.get("cift_borsa") or {}).get("max_spot_perp_basis_bps", 25.0)
            if isinstance(self.cfg, dict)
            else 25.0
        )
        self.flows: dict[str, MoneyFlow] = {}
        self.metrics = {
            "ticks_processed": 0,
            "universe_ticks_processed": 0,
            "candles_ingested": 0,
            "signals_evaluated": 0,
            "regime_blocks": 0,
            "bearish_long_blocks": 0,
            "volume_divergence_triggers": 0,
            "breadth_blocks": 0,
            "warmup_blocks": 0,
            "basis_divergence_blocks": 0,
            "funding_proximity_blocks": 0,
            "council_vetoes": 0,
            "ten_agent_vetoes": 0,
            "llm_referee_vetoes": 0,
            "commission_blocks": 0,
            "win_loss_trap_blocks": 0,
            "flow_trend_exits": 0,
            "shadow_legacy_135s_tags": 0,
            "stagnant_cuts": 0,
            "v4_vwap_atr_blocks": 0,
            "maker_unfilled_skips": 0,
            "entries_routed": 0,
        }

    @staticmethod
    def filter_pure_crypto_symbols(symbols: list[str]) -> list[str]:
        """STOCK_LIKE_DENYLIST + NON_CRYPTO_OR_PEGGED_BASES birleşik %100 saf kripto filtresi."""
        blocked = STOCK_LIKE_DENYLIST | NON_CRYPTO_OR_PEGGED_BASES
        keep: list[str] = []
        for sym in symbols:
            raw = str(sym or "").strip().upper()
            if not raw:
                continue
            base = raw.split("/")[0].split("-")[0]
            if base.endswith("USDT") and len(base) > 4:
                base = base[:-4]
            canon = canonical_underlying_asset(base)
            if base in blocked or canon in blocked or base in {
                "USDT",
                "USDC",
                "FDUSD",
                "DAI",
                "TUSD",
                "USDE",
            }:
                continue
            keep.append(sym)
        return keep

    def set_spot_perp_basis(self, symbol: str, perp_mid: float, spot_mid: float) -> float:
        """Spot-Perp basis farkını (bps) kaydeder (Denetim 2.c & 3.5)."""
        if perp_mid > 0 and spot_mid > 0:
            bps = (float(perp_mid) - float(spot_mid)) / float(spot_mid) * 10_000.0
            self.spot_perp_basis_bps[symbol] = round(bps, 3)
            return bps
        return 0.0

    def flow_for(self, symbol: str) -> MoneyFlow:
        flow = self.flows.get(symbol)
        if flow is None:
            flow = MoneyFlow(symbol, window_sec=300, compact_history=True)
            self.flows[symbol] = flow
        return flow

    def ingest_universe_price(
        self,
        exchange: str,
        symbol: str,
        price: float,
        ts_ms: int | None = None,
    ) -> None:
        """Tüm saf kripto evreninden (~545+ sembol) anlık fiyatları genişlik ve karşı-olgu ölçerine besler."""
        if not (math.isfinite(price) and price > 0):
            return
        now_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
        self._last_feed_ts = now_ms / 1000.0
        d = self.detector.durum(exchange, symbol)
        d.fiyatlar.append((now_ms, float(price)))
        d.son_fiyat = float(price)
        d.son_fiyat_ts = now_ms
        self.counterfactual.on_price_update(symbol, float(price), now_ts=now_ms / 1000.0)
        self.metrics["universe_ticks_processed"] += 1

    def update_universe_breadth(self, now_ms: int | None = None) -> float:
        """Canlı piyasa genişliğini (`genislik_oran`) günceller ve döndürür."""
        ts = int(now_ms if now_ms is not None else time.time() * 1000)
        if ts - self._last_breadth_update_ms >= 500 or self._last_breadth_update_ms == 0:
            self.detector.genislik_guncelle()
            self._last_breadth_update_ms = ts
        return float(self.detector.genislik_oran or 0.0)

    def ingest_closed_1m_candle(
        self,
        exchange: str,
        symbol: str,
        minute_id: int,
        open_px: float,
        high_px: float,
        low_px: float,
        close_px: float,
        base_vol: float,
        quote_vol: float | None = None,
        *,
        mirror_exchanges: bool = True,
    ) -> bool:
        """60dk VWAP60/ATR14 + 35dk bağlam/RVOL önbelleğini sıfır ölü zamanla besler."""
        mid = int(minute_id)
        c_px = float(close_px)
        qv = float(quote_vol) if quote_vol is not None else c_px * float(base_vol)
        targets = ("binance", "okx") if mirror_exchanges else (str(exchange),)
        any_ok = False
        for ex_key in targets:
            d = self.detector.durum(ex_key, symbol)
            ok = kapali_mum_ekle(
                d, mid, float(high_px), float(low_px), c_px, float(base_vol), qv
            )
            if ok:
                any_ok = True
                if not d.dakika_hacim or d.dakika_hacim[-1][0] < mid:
                    d.dakika_hacim.append((mid, qv))
                    d.dakika_kapanis.append((mid, c_px))
                elif d.dakika_hacim[-1][0] == mid:
                    d.dakika_hacim[-1] = (mid, qv)
                    if d.dakika_kapanis and d.dakika_kapanis[-1][0] == mid:
                        d.dakika_kapanis[-1] = (mid, c_px)
                d.dakika_id = max(d.dakika_id, mid)
                if d.son_fiyat <= 0 and c_px > 0:
                    d.son_fiyat = c_px
        if any_ok:
            self.metrics["candles_ingested"] += 1
        return any_ok

    def compute_v4_vwap_metrics(
        self,
        exchange: str,
        symbol: str,
        price: float,
        now_ms: int | None = None,
        *,
        rollover_grace_ms: int = 25_000,
    ) -> dict[str, Any] | None:
        """Dakika dönüşlerinde (`XX:XX:00..25`) REST gecikmesi yüzünden `None`/`0.0` düşmesini önler."""
        simdi_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        for ex_try in (exchange, "binance", "okx"):
            d_try = self.detector.durum(ex_try, symbol)
            raw = metrik(d_try, simdi_ms, price)
            if raw is None:
                into_min_ms = simdi_ms % 60_000
                if into_min_ms <= rollover_grace_ms:
                    prev_boundary_ms = (simdi_ms // 60_000 - 1) * 60_000 + 59_000
                    raw = metrik(d_try, prev_boundary_ms, price)
            if raw is not None:
                vwap_val = float(raw["vwap"])
                atr_pct_val = float(raw["atr_pct"])
                atr14_val = float(price) * atr_pct_val / 100.0
                vwap_z_val = ((float(price) - vwap_val) / atr14_val) if atr14_val > 0 else 0.0
                return {
                    **raw,
                    "vwap60": vwap_val,
                    "atr14": atr14_val,
                    "atr_pct": atr_pct_val,
                    "vwap_z": vwap_z_val,
                    "rvol_warmed": len(d_try.dakika_hacim) >= 15,
                }
        return None

    async def on_trade(
        self,
        exchange: str,
        symbol: str,
        price: float,
        qty: float,
        *,
        is_buyer_maker: bool,
        ts_ms: int | None = None,
    ) -> dict[str, Any] | None:
        """Canlı işlemi MoneyFlow, Pasif Maker Kuyruk Simülatörü, SpikeDetector ve Executor tick'ine besler."""
        if not (math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0):
            return None
        now_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
        now_s = now_ms / 1000.0
        self._last_feed_ts = now_s
        self.metrics["ticks_processed"] += 1

        broker = getattr(self.executor, "broker", None)
        if broker is not None and hasattr(broker, "feed_live_trade_to_maker_queue"):
            broker.feed_live_trade_to_maker_queue(
                exchange, symbol, price, qty, bool(is_buyer_maker), ts=now_s
            )

        flow = self.flow_for(symbol)
        flow.add_trade(price, qty, is_buyer_maker=bool(is_buyer_maker), ts=now_s)
        self.counterfactual.on_price_update(symbol, price, now_ts=now_s)

        d = self.detector.durum(exchange, symbol)
        prev_cum = float(getattr(d, "_v8_cum_qv", 0.0)) + price * qty
        d._v8_cum_qv = prev_cum
        self.detector.besle_hacim_kumulatif(exchange, symbol, prev_cum, now_ms)
        spike_sig = self.detector.besle_fiyat(exchange, symbol, price, 0.0, now_ms)
        self.update_universe_breadth(now_ms)

        try:
            await self.executor.on_price_tick(symbol, price, exchange=exchange)
        except TypeError:
            await self.executor.on_price_tick(symbol, price)
        return {"spike": spike_sig.etiket if spike_sig else None, "rvol": d.rvol}

    def _record_block(
        self,
        symbol: str,
        side: str,
        gate: str,
        reason: str,
        price: float,
        now_ms: int,
    ) -> None:
        if side in ("LONG", "SHORT"):
            self.counterfactual.record_blocked_signal(
                gate=gate,
                symbol=symbol,
                side=side,
                price=price,
                reason=reason,
                now_ts=now_ms / 1000.0,
            )

    async def evaluate_and_route(
        self,
        exchange: str,
        symbol: str,
        ohlcv_5m: pd.DataFrame,
        *,
        ohlcv_15m: pd.DataFrame | None = None,
        ohlcv_1h: pd.DataFrame | None = None,
        news_score: float = 0.0,
        ml_score: float = 0.0,
        spread_pct: float = 0.02,
        funding_rate: float = 0.0,
        settlement_ts: float | None = None,
        now_ms: int | None = None,
        allow_new_entries: bool = True,
        mark_price: float | None = None,
    ) -> dict[str, Any]:
        """v9.2 Tekil Kanonik Karar, 10-Ajan Çapraz Teftiş, Akım Çıkış & Yürütme Hattı."""
        if self.cfg.get("v94", {}).get("enabled", False):
            from .v94_live_router import V94LiveRouter
            from .adaptive_policy import AdaptivePolicy
            if not hasattr(self, "v94_router"):
                self.v94_router = V94LiveRouter(self, AdaptivePolicy(**self.cfg["v94"].get("policy", {})))
            self.metrics["signals_evaluated"] += 1
            return await self.v94_router.evaluate(exchange, symbol, ohlcv_5m,
                mark_price=mark_price, spread_pct=spread_pct,
                now_ms=int(now_ms if now_ms is not None else time.time()*1000),
                allow_new_entries=allow_new_entries)
        self.metrics["signals_evaluated"] += 1
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        now_sec = now_ms / 1000.0
        price = float(ohlcv_5m["close"].iloc[-1])
        self.counterfactual.on_price_update(symbol, price, now_ts=now_sec)

        ind_res = indicator_score(ohlcv_5m)
        ind_val = float(ind_res.get("score", 0.0))

        # 1) 14-mum 5m True Range ATR ve son 6 mumluk swing noktaları
        atr_5m = float(ind_res.get("atr") or (ind_res.get("details") or {}).get("atr") or 0.0)
        if atr_5m <= 0 and {"high", "low", "close"}.issubset(ohlcv_5m.columns) and len(ohlcv_5m) >= 15:
            h_arr = ohlcv_5m["high"].iloc[-15:].astype(float).to_numpy()
            l_arr = ohlcv_5m["low"].iloc[-15:].astype(float).to_numpy()
            c_arr = ohlcv_5m["close"].iloc[-15:].astype(float).to_numpy()
            tr_arr = [
                max(h_arr[k] - l_arr[k], abs(h_arr[k] - c_arr[k - 1]), abs(l_arr[k] - c_arr[k - 1]))
                for k in range(1, len(c_arr))
            ]
            if tr_arr:
                atr_5m = float(sum(tr_arr) / len(tr_arr))
        if atr_5m > 0:
            self.executor.set_atr(symbol, atr_5m)
        sw_low: float | None = None
        sw_high: float | None = None
        if "low" in ohlcv_5m.columns and "high" in ohlcv_5m.columns and len(ohlcv_5m) >= 8:
            sw_low = float(ohlcv_5m["low"].iloc[-7:-1].min())
            sw_high = float(ohlcv_5m["high"].iloc[-7:-1].max())
            if hasattr(self.executor, "set_market_structure"):
                self.executor.set_market_structure(symbol, sw_low, sw_high)
            elif hasattr(self.executor, "_structure"):
                self.executor._structure[symbol] = {"swing_low": sw_low, "swing_high": sw_high}

        # 2) Çekirdek Uyum Metrikleri (Choppiness, BOS, VWAP20_Z)
        pdf_core = compute_pdf_core_confluence(ohlcv_5m)
        flow_snap = self.flow_for(symbol).snapshot(include_vpvr=False)
        flow_val = float(flow_snap.get("score", 0.0))

        # 3) 60dk VWAP60 + Wilder ATR14
        d_v4 = self.detector.durum(exchange, symbol)
        raw_v4 = self.compute_v4_vwap_metrics(exchange, symbol, price, now_ms)
        v4_60m = None
        vwap_atr_z = 0.0
        v4_boost = 0.0
        if raw_v4 is not None:
            atr14 = price * float(raw_v4["atr_pct"]) / 100.0
            v4_60m = {
                "vwap60": float(raw_v4["vwap"]),
                "atr14": atr14,
                "atr_pct": float(raw_v4["atr_pct"]),
                "kapanis_dk": int(raw_v4["kapanis_dk"]),
            }
            if atr14 > 0:
                vwap_atr_z = (price - v4_60m["vwap60"]) / atr14
                if 0.15 <= abs(vwap_atr_z) <= 2.8:
                    v4_boost = math.copysign(min(10.0, abs(vwap_atr_z) * 4.5), vwap_atr_z)
        else:
            vwap_atr_z = float(pdf_core.get("vwap20_z", 0.0))

        dk_hist = list(getattr(d_v4, "dakika_hacim", ()))
        med_qv = (
            statistics.median([q for _, q in dk_hist[-35:] if q > 0])
            if len(dk_hist) >= 5
            else 250_000.0
        )
        raw_rvol = float(d_v4.rvol or 0.0)
        flow_1m_qv = (float(flow_snap.get("buy_usdt", 0.0)) + float(flow_snap.get("sell_usdt", 0.0))) / 5.0
        if len(dk_hist) >= 6 and med_qv > 0:
            recent_qv = max(statistics.mean([q for _, q in dk_hist[-2:]]), flow_1m_qv)
            raw_rvol = max(raw_rvol, recent_qv / med_qv)
        rvol_warmed = raw_rvol > 0.0 and len(dk_hist) >= 5
        eff_rvol = raw_rvol if rvol_warmed else 1.0

        atr_pct_val = (
            float(v4_60m["atr_pct"])
            if v4_60m and v4_60m.get("atr_pct", 0.0) > 0
            else ((atr_5m / price * 100.0) if (atr_5m > 0 and price > 0) else 0.45)
        )
        broker = getattr(self.executor, "broker", None)
        if broker is not None and hasattr(broker, "symbol_volatility_meta"):
            broker.symbol_volatility_meta[symbol] = {
                "atr_pct": atr_pct_val,
                "minute_qv_usdt": float(med_qv),
            }

        # 4) MTF + Rejim Durum Makinesi + Makro Ortam
        mtf_info: dict[str, Any] | None = None
        mtf_trend_str = "NEUTRAL"
        mtf_info = causal_mtf_from_5m(ohlcv_5m)
        mtf_trend_str = str(mtf_info.get("trend") or "NEUTRAL").upper()
        self.global_anchor.update_leader(symbol, ohlcv_5m, now_ms=now_ms)
        global_ctx = self.global_anchor.snapshot()
        regime_global = global_ctx

        bar_id = int(ohlcv_5m["ts"].iloc[-1]) if "ts" in ohlcv_5m.columns else len(ohlcv_5m)
        raw_regime = str(ind_res.get("regime") or "TREND")
        adx_val = float(ind_res.get("adx") or (25.0 if raw_regime == "TREND" else 16.0))
        regime_snap = self.regime_machine.update(
            symbol,
            raw_regime=raw_regime,
            adx=adx_val,
            bar_id=bar_id,
            rvol=eff_rvol,
        )
        confirmed_regime = regime_snap["confirmed_regime"]
        chop_14 = float(pdf_core.get("choppiness_14", 50.0))

        macro_info = self.regime_machine.evaluate_macro_regime(
            symbol,
            ohlcv_5m,
            adx=adx_val,
            choppiness_14=chop_14,
            vwap_atr_z=vwap_atr_z,
            rvol=eff_rvol,
            rvol_warmed=rvol_warmed,
            mtf_trend=mtf_trend_str,
        )
        regime_snap["macro_regime"] = macro_info["macro_regime"]
        regime_snap["volume_declining"] = macro_info["volume_declining"]
        regime_snap["vol_ratio_5m"] = macro_info["vol_ratio_5m"]

        effective_ind = ind_val + (
            (v4_boost + float(pdf_core.get("score_delta", 0.0)))
            if self.mode == "hybrid_fusion"
            else 0.0
        )
        effective_ind = max(-100.0, min(100.0, effective_ind))

        strat: Strategy = self.executor.strategy
        combined = strat.combine(
            effective_ind,
            flow_val,
            news_score,
            ml_score,
            market_context={
                "regime_aware": False,
                "cvd_divergence": flow_snap.get("cvd_divergence", "NONE"),
                "absorption": flow_snap.get("absorption", "YOK"),
            },
        )
        side = str(combined.get("signal", "BEKLE"))

        # 4b) Hacim Uyumsuzluğu (`VOLUME_DIVERGENCE_SHORT`)
        vol_div_cfg = self.cfg.get("hacim_uyumsuzlugu", {}) if isinstance(self.cfg, dict) else {}
        vol_div = self.regime_machine.detect_bearish_volume_divergence(
            ohlcv_5m,
            price=price,
            ema20=float(macro_info.get("ema20", price)),
            rvol=eff_rvol,
            rvol_warmed=rvol_warmed,
            spike_ret_2s=float(getattr(d_v4, "ret_2s", 0.0) or 0.0),
            flow_snap=flow_snap,
            cfg_div=vol_div_cfg,
        )
        if vol_div.get("triggered") and not (
            price > float(macro_info.get("ema50", price))
            and vwap_atr_z >= 1.25
            and float(ind_res.get("snapshot", {}).get("rsi", 50.0)) >= 58.0
            and mtf_trend_str != "BULLISH"
            and global_ctx["global_bias"] != "GLOBAL_BULLISH"
        ):
            vol_div = {"triggered": False}
        if vol_div.get("triggered") and macro_info["macro_regime"] != "CRASH_RISK_OFF":
            self.metrics["volume_divergence_triggers"] += 1
            side = "SHORT"
            div_floor = float(vol_div_cfg.get("agresif_short_skor_tabani", -26.5))
            combined["signal"] = "SHORT"
            combined["total"] = min(float(combined.get("total", 0.0)), div_floor)
            div_sw_high = float(vol_div["swing_high"])
            sw_high = div_sw_high
            if hasattr(self.executor, "set_market_structure") and sw_low is not None:
                self.executor.set_market_structure(symbol, sw_low, div_sw_high)

        # 5) Açık pozisyon varsa: akım + indikatör takip çıkışı, gölge 135sn karşı-olgu ve 10-ajan teftişi
        self.sync_closed_trade_feedback()
        pos_mark_px = price
        if symbol in self.executor.positions:
            pos_ref = self.executor.positions[symbol]
            pos_ex_k = str(getattr(pos_ref, "exchange", "") or "").strip().lower()
            vpx_map = getattr(self.executor, "last_venue_prices", {})
            if pos_ex_k and (pos_ex_k, symbol) in vpx_map:
                pos_mark_px = float(vpx_map[(pos_ex_k, symbol)])

        if symbol in self.executor.positions and self.mode != "shadow_only":
            if getattr(broker, "paper_funding_enabled", False):
                try:
                    self.executor.apply_funding(
                        symbol, funding_rate, pos_mark_px, enabled=True, settlement_ts=settlement_ts
                    )
                except Exception:
                    pass
            await self.executor.maybe_orderflow_exit(symbol, pos_mark_px, flow_snap)

        if symbol in self.executor.positions:
            pos_open = self.executor.positions[symbol]
            raw_opened = getattr(pos_open, "opened_at", "")
            opened_ts = 0.0
            if isinstance(raw_opened, (int, float)):
                opened_ts = float(raw_opened)
            elif isinstance(raw_opened, str) and raw_opened.strip():
                from datetime import datetime, timezone

                try:
                    dt = datetime.strptime(raw_opened.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                    opened_ts = dt.timestamp()
                except Exception:
                    opened_ts = 0.0
            age_sec = max(0.0, now_sec - opened_ts) if opened_ts > 0 else 0.0
            cur_gross = float(self.executor.risk.pnl_usdt(pos_open, pos_mark_px))
            mfe_val = float(getattr(pos_open, "mfe_usdt", 0.0))
            flow_against = (pos_open.side == "LONG" and flow_val < -18.0) or (
                pos_open.side == "SHORT" and flow_val > 18.0
            )
            stag = self.win_loss_analyzer.evaluate_stagnant_loser(
                age_sec=age_sec,
                mfe_usdt=mfe_val,
                current_gross_pnl_usdt=cur_gross,
                flow_against_position=flow_against,
            )

            if self.flow_exit_enabled:
                pos_id = f"{symbol}:{getattr(pos_open, 'opened_at', '')}"
                if stag["should_cut"]:
                    self.counterfactual.record_shadow_legacy_time_cut(
                        position_id=pos_id,
                        symbol=symbol,
                        side=pos_open.side,
                        entry_price=float(pos_open.entry),
                        shadow_cut_price=pos_mark_px,
                        qty=float(pos_open.qty),
                        entry_fee_usdt=float(getattr(pos_open, "entry_fee_usdt", 0.10)),
                        age_sec=age_sec,
                        now_ts=now_sec,
                    )
                    self.metrics["shadow_legacy_135s_tags"] += 1

                open_audit = None
                if self.ten_agent_enabled:
                    open_audit = self.ten_agent_council.audit_open_position(
                        {
                            "symbol": symbol,
                            "side": pos_open.side,
                            "gross_pnl_usdt": cur_gross,
                            "mfe_usdt": mfe_val,
                            "flow_score": flow_val,
                            "ind_score": effective_ind,
                            "combined_score": float(combined.get("total", 0.0)),
                            "buy_usdt": float(flow_snap.get("buy_usdt", 0.0)),
                            "sell_usdt": float(flow_snap.get("sell_usdt", 0.0)),
                            "cvd_60s": float(flow_snap.get("cvd_60s", 0.0)),
                            "age_sec": age_sec,
                            "st_dir": ind_res.get("snapshot", {}).get("supertrend_direction"),
                        }
                    )

                est_rt_fee = float(getattr(pos_open, "margin_usdt", 50.0)) * float(
                    getattr(pos_open, "leverage", 10.0)
                ) * 0.0007
                flow_decision = self.flow_exit_manager.evaluate_open_position(
                    side=pos_open.side,
                    gross_pnl_usdt=cur_gross,
                    mfe_usdt=mfe_val,
                    roundtrip_fee_usdt=est_rt_fee,
                    age_sec=age_sec,
                    ind_score=effective_ind,
                    flow_score=flow_val,
                    combined_score=float(combined.get("total", 0.0)),
                    flow_snap=flow_snap,
                    ten_agent_audit=open_audit,
                    supertrend_dir=ind_res.get("snapshot", {}).get("supertrend_direction"),
                    rsi=ind_res.get("snapshot", {}).get("rsi"),
                )
                if flow_decision["should_exit"] and self.mode != "shadow_only":
                    closed_ok = await self.executor.close_position(
                        symbol, pos_mark_px, str(flow_decision["reason"])
                    )
                    if closed_ok:
                        self.metrics["flow_trend_exits"] += 1
                        self.sync_closed_trade_feedback()
            else:
                if stag["should_cut"] and self.mode != "shadow_only":
                    closed_ok = await self.executor.close_position(symbol, pos_mark_px, stag["reason"])
                    if closed_ok:
                        self.metrics["stagnant_cuts"] += 1
                        self.sync_closed_trade_feedback()

        # 6) Doğal Kapanış / Drain Modu
        if not allow_new_entries:
            if symbol in self.executor.positions:
                pos_cur = self.executor.positions[symbol]
                pos_ex_d = str(getattr(pos_cur, "exchange", "") or "").strip().lower() or None
                try:
                    await self.executor.on_price_tick(symbol, pos_mark_px, exchange=pos_ex_d)
                except TypeError:
                    await self.executor.on_price_tick(symbol, pos_mark_px)
                if symbol in self.executor.positions and self.mode != "shadow_only":
                    tot_sc = float(combined.get("total", 0.0))
                    rev_long = pos_cur.side == "LONG" and side == "SHORT" and tot_sc <= -22.0
                    rev_short = pos_cur.side == "SHORT" and side == "LONG" and tot_sc >= 22.0
                    if rev_long or rev_short:
                        await self.executor.close_position(
                            symbol, pos_mark_px, f"TERS SİNYAL DOĞAL ÇIKIŞ ({tot_sc:+.1f})"
                        )
                        self.sync_closed_trade_feedback()
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "yeni_giris_durduruldu_acik_pozisyon_bekleniyor",
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        # Zorunlu 60dk VWAP ısınma kilidi
        if side in ("LONG", "SHORT") and self.require_vwap_warmup and raw_v4 is None:
            self.metrics["warmup_blocks"] += 1
            self._record_block(symbol, side, "vwap_warmup_gate", "v4_vwap60_isinmadi_giris_kilitli", price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "v4_vwap60_isinmadi_giris_kilitli",
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": None,
                "flow": flow_snap,
            }

        # 6a) Spot-Perp Basis Sapma Kapısı (Denetim 2.c & 3.5)
        basis_bps = float(self.spot_perp_basis_bps.get(symbol, 0.0))
        if side in ("LONG", "SHORT") and abs(basis_bps) > self.max_spot_perp_basis_bps:
            self.metrics["basis_divergence_blocks"] += 1
            rsn = f"spot_perp_basis_sapmasi({basis_bps:+.1f}bps>{self.max_spot_perp_basis_bps:.1f}bps)"
            self._record_block(symbol, side, "spot_perp_basis_gate", rsn, price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": rsn,
                "spot_perp_basis_bps": basis_bps,
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        # 6a-2) Fonlama Uzlaşma Yakınlığı Kapısı (Denetim 3.8)
        if side in ("LONG", "SHORT") and abs(float(funding_rate or 0.0)) > 0.0:
            fund_prox = check_funding_settlement_proximity(
                side=side,
                funding_rate=funding_rate,
                now_ts=now_sec,
                settlement_ts=settlement_ts,
            )
            if not fund_prox["allowed"]:
                self.metrics["funding_proximity_blocks"] += 1
                self._record_block(
                    symbol, side, "funding_proximity_gate", fund_prox["reason"], price, now_ms
                )
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": fund_prox["reason"],
                    "funding_proximity": fund_prox,
                    "regime": regime_snap,
                    "pdf_core": pdf_core,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

        # 6b) Çöküş (`CRASH_RISK_OFF`) ve Testere/Yatay (`CHOPPY_RANGE`) %100 Sert Sinyal Engeli
        if side in ("LONG", "SHORT") and macro_info["hard_blocked"] and not vol_div.get("triggered"):
            self.metrics["regime_blocks"] += 1
            self._record_block(symbol, side, "macro_regime_gate", macro_info["reason"], price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": macro_info["reason"],
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        # 6c) Ayı Trendi / Yatay Dağıtım + Azalan Hacim Filtresi -> LONG Engeli
        if side in ("LONG", "SHORT"):
            bd_ok, bd_reason = self.regime_machine.check_bearish_distribution_gate(
                side=side, macro_info=macro_info, mtf_trend=mtf_trend_str,
                flow_score=flow_val, vwap_atr_z=vwap_atr_z
            )
            if not bd_ok:
                self.metrics["bearish_long_blocks"] += 1
                self._record_block(symbol, side, "bearish_distribution_gate", bd_reason, price, now_ms)
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": bd_reason,
                    "regime": regime_snap,
                    "pdf_core": pdf_core,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

        # 7) Canlı Piyasa Genişliği & Playbook Seçimi
        live_breadth = self.update_universe_breadth(now_ms)
        has_universe_window = any(len(d.fiyatlar) >= 2 for d in self.detector.durumlar.values())
        breadth_ratio = live_breadth if has_universe_window else 0.40

        if vol_div.get("triggered") and side == "SHORT":
            playbook_info = {
                "allowed": True,
                "playbook": "VOLUME_DIVERGENCE_SHORT",
                "regime": confirmed_regime,
                "transition": regime_snap.get("transition", "NONE"),
                "reason": vol_div["reason"],
            }
        else:
            playbook_info = self.regime_machine.select_strategy_playbook(
                symbol,
                side=side,
                vwap_atr_z=vwap_atr_z,
                breadth_ratio=breadth_ratio,
                rvol=eff_rvol,
                flow_score=flow_val,
                rvol_warmed=rvol_warmed,
            )
        if side in ("LONG", "SHORT") and not playbook_info["allowed"]:
            self.metrics["breadth_blocks"] += 1
            self._record_block(symbol, side, "breadth_playbook_gate", playbook_info["reason"], price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": playbook_info["reason"],
                "playbook": playbook_info["playbook"],
                "breadth_ratio": round(breadth_ratio, 4),
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        mtf_aligned = True
        if side in ("LONG", "SHORT") and mtf_info is not None:
            if (side == "LONG" and mtf_trend_str == "BEARISH") or (
                side == "SHORT" and mtf_trend_str == "BULLISH"
            ):
                mtf_aligned = False

        global_dec = self.global_anchor.evaluate_global_alignment(
            symbol, side, coin_ret_1h_pct=float(macro_info.get("ret_1h_pct", 0.0)),
            rvol=eff_rvol, mtf_aligned=mtf_aligned, flow_score=flow_val,
            vwap_atr_z=vwap_atr_z, playbook=playbook_info["playbook"],
        )
        regime_snap["global_market"] = global_dec
        if side in ("LONG", "SHORT") and not global_dec["allowed"]:
            self._record_block(symbol, side, "global_leader_breadth_gate", global_dec["reason"], price, now_ms)
            return {"symbol": symbol, "signal": "BEKLE", "raw_signal": side,
                    "routed": False, "reason": global_dec["reason"], "regime": regime_snap}

        if (side == "LONG" and vwap_atr_z > 3.8) or (side == "SHORT" and vwap_atr_z < -3.8):
            self.metrics["v4_vwap_atr_blocks"] += 1
            rsn = f"v4_vwap60_asiri_uzama(z={vwap_atr_z:+.2f})"
            self._record_block(symbol, side, "vwap_overextension_gate", rsn, price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": rsn,
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        stop_dist_pct = float(self.executor.risk.effective_stop_pct(self.executor.risk.leverage))
        whale_net = float(flow_snap.get("whale_buy_usdt", 0.0)) - float(flow_snap.get("whale_sell_usdt", 0.0))
        same_side_cnt = sum(1 for p in self.executor.positions.values() if p.side == side)
        cb_obj = getattr(self.executor, "circuit_breaker", None)

        # 8) 10-Kural Kantitatif Jüri (`QuantRuleCouncil`)
        council_report = self.council.evaluate_signal(
            {
                "symbol": symbol,
                "side": side,
                "price": price,
                "ind_score": effective_ind,
                "flow_score": flow_val,
                "combined_total": float(combined.get("total", 0.0)),
                "rvol": eff_rvol,
                "rvol_warmed": rvol_warmed,
                "whale_net_usdt": whale_net,
                "vwap_atr_z": vwap_atr_z,
                "atr_pct": atr_pct_val,
                "mtf_aligned": mtf_aligned,
                "spread_pct": spread_pct,
                "max_allowed_spread_pct": self.commission_optimizer.max_entry_spread_pct,
                "smart_maker_execution": bool(getattr(broker, "smart_maker_execution", True)),
                "max_slippage_pct": float(self.executor.risk.max_slippage_pct),
                "stop_distance_pct": stop_dist_pct,
                "leverage": float(self.executor.risk.leverage),
                "cvd_divergence": flow_snap.get("cvd_divergence", "NONE"),
                "absorption": flow_snap.get("absorption", "YOK"),
                "orderbook_imbalance": float(flow_snap.get("imbalance", 0.0)),
                "same_side_open_count": same_side_cnt,
                "max_same_side_positions": int(getattr(self.executor.risk, "max_same_side_positions", 1000)),
                "breadth_ratio": breadth_ratio,
                "breadth_min_ratio": self.breadth_fade_threshold,
                "playbook": playbook_info["playbook"],
                "funding_rate": funding_rate,
                "paper_recovery_locked": bool(self.executor.paper_recovery_locked),
                "circuit_breaker_tripped": bool(getattr(cb_obj, "tripped", False)),
                "regime": confirmed_regime,
            }
        )

        if side in ("LONG", "SHORT") and not council_report["approved"]:
            self.metrics["council_vetoes"] += 1
            self._record_block(symbol, side, "quant_rule_council", council_report["reason"], price, now_ms)
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": council_report["reason"],
                "council": council_report,
                "regime": regime_snap,
                "pdf_core": pdf_core,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        # 8b) 10-Ajan Karşılıklı Çapraz Teftiş Konseyi (`TenAgentMutualAuditCouncil`)
        ten_agent_report: dict[str, Any] | None = None
        if side in ("LONG", "SHORT") and self.ten_agent_enabled:
            paper_acc = getattr(broker, "paper", None)
            vault_eq = float(getattr(paper_acc, "balance", 1000.0) if paper_acc is not None else 1000.0)
            used_m = sum(float(getattr(p, "margin_usdt", 50.0)) for p in self.executor.positions.values())
            ten_agent_report = self.ten_agent_council.evaluate_entry(
                {
                    "symbol": symbol,
                    "side": side,
                    "exchange": exchange,
                    "price": price,
                    "ind_score": effective_ind,
                    "flow_score": flow_val,
                    "combined_score": float(combined.get("total", 0.0)),
                    "playbook": playbook_info["playbook"],
                    "rvol": eff_rvol,
                    "atr_pct": atr_pct_val,
                    "spread_pct": spread_pct,
                    "choppiness_14": chop_14,
                    "adx": adx_val,
                    "macro_regime": macro_info["macro_regime"],
                    "volume_declining": macro_info["volume_declining"],
                    "global_leader_score": global_ctx["leader_score"],
                    "directional_breadth": global_ctx["breadth"]["net_score"],
                    "mtf_aligned": mtf_aligned,
                    "vwap_atr_z": vwap_atr_z,
                    "cvd_divergence": flow_snap.get("cvd_divergence", "NONE"),
                    "absorption": flow_snap.get("absorption", "YOK"),
                    "funding_rate": funding_rate,
                    "spot_perp_basis_bps": basis_bps,
                    "free_margin_usdt": max(0.0, vault_eq - used_m),
                    "required_margin_usdt": float(getattr(self.executor.sizer, "fixed_margin_usdt", 50.0)),
                    "stop_pct": stop_dist_pct,
                    "leverage": float(self.executor.risk.leverage),
                }
            )
            if not ten_agent_report["approved"]:
                self.metrics["ten_agent_vetoes"] += 1
                self._record_block(
                    symbol, side, "ten_agent_mutual_audit", ten_agent_report["reason"], price, now_ms
                )
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": ten_agent_report["reason"],
                    "council": council_report,
                    "ten_agent_audit": ten_agent_report,
                    "regime": regime_snap,
                    "pdf_core": pdf_core,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

        llm_verdict: dict[str, Any] = {"mode": "RULE_ONLY", "approved": True, "status": "SKIPPED_WAIT"}
        if side in ("LONG", "SHORT"):
            wl_verdict = self.win_loss_analyzer.check_entry_edge(
                symbol=symbol,
                side=side,
                vwap_atr_z=vwap_atr_z,
                rvol=eff_rvol,
                rvol_warmed=rvol_warmed,
                playbook=playbook_info["playbook"],
            )
            if not wl_verdict.allowed:
                self.metrics["win_loss_trap_blocks"] += 1
                rsn = f"win_loss_kalkani:{wl_verdict.pattern_tag}:{wl_verdict.reason}"
                self._record_block(symbol, side, "win_loss_shield", rsn, price, now_ms)
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": rsn,
                    "council": council_report,
                    "ten_agent_audit": ten_agent_report,
                    "regime": regime_snap,
                    "pdf_core": pdf_core,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

            est_notional = float(getattr(self.executor.sizer, "fixed_margin_usdt", 50.0)) * float(
                self.executor.risk.leverage
            )
            fee_check = self.commission_optimizer.evaluate_fee_viability(
                notional_usdt=est_notional,
                atr_pct=atr_pct_val,
                spread_pct=spread_pct,
                rvol=eff_rvol,
            )
            if not fee_check.viable:
                self.metrics["commission_blocks"] += 1
                self._record_block(symbol, side, "commission_viability", fee_check.reason, price, now_ms)
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": fee_check.reason,
                    "council": council_report,
                    "ten_agent_audit": ten_agent_report,
                    "regime": regime_snap,
                    "pdf_core": pdf_core,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

            llm_verdict = await self.llm_referee.adjudicate(
                {
                    "symbol": symbol,
                    "side": side,
                    "playbook": playbook_info["playbook"],
                    "regime": confirmed_regime,
                    "macro_regime": macro_info["macro_regime"],
                    "volume_declining": macro_info["volume_declining"],
                    "choppiness_14": round(chop_14, 2),
                    "breadth_ratio": round(breadth_ratio, 4),
                    "vwap_atr_z": round(vwap_atr_z, 3),
                    "rvol": round(eff_rvol, 2),
                    "flow_score": round(flow_val, 1),
                    "spread_pct": round(spread_pct, 4),
                    "consensus_score": council_report["consensus_score"],
                }
            )
            if not llm_verdict.get("approved", True):
                self.metrics["llm_referee_vetoes"] += 1
                rsn = f"llm_referee_veto:{llm_verdict.get('rationale', '')}"
                self._record_block(symbol, side, "strict_quant_referee", rsn, price, now_ms)
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": rsn,
                    "council": council_report,
                    "ten_agent_audit": ten_agent_report,
                    "llm_referee": llm_verdict,
                    "regime": regime_snap,
                    "pdf_core": pdf_core,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

        routed = False
        chosen_venue = exchange
        venue_book_meta: dict[str, Any] = {}
        if self.mode != "shadow_only" and side in ("LONG", "SHORT"):
            had_pos_before = symbol in self.executor.positions
            broker_obj = getattr(self.executor, "broker", None)
            if broker_obj is not None and hasattr(broker_obj, "select_best_exchange"):
                chosen_venue, venue_book_meta = broker_obj.select_best_exchange(
                    symbol, side, getattr(self.executor, "positions", None)
                )
                if chosen_venue in venue_book_meta and venue_book_meta[chosen_venue].get("mid", 0) > 0:
                    new_px = float(venue_book_meta[chosen_venue]["mid"])
                    px_shift = new_px - price
                    price = new_px
                    if sw_low is not None and sw_high is not None and abs(px_shift) > 0:
                        if hasattr(self.executor, "set_market_structure"):
                            self.executor.set_market_structure(symbol, sw_low + px_shift, sw_high + px_shift)
            try:
                await self.executor.on_price_tick(symbol, price, exchange=chosen_venue)
            except TypeError:
                await self.executor.on_price_tick(symbol, price)
            await self.executor.on_signal(
                symbol,
                price,
                combined,
                flow_val,
                False,
                mtf_trend=mtf_info,
                entry_context={
                    "engine": "UnifiedTradingEngine_v9.2",
                    "preferred_exchange": chosen_venue,
                    "exchange": chosen_venue,
                    "venue_books": {
                        k: {"spread_pct": round(v["spread_pct"], 5), "mid": v["mid"]}
                        for k, v in venue_book_meta.items()
                    },
                    "playbook": playbook_info["playbook"],
                    "regime": confirmed_regime,
                    "breadth_ratio": round(breadth_ratio, 4),
                    "v4_vwap_atr_z": round(vwap_atr_z, 4),
                    "v4_rvol": round(eff_rvol, 4),
                    "pdf_choppiness": pdf_core.get("choppiness_14", 50.0),
                    "pdf_bos": pdf_core.get("bos_dir", 0),
                    "rule_council_mode": council_report.get("council_mode", "DETERMINISTIC_QUANT_RULES"),
                    "ten_agent_approve_votes": (
                        ten_agent_report["consensus_votes"] if ten_agent_report else None
                    ),
                    "llm_referee_mode": llm_verdict.get("mode", "RULE_ONLY"),
                    "ai_council_score": council_report["consensus_score"],
                    "ai_council_votes": {
                        v["member_id"]: v["score"] for v in council_report.get("votes", [])
                    },
                },
            )
            routed = (not had_pos_before) and (symbol in self.executor.positions)
            if routed:
                self.metrics["entries_routed"] += 1
            elif not had_pos_before:
                self.metrics["maker_unfilled_skips"] += 1
                self._record_block(
                    symbol,
                    side,
                    "maker_queue_or_margin_skip",
                    "pasif_maker_dolmadi_veya_marj_yetersiz",
                    price,
                    now_ms,
                )

        return {
            "symbol": symbol,
            "signal": side,
            "playbook": playbook_info["playbook"],
            "breadth_ratio": round(breadth_ratio, 4),
            "routed": routed,
            "reason": council_report["reason"],
            "combined": combined,
            "council": council_report,
            "ten_agent_audit": ten_agent_report,
            "llm_referee": llm_verdict,
            "regime": regime_snap,
            "pdf_core": pdf_core,
            "v4_60m": v4_60m,
            "flow": flow_snap,
        }

    def sync_closed_trade_feedback(self) -> int:
        """Kapanmış işlemleri okuyup 10-Ajan öz-sıkılaştırmasını, gölge 135sn karşı-olgusunu
        ve Bayesçi ağırlıkları günceller."""
        store = getattr(self.executor, "state_store", None)
        if store is None or not hasattr(store, "get_trades"):
            return 0
        updated = 0
        try:
            import json as _json

            recent = store.get_trades(limit=200)
            new_rows = [
                r for r in recent if int(r.get("id") or 0) > self._last_processed_trade_id
            ]
            new_rows.sort(key=lambda x: int(x.get("id") or 0))
            for r in new_rows:
                tid = int(r["id"])
                sym = str(r.get("symbol") or "")
                gross_pnl = float(r.get("pnl_usdt") or 0.0)
                net_pnl = float(r.get("net_pnl_usdt") or 0.0)
                ectx_raw = r.get("entry_context")
                in_fee = float(r.get("entry_fee_usdt") or 0.0)
                out_fee = float(r.get("exit_fee_usdt") or 0.0)
                notional = max(
                    100.0, float(r.get("margin_usdt") or 50.0) * float(r.get("leverage") or 10.0)
                )
                self._last_processed_trade_id = max(self._last_processed_trade_id, tid)
                if sym:
                    self.win_loss_analyzer.record_trade_outcome(sym, net_pnl)
                    for pid in [k for k in list(self.counterfactual.shadow_legacy_cuts) if k.startswith(f"{sym}:")]:
                        self.counterfactual.resolve_shadow_cut_on_close(
                            position_id=pid,
                            actual_net_pnl_usdt=net_pnl,
                            exit_reason=str(r.get("reason") or ""),
                        )
                self.ten_agent_council.record_closed_trade_outcome(
                    gross_usdt=gross_pnl,
                    fee_usdt=in_fee + out_fee,
                    net_usdt=net_pnl,
                )
                self.commission_optimizer.record_fill_telemetry(
                    is_entry=True, is_maker=(0 < in_fee <= notional * 0.0003), notional_usdt=notional
                )
                self.commission_optimizer.record_fill_telemetry(
                    is_entry=False, is_maker=(0 < out_fee <= notional * 0.0003), notional_usdt=notional
                )
                if ectx_raw:
                    ectx = _json.loads(ectx_raw) if isinstance(ectx_raw, str) else ectx_raw
                    votes = ectx.get("ai_council_votes") if isinstance(ectx, dict) else None
                    self.council.update_weights_from_closed_trade(votes, net_pnl)
                updated += 1
        except Exception:
            pass
        return updated

    def operational_health_snapshot(self, *, max_feed_lag_sec: float = 20.0) -> dict[str, Any]:
        """Veri gecikmesi (feed latency) ve SQLite defter / bellek mutabakat alarmlarını denetler (Denetim 3.9)."""
        now_s = time.time()
        feed_lag_sec = max(0.0, now_s - float(self._last_feed_ts or now_s))
        mem_positions = set(getattr(self.executor, "positions", {}).keys())
        store = getattr(self.executor, "state_store", None)
        db_positions: set[str] = set()
        reconciled = True
        if store is not None and hasattr(store, "load_positions"):
            try:
                db_positions = set((store.load_positions() or {}).keys())
                ledger_ok = True
                if hasattr(store, "verify_paper_ledger_integrity"):
                    ledger_ok = bool(store.verify_paper_ledger_integrity().get("ok", True))
                reconciled = (mem_positions == db_positions) and ledger_ok
            except Exception:
                reconciled = False

        alarms: list[str] = []
        if feed_lag_sec > max_feed_lag_sec:
            alarms.append(f"FEED_LATENCY_ALARM({feed_lag_sec:.1f}s>{max_feed_lag_sec:.1f}s)")
        if not reconciled:
            alarms.append(
                f"LEDGER_RECONCILIATION_MISMATCH(mem={sorted(mem_positions)},db={sorted(db_positions)})"
            )
        cb = getattr(self.executor, "circuit_breaker", None)
        if cb is not None and getattr(cb, "tripped", False):
            alarms.append(f"CIRCUIT_BREAKER_TRIPPED({getattr(cb, 'reason', '')})")

        return {
            "healthy": len(alarms) == 0,
            "feed_lag_sec": round(feed_lag_sec, 2),
            "ledger_reconciled": reconciled,
            "memory_open_count": len(mem_positions),
            "sqlite_open_count": len(db_positions),
            "alarms": alarms,
        }

    def analytics_snapshot(self) -> dict[str, Any]:
        """Brüt/Net edge ayrımı, Maker kuyruk istatistikleri, 10-Ajan diyalogları ve Karşı-Olgu özeti."""
        store = getattr(self.executor, "state_store", None)
        trades = store.get_trades(limit=500) if (store and hasattr(store, "get_trades")) else []
        start_eq = float((self.cfg.get("paper") or {}).get("bakiye", 1000.0))
        one_r = float((self.cfg.get("boyutlandirma") or {}).get("sabit_marj_usdt", 50.0)) * float(
            (self.cfg.get("risk") or {}).get("marj_zarar_orani", 0.80)
        )
        edge_rep = compute_edge_separation_report(
            list(reversed(trades)), starting_balance=start_eq, one_r_usdt=max(1.0, one_r)
        )
        broker = getattr(self.executor, "broker", None)
        maker_q = (
            broker.maker_queue_stats()
            if (broker is not None and hasattr(broker, "maker_queue_stats"))
            else {"enabled": False}
        )
        return {
            "engine_version": self.version,
            "edge_separation": edge_rep,
            "maker_queue": maker_q,
            "ten_agent_council": self.ten_agent_council.snapshot(),
            "counterfactual": self.counterfactual.summary(),
            "operational_health": self.operational_health_snapshot(),
        }
