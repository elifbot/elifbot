"""Kripto Bot v8.0 Birleşik Sinyal, Evren ve Yürütme Motoru (V4 + V7.8 + Çoklu-YZ).

Bu modül Gmail'deki iki ayrı botun en güçlü ve doğrulanmış bileşenlerini tek bir
hatasız çekirdekte birleştirir:
  • V4 Katmanı:
    - `scanner.universe.saf_kripto_evreni`: Hisse/emtia/endeks/forex/stabilcoin türevlerini
      eleyen saf kripto sürekli vadeli (USDT-M Swap) evren filtresi.
    - `scanner.ws_scanner.SpikeDetector` + `scanner.ind_aktif`: Anlık RVOL/Spike tespiti,
      60 kapanmış 1m mumdan gerçek VWAP60 ve Wilder ATR14 hesabı.
    - `scanner.katalog_entegre`: A–G indikatör kataloğu çoklu uyum (confluence) skoru.
  • V7.8 Katmanı:
    - `src.moneyflow.MoneyFlow`: Tam 300s pencereli (balina kaybı olmayan) CVD,
      emir defteri dengesizliği ve emilim (absorption) analizi.
    - `src.indicators` + `src.strategy.Strategy`: Çoklu zaman dilimi (MTF) filtreli
      hibrit strateji motoru.
    - `src.executor.Executor` + `src.state_store.StateStore`: SQLite WAL, PENDING/OPEN/CLOSED/APPLIED
      atomik günlük (intent journal), çift-taraflı kasa mutabakatı ve tek-yazar kilidi.
  • Çoklu-YZ Konsey Katmanı (`src.ai_council.MultiAICouncil`):
    - Claude + DeepSeek + GPT + Gemini dörtlü sinyal/risk oylaması ve toksik akış vetosu.
"""
from __future__ import annotations

import math
import time
from typing import Any

import pandas as pd

from scanner.ind_aktif import kapali_mum_ekle, metrik
from scanner.universe import STOCK_LIKE_DENYLIST
from scanner.ws_scanner import SpikeDetector

from .ai_council import MultiAICouncil
from .commission_optimizer import CommissionOptimizer
from .futures_catalog import NON_CRYPTO_OR_PEGGED_BASES, canonical_underlying_asset
from .indicators import indicator_score, multi_timeframe_filter
from .moneyflow import MoneyFlow
from .strategy import Strategy
from .win_loss_analyzer import WinLossAnalyzer


class UnifiedV8Engine:
    """V4 gerçek zamanlı tarayıcı + V7.8 order-flow/strateji + 10-YZ Konsey + Komisyon & Kâr/Zarar Optimizatörü."""

    def __init__(
        self,
        executor,
        *,
        mode: str = "hybrid_fusion",
        council: MultiAICouncil | None = None,
        detector: SpikeDetector | None = None,
        commission_optimizer: CommissionOptimizer | None = None,
        win_loss_analyzer: WinLossAnalyzer | None = None,
    ):
        if mode not in {"shadow_only", "confluence_gate", "hybrid_fusion"}:
            raise ValueError(f"Geçersiz UnifiedV8Engine modu: {mode}")
        self.executor = executor
        self.mode = mode
        self.council = council if council is not None else MultiAICouncil()
        self.detector = detector if detector is not None else SpikeDetector(baglam_aktif=False)
        self.detector.ind_aktif = True
        self.commission_optimizer = (
            commission_optimizer if commission_optimizer is not None else CommissionOptimizer()
        )
        self.win_loss_analyzer = (
            win_loss_analyzer if win_loss_analyzer is not None else WinLossAnalyzer()
        )
        self._last_processed_trade_id: int = 0
        self.flows: dict[str, MoneyFlow] = {}
        self.metrics = {
            "ticks_processed": 0,
            "candles_ingested": 0,
            "signals_evaluated": 0,
            "council_vetoes": 0,
            "commission_blocks": 0,
            "win_loss_trap_blocks": 0,
            "stagnant_cuts": 0,
            "v4_vwap_atr_blocks": 0,
            "entries_routed": 0,
        }

    @staticmethod
    def filter_pure_crypto_symbols(symbols: list[str]) -> list[str]:
        """V4 (`STOCK_LIKE_DENYLIST`) + V7.8 (`NON_CRYPTO_OR_PEGGED_BASES`) birleşik saf kripto filtresi."""
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
            if base in blocked or canon in blocked or base in {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "USDE"}:
                continue
            keep.append(sym)
        return keep

    def flow_for(self, symbol: str) -> MoneyFlow:
        flow = self.flows.get(symbol)
        if flow is None:
            flow = MoneyFlow(symbol, window_sec=300, compact_history=True)
            self.flows[symbol] = flow
        return flow

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
    ) -> bool:
        """V4 60dk VWAP60 + Wilder ATR14 penceresine kapanmış 1m mum ekler."""
        qv = float(quote_vol) if quote_vol is not None else float(close_px) * float(base_vol)
        d = self.detector.durum(exchange, symbol)
        ok = kapali_mum_ekle(
            d, int(minute_id), float(high_px), float(low_px), float(close_px), float(base_vol), qv
        )
        if ok:
            self.metrics["candles_ingested"] += 1
        return ok

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
        """Canlı işlemi hem V7.8 300s MoneyFlow'a hem V4 SpikeDetector'a hem Executor tick'ine besler."""
        if not (math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0):
            return None
        now_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
        self.metrics["ticks_processed"] += 1

        flow = self.flow_for(symbol)
        flow.add_trade(price, qty, is_buyer_maker=bool(is_buyer_maker), ts=now_ms / 1000.0)

        d = self.detector.durum(exchange, symbol)
        prev_cum = float(getattr(d, "_v8_cum_qv", 0.0)) + price * qty
        d._v8_cum_qv = prev_cum
        self.detector.besle_hacim_kumulatif(exchange, symbol, prev_cum, now_ms)
        spike_sig = self.detector.besle_fiyat(exchange, symbol, price, 0.0, now_ms)

        await self.executor.on_price_tick(symbol, price)
        return {"spike": spike_sig.etiket if spike_sig else None, "rvol": d.rvol}

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
        allow_new_entries: bool = True,
    ) -> dict[str, Any]:
        """V4 + V7.8 + Çoklu-YZ Konseyi birleşik kararını üretir ve uygunsa Executor'a iletir."""
        self.metrics["signals_evaluated"] += 1
        price = float(ohlcv_5m["close"].iloc[-1])
        ind_res = indicator_score(ohlcv_5m)
        ind_val = float(ind_res.get("score", 0.0))

        # ATR ve yapısal swing noktalarını Executor'a senkronize et
        atr_5m = float(ind_res.get("atr") or 0.0)
        if atr_5m > 0:
            self.executor.set_atr(symbol, atr_5m)

        flow_snap = self.flow_for(symbol).snapshot(include_vpvr=False)
        flow_val = float(flow_snap.get("score", 0.0))

        # V4 60dk VWAP60 + Wilder ATR14 mikro-yapı ölçümü
        d_v4 = self.detector.durum(exchange, symbol)
        raw_v4 = metrik(d_v4, int(time.time() * 1000), price)
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
                # Trend yönünde sağlıklı VWAP kırılımı (+0.2 .. +2.5 ATR) puanı güçlendirir
                if 0.15 <= abs(vwap_atr_z) <= 2.8:
                    v4_boost = math.copysign(min(12.0, abs(vwap_atr_z) * 5.0), vwap_atr_z)

        effective_ind = ind_val + (v4_boost if self.mode == "hybrid_fusion" else 0.0)
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

        mtf_aligned = True
        mtf_info: dict[str, Any] | None = None
        if side in ("LONG", "SHORT") and ohlcv_15m is not None and ohlcv_1h is not None:
            mtf_info = multi_timeframe_filter(ohlcv_15m, ohlcv_1h)
            trend = str(mtf_info.get("trend") or "NEUTRAL").upper()
            if (side == "LONG" and trend == "BEARISH") or (side == "SHORT" and trend == "BULLISH"):
                mtf_aligned = False

        # V4 aşırı uzama kapısı: fiyat VWAP60'tan aynı yönde >3.8 ATR uzaktaysa zirve/dip kovalama!
        if side == "LONG" and vwap_atr_z > 3.8 or side == "SHORT" and vwap_atr_z < -3.8:
            self.metrics["v4_vwap_atr_blocks"] += 1
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": f"v4_vwap60_asiri_uzama(z={vwap_atr_z:+.2f})",
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        stop_dist_pct = float(self.executor.risk.effective_stop_pct(self.executor.risk.leverage))
        whale_net = float(flow_snap.get("whale_buy_usdt", 0.0)) - float(flow_snap.get("whale_sell_usdt", 0.0))
        atr_pct_val = (
            float(v4_60m["atr_pct"])
            if v4_60m and v4_60m.get("atr_pct", 0.0) > 0
            else ((atr_5m / price * 100.0) if (atr_5m > 0 and price > 0) else 0.45)
        )
        same_side_cnt = sum(1 for p in self.executor.positions.values() if p.side == side)
        cb_obj = getattr(self.executor, "circuit_breaker", None)
        raw_rvol = float(d_v4.rvol or 0.0)
        dk_hist = getattr(d_v4, "dakika_hacim", ())
        rvol_warmed = raw_rvol > 0.0 and hasattr(dk_hist, "__len__") and len(dk_hist) >= 5
        eff_rvol = raw_rvol if rvol_warmed else 1.0

        # Kapanan işlemlerden adaptif 10-YZ ağırlık öğrenmesi + churn soğuması senkronu
        self.sync_closed_trade_feedback()

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
            age_sec = max(0.0, time.time() - opened_ts) if opened_ts > 0 else 0.0
            cur_gross = float(self.executor.risk.pnl_usdt(pos_open, price))
            flow_against = (pos_open.side == "LONG" and flow_val < -18.0) or (
                pos_open.side == "SHORT" and flow_val > 18.0
            )
            stag = self.win_loss_analyzer.evaluate_stagnant_loser(
                age_sec=age_sec,
                mfe_usdt=float(getattr(pos_open, "mfe_usdt", 0.0)),
                current_gross_pnl_usdt=cur_gross,
                flow_against_position=flow_against,
            )
            if stag["should_cut"] and self.mode != "shadow_only":
                closed_ok = await self.executor.close_position(symbol, price, stag["reason"])
                if closed_ok:
                    self.metrics["stagnant_cuts"] += 1
                    self.sync_closed_trade_feedback()

        # 10. dakika sonrası "Doğal Kapanış / Drain Modu": Yeni pozisyon AÇILMAZ,
        # ancak açık pozisyonlar ters güçlü sinyalde veya iz-süren stopla bota uygun kapatılır.
        if not allow_new_entries:
            await self.executor.on_price_tick(symbol, price)
            if symbol in self.executor.positions and self.mode != "shadow_only":
                pos_cur = self.executor.positions[symbol]
                tot_sc = float(combined.get("total", 0.0))
                rev_long = pos_cur.side == "LONG" and side == "SHORT" and tot_sc <= -22.0
                rev_short = pos_cur.side == "SHORT" and side == "LONG" and tot_sc >= 22.0
                if rev_long or rev_short:
                    await self.executor.close_position(
                        symbol, price, f"TERS SİNYAL DOĞAL ÇIKIŞ ({tot_sc:+.1f})"
                    )
                    self.sync_closed_trade_feedback()
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": "yeni_giris_durduruldu_acik_pozisyon_bekleniyor",
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

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
                "smart_maker_execution": bool(
                    getattr(getattr(self.executor, "broker", None), "smart_maker_execution", True)
                ),
                "max_slippage_pct": float(self.executor.risk.max_slippage_pct),
                "stop_distance_pct": stop_dist_pct,
                "leverage": float(self.executor.risk.leverage),
                "cvd_divergence": flow_snap.get("cvd_divergence", "NONE"),
                "absorption": flow_snap.get("absorption", "YOK"),
                "orderbook_imbalance": float(flow_snap.get("imbalance", 0.0)),
                "same_side_open_count": same_side_cnt,
                "max_same_side_positions": int(getattr(self.executor.risk, "max_same_side_positions", 4)),
                "breadth_ratio": float(self.detector.genislik_oran or 0.15),
                "funding_rate": funding_rate,
                "paper_recovery_locked": bool(self.executor.paper_recovery_locked),
                "circuit_breaker_tripped": bool(getattr(cb_obj, "tripped", False)),
                "regime": str(ind_res.get("regime") or "TREND"),
            }
        )

        if side in ("LONG", "SHORT") and not council_report["approved"]:
            self.metrics["council_vetoes"] += 1
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "raw_signal": side,
                "routed": False,
                "reason": council_report["reason"],
                "council": council_report,
                "v4_60m": v4_60m,
                "flow": flow_snap,
            }

        if side in ("LONG", "SHORT"):
            wl_verdict = self.win_loss_analyzer.check_entry_edge(
                symbol=symbol,
                side=side,
                vwap_atr_z=vwap_atr_z,
                rvol=eff_rvol,
                rvol_warmed=rvol_warmed,
            )
            if not wl_verdict.allowed:
                self.metrics["win_loss_trap_blocks"] += 1
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": f"win_loss_kalkani:{wl_verdict.pattern_tag}:{wl_verdict.reason}",
                    "council": council_report,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

            est_notional = float(getattr(self.executor.sizer, "fixed_margin_usdt", 100.0)) * float(
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
                return {
                    "symbol": symbol,
                    "signal": "BEKLE",
                    "raw_signal": side,
                    "routed": False,
                    "reason": fee_check.reason,
                    "council": council_report,
                    "v4_60m": v4_60m,
                    "flow": flow_snap,
                }

        routed = False
        if self.mode != "shadow_only" and side in ("LONG", "SHORT"):
            await self.executor.on_price_tick(symbol, price)
            await self.executor.on_signal(
                symbol,
                price,
                combined,
                flow_val,
                False,
                mtf_trend=mtf_info,
                entry_context={
                    "engine": "UnifiedV8Engine",
                    "v4_vwap_atr_z": round(vwap_atr_z, 4),
                    "v4_rvol": round(float(d_v4.rvol or 0.0), 4),
                    "ai_council_score": council_report["consensus_score"],
                    "ai_council_votes": {
                        v["member_id"]: v["score"] for v in council_report.get("votes", [])
                    },
                },
            )
            routed = symbol in self.executor.positions
            if routed:
                self.metrics["entries_routed"] += 1

        return {
            "symbol": symbol,
            "signal": side,
            "routed": routed,
            "reason": council_report["reason"],
            "combined": combined,
            "council": council_report,
            "v4_60m": v4_60m,
            "flow": flow_snap,
        }

    def sync_closed_trade_feedback(self) -> int:
        """SQLite `trade_history` tablosundaki yeni kapanmış işlemleri (`store.get_trades`) okuyup
        10-YZ Bayesçi ağırlıklarını, komisyon tasarruf sayacını ve sembol churn soğumasını günceller."""
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
                net_pnl = float(r.get("net_pnl_usdt") or 0.0)
                ectx_raw = r.get("entry_context")
                in_fee = float(r.get("entry_fee_usdt") or 0.0)
                out_fee = float(r.get("exit_fee_usdt") or 0.0)
                notional = max(100.0, float(r.get("margin_usdt") or 100.0) * float(r.get("leverage") or 10.0))
                self._last_processed_trade_id = max(self._last_processed_trade_id, tid)
                if sym:
                    self.win_loss_analyzer.record_trade_outcome(sym, net_pnl)
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
