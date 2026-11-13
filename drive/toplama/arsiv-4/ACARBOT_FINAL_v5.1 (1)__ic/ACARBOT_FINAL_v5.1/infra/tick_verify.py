"""v5.1 — TICK/LOT DOĞRULAMASI ve CANLI IZGARA GÖZLEMİ.

SORUN
-----
Binance vadeli (futures) `exchangeInfo` bu bölgeden 451 döndüğü için
tickSize değerleri SPOT AYNADAN (`data-api.binance.vision/api/v3/`)
okunuyor. Spot tick büyüklüğü vadeli sözleşmeyle AYNI OLMAK ZORUNDA
DEĞİL. Farklıysa "stop ızgarası hizalama" yanlış ızgaraya göre çalışır ve
25 USDT hedefi yine sapar.

İKİ KATMANLI ÇÖZÜM
------------------
1) `TickVerifier` — vadeli kaynaklardan tickSize çekmeye çalışır:
     • uyuşma        → `match`, sembol işlem görür
     • UYUŞMAZLIK    → `mismatch`, sembol İŞLEM DIŞI (politikadan bağımsız)
     • erişilemiyor  → `unverified`, politika belirler (warn | strict)

2) `GridObserver` — vadeli API hiç erişilemediğinde tek GERÇEK kanıt:
   borsadan gelen fiyat gerçekten iddia edilen ızgaranın üzerinde mi?
   Değilse ızgara yanlıştır. Eşik sayıda ihlalde sembol işlem dışı kalır.
   Bu katman API'ye ihtiyaç duymaz, canlı akışın kendisini kanıt sayar.

DÜRÜSTLÜK NOTU
--------------
Bu ortamda vadeli uç noktaların hiçbiri yanıt vermiyor (451 / boş 202).
Yani Binance sembolleri `unverified` kalır; rapor bunu AÇIKÇA yazar.
`unverified` durumu "doğrulandı" anlamına GELMEZ.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from math import isfinite

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

# Vadeli tickSize kaynakları, öncelik sırasıyla. Hepsi denenir.
FUTURES_TICK_SOURCES: tuple[tuple[str, str], ...] = (
    ("binance_fapi", "https://fapi.binance.com/fapi/v1/exchangeInfo"),
    ("binance_fapi1", "https://fapi1.binance.com/fapi/v1/exchangeInfo"),
    ("binance_fapi2", "https://fapi2.binance.com/fapi/v1/exchangeInfo"),
    ("binance_fapi3", "https://fapi3.binance.com/fapi/v1/exchangeInfo"),
)

MATCH = "match"
MISMATCH = "mismatch"
UNVERIFIED = "unverified"


@dataclass(frozen=True)
class TickVerification:
    symbol: str
    spot_tick: float
    futures_tick: float | None
    status: str
    source: str = ""
    detail: str = ""

    @property
    def tradable(self) -> bool:
        return self.status != MISMATCH

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "spot_tick": self.spot_tick,
            "futures_tick": self.futures_tick,
            "status": self.status,
            "source": self.source,
            "detail": self.detail,
        }


def price_on_grid(price: float, tick: float, tolerance: float = 1e-6) -> bool:
    """Fiyat, verilen ızgaranın üzerinde mi? (float toleranslı)"""
    if not (isfinite(price) and isfinite(tick)) or price <= 0 or tick <= 0:
        return False
    steps = price / tick
    remainder = abs(price - round(steps) * tick)
    return remainder <= tick * tolerance


class TickVerifier:
    """Spot aynası tickSize'ını vadeli kaynakla karşılaştırır."""

    def __init__(
        self,
        policy: str = "warn",
        timeout: float = 12.0,
        relative_tolerance: float = 1e-9,
        sources: tuple[tuple[str, str], ...] = FUTURES_TICK_SOURCES,
    ) -> None:
        if policy not in ("warn", "strict"):
            raise ValueError("policy: warn | strict")
        self.policy = policy
        self.timeout = timeout
        self.relative_tolerance = relative_tolerance
        self.sources = sources
        self.futures_ticks: dict[str, float] = {}
        self.source_used: str = ""
        self.fetch_error: str = ""

    # ------------------------------------------------------------------

    def fetch_futures_ticks(self) -> dict[str, float]:
        """Vadeli tickSize haritası. Hiçbiri yanıt vermezse boş döner."""
        for name, url in self.sources:
            try:
                request = urllib.request.Request(url, headers=_UA)
                with urllib.request.urlopen(
                    request, timeout=self.timeout,
                ) as response:
                    raw = response.read()
                if not raw:
                    self.fetch_error = f"{name}: boş yanıt (HTTP {response.status})"
                    continue
                payload = json.loads(raw)
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                self.fetch_error = f"{name}: {type(exc).__name__} {exc}"
                continue
            except (ValueError, json.JSONDecodeError) as exc:
                self.fetch_error = f"{name}: geçersiz JSON ({exc})"
                continue
            ticks: dict[str, float] = {}
            for entry in payload.get("symbols", []) or []:
                symbol = entry.get("symbol")
                if not symbol:
                    continue
                for filt in entry.get("filters", []) or []:
                    if filt.get("filterType") == "PRICE_FILTER":
                        try:
                            value = float(filt.get("tickSize", 0.0))
                        except (TypeError, ValueError):
                            continue
                        if value > 0:
                            ticks[symbol] = value
            if ticks:
                self.futures_ticks = ticks
                self.source_used = name
                self.fetch_error = ""
                logger.info(
                    "TICK DOĞRULAMA: vadeli kaynak %s — %d sembol tickSize",
                    name, len(ticks),
                )
                return ticks
            self.fetch_error = f"{name}: PRICE_FILTER bulunamadı"
        logger.warning(
            "TICK DOĞRULAMA: vadeli kaynakların HİÇBİRİ yanıt vermedi (%s) — "
            "Binance sembolleri 'unverified' kalacak, canlı ızgara gözlemi "
            "tek kanıt olarak kullanılacak",
            self.fetch_error or "bilinmeyen",
        )
        return {}

    # ------------------------------------------------------------------

    def verify(self, symbol: str, spot_tick: float) -> TickVerification:
        bare = symbol.split(":", 1)[-1]
        futures_tick = self.futures_ticks.get(bare)
        if futures_tick is None:
            return TickVerification(
                symbol, spot_tick, None, UNVERIFIED, self.source_used,
                "vadeli tickSize alınamadı",
            )
        delta = abs(futures_tick - spot_tick)
        scale = max(abs(futures_tick), abs(spot_tick), 1e-18)
        if delta / scale <= self.relative_tolerance:
            return TickVerification(
                symbol, spot_tick, futures_tick, MATCH, self.source_used,
                "spot ve vadeli tickSize aynı",
            )
        return TickVerification(
            symbol, spot_tick, futures_tick, MISMATCH, self.source_used,
            f"UYUŞMAZLIK: spot {spot_tick:g} != vadeli {futures_tick:g}",
        )

    def verify_many(
        self, spot_ticks: dict[str, float],
    ) -> dict[str, TickVerification]:
        if not self.futures_ticks:
            self.fetch_futures_ticks()
        return {
            symbol: self.verify(symbol, tick)
            for symbol, tick in spot_ticks.items()
        }

    def filter_grid(
        self, spot_ticks: dict[str, float],
    ) -> tuple[dict[str, float], dict]:
        """İşlem görebilecek ızgara haritası + denetim raporu.

        `mismatch` her zaman dışlanır. `unverified` yalnızca `strict`
        politikada dışlanır; `warn` politikada sayılır ve raporlanır.
        """
        results = self.verify_many(spot_ticks)
        allowed: dict[str, float] = {}
        excluded: list[str] = []
        counts = {MATCH: 0, MISMATCH: 0, UNVERIFIED: 0}
        for symbol, result in results.items():
            counts[result.status] += 1
            if result.status == MISMATCH:
                excluded.append(symbol)
                logger.warning(
                    "TICK UYUŞMAZLIĞI: [%s] %s — sembol işlem dışı",
                    symbol, result.detail,
                )
                continue
            if result.status == UNVERIFIED and self.policy == "strict":
                excluded.append(symbol)
                continue
            allowed[symbol] = result.spot_tick
        report = {
            "policy": self.policy,
            "futures_source": self.source_used,
            "futures_error": self.fetch_error,
            "futures_symbols": len(self.futures_ticks),
            "checked": len(results),
            "match": counts[MATCH],
            "mismatch": counts[MISMATCH],
            "unverified": counts[UNVERIFIED],
            "excluded_symbols": excluded,
            "allowed_symbols": len(allowed),
            "verified": counts[MATCH] > 0,
        }
        return allowed, report


@dataclass
class GridObserver:
    """Canlı fiyatlardan ampirik ızgara doğrulaması.

    Vadeli API erişilemediğinde tek gerçek kanıt budur: borsa bir fiyat
    verdiyse o fiyat gerçek ızgaranın üzerindedir. İddia edilen tick ile
    uyuşmuyorsa ızgara YANLIŞTIR ve o sembolde ızgara hizalama güvenilmez.
    """

    max_violations: int = 3
    tolerance: float = 1e-6
    violations: dict[str, int] = field(default_factory=dict)
    rejected: set[str] = field(default_factory=set)
    checked: dict[str, int] = field(default_factory=dict)
    examples: dict[str, dict] = field(default_factory=dict)

    def observe(self, symbol: str, price: float, tick: float) -> bool:
        """True = ızgara tutarlı. False = ihlal (eşik aşıldıysa sembol reddedildi)."""
        if symbol in self.rejected or tick <= 0:
            return symbol not in self.rejected
        self.checked[symbol] = self.checked.get(symbol, 0) + 1
        if price_on_grid(price, tick, self.tolerance):
            return True
        self.violations[symbol] = self.violations.get(symbol, 0) + 1
        self.examples.setdefault(symbol, {"price": price, "tick": tick})
        if self.violations[symbol] >= self.max_violations:
            self.rejected.add(symbol)
            logger.error(
                "IZGARA REDDİ: [%s] %d fiyat, iddia edilen tick %g üzerinde "
                "değil (örnek fiyat %g) — tickSize yanlış, sembol işlem dışı",
                symbol, self.violations[symbol], tick, price,
            )
        return symbol not in self.rejected

    def as_dict(self) -> dict:
        return {
            "symbols_checked": len(self.checked),
            "ticks_checked": sum(self.checked.values()),
            "violations": dict(self.violations),
            "rejected_symbols": sorted(self.rejected),
            "examples": dict(self.examples),
            "max_violations": self.max_violations,
        }
