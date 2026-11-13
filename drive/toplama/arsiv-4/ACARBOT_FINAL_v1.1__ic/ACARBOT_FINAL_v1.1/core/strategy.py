"""İki motorlu strateji — süper sürüm.

Yorum 2, madde 2'deki yön çelişkisi giderildi:

  ESKİ: canlı yolda spike yönü + FADE (yalnız LONG) + Trend onayı aynı anda
  isteniyordu → SHORT canlıda hiç açılamıyor, LONG da neredeyse imkânsızdı.

  YENİ: hacim patlaması bir "tetikleyici"dir, yön dikte etmez. Her motor
  bağımsız olarak LONG ve SHORT üretebilir:

      Patlama YUKARI → FADE-LONG (düşüşü ters çevirme) VEYA TREND-LONG (kırılım)
      Patlama AŞAĞI  → FADE-SHORT (rally'yi ters çevirme) VEYA TREND-SHORT

  Aynı tarafa iki motor da sinyal verirse güven artar; zıt sinyallerde
  rejim kararı verir (ADX >= eşik → trend motoru kazanır, değilse FADE;
  bu da netleşmezse çakışma → HOLD).

Ek filtreler (Yorum 1 E):
  - Rejim tespiti (ADX + EMA20/50) : TREND_UP / TREND_DOWN / RANGE
  - BTC yön filtresi               : ters yönde sinyali engeller/küçültür
  - Sahte kırılım filtresi          : fitil oranı + aşırı RVOL şüphesi
  - "Düşen bıçak" koruması          : FADE-LONG için son 5s toparlanma şartı
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Sequence

from core.config import SignalConfig, SuperConfig
from core.indicators import adx, atr, ema, macd
from core.spike import SpikeEvent, candle_rvol
from infra.market_data.models import Candle  # noqa: F401  (tip uyumluluğu)


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Signal:
    side: str                      # "LONG" | "SHORT" | "HOLD"
    motor: str                     # "fade" | "trend"
    impulse_pct: float
    rvol: float
    stop_distance_fraction: float | None
    take_profit: float | None = None
    confidence: float = 0.0
    rejection_code: str | None = None
    reason: str = ""


@dataclass
class MarketContext:
    """Bir sembolün değerlendirme bağlamı (canlı ve backtest ortak)."""
    symbol: str
    candles: Sequence[Candle]              # kapanmış 5m mumlar (en yeni sonda)
    spike: SpikeEvent | None = None
    btc_change_pct_15m: float = 0.0        # BTC son 3x5m mum değişimi
    config: SuperConfig = field(default_factory=SuperConfig)

    def closes(self) -> list[float]:
        return [c.close for c in self.candles]

    def volumes(self) -> list[float]:
        return [c.volume for c in self.candles]


class RegimeDetector:
    """ADX + EMA20/50 ile piyasa rejimi sınıflandırması (Yorum 1 E)."""

    def __init__(self, config: SignalConfig | None = None) -> None:
        cfg = config or SignalConfig()
        self.adx_period = cfg.regime_adx_period
        self.trend_threshold = cfg.regime_adx_trend_threshold

    def classify(self, candles: Sequence[Candle]) -> Regime:
        if len(candles) < 60:
            return Regime.UNKNOWN
        close = [c.close for c in candles]
        high = [c.high for c in candles]
        low = [c.low for c in candles]
        try:
            movement = adx(high, low, close, self.adx_period)
            adx_value = movement.adx[-1]
        except Exception:
            return Regime.UNKNOWN
        if adx_value is None or not isfinite(adx_value):
            return Regime.UNKNOWN
        ema20 = ema(close, 20)[-1]
        ema50 = ema(close, 50)[-1]
        if ema20 is None or ema50 is None:
            return Regime.UNKNOWN
        if adx_value < self.trend_threshold:
            return Regime.RANGE
        if ema20 > ema50:
            return Regime.TREND_UP
        return Regime.TREND_DOWN


class BtcDirectionFilter:
    """BTC son 15 dakikalık yönü, altcoin sinyallerini engelleyebilir (Y1-E).

    Kural: sinyal yönü BTC'nin 15dk hareketine TERS ise ve BTC o yönde
    `btc_block_change_pct`'i aşmışsa sinyal reddedilir (news şoku koruması).
    """

    def __init__(self, config: SignalConfig | None = None) -> None:
        cfg = config or SignalConfig()
        self.enabled = cfg.btc_filter_enabled
        self.block_change_pct = cfg.btc_block_change_pct

    def allows(self, side: str, btc_change_pct_15m: float) -> bool:
        if not self.enabled:
            return True
        if abs(btc_change_pct_15m) < self.block_change_pct:
            return True
        if side == "LONG" and btc_change_pct_15m <= -self.block_change_pct:
            return False
        if side == "SHORT" and btc_change_pct_15m >= self.block_change_pct:
            return False
        return True


class FakeBreakoutFilter:
    """Sahte kırılım koruması (Y1-E).

    - Son mumun fitili gövdesinden çok uzunsa (kırılımın paniği) reddet.
    - RVOL aşırı yüksekse (sanity cap üstü) veri şüphesi nedeniyle reddet.
    """

    def __init__(self, config: SignalConfig | None = None) -> None:
        cfg = config or SignalConfig()
        self.wick_ratio = cfg.fake_breakout_wick_ratio
        self.max_rvol = cfg.max_rvol_entry
        self.min_body_pct = cfg.fake_breakout_min_body_pct

    def allows(self, candles: Sequence[Candle], rvol: float) -> bool:
        if not candles:
            return False
        last = candles[-1]
        body = abs(last.close - last.open)
        wick = last.high - last.low
        if rvol > self.max_rvol:
            return False  # aşırı sapma: muhtemelen birim/veri hatası
        # Önemsiz gövde (yatay/sakin mum): fitil oranı anlamlı değil.
        if body < last.close * self.min_body_pct:
            return True
        # Anlamlı gövde + fitil gövdeden çok uzunsa paniğe dayalı kırılımdır.
        if wick > body / max(self.wick_ratio, 1e-9):
            return False
        return True


class FadeEngine:
    """Dip/satır sonu ters-vuruş motoru — LONG ve SHORT (Y2-2 düzeltmesi)."""

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        self.signal_cfg = self.config.signal

    def evaluate(self, ctx: MarketContext) -> Signal:
        cfg = self.signal_cfg
        candles = ctx.candles
        if len(candles) < 30:
            return Signal("HOLD", "fade", 0.0, 0.0, None, rejection_code="WARMUP")
        closes = ctx.closes()
        # 10 dakikalık bacak: close[-1] vs close[-3]
        impulse_pct = (closes[-1] / closes[-3] - 1.0) * 100.0 if closes[-3] > 0 else 0.0
        rvol = candle_rvol(ctx.volumes(), cfg.candle_rvol_lookback)

        # Spike tetikleyicisi: mum RVOL'u veya canlı spike olayı yeterli.
        has_trigger = rvol >= cfg.min_rvol_for_entry or (
            ctx.spike is not None
            and not ctx.spike.suspect
            and ctx.spike.rvol >= cfg.spike_multiplier
        )
        if not has_trigger:
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="dusuk_hacim")

        # Sahte kırılım / panik mumu filtresi
        if not FakeBreakoutFilter(cfg).allows(candles, rvol):
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="fake_breakout_or_suspect")

        regime = RegimeDetector(cfg).classify(candles)
        adx_value = self._adx(candles)
        if adx_value is not None and adx_value >= cfg.regime_adx_strong_trend:
            # Güçlü trendde ters vuruş = bıçak yakalama (Y1-E)
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="guclu_trend_fade_kapali")

        if impulse_pct <= -cfg.fade_impulse_pct:
            return self._fade_long(ctx, impulse_pct, rvol, regime)
        if impulse_pct >= cfg.fade_impulse_pct:
            return self._fade_short(ctx, impulse_pct, rvol, regime)
        return Signal("HOLD", "fade", impulse_pct, rvol, None,
                      rejection_code="fade_kosulu_yok")

    def _fade_long(self, ctx, impulse_pct, rvol, regime) -> Signal:
        cfg = self.signal_cfg
        closes = ctx.closes()
        # "Düşen bıçak" koruması: son mum kapanışı, önceki mumun düşüğünün
        # altında değilse toparlanma başlamış sayılır.
        last = ctx.candles[-1]
        prev = ctx.candles[-2]
        if last.close < prev.low:
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="dusen_bicak")
        if regime == Regime.TREND_DOWN and not BtcDirectionFilter(cfg).allows(
            "LONG", ctx.btc_change_pct_15m
        ):
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="btc_tersi")
        if not BtcDirectionFilter(cfg).allows("LONG", ctx.btc_change_pct_15m):
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="btc_tersi")
        stop_distance = self._stop_distance(ctx, "LONG")
        return Signal(
            side="LONG", motor="fade",
            impulse_pct=impulse_pct, rvol=rvol,
            stop_distance_fraction=stop_distance,
            confidence=min(1.0, rvol / (cfg.min_rvol_for_entry * 2.0)),
            reason=f"fade_long_dip rvol={rvol:.2f}",
        )

    def _fade_short(self, ctx, impulse_pct, rvol, regime) -> Signal:
        cfg = self.signal_cfg
        last = ctx.candles[-1]
        prev = ctx.candles[-2]
        # Ayna koruma: yükseliş bıçağı — son kapanış önceki mumun üstüğünden
        # yukarıdaysa hâlâ pump devam ediyor demektir.
        if last.close > prev.high:
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="yukselen_bicak")
        if not BtcDirectionFilter(cfg).allows("SHORT", ctx.btc_change_pct_15m):
            return Signal("HOLD", "fade", impulse_pct, rvol, None,
                          rejection_code="btc_tersi")
        stop_distance = self._stop_distance(ctx, "SHORT")
        return Signal(
            side="SHORT", motor="fade",
            impulse_pct=impulse_pct, rvol=rvol,
            stop_distance_fraction=stop_distance,
            confidence=min(1.0, rvol / (cfg.min_rvol_for_entry * 2.0)),
            reason=f"fade_short_zirve rvol={rvol:.2f}",
        )

    def _stop_distance(self, ctx, side: str) -> float:
        cfg = self.config.exit
        candles = ctx.candles
        high = [c.high for c in candles]
        low = [c.low for c in candles]
        close = [c.close for c in candles]
        atr_value = atr(high, low, close, cfg.atr_period)[-1]
        price = close[-1]
        if atr_value is None or not isfinite(atr_value) or atr_value <= 0:
            distance = cfg.min_stop_fraction
        else:
            distance = (cfg.stop_atr_multiple * atr_value) / price
        return min(max(distance, cfg.min_stop_fraction), cfg.max_stop_fraction)

    @staticmethod
    def _adx(candles: Sequence[Candle]) -> float | None:
        high = [c.high for c in candles]
        low = [c.low for c in candles]
        close = [c.close for c in candles]
        try:
            return adx(high, low, close, 14).adx[-1]
        except Exception:
            return None


class TrendEngine:
    """EMA20/50 + MACD trend motoru — LONG ve SHORT (Y2-2 düzeltmesi)."""

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        self.signal_cfg = self.config.signal

    def evaluate(self, ctx: MarketContext) -> Signal:
        cfg = self.signal_cfg
        candles = ctx.candles
        if len(candles) < cfg.trend_warmup_candles:
            return Signal("HOLD", "trend", 0.0, 0.0, None,
                          rejection_code="TREND_WARMUP")
        closes = ctx.closes()
        volumes = ctx.volumes()
        fast = ema(closes, 20)[-1]
        slow = ema(closes, 50)[-1]
        macd_values = macd(closes)
        line = macd_values.line[-1]
        signal_line = macd_values.signal[-1]
        hist = macd_values.histogram[-1]
        prev_hist = macd_values.histogram[-2]
        if any(v is None for v in (fast, slow, line, signal_line, hist, prev_hist)):
            return Signal("HOLD", "trend", 0.0, 0.0, None,
                          rejection_code="TREND_WARMUP")

        rvol = candle_rvol(volumes, cfg.candle_rvol_lookback)
        has_trigger = rvol >= cfg.min_rvol_for_entry or (
            ctx.spike is not None
            and not ctx.spike.suspect
            and ctx.spike.rvol >= cfg.spike_multiplier
        )
        if not has_trigger:
            return Signal("HOLD", "trend", 0.0, rvol, None,
                          rejection_code="dusuk_hacim")
        if not FakeBreakoutFilter(cfg).allows(candles, rvol):
            return Signal("HOLD", "trend", 0.0, rvol, None,
                          rejection_code="fake_breakout_or_suspect")

        side = "HOLD"
        if fast > slow and line > signal_line and hist > prev_hist:
            side = "LONG"
        elif fast < slow and line < signal_line and hist < prev_hist:
            side = "SHORT"
        if side == "HOLD":
            return Signal("HOLD", "trend", 0.0, rvol, None,
                          rejection_code="trend_onayi_yok")

        # Yükselişte geri çekilme / düşüşte tepki şartı: son 3 mumdan biri
        # EMA20'ye değdiyse giriş "geç kırılım" değil, geri çekilmedir.
        ema20_series = ema(closes, 20)
        touched = any(
            ema20_series[-i] is not None
            and candles[-i].low <= ema20_series[-i] <= candles[-i].high
            for i in (1, 2, 3)
        )
        if not touched:
            return Signal("HOLD", "trend", 0.0, rvol, None,
                          rejection_code="geri_cekilme_yok")

        if not BtcDirectionFilter(cfg).allows(side, ctx.btc_change_pct_15m):
            return Signal("HOLD", "trend", 0.0, rvol, None,
                          rejection_code="btc_tersi")

        fade = FadeEngine(self.config)
        stop_distance = fade._stop_distance(ctx, side)
        return Signal(
            side=side, motor="trend",
            impulse_pct=0.0, rvol=rvol,
            stop_distance_fraction=stop_distance,
            confidence=min(1.0, rvol / (cfg.min_rvol_for_entry * 2.0)),
            reason=f"trend_{side.lower()}_devam",
        )


class SignalResolver:
    """İki motorun sinyalini rejime göre birleştirir (Y2-2 çözümü)."""

    def __init__(self, config: SuperConfig | None = None) -> None:
        self.config = config or SuperConfig()
        self.threshold = self.config.signal.regime_adx_trend_threshold

    def resolve(self, fade: Signal, trend: Signal, regime: Regime) -> Signal:
        trend_side_ok = trend.side != "HOLD"
        fade_side_ok = fade.side != "HOLD"
        if fade_side_ok and trend_side_ok:
            if fade.side == trend.side:
                # İki motor aynı yönde: güveni artır, FADE'in stopunu kullan.
                return Signal(
                    side=fade.side, motor="fade+trend",
                    impulse_pct=fade.impulse_pct, rvol=max(fade.rvol, trend.rvol),
                    stop_distance_fraction=fade.stop_distance_fraction,
                    confidence=min(1.0, fade.confidence + trend.confidence),
                    reason="cift_motor_uyum",
                )
            # Zıt sinyaller: rejim karar verir.
            if regime in (Regime.TREND_UP, Regime.TREND_DOWN):
                return trend
            if regime == Regime.RANGE:
                return fade
            return Signal("HOLD", "resolver", fade.impulse_pct,
                          fade.rvol, None, rejection_code="sinyal_cakismasi")
        if fade_side_ok:
            if regime in (Regime.TREND_UP, Regime.TREND_DOWN) and fade.confidence < 0.5:
                # Trendde zayıf FADE sinyaline izin yok (rejim uyumu şartı).
                return Signal("HOLD", "fade", fade.impulse_pct, fade.rvol,
                              None, rejection_code="rejim_uyumsuz")
            return fade
        if trend_side_ok:
            if regime == Regime.RANGE:
                return Signal("HOLD", "trend", trend.impulse_pct, trend.rvol,
                              None, rejection_code="rejim_uyumsuz")
            return trend
        # İkisi de HOLD: en açıklayıcı red kodunu taşı.
        return fade if fade.rejection_code else trend
