"""Sinyal birleştirici — botun "beyni".

  Toplam skor = indikatör + para akışı (OI/Likidasyon/Squeeze dahil) + haber + ML yön tahmini

  GİRİŞ: skor >= +long_esik → LONG | skor <= -short_esik → SHORT (veto yoksa)
  ARTIDA EKLEME (Sınırsız Pyramiding):
    - Açık pozisyon artıdaysa (kârda) ve sinyal aynı yönde güçlü kalmaya devam ediyorsa
      üst sınır olmaksızın yeni kademe (%10 kasa × 20x) eklenir.
  ÇIKIŞ (botun kendi çözümü):
    - Skor ters yöne döndüyse veya nötre çöktüyse kârı al
    - Para akışı sertçe tersine döndüyse çık
    - Kritik haber vetosu + kâr varsa pozisyonu koru (erken çık)
    - Stop/trailing ve Çapraz Kurtarma (1 artıda + 1 ekside ikili kapama) risk.py / executor.py
      tarafından her tick'te denetlenir.
"""
from __future__ import annotations


class Strategy:
    def __init__(
        self,
        w_ind: float = 0.50,
        w_flow: float = 0.30,
        w_news: float = 0.20,
        long_th: float = 55,
        short_th: float = -55,
        exit_th: float = 15,
        allow_short: bool = True,
        w_ml: float = 0.0,
        flow_trigger: bool = True,
        flow_th: float = 50.0,
        flow_ind_min: float = 10.0,
        flow_min_total: float = 15.0,
    ):
        # Para Akışı Tetikleyicisi: toplam skor eşiğe ulaşmasa da güçlü para girişi/çıkışı
        # yakalanınca (ve indikatör aynı yönü onaylıyorsa) giriş yapılır.
        self.flow_trigger = bool(flow_trigger)
        self.flow_th = float(flow_th)
        self.flow_ind_min = float(flow_ind_min)
        self.flow_min_total = float(flow_min_total)
        tot = w_ind + w_flow + w_news + w_ml
        if tot <= 0:
            tot = 1.0
        self.w_ind = w_ind / tot
        self.w_flow = w_flow / tot
        self.w_news = w_news / tot
        self.w_ml = w_ml / tot
        self.long_th = long_th
        self.short_th = short_th
        self.exit_th = exit_th
        self.allow_short = allow_short

    def combine(
        self,
        ind_score: float,
        flow_score: float,
        news_score: float,
        ml_score: float | None = None,
    ) -> dict:
        if ml_score is not None and self.w_ml > 0:
            total = (
                ind_score * self.w_ind
                + flow_score * self.w_flow
                + news_score * self.w_news
                + ml_score * self.w_ml
            )
        elif ml_score is not None and self.w_ml == 0:
            # w_ml=0 olarak başlatılmış ama ml_score verilmişse %85 baz + %15 ML harmanla
            base = (
                ind_score * self.w_ind
                + flow_score * self.w_flow
                + news_score * self.w_news
            )
            total = base * 0.85 + ml_score * 0.15
        else:
            denom = (self.w_ind + self.w_flow + self.w_news) or 1.0
            total = (
                ind_score * self.w_ind
                + flow_score * self.w_flow
                + news_score * self.w_news
            ) / denom

        total = round(max(-100, min(100, total)), 1)
        if total >= self.long_th:
            signal = "LONG"
        elif total <= self.short_th:
            signal = "SHORT"
        else:
            signal = "BEKLE"
        trigger = None
        if signal == "BEKLE" and self.flow_trigger:
            # Güçlü para GİRİŞİ + indikatör en azından aynı yönde + diğer bileşenler çelişmiyor
            if (
                flow_score >= self.flow_th
                and ind_score >= self.flow_ind_min
                and total >= self.flow_min_total
            ):
                signal, trigger = "LONG", "PARA_GIRISI"
            elif (
                flow_score <= -self.flow_th
                and ind_score <= -self.flow_ind_min
                and total <= -self.flow_min_total
            ):
                signal, trigger = "SHORT", "PARA_CIKISI"
        parts = {
            "indikator": round(float(ind_score), 1),
            "para_akisi": round(float(flow_score), 1),
            "haber": round(float(news_score), 1),
        }
        if ml_score is not None:
            parts["ml_tahmin"] = round(float(ml_score), 1)
        return {"total": total, "signal": signal, "parts": parts, "trigger": trigger}

    def entry_decision(
        self,
        combined: dict,
        veto: bool,
        has_position: bool,
        veto_long: bool = False,
        veto_short: bool = False,
        can_pyramid: bool = False,
        current_side: str | None = None,
        mtf_trend: str | dict | None = None,
    ) -> dict:
        """Yeni pozisyon açılmalı mı veya artıdaki pozisyona ekleme yapılmalı mı?
        Multi-Timeframe (`1h`/`4h`) Trend Filtresi ile ana trende ters girişleri engeller.
        """
        if has_position and not can_pyramid:
            return {"action": "yok", "reason": "zaten pozisyon var"}
        if veto:
            return {
                "action": "yok",
                "reason": "HABER VETOSU (kritik olumsuz haber / panik)",
            }

        # Multi-Timeframe (1h/4h) Trend Filtresi çözümlemesi
        mtf_allow_long = True
        mtf_allow_short = True
        mtf_label = "NEUTRAL"
        if isinstance(mtf_trend, dict):
            mtf_label = str(mtf_trend.get("trend", "NEUTRAL")).upper()
            mtf_allow_long = bool(
                mtf_trend.get("allow_long", mtf_label not in ("BEARISH", "DOWN"))
            )
            mtf_allow_short = bool(
                mtf_trend.get("allow_short", mtf_label not in ("BULLISH", "UP"))
            )
        elif isinstance(mtf_trend, str) and mtf_trend:
            mtf_label = mtf_trend.strip().upper()
            if mtf_label in ("BEARISH", "DOWN", "DUSUS", "SHORT"):
                mtf_allow_long = False
            elif mtf_label in ("BULLISH", "UP", "YUKSELIS", "LONG"):
                mtf_allow_short = False

        sig = combined["signal"]
        if sig == "LONG":
            if veto_long:
                return {
                    "action": "yok",
                    "reason": "AÇGÖZLÜLÜK VETOSU (zirve kovalanmaz)",
                }
            if not mtf_allow_long:
                return {
                    "action": "yok",
                    "reason": f"MTF TREND FİLTRESİ (1h/4h {mtf_label}): Ana trend aşağı yönlüyken küçük tepkiye LONG açılmaz",
                }
            if has_position and can_pyramid:
                if current_side == "LONG":
                    return {
                        "action": "ADD_LONG",
                        "reason": f"artıda kademe ekleme (skor {combined['total']})",
                    }
                return {"action": "yok", "reason": "ters yönde açık pozisyon var"}
            tg = f" | tetik: {combined['trigger']}" if combined.get("trigger") else ""
            return {"action": "LONG", "reason": f"skor {combined['total']}{tg}"}
        if sig == "SHORT":
            if veto_short:
                return {"action": "yok", "reason": "HABER VETOSU (short engellendi)"}
            if not self.allow_short:
                return {"action": "yok", "reason": "short izni kapalı"}
            if not mtf_allow_short:
                return {
                    "action": "yok",
                    "reason": f"MTF TREND FİLTRESİ (1h/4h {mtf_label}): Ana trend yukarı yönlüyken ters SHORT açılmaz",
                }
            if has_position and can_pyramid:
                if current_side == "SHORT":
                    return {
                        "action": "ADD_SHORT",
                        "reason": f"artıda kademe ekleme (skor {combined['total']})",
                    }
                return {"action": "yok", "reason": "ters yönde açık pozisyon var"}
            tg = f" | tetik: {combined['trigger']}" if combined.get("trigger") else ""
            return {"action": "SHORT", "reason": f"skor {combined['total']}{tg}"}
        return {"action": "yok", "reason": f"skor yetersiz ({combined['total']})"}

    def exit_decision(
        self,
        side: str,
        combined: dict,
        flow_score: float,
        veto: bool,
        pnl_pct: float,
    ) -> dict:
        """Açık pozisyon kapatılmalı mı? (botun kâr çıkış çözümü)"""
        total = combined["total"]
        # 1) Kritik haber + kârdayken → koru, çık
        if veto and pnl_pct > 1.0:
            return {"action": "close", "reason": "HABER VETOSU + kâr koruma"}
        # 2) Skor ters yöne döndü → trend bitti
        if side == "LONG":
            if total <= -self.exit_th:
                return {"action": "close", "reason": f"sinyal terse döndü ({total})"}
            if flow_score <= -50 and pnl_pct > 0.5:
                return {"action": "close", "reason": "para çıkışı başladı, kârı al"}
            if total < self.exit_th and pnl_pct > 2.0:
                return {"action": "close", "reason": "momentum söndü, kârı al"}
        else:  # SHORT
            if total >= self.exit_th:
                return {"action": "close", "reason": f"sinyal terse döndü ({total})"}
            if flow_score >= 50 and pnl_pct > 0.5:
                return {"action": "close", "reason": "para girişi başladı, kârı al"}
            if total > -self.exit_th and pnl_pct > 2.0:
                return {"action": "close", "reason": "momentum söndü, kârı al"}
        return {"action": "hold", "reason": "sinyal sürüyor"}
