"""v5.1 — GERÇEK MALİYET MODELİ (spread / kayma / gecikme).

SORUN
-----
v3.0–v5.0 backtest'lerinde `spread = uygulanmadi`, `slippage_bps = 0`,
`latency_ms = 0` idi. Yani sonuçlar yapısal olarak İYİMSERDİ. Kârlılık
iddiası bu hâliyle geçersizdir.

ÇÖZÜM
-----
`CostModel` üç kaynaktan beslenir, öncelik sırasıyla:
  1. ÖLÇÜLMÜŞ  — `tools/measure_costs.py` canlı emir defterinden örnekler,
                 sembol başına spread ve derinlik-kayması yazar.
  2. BORSA VARSAYILANI — ölçüm yoksa muhafazakâr tahmin. Bunlar ÖLÇÜM
                 DEĞİLDİR ve raporda `defaults_conservative` diye etiketlenir.
  3. KAPALI — yalnızca bilinçli `CostModel.disabled()` ile; rapor kırmızı
     bayrak taşır ve sürüm regresyon kapısı bunu reddeder.

Ayrıca kayma tek bir global sayı olmaktan çıkar: sembol/borsa bazında
ayrışır ve ÇIKIŞ bacağına da uygulanır (eski model yalnız girişi
kaydırıyordu).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExchangeCosts:
    """Borsa başına maliyet varsayımı (bps = baz puan, 1 bps = %0,01)."""

    spread_bps: float = 2.0
    slippage_bps: float = 2.0
    latency_ms: int = 300
    exit_slippage_bps: float = 3.0
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005

    def __post_init__(self) -> None:
        for name in (
            "spread_bps", "slippage_bps", "exit_slippage_bps",
            "maker_fee", "taker_fee",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} negatif olamaz")
        if self.latency_ms < 0:
            raise ValueError("latency_ms negatif olamaz")


# Muhafazakâr VARSAYIMLAR — ölçüm değil. Ölçüm geldiğinde üzerine yazılır.
DEFAULT_COSTS: dict[str, ExchangeCosts] = {
    "binance": ExchangeCosts(
        spread_bps=1.5, slippage_bps=2.0, latency_ms=250, exit_slippage_bps=3.0,
    ),
    "okx": ExchangeCosts(
        spread_bps=2.5, slippage_bps=3.0, latency_ms=350, exit_slippage_bps=4.0,
    ),
}
_FALLBACK = ExchangeCosts(
    spread_bps=3.0, slippage_bps=4.0, latency_ms=400, exit_slippage_bps=5.0,
)


@dataclass
class CostModel:
    """Sembol başına çözümlenen maliyet modeli."""

    by_exchange: dict[str, ExchangeCosts] = field(
        default_factory=lambda: dict(DEFAULT_COSTS),
    )
    measured_spread_bps: dict[str, float] = field(default_factory=dict)
    measured_slippage_bps: dict[str, float] = field(default_factory=dict)
    measured_exit_slippage_bps: dict[str, float] = field(default_factory=dict)
    measured_latency_ms: dict[str, int] = field(default_factory=dict)
    source: str = "defaults_conservative"
    measured_at: str | None = None
    measured_symbols: int = 0
    enabled: bool = True

    # ------------------------------------------------------------------

    @staticmethod
    def _exchange_of(symbol: str) -> str:
        return symbol.split(":", 1)[0].lower() if ":" in symbol else "binance"

    def _base(self, symbol: str) -> ExchangeCosts:
        return self.by_exchange.get(self._exchange_of(symbol), _FALLBACK)

    def spread_bps(self, symbol: str) -> float:
        if not self.enabled:
            return 0.0
        return self.measured_spread_bps.get(symbol, self._base(symbol).spread_bps)

    def slippage_bps(self, symbol: str) -> float:
        if not self.enabled:
            return 0.0
        return self.measured_slippage_bps.get(
            symbol, self._base(symbol).slippage_bps,
        )

    def exit_slippage_bps(self, symbol: str) -> float:
        if not self.enabled:
            return 0.0
        return self.measured_exit_slippage_bps.get(
            symbol, self._base(symbol).exit_slippage_bps,
        )

    def latency_ms(self, symbol: str) -> int:
        if not self.enabled:
            return 0
        return self.measured_latency_ms.get(symbol, self._base(symbol).latency_ms)

    def spread_map(self, symbols) -> dict[str, float]:
        return {s: self.spread_bps(s) for s in symbols}

    @property
    def is_measured(self) -> bool:
        return self.source == "measured" and self.measured_symbols > 0

    @property
    def is_optimistic(self) -> bool:
        """Maliyetler fiilen kapalı mı? Regresyon kapısı bunu reddeder."""
        return not self.enabled

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "enabled": self.enabled,
            "measured_at": self.measured_at,
            "measured_symbols": self.measured_symbols,
            "optimistic_warning": self.is_optimistic,
            "by_exchange": {k: asdict(v) for k, v in self.by_exchange.items()},
            "measured_spread_bps": dict(self.measured_spread_bps),
            "measured_slippage_bps": dict(self.measured_slippage_bps),
            "measured_exit_slippage_bps": dict(self.measured_exit_slippage_bps),
            "measured_latency_ms": dict(self.measured_latency_ms),
        }

    def summary_text(self) -> str:
        if self.is_optimistic:
            return "MALİYET MODELİ KAPALI — sonuçlar İYİMSER, kârlılık iddiası geçersiz"
        label = "ÖLÇÜLMÜŞ" if self.is_measured else "MUHAFAZAKÂR VARSAYIM (ölçülmedi)"
        return (
            f"Maliyet modeli: {label} · {self.measured_symbols} sembol ölçüldü · "
            + " | ".join(
                f"{ex}: spread {c.spread_bps:.2f}bps, kayma {c.slippage_bps:.2f}bps, "
                f"çıkış kayması {c.exit_slippage_bps:.2f}bps, gecikme {c.latency_ms}ms"
                for ex, c in sorted(self.by_exchange.items())
            )
        )

    # ------------------------------------------------------------------

    @classmethod
    def disabled(cls) -> CostModel:
        """Bilinçli olarak maliyetsiz koşu (yalnızca karşılaştırma için)."""
        return cls(source="disabled", enabled=False)

    @classmethod
    def load(cls, path: str | Path) -> CostModel:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        by_exchange = {
            k: ExchangeCosts(**v)
            for k, v in (raw.get("by_exchange") or {}).items()
        } or dict(DEFAULT_COSTS)
        return cls(
            by_exchange=by_exchange,
            measured_spread_bps={
                k: float(v)
                for k, v in (raw.get("measured_spread_bps") or {}).items()
            },
            measured_slippage_bps={
                k: float(v)
                for k, v in (raw.get("measured_slippage_bps") or {}).items()
            },
            measured_exit_slippage_bps={
                k: float(v)
                for k, v in (raw.get("measured_exit_slippage_bps") or {}).items()
            },
            measured_latency_ms={
                k: int(v)
                for k, v in (raw.get("measured_latency_ms") or {}).items()
            },
            source=raw.get("source", "measured"),
            measured_at=raw.get("measured_at"),
            measured_symbols=int(raw.get("measured_symbols", 0)),
            enabled=bool(raw.get("enabled", True)),
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
