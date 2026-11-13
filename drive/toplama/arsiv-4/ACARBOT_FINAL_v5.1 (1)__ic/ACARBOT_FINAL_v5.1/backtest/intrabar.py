"""v5.1 — MUM İÇİ YOL MODELİ (intrabar path).

SORUN
-----
5 dakikalık mumda stop ile TP aynı bar içinde görülürse sıra bilinmez.
Eski motor bunu "muhafazakâr: önce stop" diye çözüyordu ama çıkış fiyatı
olarak **mumun ucunu** (low/high) kullanıyordu. Acil net-risk stopu da
aynı uçtan hesaplandığı için, stop seviyesi 75.475 iken mum ucu 75.810
olan bir barda kayıp 25 USDT yerine 40 USDT çıkıyordu.

Bu, gerçek bir gap riski mi yoksa modelin aşırı kötümserliği mi?
5m veriyle AYIRT EDİLEMEZ. Çözüm: alt çözünürlük.

ÇÖZÜM
-----
1) `real_1m`: 1 dakikalık mumlar varsa 5m barın içindeki gerçek sıra ile
   yürünür. Stop, tetiklendiği İLK 1m barda ve o barın (çok daha dar)
   ucundan kapanır → gerçekçi kayıp.
2) `synthetic`: 1m yoksa OHLC'den deterministik bir yol üretilir ve
   `adverse_first` / `favorable_first` ile ALT/ÜST SINIR koşulur.
   Tek bir sayı yerine ARALIK raporlanır — dürüst olan budur.

Her durumda yol kaynağı (`real_1m` / `synthetic_adverse` /
`synthetic_favorable`) sonuçta etiketlenir; sentetik sonuç asla gerçek
veri sonucu gibi sunulmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.market_data.models import Candle

REAL = "real_1m"
SYN_ADVERSE = "synthetic_adverse_first"
SYN_FAVORABLE = "synthetic_favorable_first"


@dataclass
class IntrabarStats:
    """Yol modelinin kapsama sayacı — raporda dürüstlük için zorunlu."""

    real_bars: int = 0
    synthetic_bars: int = 0
    partial_coverage_bars: int = 0
    inconsistent_bars: int = 0
    single_step_bars: int = 0

    def as_dict(self) -> dict:
        total = self.real_bars + self.synthetic_bars
        return {
            "real_1m_bars": self.real_bars,
            "synthetic_bars": self.synthetic_bars,
            "partial_coverage_bars": self.partial_coverage_bars,
            "inconsistent_bars": self.inconsistent_bars,
            "single_step_bars": self.single_step_bars,
            "real_coverage_ratio": (
                round(self.real_bars / total, 4) if total else 0.0
            ),
        }


@dataclass
class IntrabarPath:
    """Kaba mumu, sıralı alt mumlara çevirir.

    fine_by_symbol: sembol -> 1m (veya daha ince) mum listesi, zaman sıralı.
    mode: "auto" (ince veri varsa kullan) | "real_only" | "synthetic"
    synthetic_order: "adverse_first" (kötümser) | "favorable_first" (iyimser)
    """

    fine_by_symbol: dict[str, list[Candle]] = field(default_factory=dict)
    coarse_interval_ms: int = 300_000
    mode: str = "auto"
    synthetic_order: str = "adverse_first"
    price_tolerance: float = 1e-6
    stats: IntrabarStats = field(default_factory=IntrabarStats)
    _index: dict[str, dict[int, list[Candle]]] = field(
        default_factory=dict, init=False, repr=False,
    )

    def __post_init__(self) -> None:
        if self.mode not in ("auto", "real_only", "synthetic"):
            raise ValueError("mode: auto | real_only | synthetic")
        if self.synthetic_order not in ("adverse_first", "favorable_first"):
            raise ValueError("synthetic_order: adverse_first | favorable_first")
        if self.coarse_interval_ms <= 0:
            raise ValueError("coarse_interval_ms pozitif olmalı")
        for symbol, candles in self.fine_by_symbol.items():
            buckets: dict[int, list[Candle]] = {}
            for candle in sorted(candles, key=lambda c: c.timestamp):
                key = candle.timestamp - (
                    candle.timestamp % self.coarse_interval_ms
                )
                buckets.setdefault(key, []).append(candle)
            self._index[symbol] = buckets

    # ------------------------------------------------------------------

    def steps(self, symbol: str, coarse: Candle) -> tuple[list[Candle], str]:
        """Kaba mum için sıralı alt mumlar + kullanılan yolun etiketi."""
        fine = self._lookup(symbol, coarse)
        if fine is not None and self.mode != "synthetic":
            return fine, REAL
        if self.mode == "real_only":
            # İnce veri yoksa tek adım: kaba mumun kendisi (eski davranış).
            self.stats.single_step_bars += 1
            return [coarse], REAL
        return self._synthetic(coarse), (
            SYN_ADVERSE if self.synthetic_order == "adverse_first"
            else SYN_FAVORABLE
        )

    def _lookup(self, symbol: str, coarse: Candle) -> list[Candle] | None:
        buckets = self._index.get(symbol)
        if not buckets:
            return None
        key = coarse.timestamp - (
            coarse.timestamp % self.coarse_interval_ms
        )
        fine = buckets.get(key)
        if not fine:
            return None
        expected = max(1, self.coarse_interval_ms // self._fine_step_ms(fine))
        if len(fine) < expected:
            self.stats.partial_coverage_bars += 1
            return None
        # Tutarlılık: ince mumların uçları kaba mumu yeniden üretmeli.
        hi = max(c.high for c in fine)
        lo = min(c.low for c in fine)
        tol = max(abs(coarse.high), abs(coarse.low)) * self.price_tolerance
        if abs(hi - coarse.high) > tol or abs(lo - coarse.low) > tol:
            self.stats.inconsistent_bars += 1
            return None
        self.stats.real_bars += 1
        return fine

    @staticmethod
    def _fine_step_ms(fine: list[Candle]) -> int:
        if len(fine) < 2:
            return 60_000
        deltas = [
            b.timestamp - a.timestamp
            for a, b in zip(fine, fine[1:])
            if b.timestamp > a.timestamp
        ]
        return min(deltas) if deltas else 60_000

    def _synthetic(self, coarse: Candle) -> list[Candle]:
        """OHLC'den deterministik yol. Uçlar kaba mumla aynı kalır.

        adverse_first  : open → aleyhte uç → lehte uç → close  (kötümser)
        favorable_first: open → lehte uç → aleyhte uç → close  (iyimser)

        Not: sentetik yol stop/TP SIRASINI belirler ama mum ucunu
        daraltmaz; bu yüzden acil stop kaybı yine uçtan hesaplanır.
        Gerçek daralma yalnız `real_1m` ile elde edilir.
        """
        self.stats.synthetic_bars += 1
        bullish = coarse.close >= coarse.open
        adverse, favorable = (
            (coarse.low, coarse.high) if bullish else (coarse.high, coarse.low)
        )
        if self.synthetic_order == "favorable_first":
            adverse, favorable = favorable, adverse
        base = coarse.timestamp
        span = self.coarse_interval_ms
        o, a, f, c = coarse.open, adverse, favorable, coarse.close
        vol = coarse.volume / 3.0

        def leg(index: int, start: float, end: float) -> Candle:
            return Candle(
                timestamp=base + index * (span // 3),
                open=start,
                high=max(start, end),
                low=min(start, end),
                close=end,
                volume=vol,
            )

        return [leg(0, o, a), leg(1, a, f), leg(2, f, c)]


def overshoot_ratio(
    side: str, entry: float, stop_level: float, exit_price: float,
) -> float:
    """Çıkışın stop seviyesini ne kadar AŞTIĞI (stop mesafesi oranı).

    0.0  → tam stop seviyesinden kapandı (ideal)
    0.5  → stop mesafesinin yarısı kadar daha kötü kapandı
    >1.0 → stop mesafesinden fazla kayma (gap veya model kötümserliği)
    """
    distance = abs(entry - stop_level)
    if distance <= 0:
        return 0.0
    direction = 1.0 if side == "LONG" else -1.0
    adverse = (stop_level - exit_price) * direction
    return max(0.0, adverse / distance)
