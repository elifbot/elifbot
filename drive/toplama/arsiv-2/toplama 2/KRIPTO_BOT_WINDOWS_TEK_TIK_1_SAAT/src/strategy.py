"""Sinyal Birleştirme, Piyasa Rejimi / MTF / Order-Flow Onayı ve Giriş/Çıkış Kararı."""
from __future__ import annotations


class Strategy:
    def __init__(
        self,
        w_ind: float = 0.40,
        w_flow: float = 0.30,
        w_news: float = 0.15,
        long_th: float = 55.0,
        short_th: float = -55.0,
        exit_th: float = 15.0,
        allow_short: bool = True,
        w_ml: float = 0.15,
        flow_trigger: bool = True,
        flow_th: float = 50.0,
        flow_ind_min: float = 10.0,
        flow_min_total: float = 15.0,
        regime_filter: bool = True,
        breakout_flow_confirmation: bool = True,
        orderflow_filter: bool = True,
        runner_exit: bool = False,
    ):
        self.flow_trigger = bool(flow_trigger)
        self.flow_th = float(flow_th)
        self.flow_ind_min = float(flow_ind_min)
        self.flow_min_total = float(flow_min_total)
        self.regime_filter = bool(regime_filter)
        self.breakout_flow_confirmation = bool(breakout_flow_confirmation)
        self.orderflow_filter = bool(orderflow_filter)
        self.runner_exit = bool(runner_exit)
        tot = w_ind + w_flow + w_news + w_ml
        if tot <= 0:
            tot = 1.0
        self.w_ind = w_ind / tot
        self.w_flow = w_flow / tot
        self.w_news = w_news / tot
        self.w_ml = w_ml / tot
        self.long_th = float(long_th)
        self.short_th = float(short_th)
        self.exit_th = abs(float(exit_th))
        self.allow_short = bool(allow_short)

    def combine(
        self,
        ind_score: float,
        flow_score: float,
        news_score: float,
        ml_score: float | None = None,
        market_context: dict | None = None,
    ) -> dict:
        if ml_score is not None and self.w_ml > 0:
            total = (
                ind_score * self.w_ind
                + flow_score * self.w_flow
                + news_score * self.w_news
                + ml_score * self.w_ml
            )
        else:
            denom = (self.w_ind + self.w_flow + self.w_news) or 1.0
            total = (
                ind_score * self.w_ind
                + flow_score * self.w_flow
                + news_score * self.w_news
            ) / denom

        total = round(max(-100, min(100, total)), 1)
        if total >= self.long_th:
            raw_signal = "LONG"
        elif total <= self.short_th:
            raw_signal = "SHORT"
        else:
            raw_signal = "BEKLE"

        context = market_context or {}
        entry_allowed = True
        block_reason = ""
        if self.regime_filter and bool(context.get("regime_aware", True)):
            entry_allowed = bool(context.get("entry_allowed", True))
            block_reason = str(context.get("entry_block_reason", ""))
            direction = 1 if raw_signal == "LONG" else -1
            is_breakout = raw_signal != "BEKLE" and bool(
                context.get("breakout_long") if direction > 0 else context.get("breakout_short")
            )
            if raw_signal != "BEKLE" and entry_allowed and is_breakout and self.breakout_flow_confirmation:
                try:
                    cvd_slope = float(context.get("cvd_slope", 0.0) or 0.0)
                except (TypeError, ValueError):
                    cvd_slope = 0.0
                directional_flow = flow_score * direction
                flow_confirmed = directional_flow > -10 and (
                    directional_flow >= 10 or cvd_slope * direction > 0
                )
                if not flow_confirmed:
                    entry_allowed = False
                    block_reason = "Breakout için para akışı/CVD aynı yönü onaylamıyor"
                else:
                    oi_signal = str(context.get("oi_signal", "NOTR"))
                    opposite = (
                        {"YENI_SHORT_GIRISI", "LONG_TASFIYE_DUSUSU"}
                        if direction > 0
                        else {"YENI_LONG_GIRISI", "SHORT_KAPAMA_RALLISI"}
                    )
                    if oi_signal in opposite:
                        entry_allowed = False
                        block_reason = f"Breakout OI/fiyat matrisiyle çelişiyor: {oi_signal}"

        signal = raw_signal if entry_allowed else "BEKLE"
        trigger = None
        if signal == "BEKLE" and entry_allowed and self.flow_trigger:
            if (
                flow_score >= self.flow_th
                and ind_score >= self.flow_ind_min
                and news_score > -35
                and total >= self.flow_min_total
            ):
                signal, trigger = "LONG", "PARA_GIRISI"
            elif (
                flow_score <= -self.flow_th
                and ind_score <= -self.flow_ind_min
                and news_score < 35
                and total <= -self.flow_min_total
            ):
                signal, trigger = "SHORT", "PARA_CIKISI"

        if (
            trigger
            and self.regime_filter
            and self.breakout_flow_confirmation
            and bool(context.get("regime_aware", True))
        ):
            direction = 1 if signal == "LONG" else -1
            is_breakout = bool(
                context.get("breakout_long") if direction > 0 else context.get("breakout_short")
            )
            oi_signal = str(context.get("oi_signal", "NOTR"))
            opposite = (
                {"YENI_SHORT_GIRISI", "LONG_TASFIYE_DUSUSU"}
                if direction > 0
                else {"YENI_LONG_GIRISI", "SHORT_KAPAMA_RALLISI"}
            )
            if is_breakout and oi_signal in opposite:
                signal, trigger = "BEKLE", None
                entry_allowed = False
                block_reason = f"Breakout OI/fiyat matrisiyle çelişiyor: {oi_signal}"

        orderflow_veto = ""
        if self.orderflow_filter and signal in {"LONG", "SHORT"}:
            divergence = str(context.get("cvd_divergence", "YOK")).upper()
            absorption = str(context.get("absorption", "YOK")).upper()
            if signal == "LONG":
                conflicts = []
                if divergence == "BEARISH":
                    conflicts.append("bearish CVD divergence")
                if absorption == "ALIS_EMILIMI":
                    conflicts.append("agresif alışların ask derinliğinde emilimi")
            else:
                conflicts = []
                if divergence == "BULLISH":
                    conflicts.append("bullish CVD divergence")
                if absorption == "SATIS_EMILIMI":
                    conflicts.append("agresif satışların bid derinliğinde emilimi")
            if conflicts:
                orderflow_veto = " + ".join(conflicts)
                signal, trigger = "BEKLE", None
                entry_allowed = False
                block_reason = f"Order-flow karşı onayı: {orderflow_veto}"

        parts = {
            "indikator": round(float(ind_score), 1),
            "para_akisi": round(float(flow_score), 1),
            "haber": round(float(news_score), 1),
        }
        if ml_score is not None:
            parts["ml_tahmin"] = round(float(ml_score), 1)
        return {
            "total": total,
            "signal": signal,
            "raw_signal": raw_signal,
            "parts": parts,
            "trigger": trigger,
            "entry_allowed": entry_allowed,
            "entry_block_reason": block_reason,
            "orderflow_veto": orderflow_veto,
            "regime": context.get("regime", "BELIRSIZ"),
            "setup": context.get("setup", "BELIRSIZ"),
        }

    def entry_decision(
        self,
        combined: dict,
        veto: bool = False,
        has_position: bool = False,
        veto_long: bool = False,
        veto_short: bool = False,
        can_pyramid: bool = False,
        current_side: str | None = None,
        mtf_trend: dict | str | None = None,
    ) -> dict:
        if veto:
            return {
                "action": "yok",
                "reason": "HABER VETOSU (kritik olumsuz haber / panik)",
            }
        if not combined.get("entry_allowed", True) and combined.get("raw_signal") in (
            "LONG", "SHORT"
        ):
            return {
                "action": "yok",
                "reason": "PİYASA REJİMİ/ONAY FİLTRESİ: "
                + str(combined.get("entry_block_reason") or "giriş koşulları oluşmadı"),
            }

        # Multi-Timeframe (1h/4h) Trend Filtresi çözümlemesi
        mtf_allow_long = True
        mtf_allow_short = True
        mtf_label = "NEUTRAL"
        if isinstance(mtf_trend, dict):
            mtf_allow_long = bool(mtf_trend.get("allow_long", True))
            mtf_allow_short = bool(mtf_trend.get("allow_short", True))
            mtf_label = str(mtf_trend.get("trend", "NEUTRAL"))
        elif isinstance(mtf_trend, str) and mtf_trend:
            mtf_label = mtf_trend.upper()
            if mtf_label in ("BEARISH", "DOWN"):
                mtf_allow_long = False
            elif mtf_label in ("BULLISH", "UP"):
                mtf_allow_short = False
            elif mtf_label == "UNKNOWN":
                mtf_allow_long = False
                mtf_allow_short = False

        sig = combined.get("signal", "BEKLE")
        total = combined.get("total", 0.0)
        trigger = combined.get("trigger")

        if has_position:
            if not can_pyramid:
                return {"action": "yok", "reason": "açık pozisyon var"}
            if current_side == "LONG" and sig == "LONG":
                if veto_long:
                    return {"action": "yok", "reason": "aşırı açgözlülük LONG ekleme vetosu"}
                if not mtf_allow_long:
                    return {
                        "action": "yok",
                        "reason": f"MTF TREND FİLTRESİ: {mtf_label} LONG eklemeyi engelledi",
                    }
                return {"action": "ADD_LONG", "reason": f"skor={total:+.1f} ekleme"}
            if current_side == "SHORT" and sig == "SHORT" and self.allow_short:
                if veto_short:
                    return {"action": "yok", "reason": "SHORT ekleme vetosu"}
                if not mtf_allow_short:
                    return {
                        "action": "yok",
                        "reason": f"MTF TREND FİLTRESİ: {mtf_label} SHORT eklemeyi engelledi",
                    }
                return {"action": "ADD_SHORT", "reason": f"skor={total:+.1f} ekleme"}
            return {"action": "yok", "reason": "ekleme sinyali yok"}

        if sig == "LONG":
            if veto_long:
                return {"action": "yok", "reason": "AŞIRI AÇGÖZLÜLÜK LONG VETOSU"}
            if not mtf_allow_long:
                return {
                    "action": "yok",
                    "reason": f"MTF TREND FİLTRESİ: üst zaman dilimi ({mtf_label}) LONG yönünü onaylamıyor",
                }
            why = (
                f"PARA AKIŞI TETİKLEYİCİSİ ({trigger}) | toplam={total:+.1f}"
                if trigger
                else f"birleşik skor={total:+.1f} >= +{self.long_th:g}"
            )
            return {"action": "LONG", "reason": why}

        if sig == "SHORT":
            if not self.allow_short:
                return {"action": "yok", "reason": "short izni kapalı"}
            if veto_short:
                return {"action": "yok", "reason": "SHORT VETOSU"}
            if not mtf_allow_short:
                return {
                    "action": "yok",
                    "reason": f"MTF TREND FİLTRESİ: üst zaman dilimi ({mtf_label}) SHORT yönünü onaylamıyor",
                }
            why = (
                f"PARA AKIŞI TETİKLEYİCİSİ ({trigger}) | toplam={total:+.1f}"
                if trigger
                else f"birleşik skor={total:+.1f} <= {self.short_th:g}"
            )
            return {"action": "SHORT", "reason": why}

        return {"action": "yok", "reason": f"skor yetersiz ({total:+.1f})"}

    def exit_decision(
        self,
        side: str,
        combined: dict,
        flow_score: float,
        veto: bool,
        pnl_pct: float,
    ) -> dict:
        total = float(combined.get("total", 0.0))
        # 1) Kritik haber + kârdayken → koru, çık
        if veto and pnl_pct > 1.0:
            return {"action": "close", "reason": "HABER VETOSU + kâr koruma"}
        if self.runner_exit:
            return {
                "action": "hold",
                "reason": "kâr koşusu: trailing + doğrulanmış order-flow çıkışı",
            }
        # 2) Skor ters yöne döndü → trend bitti
        if side == "LONG":
            if total <= -self.exit_th:
                return {"action": "close", "reason": f"skor tersine döndü ({total:+.1f})"}
            if pnl_pct > 1.5 and flow_score <= -55:
                return {"action": "close", "reason": f"para çıkışı hızlandı ({flow_score:+.0f})"}
        elif side == "SHORT":
            if total >= self.exit_th:
                return {"action": "close", "reason": f"skor tersine döndü ({total:+.1f})"}
            if pnl_pct > 1.5 and flow_score >= 55:
                return {"action": "close", "reason": f"para girişi hızlandı ({flow_score:+.0f})"}
        return {"action": "hold", "reason": "trend devam ediyor"}
