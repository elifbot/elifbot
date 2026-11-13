"""Veri bütünlüğü ve güvenli mod (Yorum 1-F).

Kapsam:
  - Mum boşluğu tespiti + REST geri doldurma denemesi; başarısızsa sembol
    "bayat" ilan edilir ve yeni giriş engellenir.
  - Tick tazeliği: son tick eşiği aşarsa o sembolde giriş yok; global
    bayatlık oranı eşik aşarsa TÜM sistem GÜVENLİ MOD'a geçer.
  - Borsalar arası fiyat sapması sürekli ölçülür; sapma eşik üstünde ise
    o sembolde giriş engellenir (veri şüphesi).
  - Yeniden başlatma sonrası ısınma süresi: sinyal motoru çalışmaz.
  - Güvenli mod: yeni giriş YOK, bekleyen emirler iptal edilir; açık
    pozisyonların stopları ÇALIŞMAYA DEVAM EDER (riskten korunma).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import isfinite

from core.config import DataConfig

logger = logging.getLogger(__name__)


class FeedState(str, __import__("enum").Enum):
    WARMUP = "WARMUP"
    OK = "OK"
    STALE = "STALE"
    SAFE_MODE = "SAFE_MODE"


@dataclass
class _SymbolFeed:
    last_tick_ms: int = 0
    last_candle_ts: int = 0
    stale_until_ms: int = 0
    tick_count: int = 0


class DataIntegrityManager:
    """Canlı akışın veri sağlığı hakemi. fail-closed tasarım."""

    def __init__(self, config: DataConfig | None = None, now_ms: int = 0) -> None:
        self.config = config or DataConfig()
        self.started_ms = now_ms
        self._feeds: dict[str, _SymbolFeed] = {}
        self.safe_mode = False
        self.safe_mode_reason: str | None = None
        self._cross_prices: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Isınma (restart sonrası)
    # ------------------------------------------------------------------

    def is_warmed_up(self, now_ms: int) -> bool:
        if now_ms - self.started_ms < self.config.warmup_seconds * 1000:
            return False
        tracked = [f for f in self._feeds.values() if f.tick_count > 0]
        if not tracked:
            return False
        return all(f.tick_count >= self.config.warmup_min_ticks for f in tracked)

    # ------------------------------------------------------------------
    # Tick tazeliği
    # ------------------------------------------------------------------

    def record_tick(self, symbol: str, now_ms: int) -> None:
        feed = self._feeds.setdefault(symbol, _SymbolFeed())
        feed.last_tick_ms = now_ms
        feed.tick_count += 1

    def symbol_fresh(self, symbol: str, now_ms: int) -> bool:
        feed = self._feeds.get(symbol)
        if feed is None or feed.last_tick_ms == 0:
            return False
        age_s = (now_ms - feed.last_tick_ms) / 1000.0
        return age_s <= self.config.tick_freshness_s

    def symbol_stale(self, symbol: str, now_ms: int) -> bool:
        feed = self._feeds.get(symbol)
        if feed is None:
            return True
        if now_ms < feed.stale_until_ms:
            return True
        age_s = (now_ms - feed.last_tick_ms) / 1000.0
        return feed.last_tick_ms == 0 or age_s > self.config.tick_freshness_s

    # ------------------------------------------------------------------
    # Mum boşlukları
    # ------------------------------------------------------------------

    def on_candle_closed(
        self,
        symbol: str,
        candle_timestamp: int,
        now_ms: int,
    ) -> str:
        """Kapanan mumda sürekliliği denetler.

        Dönüş: "ok" | "gap_backfilled" | "gap_blocked"
        """
        feed = self._feeds.setdefault(symbol, _SymbolFeed())
        expected = self.config.timeframe_ms
        if feed.last_candle_ts and candle_timestamp > feed.last_candle_ts + expected:
            missing = int(
                (candle_timestamp - feed.last_candle_ts) // expected
            ) - 1
            if missing > 0:
                logger.warning(
                    "MUM BOŞLUĞU: [%s] %d mum eksik (ts=%d)",
                    symbol, missing, candle_timestamp,
                )
                feed.last_candle_ts = candle_timestamp
                return "gap_backfilled" if self.config.gap_backfill_enabled \
                    else "gap_blocked"
        feed.last_candle_ts = candle_timestamp
        return "ok"

    def mark_symbol_stale(self, symbol: str, now_ms: int) -> None:
        feed = self._feeds.setdefault(symbol, _SymbolFeed())
        feed.stale_until_ms = now_ms + int(self.config.stale_symbol_cooldown_s * 1000)
        logger.warning("SEMBOOL BAYAT: [%s] girişler %s sn engellenecek",
                       symbol, self.config.stale_symbol_cooldown_s)

    # ------------------------------------------------------------------
    # Borsalar arası sapma
    # ------------------------------------------------------------------

    def record_cross_price(self, exchange: str, symbol: str, price: float) -> float | None:
        """Aynı dayanak sembolün iki borsadaki fiyatını karşılaştırır.

        Döndürür: sapma yüzdesi (karşılaştırma yapılabildiyse) veya None.
        """
        if not isfinite(price) or price <= 0:
            return None
        per_symbol = self._cross_prices.setdefault(symbol, {})
        per_symbol[exchange] = price
        if len(per_symbol) < 2:
            return None
        prices = sorted(per_symbol.values())
        mid = (prices[0] + prices[-1]) / 2.0
        if mid <= 0:
            return None
        divergence = (prices[-1] - prices[0]) / mid * 100.0
        return divergence

    def divergence_blocked(self, symbol: str) -> bool:
        prices = self._cross_prices.get(symbol, {})
        if len(prices) < 2:
            return False
        values = sorted(prices.values())
        mid = (values[0] + values[-1]) / 2.0
        if mid <= 0:
            return True
        divergence = (values[-1] - values[0]) / mid * 100.0
        return divergence > self.config.cross_exchange_divergence_pct

    # ------------------------------------------------------------------
    # Güvenli mod
    # ------------------------------------------------------------------

    def update_global_state(self, now_ms: int) -> bool:
        """Global bayatlık oranı + ısınma durumuna göre güvenli modu günceller.

        Döndürür: safe_mode geçerli mi?
        """
        if not self.is_warmed_up(now_ms):
            self.safe_mode = True
            self.safe_mode_reason = "warmup"
            return True
        stale_count = sum(
            1 for feed in self._feeds.values()
            if feed.last_tick_ms and (now_ms - feed.last_tick_ms) / 1000.0
            > self.config.global_stale_s
        )
        tracked = sum(1 for f in self._feeds.values() if f.last_tick_ms)
        if tracked >= 2:
            fraction = stale_count / tracked
            if fraction >= self.config.global_stale_symbol_fraction:
                if not self.safe_mode:
                    logger.error(
                        "GÜVENLİ MOD: %d/%d sembol bayat (%.0f sn)",
                        stale_count, tracked, self.config.global_stale_s,
                    )
                self.safe_mode = True
                self.safe_mode_reason = "global_stale_data"
                return True
        if self.safe_mode and self.safe_mode_reason in {
            "warmup", "global_stale_data"
        }:
            self.safe_mode = False
            self.safe_mode_reason = None
        return self.safe_mode

    def entry_allowed(self, symbol: str, now_ms: int) -> tuple[bool, str | None]:
        """Yeni giriş için TÜM veri bütünlüğü koşulları.

        `symbol` "binance:BTCUSDT" biçiminde olabilir; borsalar arası sapma
        kontrolü dayanak sembol ("BTCUSDT") üzerinden yapılır.
        """
        if self.safe_mode:
            return False, "safe_mode"
        if not self.is_warmed_up(now_ms):
            return False, "warmup"
        if self.symbol_stale(symbol, now_ms):
            return False, "stale_symbol"
        base_symbol = symbol.rsplit(":", 1)[-1].upper()
        if self.divergence_blocked(base_symbol):
            return False, "cross_exchange_divergence"
        return True, None


@dataclass
class CandleGapBackfillResult:
    symbol: str
    fetched: int = 0
    success: bool = False
    error: str | None = None
    notes: list[str] = field(default_factory=list)
