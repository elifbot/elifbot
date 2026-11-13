"""ACARBOT v4.0 — Ek strateji motorları + Confluence + seans filtresi.

Kullanıcı listesi (madde 6, 7, 9):
  - Seçilebilir stratejiler: rsirev, macd, bollkir, bolldon (--strategy)
  - Confluence stratejisi: 10 filtreli ağırlıklı oylama, eşik ayarlı
  - Seans (saat) filtresi: kapalı pencerede YENİ GİRİŞ yok

Sözleşme: tüm motorlar FadeEngine/TrendEngine ile AYNI arayüzü kullanır
(evaluate(MarketContext) -> Signal); pipeline'a "temel sinyal" üreticisi
olarak bağlanır. Böylece Hakem/MTF/skorlama zinciri ve canlı+backtest ortak
davranış AYNEN korunur. Stop mesafesi ATR tabanlıdır ve ExitConfig
min/max stop fraksiyonuna kırpılır (v1.2 risk zemini korunur).

MOTORLAR YALNIZ SİNYAL ÜRETİR; işlem kararı yine risk kapılarından geçer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

from core.indicators import atr, ema, macd, rsi
from core.spike import candle_rvol
from core.strategy import MarketContext, Signal

# Seans pencereleri (UTC saat aralıkları, başlangıç dâhil / bitiş hariç)
SESSION_WINDOWS: dict[str, tuple[int, int]] = {
    "asia": (0, 8),
    "eu": (7, 16),
    "us": (13, 22),
}


def session_blocks(session_filter: str, ts_ms: int) -> str | None:
    """Seans filtresi girişi engelliyorsa neden metni, değilse None.

    "off" → asla engellemez. "asia"/"eu"/"us" → hazır pencere.
    "HH-HH" (örn. "08-17") → özel UTC aralığı. Geçersiz değer → engellemez
    ve uyarı gerekçesi döndürülmez (fail-open, yanlış yapılandırma oturumu
    komple kilitlemesin).
    """
    value = (session_filter or "off").strip().lower()
    if value in ("", "off"):
        return None
    window = SESSION_WINDOWS.get(value)
    if window is None:
        try:
            start_s, end_s = value.split("-")
            window = (int(start_s) % 24, int(end_s) % 24)
        except ValueError:
            return None  # yapılandırma hatası → engelleme yok (fail-open)
    hour = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).hour
    start, end = window
    if start == end:
        return None  # 0 uzunluk = kapalı filtre
    if start < end:
        inside = start <= hour < end
    else:  # gece yarısını saran aralık (örn. 22-06)
        inside = hour >= start or hour < end
    if inside:
        return None
    return f"seans filtresi ({value} dışı, UTC {hour}:00)"


def _stop_distance(ctx: MarketContext, side: str, multiple: float = 1.5) -> float | None:
    """ATR tabanlı stop mesafesi (ExitConfig min/max fraksiyonuna kırpılır)."""
    candles = ctx.candles
    if len(candles) < 20:
        return None
    exit_cfg = ctx.config.exit
    value = atr(
        [c.high for c in candles[-100:]],
        [c.low for c in candles[-100:]],
        [c.close for c in candles[-100:]],
        exit_cfg.atr_period,
    )[-1]
    price = candles[-1].close
    if not value or value <= 0 or price <= 0 or not isfinite(value):
        return None
    fraction = (value * multiple) / price
    return min(max(fraction, exit_cfg.min_stop_fraction), exit_cfg.max_stop_fraction)


def _hold(motor: str, ctx: MarketContext, code: str) -> Signal:
    last = ctx.candles[-1] if ctx.candles else None
    prev = ctx.candles[-3] if len(ctx.candles) >= 3 else None
    impulse = (
        (last.close / prev.close - 1.0) * 100.0
        if last and prev and prev.close > 0 else 0.0
    )
    rvol = candle_rvol(ctx.volumes(), ctx.config.signal.candle_rvol_lookback)
    return Signal("HOLD", motor, impulse, rvol, None, rejection_code=code)


class RsiRevEngine:
    """rsirev — RSI aşırı uç dönüş motoru (madde 7)."""

    motor = "rsirev"

    def __init__(self, config) -> None:
        self.cfg = config.signal

    def evaluate(self, ctx: MarketContext) -> Signal:
        candles = ctx.candles
        if len(candles) < 30:
            return _hold(self.motor, ctx, "WARMUP")
        closes = ctx.closes()
        r = rsi(closes, 14)
        last_r, prev_r = r[-1], r[-2]
        if last_r is None or prev_r is None or not isfinite(last_r):
            return _hold(self.motor, ctx, "veri_yetersiz")
        stop = _stop_distance(ctx, "LONG")
        if stop is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        rvol = candle_rvol(ctx.volumes(), self.cfg.candle_rvol_lookback)
        if last_r <= 30.0 and last_r > prev_r:
            return Signal(
                "LONG", self.motor, (50.0 - last_r) / 10.0, rvol, stop,
                confidence=min(1.0, (30.0 - last_r) / 20.0 + 0.3),
                reason=f"rsirev_long rsi={last_r:.1f} dönüş",
            )
        if last_r >= 70.0 and last_r < prev_r:
            return Signal(
                "SHORT", self.motor, (last_r - 50.0) / 10.0, rvol, stop,
                confidence=min(1.0, (last_r - 70.0) / 20.0 + 0.3),
                reason=f"rsirev_short rsi={last_r:.1f} dönüş",
            )
        return _hold(self.motor, ctx, "rsirev_kosulu_yok")


class MacdEngine:
    """macd — MACD histogram/kesişim motoru (madde 7)."""

    motor = "macd"

    def __init__(self, config) -> None:
        self.cfg = config.signal

    def evaluate(self, ctx: MarketContext) -> Signal:
        candles = ctx.candles
        if len(candles) < 40:
            return _hold(self.motor, ctx, "WARMUP")
        closes = ctx.closes()
        block = macd(closes, 12, 26, 9)
        hist = block.histogram
        if hist is None or len(hist) < 2 or hist[-1] is None or hist[-2] is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        stop = _stop_distance(ctx, "LONG")
        if stop is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        rvol = candle_rvol(ctx.volumes(), self.cfg.candle_rvol_lookback)
        # Hacim kapısı: klasik motorlarla aynı veri sağlığı standardı
        if rvol < self.cfg.min_rvol_for_entry:
            return _hold(self.motor, ctx, "dusuk_hacim")
        cross_up = hist[-2] <= 0 < hist[-1]
        cross_down = hist[-2] >= 0 > hist[-1]
        impulse = (closes[-1] / closes[-3] - 1.0) * 100.0
        if cross_up:
            return Signal(
                "LONG", self.motor, impulse, rvol, stop,
                confidence=min(1.0, abs(hist[-1]) / (abs(closes[-1]) * 0.001) + 0.3),
                reason=f"macd_long hist +{hist[-1]:.4g}",
            )
        if cross_down:
            return Signal(
                "SHORT", self.motor, impulse, rvol, stop,
                confidence=min(1.0, abs(hist[-1]) / (abs(closes[-1]) * 0.001) + 0.3),
                reason=f"macd_short hist {hist[-1]:.4g}",
            )
        return _hold(self.motor, ctx, "macd_kesisim_yok")


class BollBreakEngine:
    """bollkir — Bollinger kırılım (breakout) motoru (madde 7)."""

    motor = "bollkir"

    def __init__(self, config) -> None:
        self.cfg = config.signal

    def _bands(self, closes: list[float]) -> tuple[float, float, float] | None:
        window = closes[-20:]
        if len(window) < 20:
            return None
        mean = sum(window) / len(window)
        variance = sum((c - mean) ** 2 for c in window) / len(window)
        sd = variance ** 0.5
        return mean - 2 * sd, mean, mean + 2 * sd

    def evaluate(self, ctx: MarketContext) -> Signal:
        candles = ctx.candles
        if len(candles) < 30:
            return _hold(self.motor, ctx, "WARMUP")
        closes = ctx.closes()
        bands = self._bands(closes[:-1])  # kırılım ÖNCEKİ bantlara göre
        if bands is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        lower, mid, upper = bands
        last = candles[-1]
        stop = _stop_distance(ctx, "LONG")
        if stop is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        rvol = candle_rvol(ctx.volumes(), self.cfg.candle_rvol_lookback)
        if rvol < self.cfg.min_rvol_for_entry:
            return _hold(self.motor, ctx, "dusuk_hacim")
        impulse = (closes[-1] / closes[-3] - 1.0) * 100.0
        body = abs(last.close - last.open)
        wick = last.high - last.low
        if last.close > upper and last.close > last.open:
            # fitil/gövde sahte kırılım koruması (v1.2 kuralı)
            if body > 0 and wick > body / max(
                self.cfg.fake_breakout_wick_ratio, 1e-9,
            ):
                return _hold(self.motor, ctx, "fake_breakout_or_suspect")
            return Signal(
                "LONG", self.motor, impulse, rvol, stop,
                confidence=min(1.0, rvol / (self.cfg.min_rvol_for_entry * 2.0)),
                reason=f"bollkir_long üst bant {upper:.6g} kırıldı",
            )
        if last.close < lower and last.close < last.open:
            if body > 0 and wick > body / max(
                self.cfg.fake_breakout_wick_ratio, 1e-9,
            ):
                return _hold(self.motor, ctx, "fake_breakout_or_suspect")
            return Signal(
                "SHORT", self.motor, impulse, rvol, stop,
                confidence=min(1.0, rvol / (self.cfg.min_rvol_for_entry * 2.0)),
                reason=f"bollkir_short alt bant {lower:.6g} kırıldı",
            )
        return _hold(self.motor, ctx, "bollkir_kosulu_yok")


class BollRevEngine:
    """bolldon — Bollinger ortalamaya dönüş motoru (madde 7)."""

    motor = "bolldon"

    def __init__(self, config) -> None:
        self.cfg = config.signal

    def evaluate(self, ctx: MarketContext) -> Signal:
        candles = ctx.candles
        if len(candles) < 30:
            return _hold(self.motor, ctx, "WARMUP")
        closes = ctx.closes()
        window = closes[-20:]
        mean = sum(window) / len(window)
        sd = (sum((c - mean) ** 2 for c in window) / len(window)) ** 0.5
        lower, upper = mean - 2 * sd, mean + 2 * sd
        last_close = closes[-1]
        stop = _stop_distance(ctx, "LONG")
        if stop is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        r = rsi(closes, 14)
        last_r = r[-1] if r and r[-1] is not None else 50.0
        rvol = candle_rvol(ctx.volumes(), self.cfg.candle_rvol_lookback)
        impulse = (last_close / closes[-3] - 1.0) * 100.0
        if last_close < lower and last_r <= 35.0:
            return Signal(
                "LONG", self.motor, impulse, rvol, stop,
                confidence=min(1.0, (mean - last_close) / max(sd, 1e-9) / 4.0 + 0.3),
                reason=f"bolldon_long alt bant + rsi {last_r:.0f}",
            )
        if last_close > upper and last_r >= 65.0:
            return Signal(
                "SHORT", self.motor, impulse, rvol, stop,
                confidence=min(1.0, (last_close - mean) / max(sd, 1e-9) / 4.0 + 0.3),
                reason=f"bolldon_short üst bant + rsi {last_r:.0f}",
            )
        return _hold(self.motor, ctx, "bolldon_kosulu_yok")


class ConfluenceEngine:
    """confluence — 10 filtreli ağırlıklı oylama, eşik ayarlı (madde 6).

    Her filtre -1 (ayı) / 0 (nötr) / +1 (boğa) oyu verir; ağırlıklı toplam
    toplam ağırlığa bölünerek [-1, 1] aralığına normalize edilir. |puan| ≥
    eşik (signal.confluence_threshold) ise yön verilir; altında HOLD
    ("confluence_yetersiz", gerekçede puan görünür).
    """

    motor = "confluence"

    # (ad, ağırlık) — ağırlıklar eşit (1.0): şeffaf ve ayarlanabilir taban
    FILTERS = (
        ("ema20_ema50", 1.0),
        ("fiyat_ema200", 1.0),
        ("macd_hist", 1.0),
        ("rsi_bolge", 1.0),
        ("rvol_yon", 1.0),
        ("yapi_kirilim", 1.0),
        ("btc_uyum", 1.0),
        ("atr_genislemesi", 1.0),
        ("momentum_serisi", 1.0),
        ("ema20_egimi", 1.0),
    )

    def __init__(self, config) -> None:
        self.cfg = config.signal

    # -- filtre oyları -------------------------------------------------------

    @staticmethod
    def _sign(value: float, epsilon: float = 1e-9) -> float:
        """Eşitlik nötrdür (düz piyasada sahte ayı/boğa oyu YOK)."""
        if value > epsilon:
            return 1.0
        if value < -epsilon:
            return -1.0
        return 0.0

    def _votes(self, ctx: MarketContext) -> dict[str, float]:
        candles = ctx.candles
        closes = ctx.closes()
        votes: dict[str, float] = {name: 0.0 for name, _ in self.FILTERS}
        if len(closes) >= 60:
            ema20 = ema(closes, 20)[-1]
            ema50 = ema(closes, 50)[-1]
            if None not in (ema20, ema50):
                votes["ema20_ema50"] = self._sign(ema20 - ema50)
                # uzun çapa: EMA200 varsa o, yoksa EMA50 (kısa geçmişte de
                # çalışır; canlıda candle_history=300 → EMA200 düzenli gelir)
                anchor = ema50
                if len(closes) >= 200:
                    ema200 = ema(closes, 200)[-1]
                    if ema200 is not None:
                        anchor = ema200
                votes["fiyat_ema200"] = self._sign(closes[-1] - anchor)
                if len(closes) >= 61:
                    ema20_prev = ema(closes[:-1], 20)[-1]
                    if ema20_prev is not None:
                        votes["ema20_egimi"] = self._sign(ema20 - ema20_prev)
        if len(closes) >= 40:
            block = macd(closes, 12, 26, 9)
            if block.histogram and block.histogram[-1] is not None:
                votes["macd_hist"] = self._sign(block.histogram[-1])
        if len(closes) >= 20:
            r = rsi(closes, 14)
            if r[-1] is not None and isfinite(r[-1]):
                if r[-1] >= 55.0:
                    votes["rsi_bolge"] = 1.0
                elif r[-1] <= 45.0:
                    votes["rsi_bolge"] = -1.0
            # yapi_kirilim: son kapanış 20 mumluk yüksek/düşük kırılımı
            window = closes[-21:-1]
            if window:
                if closes[-1] > max(window):
                    votes["yapi_kirilim"] = 1.0
                elif closes[-1] < min(window):
                    votes["yapi_kirilim"] = -1.0
            # rvol_yon: hacim onaylı son mum yönü
            rvol = candle_rvol(ctx.volumes(), self.cfg.candle_rvol_lookback)
            body_dir = 1.0 if candles[-1].close > candles[-1].open else -1.0
            if rvol >= self.cfg.min_rvol_for_entry:
                votes["rvol_yon"] = body_dir
            # momentum_serisi: son 3 mum aynı yönlü mü
            if len(closes) >= 4:
                diffs = [closes[-i] - closes[-i - 1] for i in (1, 2, 3)]
                if all(d > 0 for d in diffs):
                    votes["momentum_serisi"] = 1.0
                elif all(d < 0 for d in diffs):
                    votes["momentum_serisi"] = -1.0
            # atr_genislemesi: ATR genişliyor + son mum yönü
            if len(candles) >= 30:
                highs = [c.high for c in candles[-60:]]
                lows = [c.low for c in candles[-60:]]
                cls = [c.close for c in candles[-60:]]
                a = atr(highs, lows, cls, 14)
                if len(a) >= 5 and a[-1] and a[-5]:
                    if a[-1] > a[-5]:
                        votes["atr_genislemesi"] = body_dir
        # btc_uyum: BTC 15dk yönü ile son mum yönü uyumu
        body_dir = 1.0 if candles[-1].close > candles[-1].open else -1.0
        if abs(ctx.btc_change_pct_15m) >= 0.1:
            votes["btc_uyum"] = (
                1.0 if (ctx.btc_change_pct_15m > 0) == (body_dir > 0) else -1.0
            )
        return votes

    def evaluate(self, ctx: MarketContext) -> Signal:
        candles = ctx.candles
        if len(candles) < 60:
            return _hold(self.motor, ctx, "WARMUP")
        votes = self._votes(ctx)
        total_weight = sum(w for _, w in self.FILTERS)
        score = sum(votes[name] * w for name, w in self.FILTERS) / total_weight
        if not isfinite(score):
            return _hold(self.motor, ctx, "veri_yetersiz")
        stop = _stop_distance(ctx, "LONG")
        if stop is None:
            return _hold(self.motor, ctx, "veri_yetersiz")
        rvol = candle_rvol(ctx.volumes(), self.cfg.candle_rvol_lookback)
        threshold = min(max(self.cfg.confluence_threshold, 0.05), 1.0)
        detail = " ".join(
            f"{name}={votes[name]:+.0f}" for name, _ in self.FILTERS
        )
        if score >= threshold:
            return Signal(
                "LONG", self.motor, 0.0, rvol, stop,
                confidence=abs(score),
                reason=f"confluence_long puan={score:.2f} | {detail}",
            )
        if score <= -threshold:
            return Signal(
                "SHORT", self.motor, 0.0, rvol, stop,
                confidence=abs(score),
                reason=f"confluence_short puan={score:.2f} | {detail}",
            )
        last = candles[-1]
        prev = candles[-3] if len(candles) >= 3 else None
        impulse = (
            (last.close / prev.close - 1.0) * 100.0
            if prev and prev.close > 0 else 0.0
        )
        return Signal(
            "HOLD", self.motor, impulse, rvol, None,
            rejection_code="confluence_yetersiz",
            reason=f"confluence puan={score:.2f} < eşik {threshold:.2f}",
        )


EXTRA_STRATEGIES = {
    "confluence": ConfluenceEngine,
    "rsirev": RsiRevEngine,
    "macd": MacdEngine,
    "bollkir": BollBreakEngine,
    "bolldon": BollRevEngine,
}
