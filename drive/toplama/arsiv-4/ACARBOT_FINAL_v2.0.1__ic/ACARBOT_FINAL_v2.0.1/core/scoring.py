"""ACARBOT v2.0 — Adaptif sinyal puanlama motoru (şartname madde 5).

Her sinyal 100 üzerinden puanlanır:

    Kriter               Ağırlık
    -----------------    -------
    Trend uyumu            20
    Hacim doğrulaması      15
    Order flow             20
    Likidite analizi       15
    MTF uyumu              15
    BTC korelasyonu        10
    Volatilite uygunluğu    5
    Toplam                100

    90-100 : çok güçlü sinyal
    80-89  : güçlü sinyal
    70-79  : normal sinyal
    70 altı: işlem yok

ÖNEMLİ KURALLAR:
  - Puanlama BAŞLANGIÇTA sabittir; ağırlıklar yalnızca backtest ve paper
    sonuçlarından elle/optimize edilerek güncellenir. Yapay zekâ canlıda
    kendi kendine işlem parametresi DEĞİŞTİRMEZ.
  - Verisi olmayan bileşen "uygulanmadı" işaretlenir; ağırlığı paydadan
    düşülür (yer tutucu puan yazılmaz). Uygulama ölçeği: mevcut ağırlık
    toplamına normalize edilir ve raporda `available_fraction` şeffaf
    belirtilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from core.config import ScoringConfig, SuperConfig
from core.orderflow import OrderFlowSnapshot
from core.regime import MarketRegime, RegimeReading
from core.mtf import MtfReading
from core.spike import candle_rvol
from infra.market_data.models import Candle


@dataclass
class ScoreComponent:
    name: str
    raw: float                      # 0..1 bileşen puanı
    weight: float
    available: bool = True
    note: str = ""

    @property
    def points(self) -> float:
        return self.raw * self.weight if self.available else 0.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "raw": round(self.raw, 3),
            "weight": self.weight,
            "points": round(self.points, 2),
            "available": self.available,
            "note": self.note,
        }


@dataclass
class SignalScore:
    total: float                    # 0-100 (mevcut bileşen ölçeğinde)
    grade: str                      # VERY_STRONG | STRONG | NORMAL | WEAK
    components: list[ScoreComponent] = field(default_factory=list)
    available_weight: float = 0.0
    available_fraction: float = 1.0
    tradeable: bool = False

    def as_dict(self) -> dict:
        return {
            "total": round(self.total, 2),
            "grade": self.grade,
            "tradeable": self.tradeable,
            "available_weight": round(self.available_weight, 2),
            "available_fraction": round(self.available_fraction, 3),
            "components": [c.as_dict() for c in self.components],
        }


class SignalScorer:
    """Şartnamedeki ağırlık tablosuyla sinyal puanlar."""

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        self.cfg: ScoringConfig = self.config.v2.scoring

    # ------------------------------------------------------------------
    # Bileşen hesapları
    # ------------------------------------------------------------------

    def _trend_component(
        self, side: str, regime: RegimeReading, motor: str = "",
    ) -> ScoreComponent:
        """Sinyal yönünün rejim ve motor önerisiyle uyumu (ağırlık 20)."""
        suggestion = regime.engine_suggestion
        if side == "LONG":
            wanted = {"TREND_LONG"}
            opposed = {"TREND_SHORT", "BLOCK"}
        else:
            wanted = {"TREND_SHORT"}
            opposed = {"TREND_LONG", "BLOCK"}
        if suggestion in wanted:
            raw = 1.0 if regime.regime in (
                MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN,
            ) else 0.85
        elif suggestion == "FADE":
            # FADE önerisi: RANGE'de dönüş sinyalleri mantıklı
            raw = 0.7 if regime.regime == MarketRegime.RANGE else 0.45
        elif suggestion == "SPIKE_CONFIRM":
            # SPIKE + teyit: FADE/TREND sinyali bu rejimin doğal stratejisidir;
            # teyit diğer bileşenlerden (hacim/order flow/MTF) gelir.
            raw = 0.7
        elif suggestion in opposed:
            raw = 0.1
        else:  # WAIT / UNKNOWN
            raw = 0.3
        # Yapı ve BTC yönü desteği küçük koreksiyon
        if regime.structure == ("UP" if side == "LONG" else "DOWN"):
            raw = min(1.0, raw + 0.1)
        if regime.btc_direction == ("UP" if side == "LONG" else "DOWN"):
            raw = min(1.0, raw + 0.05)
        return ScoreComponent("trend", raw, self.cfg.weight_trend)

    def _volume_component(self, rvol: float) -> ScoreComponent:
        """Hacim doğrulaması (ağırlık 15): RVOL ölçekli."""
        if rvol >= 3.0:
            raw = 1.0
        elif rvol >= 2.0:
            raw = 0.85
        elif rvol >= 1.5:
            raw = 0.7
        elif rvol >= 1.0:
            raw = 0.4
        else:
            raw = 0.1
        return ScoreComponent("volume", raw, self.cfg.weight_volume,
                              note=f"rvol={rvol:.2f}")

    def _orderflow_component(
        self, snapshot: OrderFlowSnapshot | None, side: str,
    ) -> ScoreComponent:
        """Order flow (ağırlık 20): mevcut alt ölçümlerin ortalaması."""
        if snapshot is None:
            return ScoreComponent(
                "orderflow", 0.0, self.cfg.weight_orderflow,
                available=False, note="veri_yok",
            )
        wanted = 1.0 if side == "LONG" else -1.0
        subs: list[tuple[float, str]] = []
        if snapshot.imbalance.available:
            subs.append((snapshot.imbalance.value * wanted, "imbalance"))
        if snapshot.big_orders.available:
            subs.append((snapshot.big_orders.value * wanted, "big_orders"))
        if snapshot.cvd.available:
            subs.append((snapshot.cvd.value * wanted, "cvd"))
        if snapshot.absorption.available:
            # Emilim şüphesi nötr-küçük destek kabul edilir
            subs.append((0.3, "absorption")
                        if "emilim" in snapshot.absorption.note else (0.0, "absorption"))
        if snapshot.oi_change.available:
            subs.append((snapshot.oi_change.value * wanted, "oi"))
        if snapshot.sweep_reversal.available and snapshot.sweep_reversal.value > 0:
            subs.append((snapshot.sweep_reversal.value, "sweep_reversal"))
        if not subs:
            return ScoreComponent(
                "orderflow", 0.0, self.cfg.weight_orderflow,
                available=False, note="alt_olcum_yok",
            )
        raw = max(0.0, min(1.0, sum(v for v, _ in subs) / len(subs) * 0.5 + 0.5))
        return ScoreComponent(
            "orderflow", raw, self.cfg.weight_orderflow,
            note=",".join(n for _, n in subs),
        )

    def _liquidity_component(
        self, snapshot: OrderFlowSnapshot | None, side: str,
    ) -> ScoreComponent:
        """Likidite analizi (ağırlık 15): kümeler + spread + süpürme."""
        if snapshot is None:
            return ScoreComponent(
                "liquidity", 0.0, self.cfg.weight_liquidity,
                available=False, note="defter_yok",
            )
        subs: list[tuple[float, str]] = []
        # Spread sağlığı
        if snapshot.spread_bps is not None:
            if snapshot.spread_bps <= 5.0:
                subs.append((1.0, "spread_saglikli"))
            elif snapshot.spread_bps <= 20.0:
                subs.append((0.5, "spread_genis"))
            else:
                subs.append((0.1, "spread_cok_genis"))
        # Sinyal yönündeki süpürme-dönüş güçlü likidite teyidi
        if snapshot.sweep_reversal.available and snapshot.sweep_reversal.value > 0:
            wanted_note_ok = (
                (side == "LONG" and "dip" in snapshot.sweep_reversal.note)
                or (side == "SHORT" and "zirve" in snapshot.sweep_reversal.note)
            )
            if wanted_note_ok:
                subs.append((1.0, "supurme_donus"))
        # Sinyal YÖNÜNDE duran büyük ask/bid kümesi = manyetik risk
        if snapshot.clusters:
            opposing_side = "ask" if side == "LONG" else "bid"
            near_opposing = any(
                c["side"] == opposing_side and c["distance_pct"] <= 0.35
                for c in snapshot.clusters
            )
            if near_opposing:
                subs.append((0.2, "yakin_karsi_kume"))
            else:
                subs.append((0.7, "kume_engel_yok"))
        if not subs:
            return ScoreComponent(
                "liquidity", 0.0, self.cfg.weight_liquidity,
                available=False, note="alt_olcum_yok",
            )
        raw = sum(v for v, _ in subs) / len(subs)
        return ScoreComponent(
            "liquidity", raw, self.cfg.weight_liquidity,
            note=",".join(n for _, n in subs),
        )

    def _mtf_component(self, mtf: MtfReading | None, side: str) -> ScoreComponent:
        """MTF uyumu (ağırlık 15)."""
        if mtf is None:
            return ScoreComponent(
                "mtf", 0.0, self.cfg.weight_mtf, available=False, note="veri_yok",
            )
        available = [b for b in mtf.biases.values() if b.available]
        if not available:
            return ScoreComponent(
                "mtf", 0.0, self.cfg.weight_mtf, available=False,
                note="ust_tf_uygulanmadi",
            )
        _, alignment = mtf.bias_for(side)
        return ScoreComponent(
            "mtf", alignment, self.cfg.weight_mtf,
            note=f"uyum={alignment:.2f}",
        )

    def _btc_component(self, btc_change_pct: float, side: str) -> ScoreComponent:
        """BTC korelasyonu (ağırlık 10)."""
        threshold = self.config.signal.btc_block_change_pct
        wanted_up = side == "LONG"
        if btc_change_pct >= threshold:
            direction = "UP"
        elif btc_change_pct <= -threshold:
            direction = "DOWN"
        else:
            return ScoreComponent("btc", 0.6, self.cfg.weight_btc,
                                  note="btc_notr")
        aligned = (direction == "UP") == wanted_up
        raw = 0.9 if aligned else 0.05
        return ScoreComponent("btc", raw, self.cfg.weight_btc,
                              note=f"btc_{direction.lower()}")

    def _volatility_component(self, regime: RegimeReading) -> ScoreComponent:
        """Volatilite uygunluğu (ağırlık 5): ATR oranı makul bandda mı?"""
        ratio = regime.atr_ratio
        if regime.regime == MarketRegime.SPIKE_VOLATILE:
            raw = 0.4  # ani volatilite: kayma riski var ama FADE'in doğal ortamı
        elif 0.7 <= ratio <= 1.8:
            raw = 1.0
        elif ratio < 0.7:
            raw = 0.5  # ölü volatilite: hedefe ulaşma riski
        else:
            raw = 0.4  # genişleme: kayma riski
        return ScoreComponent("volatility", raw, self.cfg.weight_volatility,
                              note=f"atr_oran={ratio:.2f}")

    # ------------------------------------------------------------------

    def score(
        self,
        side: str,
        regime: RegimeReading,
        rvol: float,
        candles: Sequence[Candle],
        btc_change_pct: float = 0.0,
        mtf: MtfReading | None = None,
        orderflow: OrderFlowSnapshot | None = None,
        motor: str = "",
    ) -> SignalScore:
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side LONG veya SHORT olmalı")
        components = [
            self._trend_component(side, regime, motor),
            self._volume_component(rvol),
            self._orderflow_component(orderflow, side),
            self._liquidity_component(orderflow, side),
            self._mtf_component(mtf, side),
            self._btc_component(btc_change_pct, side),
            self._volatility_component(regime),
        ]
        available_weight = sum(c.weight for c in components if c.available)
        points = sum(c.points for c in components if c.available)
        total = points / available_weight * 100.0 if available_weight > 0 else 0.0
        fraction = available_weight / self.cfg.total_weight
        if total >= self.cfg.very_strong_score:
            grade = "VERY_STRONG"
        elif total >= self.cfg.strong_score:
            grade = "STRONG"
        elif total >= self.cfg.min_score_to_trade:
            grade = "NORMAL"
        else:
            grade = "WEAK"
        return SignalScore(
            total=total,
            grade=grade,
            components=components,
            available_weight=available_weight,
            available_fraction=fraction,
            tradeable=total >= self.cfg.min_score_to_trade,
        )


def rvol_from_candles(candles: Sequence[Candle], lookback: int = 20) -> float:
    """5m mum RVOL (skorlama girişi için yardımcı)."""
    return candle_rvol([c.volume for c in candles], lookback)
