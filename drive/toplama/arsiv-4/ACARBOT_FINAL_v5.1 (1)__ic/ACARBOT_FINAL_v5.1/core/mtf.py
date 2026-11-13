"""ACARBOT v2.0 — Çoklu zaman dilimi (MTF) analizi (şartname madde 2).

Bot aynı anda şu zaman dilimlerini inceler:
    1 dakika : giriş zamanlaması (canlı REST ile beslenir; yoksa "uygulanmadı")
    5 dakika : ana işlem sinyali (mevcut motorlar)
    15 dakika: trend onayı
    1 saat   : ana piyasa yönü
    4 saat   : büyük piyasa yapısı

Kural: 5m LONG sinyalinde 15m/1h/4h GÜÇLÜ biçimde SHORT gösteriyorsa işlem
ya engellenir ya da sinyal puanı düşürülür.

Eksik mum koruması: resample YALNIZCA tamamlanmış üst TF barlarını üretir —
son kovası henüz dolmamışsa o bar değerlendirmeye ALINMAZ.
Üst TF mumları doğrudan REST'ten de beslenebilir (canlıda öyle yapılır);
resample yalnızca 5m geçmişten türetme gerekirse kullanılır (veri türetme,
uydurma değildir).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Sequence

from core.config import MtfConfig
from core.indicators import adx, ema
from infra.market_data.models import Candle

# Üst TF'lerin 5m mum cinsinden bar sayısı
TF_TO_FACTOR: dict[str, int] = {"15m": 3, "1h": 12, "4h": 48}
TF_TO_MS: dict[str, int] = {
    "15m": 15 * 60_000, "1h": 60 * 60_000, "4h": 4 * 60 * 60_000,
}


@dataclass(frozen=True)
class TfBias:
    timeframe: str
    direction: str                    # "UP" | "DOWN" | "NEUTRAL"
    strength: float                   # 0-1 (ADX ve eğimden)
    adx: float | None = None
    slope_pct: float = 0.0
    bars: int = 0
    available: bool = True            # False → "uygulanmadı"
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "tf": self.timeframe,
            "direction": self.direction,
            "strength": round(self.strength, 3),
            "adx": None if self.adx is None else round(self.adx, 2),
            "slope_pct": round(self.slope_pct, 4),
            "bars": self.bars,
            "available": self.available,
            "note": self.note,
        }


@dataclass
class MtfReading:
    biases: dict[str, TfBias] = field(default_factory=dict)

    def bias_for(self, side: str) -> tuple[int, float]:
        """Sinyal yönüyle uyumlu/ters TF sayısı ve uyum skoru (0-1).

        Döndürür: (ters_güçlü_tf_sayısı, hizalama_skoru).
        Skor: uyumlu TF oranı - ters TF oranı (0.5 taban → 0-1 aralığına).
        """
        available = [b for b in self.biases.values() if b.available]
        if not available:
            return 0, 0.0
        wanted = "UP" if side == "LONG" else "DOWN"
        opposite = "DOWN" if side == "LONG" else "UP"
        agreeing = sum(1 for b in available if b.direction == wanted)
        opposing = sum(1 for b in available if b.direction == opposite)
        opposing_strong = sum(
            1 for b in available
            if b.direction == opposite and b.strength >= 0.6
        )
        score = (agreeing - opposing) / len(available)  # -1..1
        return opposing_strong, (score + 1.0) / 2.0

    def as_dict(self) -> dict:
        return {tf: b.as_dict() for tf, b in self.biases.items()}


def resample_closed(
    candles: Sequence[Candle], timeframe: str,
) -> list[Candle]:
    """5m mumlardan üst TF barları türetir — YALNIZCA TAMAMLANMIŞ barlar.

    Bir kova (bucket) ancak serinin son mumu kova sonuna ULAŞMIŞSA
    tamamlanmış sayılır (şartname: eksik mumlar tamamlanmadan
    değerlendirmeye alınmaz). Başlangıç/bitiş kısmi kovaları elenir.
    """
    bucket_ms = TF_TO_MS[timeframe]
    base_interval_ms = 300_000  # girdi 5m mumlardır (modül sözleşmesi)
    buckets: dict[int, list[Candle]] = {}
    for candle in candles:
        if candle.timestamp <= 0:
            continue
        idx = candle.timestamp // bucket_ms
        buckets.setdefault(idx, []).append(candle)
    if not buckets:
        return []
    max_close_ts = max(c.timestamp for c in candles) + base_interval_ms
    out: list[Candle] = []
    for idx in sorted(buckets):
        bucket_end = (idx + 1) * bucket_ms
        if max_close_ts < bucket_end:
            continue  # kova henüz dolmadı → atla
        rows = buckets[idx]
        out.append(Candle(
            timestamp=idx * bucket_ms,
            open=rows[0].open,
            high=max(r.high for r in rows),
            low=min(r.low for r in rows),
            close=rows[-1].close,
            volume=sum(r.volume for r in rows),
        ))
    return out


def _bias_from_candles(timeframe: str, candles: Sequence[Candle],
                       cfg: MtfConfig) -> TfBias:
    """Kapanmış üst TF barlarından yön oyu (EMA20/50 + eğim + ADX)."""
    closes = [c.close for c in candles]
    if len(closes) < cfg.min_bars_for_bias:
        return TfBias(
            timeframe=timeframe, direction="NEUTRAL", strength=0.0,
            bars=len(closes), available=False,
            note=f"yetersiz_bar({len(closes)})",
        )
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    if ema20 is None or ema50 is None:
        return TfBias(
            timeframe=timeframe, direction="NEUTRAL", strength=0.0,
            bars=len(closes), available=False, note="ema_eksik",
        )
    prev = ema(closes, 20)[-4] or ema20
    slope_pct = (float(ema20) - float(prev)) / float(ema20) * 100.0
    adx_value: float | None = None
    try:
        movement = adx(
            [c.high for c in candles], [c.low for c in candles], closes, 14,
        )
        adx_value = movement.adx[-1]
    except Exception:
        adx_value = None
    if adx_value is None or not isfinite(adx_value):
        adx_value = 0.0

    strong_adx = adx_value >= cfg.strong_adx
    abs(slope_pct) >= cfg.slope_threshold_pct
    if ema20 > ema50 and (slope_pct > 0 or strong_adx):
        direction, base = "UP", 0.5
    elif ema20 < ema50 and (slope_pct < 0 or strong_adx):
        direction, base = "DOWN", 0.5
    else:
        return TfBias(
            timeframe=timeframe, direction="NEUTRAL", strength=0.2,
            adx=adx_value, slope_pct=slope_pct, bars=len(closes),
        )
    # Güç: ADX ve eğimin birlikte büyüklüğü (0.5-1.0)
    strength = min(1.0, base + (adx_value / 100.0) + (abs(slope_pct) / 2.0))
    return TfBias(
        timeframe=timeframe, direction=direction, strength=strength,
        adx=adx_value, slope_pct=slope_pct, bars=len(closes),
    )


class MtfAnalyzer:
    """Üst TF oy toplayıcı ve çelişki kapısı."""

    def __init__(self, config: MtfConfig | None = None) -> None:
        self.cfg = config or MtfConfig()

    def analyze_rest(
        self, candles_by_tf: dict[str, list[Candle]],
    ) -> MtfReading:
        """Canlı yol: üst TF mumları doğrudan REST'ten gelir (kapanmışlar)."""
        reading = MtfReading()
        for tf in self.cfg.timeframes:
            candles = candles_by_tf.get(tf) or []
            if not candles:
                reading.biases[tf] = TfBias(
                    timeframe=tf, direction="NEUTRAL", strength=0.0,
                    available=False, note="veri_yok",
                )
                continue
            reading.biases[tf] = _bias_from_candles(tf, candles, self.cfg)
        return reading

    def analyze_resampled(
        self, base_candles: Sequence[Candle],
    ) -> MtfReading:
        """Backtest/soğuk yol: 5m geçmişten kapanmış üst TF barları türet."""
        reading = MtfReading()
        for tf in self.cfg.timeframes:
            resampled = resample_closed(base_candles, tf)
            if not resampled:
                reading.biases[tf] = TfBias(
                    timeframe=tf, direction="NEUTRAL", strength=0.0,
                    available=False, note="resample_yetersiz",
                )
                continue
            reading.biases[tf] = _bias_from_candles(tf, resampled, self.cfg)
        return reading

    def evaluate_conflict(
        self, reading: MtfReading, side: str,
    ) -> tuple[str | None, float]:
        """Sinyal yönü için MTF kararı.

        Döndürür: (blok_nedeni | None, hizalama_skoru 0-1).
        Blok kuralı: `block_tfs_required` kadar GÜÇLÜ ters TF (15m+1h
        varsayılan) ve 4h zıt yönde değilse bile en az nötr.
        """
        if not self.cfg.enabled:
            return None, 1.0
        available = [b for b in reading.biases.values() if b.available]
        if not available:
            return None, 1.0  # veri yok → görüş yok, engellenmez ("uygulanmadı")
        opposing_strong, alignment = reading.bias_for(side)
        if opposing_strong >= self.cfg.block_tfs_required:
            return "mtf_uyumsuz", alignment
        return None, alignment

    def entry_timing(self, candles_1m: Sequence[Candle] | None, side: str) -> str:
        """1 dakikalık giriş zamanlaması (şartname 2: 1m = giriş zamanlaması).

        Döndürür: "ok" | "wait". Yalnızca 1m verisi GERÇEKTEN geldiyse
        görüş bildirir; veri yoksa "ok" ("uygulanmadı" — engel konmaz).
        """
        if not candles_1m or len(candles_1m) < 15:
            return "ok"
        bias = _bias_from_candles("1m", candles_1m[-60:], self.cfg)
        if not bias.available:
            return "ok"
        wanted = "UP" if side == "LONG" else "DOWN"
        if bias.direction != "NEUTRAL" and bias.direction != wanted:
            # 1m bariz ters yönde: zamanlama beklemede (sinyal düşmez,
            # bir sonraki mumda yeniden denenir)
            return "wait"
        return "ok"
