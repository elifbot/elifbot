"""Stop-hunt / likidasyon duvarı dedektörü — FINAL v1.1.

ultra_plus'taki 15 satırlık taslağın (hiçbir yerin beslemediği
'bid_volume_cluster' anahtarı bekleyen prototip) gerçek implementasyonu.

Yöntem (REST orderbook anlık görüntüsü, sezgisel vekil):
  1. Orta fiyatın ±max_distance_pct çevresi band_pct bantlara bölünür.
  2. Her banttaki emirlerin USD nominali toplanır (OKX kontrat dönüşümü
     borsa istemcisinde zaten yapılmış olur; miktarlar BAZ varlık cinsindendir).
  3. Bir bant hem mutlak eşiği (wall_min_usd) hem de medyan bant nominalinin
     wall_multiple katını aşıyorsa DUVAR sayılır.
  4. Duvar fiyatın block_distance_pct yakınındaysa, fiyatın duvara çekilip
     avlanması (stop-hunt sweep) riski nedeniyle YENİ GİRİŞ engellenir.
     Açık pozisyonların stop/çıkış yönetimi etkilenmez.

Sınırlar: Gerçek likidasyon ısı haritası (borsa içi kaldıraç dağılımı) değildir;
defterde görünen likiditeye dayalı muhafazakâr bir giriş filtresidir.
Bayat defter (book_ttl_seconds) karar dışı bırakılır (fail-open).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median

from core.config import SweepGuardConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiquidityWall:
    side: str            # "bid" (altta) | "ask" (üstte)
    price: float         # bandın ağırlıklanmış orta fiyatı
    notional_usd: float
    distance_pct: float  # orta fiyata uzaklık (0-1)


def detect_walls(
    bids: list[tuple[float, float]] | tuple,
    asks: list[tuple[float, float]] | tuple,
    config: SweepGuardConfig,
) -> list[LiquidityWall]:
    """Orderbook anlık görüntüsünden anormal duvarları çıkarır."""
    if not bids or not asks:
        return []
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return []
    mid = (best_bid + best_ask) / 2.0

    walls: list[LiquidityWall] = []
    for side, levels in (("bid", bids), ("ask", asks)):
        # Bant kovaları: index = floor(distance / band_pct)
        buckets: dict[int, list[float]] = {}
        for price, qty in levels:
            if price <= 0 or qty <= 0:
                continue
            distance = abs(price - mid) / mid
            if distance > config.max_distance_pct:
                continue
            idx = int(distance / config.band_pct)
            notional = price * qty
            bucket = buckets.setdefault(idx, [0.0, 0.0])
            bucket[0] += notional
            bucket[1] += notional * distance  # ağırlıklı uzaklık toplamı
        if not buckets:
            continue
        band_notionals = [v[0] for v in buckets.values()]
        med = median(band_notionals) if band_notionals else 0.0
        threshold = max(config.wall_min_usd, config.wall_multiple * med)
        for idx, (notional, weighted_distance) in buckets.items():
            if notional >= threshold and notional > 0:
                avg_distance = weighted_distance / notional
                walls.append(LiquidityWall(
                    side=side,
                    price=mid * (1 - avg_distance) if side == "bid" else mid * (1 + avg_distance),
                    notional_usd=notional,
                    distance_pct=avg_distance,
                ))
    return walls


class SweepGuard:
    """Sembol bazlı defter izleme + giriş kapısı."""

    def __init__(self, config: SweepGuardConfig) -> None:
        self.config = config
        # key -> (ts_ms, walls)
        self._books: dict[str, tuple[int, list[LiquidityWall]]] = {}
        self.blocks_count = 0
        self.books_updated = 0

    def update_book(self, key: str, bids, asks, ts_ms: int) -> list[LiquidityWall]:
        walls = detect_walls(bids, asks, self.config)
        self._books[key] = (ts_ms, walls)
        self.books_updated += 1
        if walls:
            logger.info(
                "DUVAR TESPİTİ: [%s] %s", key,
                "; ".join(
                    f"{w.side} {w.notional_usd/1000:.0f}k$ @ %{w.distance_pct*100:.2f}"
                    for w in walls
                ),
            )
        return walls

    def entry_block(self, key: str, side: str, now_ms: int) -> str | None:
        """Yeni giriş engellenecekse neden metni, aksi hâlde None."""
        record = self._books.get(key)
        if record is None:
            return None  # defter yok → fail-open
        ts_ms, walls = record
        age_s = (now_ms - ts_ms) / 1000.0
        if age_s < 0 or age_s > self.config.book_ttl_seconds:
            return None  # bayat defter → karar dışı
        for wall in walls:
            if wall.distance_pct <= self.config.block_distance_pct:
                self.blocks_count += 1
                return (
                    f"SWEEP_GUARD:{wall.side}_wall"
                    f"_{wall.notional_usd/1000:.0f}k$"
                    f"@%{wall.distance_pct*100:.2f}"
                )
        return None

    def status(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "books_tracked": len(self._books),
            "books_updated": self.books_updated,
            "active_walls": sum(len(w) for _, w in self._books.values()),
            "blocks_count": self.blocks_count,
            "wall_min_usd": self.config.wall_min_usd,
            "block_distance_pct": self.config.block_distance_pct,
        }
