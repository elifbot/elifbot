"""ACARBOT v2.0 — Akıllı piyasa rejimi ve strateji seçimi (şartname madde 1).

Bot her piyasada aynı stratejiyle işlem yapmamalı. Piyasa otomatik
sınıflandırılır ve kullanılacak motor önerilir:

    Piyasa durumu          Kullanılacak motor
    -------------------    --------------------
    Güçlü yükseliş         TREND LONG
    Güçlü düşüş            TREND SHORT
    Yatay piyasa           FADE
    Ani volatilite         SPIKE + teyit
    Sahte kırılım          İşlem engeli
    Belirsiz piyasa        Bekleme

Sınıflandırma yalnızca ADX'e bırakılmaz; birlikte değerlendirilir:
  - EMA20/50 konumu ve EMA20 EĞİMİ (fiyata normalize)
  - ATR değişimi (volatilite genişlemesi/daralması)
  - Hacim (RVOL)
  - Piyasa yapısı (swing yüksek/düşük: HH-HL / LH-LL)
  - BTC yönü (dışarıdan beslenir)

v1.2'deki `RegimeDetector` (ADX + EMA20/50) AYNEN korunur; bu sınıf
onun üstüne eklenen zenginleştirilmiş katmandır (mevcut testler bozulmaz).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Sequence

from core.config import SignalConfig, SuperConfig
from core.indicators import adx, atr, ema
from core.spike import candle_rvol
from infra.market_data.models import Candle


class MarketRegime(str, Enum):
    STRONG_TREND_UP = "STRONG_TREND_UP"
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    RANGE = "RANGE"
    SPIKE_VOLATILE = "SPIKE_VOLATILE"
    FAKE_BREAKOUT_RISK = "FAKE_BREAKOUT_RISK"
    UNCERTAIN = "UNCERTAIN"


# Şartname tablosundaki motor önerisi
ENGINE_SUGGESTION: dict[str, str] = {
    MarketRegime.STRONG_TREND_UP.value: "TREND_LONG",
    MarketRegime.TREND_UP.value: "TREND_LONG",
    MarketRegime.STRONG_TREND_DOWN.value: "TREND_SHORT",
    MarketRegime.TREND_DOWN.value: "TREND_SHORT",
    MarketRegime.RANGE.value: "FADE",
    MarketRegime.SPIKE_VOLATILE.value: "SPIKE_CONFIRM",
    MarketRegime.FAKE_BREAKOUT_RISK.value: "BLOCK",
    MarketRegime.UNCERTAIN.value: "WAIT",
}


@dataclass
class RegimeReading:
    """Rejim okuması: sınıf + şeffaf gerekçe (dashboard/skor kullanır)."""
    regime: MarketRegime
    engine_suggestion: str
    adx: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema20_slope_pct: float = 0.0           # son 3 bar EMA20 eğimi (%)
    atr_ratio: float = 1.0                 # ATR(14) / uzun ATR ortalaması
    rvol: float = 1.0
    structure: str = "NEUTRAL"             # UP | DOWN | NEUTRAL
    btc_direction: str = "NEUTRAL"         # UP | DOWN | NEUTRAL
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "engine": self.engine_suggestion,
            "adx": None if self.adx is None else round(self.adx, 2),
            "ema20_slope_pct": round(self.ema20_slope_pct, 4),
            "atr_ratio": round(self.atr_ratio, 3),
            "rvol": round(self.rvol, 3),
            "structure": self.structure,
            "btc_direction": self.btc_direction,
            "notes": self.notes,
        }


def _swing_structure(
    highs: Sequence[float], lows: Sequence[float], lookback: int = 60,
) -> str:
    """Son `lookback` barda swing yüksek/düşüklerle yapı tespiti (HH-HL / LH-LL)."""
    window = list(zip(highs[-lookback:], lows[-lookback:]))
    if len(window) < 9:
        return "NEUTRAL"
    swing_highs: list[float] = []
    swing_lows: list[float] = []
    for i in range(2, len(window) - 2):
        h = window[i][0]
        lo = window[i][1]
        if (
            h > window[i - 1][0] and h > window[i - 2][0]
            and h > window[i + 1][0] and h > window[i + 2][0]
        ):
            swing_highs.append(h)
        if (
            lo < window[i - 1][1] and lo < window[i - 2][1]
            and lo < window[i + 1][1] and lo < window[i + 2][1]
        ):
            swing_lows.append(lo)
    up = down = 0
    if len(swing_highs) >= 2:
        up += swing_highs[-1] > swing_highs[-2]
        down += swing_highs[-1] < swing_highs[-2]
    if len(swing_lows) >= 2:
        up += swing_lows[-1] > swing_lows[-2]
        down += swing_lows[-1] < swing_lows[-2]
    if up > down:
        return "UP"
    if down > up:
        return "DOWN"
    return "NEUTRAL"


class SmartRegimeDetector:
    """Şartname madde 1: çok girdili piyasa rejimi sınıflandırıcı."""

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        self.signal_cfg: SignalConfig = self.config.signal

    def classify(
        self,
        candles: Sequence[Candle],
        btc_change_pct_15m: float = 0.0,
    ) -> RegimeReading:
        cfg = self.signal_cfg
        if len(candles) < 60:
            return RegimeReading(
                regime=MarketRegime.UNCERTAIN,
                engine_suggestion=ENGINE_SUGGESTION[MarketRegime.UNCERTAIN.value],
                notes=["warmup"],
            )
        close = [c.close for c in candles]
        high = [c.high for c in candles]
        low = [c.low for c in candles]
        price = close[-1]
        reading = RegimeReading(
            regime=MarketRegime.UNCERTAIN,
            engine_suggestion=ENGINE_SUGGESTION[MarketRegime.UNCERTAIN.value],
        )

        try:
            movement = adx(high, low, close, cfg.regime_adx_period)
            reading.adx = movement.adx[-1]
        except Exception:
            reading.adx = None
        ema20_series = ema(close, 20)
        ema50_series = ema(close, 50)
        reading.ema20 = ema20_series[-1]
        reading.ema50 = ema50_series[-1]
        if any(v is None for v in (reading.adx, reading.ema20, reading.ema50)):
            reading.notes.append("gosterge_eksik")
            return reading
        adx_value = float(reading.adx)  # type: ignore[arg-type]
        ema20 = float(reading.ema20)    # type: ignore[arg-type]
        ema50 = float(reading.ema50)    # type: ignore[arg-type]

        # EMA20 eğimi: son 3 barda değişim, fiyatın yüzdesi olarak
        ema20_prev = ema20_series[-4] or ema20
        reading.ema20_slope_pct = (
            (ema20 - float(ema20_prev)) / price * 100.0 if price > 0 else 0.0
        )

        # ATR değişimi: kısa ATR / uzun pencere ortalaması
        atr_short = self._atr(high, low, close, cfg.regime_adx_period)
        atr_long = self._atr(high, low, close, 50)
        if atr_short is not None and atr_long is not None and atr_long > 0:
            reading.atr_ratio = atr_short / atr_long

        # Hacim
        reading.rvol = candle_rvol(
            [c.volume for c in candles], cfg.candle_rvol_lookback,
        )

        # Piyasa yapısı + BTC yönü
        reading.structure = _swing_structure(high, low)
        if btc_change_pct_15m >= cfg.btc_block_change_pct:
            reading.btc_direction = "UP"
        elif btc_change_pct_15m <= -cfg.btc_block_change_pct:
            reading.btc_direction = "DOWN"

        slope = reading.ema20_slope_pct
        slope_up = slope > 0.02
        slope_down = slope < -0.02

        reading.regime = self._decide(
            adx_value=adx_value,
            ema20=ema20, ema50=ema50,
            slope_up=slope_up, slope_down=slope_down,
            atr_ratio=reading.atr_ratio, rvol=reading.rvol,
            structure=reading.structure,
            candles=candles,
        )
        reading.engine_suggestion = ENGINE_SUGGESTION[reading.regime.value]
        return reading

    # ------------------------------------------------------------------

    def _decide(
        self,
        adx_value: float,
        ema20: float, ema50: float,
        slope_up: bool, slope_down: bool,
        atr_ratio: float, rvol: float,
        structure: str,
        candles: Sequence[Candle],
    ) -> MarketRegime:
        # 1) Sahte kırılım riski: son mum yakın zirve/dip kırılımı + uzun fitil
        if self._fake_breakout(candles):
            return MarketRegime.FAKE_BREAKOUT_RISK
        # 2) Ani volatilite: ATR genişlemesi + hacim patlaması
        if atr_ratio >= 1.8 and rvol >= 3.0:
            return MarketRegime.SPIKE_VOLATILE
        # 3) Güçlü trend: ADX + EMA konumu + eğim + yapı uyumlu
        strong = adx_value >= self.signal_cfg.regime_adx_strong_trend
        up_stack = ema20 > ema50 and slope_up
        down_stack = ema20 < ema50 and slope_down
        if strong and up_stack and structure in {"UP", "NEUTRAL"}:
            return MarketRegime.STRONG_TREND_UP
        if strong and down_stack and structure in {"DOWN", "NEUTRAL"}:
            return MarketRegime.STRONG_TREND_DOWN
        # 4) Normal trend: ADX eşiği üstü + EMA konumu
        if adx_value >= self.signal_cfg.regime_adx_trend_threshold:
            if ema20 > ema50:
                return MarketRegime.TREND_UP
            return MarketRegime.TREND_DOWN
        # 5) Yatay: ADX düşük ve yapı nötr
        if structure == "NEUTRAL":
            return MarketRegime.RANGE
        # 6) Çelişkili göstergeler: belirsiz → bekle
        return MarketRegime.UNCERTAIN

    def _fake_breakout(self, candles: Sequence[Candle]) -> bool:
        """Son mum yakın (20 bar) zirve/dip kırdıysa ama fitili gövdeden uzunsa."""
        if len(candles) < 21:
            return False
        cfg = self.signal_cfg
        last = candles[-1]
        body = abs(last.close - last.open)
        wick = last.high - last.low
        if body < last.close * cfg.fake_breakout_min_body_pct:
            return False
        prior_high = max(c.high for c in candles[-21:-1])
        prior_low = min(c.low for c in candles[-21:-1])
        broke_up = last.high > prior_high
        broke_down = last.low < prior_low
        if not (broke_up or broke_down):
            return False
        return wick > body / max(cfg.fake_breakout_wick_ratio, 1e-9)

    @staticmethod
    def _atr(high, low, close, period: int) -> float | None:
        try:
            value = atr(high, low, close, period)[-1]
        except Exception:
            return None
        if value is None or not isfinite(value) or value <= 0:
            return None
        return float(value)
