"""ACARBOT v2.0 — 5 uzman motor ve Piyasa Hakemi (kullanıcının mimarisi).

    1. Trend Avcısı     — güçlü trendleri yakalar.
    2. Likidite Avcısı  — stop avı ve likidite süpürmelerini bulur.
    3. Momentum Avcısı  — ani hacim ve fiyat hareketlerini değerlendirir.
    4. Reversal Avcısı  — aşırı hareketlerden dönüşleri arar.
    5. Piyasa Hakemi    — oyları, piyasa koşullarını ve riskleri değerlendirir;
                          SON KARARI verir.

Her motorun performansı ayrı ölçülür (kapanan işlemlerden R bazında);
başarısız olan motorun katkısı azaltılır. Ağırlık güncellemesi YALNIZCA
paper/backtest kapanış kayıtlarından yapılır — canlıda kendi kendine
parametre değiştirme yoktur (şartname madde 5'in güvenlik kuralı).

Uyumluluk notu: v1.2'nin FADE/TREND + SignalResolver davranışı KORUNUR.
Mevcut çözümleyici "temel oy" (yüksek ağırlık) olarak Hakeme girer; Hakem
yalnızca uzmanların BÜYÜK ÇOĞUNLUĞU ters yönde güçlü oy verirse veto eder.
Böylece mevcut testler ve davranış bozulmadan çok oyculu mimari eklenir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import isfinite
from typing import Sequence

from core.config import ExpertConfig, SuperConfig
from core.indicators import ema, macd, rsi
from core.orderflow import OrderFlowSnapshot
from core.regime import MarketRegime, RegimeReading
from core.spike import candle_rvol
from infra.market_data.models import Candle

logger = logging.getLogger(__name__)

MOTORS = ("trend_hunter", "liquidity_hunter", "momentum_hunter", "reversal_hunter")


@dataclass(frozen=True)
class ExpertVote:
    motor: str
    side: str                 # "LONG" | "SHORT" | "NONE"
    confidence: float         # 0-1
    note: str = ""


@dataclass
class MotorPerformance:
    trades: int = 0
    wins: int = 0
    r_sum: float = 0.0
    weight: float = 1.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def avg_r(self) -> float:
        return self.r_sum / self.trades if self.trades else 0.0

    def as_dict(self) -> dict:
        return {
            "trades": self.trades,
            "win_rate": round(self.win_rate, 3),
            "avg_r": round(self.avg_r, 3),
            "weight": round(self.weight, 3),
        }


class ExpertPerformanceTracker:
    """Motor başına işlem sonucu takibi ve ağırlık adaptasyonu.

    Kayıt kaynağı: kapanan işlemler (paper/backtest). R > 0 → motor oyu
    doğruydu demektir; R < 0 → yanlıştı. Ağırlık:
        weight = clamp(1.0 + avg_r / 2.0, min_weight, max_weight)
    yalnızca `perf_min_trades` işlem birikince güncellenir.
    """

    def __init__(self, cfg: ExpertConfig) -> None:
        self.cfg = cfg
        self.stats: dict[str, MotorPerformance] = {
            m: MotorPerformance() for m in MOTORS
        }

    def record(self, motor: str, r_multiple: float) -> None:
        if motor not in self.stats:
            motor = "momentum_hunter"  # fade+trend birleşik sinyali
        perf = self.stats[motor]
        perf.trades += 1
        perf.r_sum += float(r_multiple)
        if r_multiple > 0:
            perf.wins += 1
        if perf.trades >= self.cfg.perf_min_trades:
            perf.weight = max(
                self.cfg.min_weight,
                min(self.cfg.max_weight, 1.0 + perf.avg_r / 2.0),
            )

    def weight_of(self, motor: str) -> float:
        return self.stats.get(motor, MotorPerformance()).weight

    def as_dict(self) -> dict:
        return {m: p.as_dict() for m, p in self.stats.items()}


# ---------------------------------------------------------------------------
# Uzman motorlar
# ---------------------------------------------------------------------------

class TrendHunter:
    """EMA20/50 yığını + MACD momentum + ADX tabanlı trend oyu."""

    def evaluate(
        self, candles: Sequence[Candle], regime: RegimeReading,
    ) -> ExpertVote:
        closes = [c.close for c in candles]
        if len(closes) < 60:
            return ExpertVote("trend_hunter", "NONE", 0.0, "warmup")
        fast = ema(closes, 20)[-1]
        slow = ema(closes, 50)[-1]
        macd_values = macd(closes)
        hist = macd_values.histogram[-1]
        if fast is None or slow is None or hist is None:
            return ExpertVote("trend_hunter", "NONE", 0.0, "gosterge_eksik")
        if regime.regime in (
            MarketRegime.STRONG_TREND_UP, MarketRegime.TREND_UP,
        ) and fast > slow and hist > 0:
            conf = 0.9 if regime.regime == MarketRegime.STRONG_TREND_UP else 0.7
            return ExpertVote("trend_hunter", "LONG", conf, "ema_macd_uyum")
        if regime.regime in (
            MarketRegime.STRONG_TREND_DOWN, MarketRegime.TREND_DOWN,
        ) and fast < slow and hist < 0:
            conf = 0.9 if regime.regime == MarketRegime.STRONG_TREND_DOWN else 0.7
            return ExpertVote("trend_hunter", "SHORT", conf, "ema_macd_uyum")
        return ExpertVote("trend_hunter", "NONE", 0.0, "trend_uyumu_yok")


class LiquidityHunter:
    """Süpürme-dönüş ve defter dengesizliğinden likidite oyu."""

    def evaluate(
        self,
        candles: Sequence[Candle],
        snapshot: OrderFlowSnapshot | None,
        regime: RegimeReading,
    ) -> ExpertVote:
        if snapshot is None:
            # Defter yoksa mum temelli süpürme-dönüşle sınırlı kalır
            if regime.regime == MarketRegime.RANGE and len(candles) >= 15:
                window = candles[-15:-1]  # son mum HARIÇ (süpürme karşılaştırması)
                last = candles[-1]
                prior_low = min(c.low for c in window)
                prior_high = max(c.high for c in window)
                mid = (prior_low + prior_high) / 2.0
                if last.low < prior_low and last.close > mid:
                    return ExpertVote(
                        "liquidity_hunter", "LONG", 0.4, "mum_supurme_donus",
                    )
                if last.high > prior_high and last.close < mid:
                    return ExpertVote(
                        "liquidity_hunter", "SHORT", 0.4, "mum_supurme_donus",
                    )
            return ExpertVote("liquidity_hunter", "NONE", 0.0, "defter_yok")
        # Defter varsa: dengesizlik + süpürme-dönüş birlikte
        imb = snapshot.imbalance
        sweep = snapshot.sweep_reversal
        if sweep.available and sweep.value > 0:
            side = "LONG" if "dip" in sweep.note else "SHORT"
            conf = 0.7
            if imb.available and ((imb.value > 0) == (side == "LONG")):
                conf = 0.85
            return ExpertVote("liquidity_hunter", side, conf, sweep.note)
        if imb.available and abs(imb.value) >= 0.34:
            side = "LONG" if imb.value > 0 else "SHORT"
            return ExpertVote(
                "liquidity_hunter", side, 0.4, f"defter_dengesizligi_{imb.note}",
            )
        return ExpertVote("liquidity_hunter", "NONE", 0.0, "likidite_ipucu_yok")


class MomentumHunter:
    """RVOL + 10dk bacak + MACD histogram ivmesinden momentum oyu."""

    def evaluate(self, candles: Sequence[Candle]) -> ExpertVote:
        closes = [c.close for c in candles]
        if len(closes) < 30:
            return ExpertVote("momentum_hunter", "NONE", 0.0, "warmup")
        rvol = candle_rvol([c.volume for c in candles], 20)
        impulse = (closes[-1] / closes[-3] - 1.0) * 100.0 if closes[-3] > 0 else 0.0
        macd_values = macd(closes)
        hist = macd_values.histogram[-1]
        prev_hist = macd_values.histogram[-2]
        accelerating = (
            hist is not None and prev_hist is not None
            and isfinite(hist) and isfinite(prev_hist)
            and abs(hist) > abs(prev_hist)
        )
        if rvol >= 2.0 and impulse >= 0.35 and accelerating and (hist or 0) > 0:
            return ExpertVote("momentum_hunter", "LONG", 0.75, "rvol_ivme_yukari")
        if rvol >= 2.0 and impulse <= -0.35 and accelerating and (hist or 0) < 0:
            return ExpertVote("momentum_hunter", "SHORT", 0.75, "rvol_ivme_asagi")
        return ExpertVote("momentum_hunter", "NONE", 0.0, "momentum_yok")


class ReversalHunter:
    """RSI aşırılığı + dönüş mumundan ters-vuruş oyu."""

    def __init__(self, cfg: ExpertConfig) -> None:
        self.cfg = cfg

    def evaluate(self, candles: Sequence[Candle]) -> ExpertVote:
        closes = [c.close for c in candles]
        if len(closes) < 30:
            return ExpertVote("reversal_hunter", "NONE", 0.0, "warmup")
        rsi_value = rsi(closes, 14)[-1]
        if rsi_value is None or not isfinite(rsi_value):
            return ExpertVote("reversal_hunter", "NONE", 0.0, "rsi_eksik")
        last = candles[-1]
        prev = candles[-2]
        bullish_close = last.close > last.open and last.close > prev.close
        bearish_close = last.close < last.open and last.close < prev.close
        if rsi_value <= self.cfg.reversal_rsi_low and bullish_close:
            return ExpertVote(
                "reversal_hunter", "LONG", 0.7, f"rsi={rsi_value:.0f}_donus",
            )
        if rsi_value >= self.cfg.reversal_rsi_high and bearish_close:
            return ExpertVote(
                "reversal_hunter", "SHORT", 0.7, f"rsi={rsi_value:.0f}_donus",
            )
        return ExpertVote("reversal_hunter", "NONE", 0.0, "asirilik_yok")


# ---------------------------------------------------------------------------
# Piyasa Hakemi
# ---------------------------------------------------------------------------

@dataclass
class JuryDecision:
    side: str                  # "LONG" | "SHORT" | "HOLD"
    vetoed: bool = False
    agree_bonus: float = 0.0   # uyum bonusu (skora yansır)
    votes: list[ExpertVote] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "vetoed": self.vetoed,
            "agree_bonus": round(self.agree_bonus, 3),
            "votes": [v.__dict__ for v in self.votes],
            "notes": self.notes,
        }


class MarketJudge:
    """Piyasa Hakemi: temel oy + 4 uzman oyu → son karar.

    Kural:
      - Temel oy (mevcut FADE/TREND çözümleyicisi) ağırlığı yüksek.
      - Temel oyun YÖNÜNE ters oyların ağırlıklı payı `veto_fraction`
        aşarsa → HOLD (veto).
      - Aynı yönde uzman oyları çoksa küçük uyum bonusu döner (skora).
    """

    def __init__(
        self,
        config: SuperConfig | None = None,
        performance: ExpertPerformanceTracker | None = None,
    ) -> None:
        self.config = config or SuperConfig()
        self.cfg = self.config.v2.experts
        self.trend = TrendHunter()
        self.liquidity = LiquidityHunter()
        self.momentum = MomentumHunter()
        self.reversal = ReversalHunter(self.cfg)
        self.performance = performance or ExpertPerformanceTracker(self.cfg)

    def collect_votes(
        self,
        candles: Sequence[Candle],
        regime: RegimeReading,
        snapshot: OrderFlowSnapshot | None,
    ) -> list[ExpertVote]:
        return [
            self.trend.evaluate(candles, regime),
            self.liquidity.evaluate(candles, snapshot, regime),
            self.momentum.evaluate(candles),
            self.reversal.evaluate(candles),
        ]

    def judge(
        self,
        base_side: str,
        base_confidence: float,
        votes: list[ExpertVote],
    ) -> JuryDecision:
        decision = JuryDecision(side=base_side, votes=votes)
        if base_side == "HOLD":
            decision.notes.append("temel_oy_hold")
            return decision
        opposite = "SHORT" if base_side == "LONG" else "LONG"
        base_w = self.cfg.base_vote_weight * max(0.2, min(1.0, base_confidence))
        opposite_w = 0.0
        agree_w = 0.0
        for vote in votes:
            w = self.performance.weight_of(vote.motor) * vote.confidence
            if vote.side == opposite:
                opposite_w += w
            elif vote.side == base_side:
                agree_w += w
        total = base_w + opposite_w + agree_w
        if total > 0 and opposite_w / total >= self.cfg.veto_fraction:
            decision.side = "HOLD"
            decision.vetoed = True
            decision.notes.append(
                f"hakem_veto: ters_oy_orani={opposite_w / total:.2f}"
            )
            return decision
        if total > 0:
            decision.agree_bonus = min(0.2, agree_w / total * 0.3)
        return decision
