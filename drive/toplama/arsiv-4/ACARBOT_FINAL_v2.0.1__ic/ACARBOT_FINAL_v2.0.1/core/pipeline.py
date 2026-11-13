"""ACARBOT v2.0 — Ortak sinyal değerlendirme boru hattı.

Kural (v1.2'den devralınan ilke): BACKTEST, CANLI SİSTEMİ TEST EDER.
Bu modül hem Executor (canlı) hem BacktestEngine tarafından kullanılır;
rejim → uzmanlar → MTF → skorlama zinciri TEK yerde tanımlıdır.

Zincir (şartname 1, 2, 5 + uzman mimarisi):
  1. Akıllı rejim (EMA eğimi + ATR değişimi + hacim + yapı + BTC)
  2. Temel sinyal (v1.2 FADE/TREND çözümleyicisi — davranış korunur)
  3. 4 uzman oyu + Piyasa Hakemi (veto / uyum bonusu)
  4. MTF çelişki kapısı (güçlü ters TF → engel)
  5. 100 puanlık skor → <70 işlem yok
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from core.config import SuperConfig
from core.experts import ExpertVote, JuryDecision, MarketJudge
from core.mtf import MtfAnalyzer, MtfReading
from core.orderflow import OrderFlowSnapshot
from core.regime import RegimeReading, SmartRegimeDetector
from core.scoring import SignalScore, SignalScorer
from core.spike import SpikeEvent, candle_rvol
from core.strategy import (
    FadeEngine,
    MarketContext,
    RegimeDetector,
    Signal,
    SignalResolver,
    TrendEngine,
)
from infra.market_data.models import Candle


@dataclass
class PipelineDecision:
    symbol: str
    signal: Signal                     # HOLD veya LONG/SHORT
    regime: RegimeReading
    rvol: float = 0.0
    score: SignalScore | None = None
    mtf: MtfReading | None = None
    orderflow: OrderFlowSnapshot | None = None
    jury: JuryDecision | None = None
    votes: list[ExpertVote] = field(default_factory=list)
    rejection_code: str | None = None

    @property
    def side(self) -> str:
        return self.signal.side

    def reason_text(self) -> str:
        """Dashboard 'neden işlem açmadı' metni."""
        if self.side != "HOLD":
            return (
                f"{self.side} skor={self.score.total:.0f}"
                if self.score else self.side
            )
        code = self.rejection_code or self.signal.rejection_code or "sinyal_yok"
        if self.score is not None and code == "dusuk_puan":
            return f"skor düşük ({self.score.total:.0f} < eşik)"
        labels = {
            "hakem_veto": "Piyasa Hakemi veto (uzman çoğunluğu ters)",
            "mtf_uyumsuz": "MTF uyumsuz (üst zaman dilimleri ters)",
            "dusuk_hacim": "hacim yetersiz (RVOL düşük)",
            "fake_breakout_or_suspect": "sahte kırılım / şüpheli veri",
            "btc_tersi": "BTC yön filtresi başarısız",
            "guclu_trend_fade_kapali": "güçlü trendde FADE kapalı",
            "rejim_uyumsuz": "rejim-motor uyumsuzluğu",
            "dusen_bicak": "düşen bıçak koruması",
            "yukselen_bicak": "yükselen bıçak koruması",
            "sinyal_cakismasi": "motor sinyalleri çakışıyor",
            "trend_onayi_yok": "trend onayı yok",
            "geri_cekilme_yok": "geri çekilme şartı yok",
            "fade_kosulu_yok": "FADE koşulu yok",
            "WARMUP": "ısınma dönemi",
            "TREND_WARMUP": "trend ısınma dönemi",
        }
        return labels.get(code, code)


class SignalPipeline:
    """Canlı ve backtest ortak değerlendirici."""

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        self.fade = FadeEngine(self.config)
        self.trend = TrendEngine(self.config)
        self.resolver = SignalResolver(self.config)
        self.legacy_regime = RegimeDetector(self.config.signal)
        self.smart_regime = SmartRegimeDetector(self.config)
        self.scorer = SignalScorer(self.config)
        self.mtf_analyzer = MtfAnalyzer(self.config.v2.mtf)
        self.judge = MarketJudge(self.config)

    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        candles: Sequence[Candle],
        btc_change_pct_15m: float = 0.0,
        spike: SpikeEvent | None = None,
        mtf_reading: MtfReading | None = None,
        orderflow_snapshot: OrderFlowSnapshot | None = None,
        orderflow_engine=None,
        orderflow_key: str | None = None,
    ) -> PipelineDecision:
        cfg = self.config
        regime = self.smart_regime.classify(candles, btc_change_pct_15m)
        rvol = candle_rvol(
            [c.volume for c in candles], cfg.signal.candle_rvol_lookback,
        )
        decision = PipelineDecision(
            symbol=symbol, signal=Signal(
                "HOLD", "pipeline", 0.0, rvol, None,
                rejection_code="WARMUP",
            ),
            regime=regime, rvol=rvol, mtf=mtf_reading,
            orderflow=orderflow_snapshot,
        )
        if len(candles) < 30:
            decision.rejection_code = "WARMUP"
            return decision

        # 2) Temel sinyal (v1.2 davranışı)
        ctx = MarketContext(
            symbol=symbol, candles=candles, spike=spike,
            btc_change_pct_15m=btc_change_pct_15m, config=cfg,
        )
        legacy_regime = self.legacy_regime.classify(candles)
        fade_signal = self.fade.evaluate(ctx)
        trend_signal = self.trend.evaluate(ctx)
        signal = self.resolver.resolve(fade_signal, trend_signal, legacy_regime)
        decision.signal = signal
        if signal.side == "HOLD":
            decision.rejection_code = signal.rejection_code
            return decision

        # Order flow anlık görüntüsü (canlı: GERÇEK defter + CVD + OI;
        # yön belli olduktan sonra süpürme-dönüş bileşeni de eklenir).
        if orderflow_snapshot is None and orderflow_engine is not None and orderflow_key:
            orderflow_snapshot = orderflow_engine.snapshot_for(
                orderflow_key, candles, signal.side,
            )
            decision.orderflow = orderflow_snapshot

        # 3) Uzmanlar + Hakem (şartname: son kararı Hakem verir)
        if cfg.v2.enabled and cfg.v2.experts.enabled:
            votes = self.judge.collect_votes(candles, regime, orderflow_snapshot)
            decision.votes = votes
            jury = self.judge.judge(
                signal.side, max(signal.confidence, 0.2), votes,
            )
            decision.jury = jury
            if jury.side == "HOLD":
                decision.signal = Signal(
                    "HOLD", signal.motor, signal.impulse_pct, signal.rvol,
                    signal.stop_distance_fraction,
                    rejection_code="hakem_veto",
                    reason=signal.reason,
                )
                decision.rejection_code = "hakem_veto"
                return decision

        # 4) MTF çelişki kapısı (şartname 2)
        if cfg.v2.enabled and cfg.v2.mtf.enabled:
            reading = mtf_reading
            if reading is None:
                reading = self.mtf_analyzer.analyze_resampled(candles)
                decision.mtf = reading
            block, alignment = self.mtf_analyzer.evaluate_conflict(
                reading, signal.side,
            )
            if block:
                decision.rejection_code = block
                decision.signal = Signal(
                    "HOLD", signal.motor, signal.impulse_pct, signal.rvol,
                    signal.stop_distance_fraction,
                    rejection_code=block, reason=signal.reason,
                )
                return decision

        # 5) Skorlama (şartname 5): <70 → işlem yok
        if cfg.v2.enabled:
            score = self.scorer.score(
                side=signal.side,
                regime=regime,
                rvol=rvol,
                candles=candles,
                btc_change_pct=btc_change_pct_15m,
                mtf=decision.mtf,
                orderflow=orderflow_snapshot,
            )
            if decision.jury is not None and decision.jury.agree_bonus > 0:
                bonus_points = decision.jury.agree_bonus * 10.0
                score.total = min(100.0, score.total + bonus_points)
                score.tradeable = (
                    score.total >= cfg.v2.scoring.min_score_to_trade
                )
            decision.score = score
            if not score.tradeable:
                decision.rejection_code = "dusuk_puan"
                decision.signal = Signal(
                    "HOLD", signal.motor, signal.impulse_pct, signal.rvol,
                    signal.stop_distance_fraction,
                    rejection_code="dusuk_puan", reason=signal.reason,
                )
                return decision
        return decision
