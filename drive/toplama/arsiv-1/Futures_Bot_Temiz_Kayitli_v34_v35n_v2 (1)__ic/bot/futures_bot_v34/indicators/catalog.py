"""
indicators/catalog.py — Phase B gösterge envanteri.

Her giriş: input_columns, period_warmup, data_source, status, last_verified_date.

STATUS tanımları
----------------
ACTIVE           : hesaplanıyor ve en az bir aday stratejide kullanılıyor
SHADOW           : hesaplanabilir, ancak hiçbir aday stratejide kullanılmıyor
MISSING          : kodlanmadı veya doğrulanmış bir kaynağı yok
DATA_UNAVAILABLE : veri kaynağı doğrulanmadı (Phase C)

last_verified_date yalnızca HESAPLAMANIN bu depoda doğrulandığı tarihi gösterir;
piyasa verisinin doğrulanması anlamına GELMEZ.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERIFIED_DATE = "2026-10-28"
UNVERIFIED = "dogrulanmadi"


@dataclass(frozen=True)
class IndicatorEntry:
    name: str
    family: str
    input_columns: tuple[str, ...]
    period_warmup: int
    data_source: str
    status: str
    last_verified_date: str = VERIFIED_DATE
    note: str = ""


@dataclass
class IndicatorCatalog:
    """Aile bazlı gösterge envanteri."""

    entries: list[IndicatorEntry] = field(default_factory=list)

    FAMILY_NAMES: dict[str, str] = field(
        default_factory=lambda: {
            "A": "Trend",
            "B": "Momentum",
            "C": "Volatilite",
            "D": "Hacim",
            "E": "Piyasa Yapısı",
            "F": "Vadeli Mikroyapı",
            "G": "Bağlam",
        },
        repr=False,
    )

    def by_family(self, family: str) -> list[IndicatorEntry]:
        return [e for e in self.entries if e.family == family]

    def by_status(self, status: str) -> list[IndicatorEntry]:
        return [e for e in self.entries if e.status == status]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.status] = counts.get(e.status, 0) + 1
        return dict(sorted(counts.items()))

    def get(self, name: str) -> IndicatorEntry | None:
        for e in self.entries:
            if e.name == name:
                return e
        return None

    def total(self) -> int:
        return len(self.entries)


# ---------------------------------------------------------------------------
# Envanter tablosu: (family, name, input_columns, warmup, data_source, status, note)
# ---------------------------------------------------------------------------
_OHLCV = ("open", "high", "low", "close", "volume")
_CLOSE = ("close",)
_CLOSE_VOL = ("close", "volume")

_SPEC: tuple[tuple, ...] = (
    # --- A: Trend ---------------------------------------------------------
    ("A", "EMA 5/8/10/13/21/34/50/100/200 (ribbon)", _CLOSE, 200, "binance/okx klines", "ACTIVE", "yon: 5>8>...>200"),
    ("A", "SMA 20/50/200", _CLOSE, 200, "binance/okx klines", "SHADOW", ""),
    ("A", "WMA", _CLOSE, 20, "binance/okx klines", "SHADOW", ""),
    ("A", "HMA", _CLOSE, 20, "binance/okx klines", "SHADOW", ""),
    ("A", "DEMA", _CLOSE, 40, "binance/okx klines", "SHADOW", ""),
    ("A", "TEMA", _CLOSE, 60, "binance/okx klines", "SHADOW", ""),
    ("A", "KAMA", _CLOSE, 30, "binance/okx klines", "SHADOW", ""),
    ("A", "VWMA", _CLOSE_VOL, 20, "binance/okx klines", "SHADOW", ""),
    ("A", "Ichimoku", _OHLCV, 52, "binance/okx klines", "SHADOW", ""),
    ("A", "Supertrend", _OHLCV, 10, "binance/okx klines", "ACTIVE", "iteratif flip"),
    ("A", "Parabolic SAR", _OHLCV, 10, "binance/okx klines", "SHADOW", ""),
    ("A", "ADX / +DI / -DI", _OHLCV, 28, "binance/okx klines", "ACTIVE", "zincirli warmup"),
    ("A", "Aroon", _OHLCV, 25, "binance/okx klines", "SHADOW", ""),
    # --- B: Momentum ------------------------------------------------------
    ("B", "RSI 14 (Wilder)", _CLOSE, 14, "binance/okx klines", "ACTIVE", ""),
    ("B", "Stoch RSI", _CLOSE, 28, "binance/okx klines", "SHADOW", ""),
    ("B", "Stochastic %K/%D", _OHLCV, 17, "binance/okx klines", "SHADOW", ""),
    ("B", "MACD 12/26/9", _CLOSE, 35, "binance/okx klines", "ACTIVE", ""),
    ("B", "ROC", _CLOSE, 12, "binance/okx klines", "SHADOW", ""),
    ("B", "Momentum", _CLOSE, 10, "binance/okx klines", "SHADOW", ""),
    ("B", "CCI", _OHLCV, 20, "binance/okx klines", "SHADOW", ""),
    ("B", "Williams %R", _OHLCV, 14, "binance/okx klines", "SHADOW", ""),
    ("B", "TSI", _CLOSE, 40, "binance/okx klines", "SHADOW", ""),
    ("B", "TRIX", _CLOSE, 45, "binance/okx klines", "SHADOW", ""),
    ("B", "PPO", _CLOSE, 35, "binance/okx klines", "SHADOW", ""),
    ("B", "CMO", _CLOSE, 14, "binance/okx klines", "SHADOW", ""),
    ("B", "Ultimate Oscillator", _OHLCV, 28, "binance/okx klines", "SHADOW", ""),
    ("B", "Awesome Oscillator", _OHLCV, 34, "binance/okx klines", "SHADOW", ""),
    ("B", "WaveTrend", _OHLCV, 21, "binance/okx klines", "SHADOW", ""),
    # --- C: Volatilite ----------------------------------------------------
    ("C", "ATR / NATR (Wilder)", _OHLCV, 14, "binance/okx klines", "ACTIVE", ""),
    ("C", "Bollinger 20/2 (ddof=1)", _CLOSE, 20, "binance/okx klines", "ACTIVE", ""),
    ("C", "Keltner", _OHLCV, 20, "binance/okx klines", "ACTIVE", ""),
    ("C", "Donchian", _OHLCV, 20, "binance/okx klines", "SHADOW", ""),
    ("C", "BB-Keltner squeeze", _OHLCV, 20, "binance/okx klines", "ACTIVE", ""),
    ("C", "StdDev", _CLOSE, 20, "binance/okx klines", "SHADOW", ""),
    ("C", "Historical Vol", _CLOSE, 21, "binance/okx klines", "SHADOW", ""),
    ("C", "Choppiness", _OHLCV, 14, "binance/okx klines", "SHADOW", ""),
    ("C", "Parkinson vol", _OHLCV, 20, "binance/okx klines", "SHADOW", ""),
    ("C", "Garman-Klass vol", _OHLCV, 20, "binance/okx klines", "SHADOW", ""),
    # --- D: Hacim ---------------------------------------------------------
    ("D", "OBV", _CLOSE_VOL, 1, "binance/okx klines", "SHADOW", ""),
    ("D", "Session VWAP", _OHLCV, 1, "binance/okx klines", "ACTIVE", "gunluk sifirlanir"),
    ("D", "Anchored VWAP", _OHLCV, 1, "binance/okx klines", "SHADOW", "capalanma noktasi kullanici secimi"),
    ("D", "MFI 14", _OHLCV, 14, "binance/okx klines", "SHADOW", ""),
    ("D", "CMF", _OHLCV, 20, "binance/okx klines", "SHADOW", ""),
    ("D", "A/D Line", _OHLCV, 1, "binance/okx klines", "SHADOW", ""),
    ("D", "Force Index", _CLOSE_VOL, 13, "binance/okx klines", "SHADOW", ""),
    ("D", "Relative Volume", _CLOSE_VOL, 20, "binance/okx klines", "SHADOW", ""),
    ("D", "Volume Z-Score", _CLOSE_VOL, 20, "binance/okx klines", "ACTIVE", ""),
    # --- E: Piyasa Yapısı -------------------------------------------------
    ("E", "Swing High/Low (kapalı mum)", _OHLCV, 10, "binance/okx klines", "SHADOW", "sadece kapanmis mum"),
    ("E", "HH/HL/LH/LL", _OHLCV, 10, "binance/okx klines", "SHADOW", ""),
    ("E", "Support/Resistance", _OHLCV, 50, "binance/okx klines", "SHADOW", ""),
    ("E", "Engulfing", _OHLCV, 2, "binance/okx klines", "SHADOW", ""),
    ("E", "Doji", _OHLCV, 1, "binance/okx klines", "SHADOW", ""),
    ("E", "Hammer", _OHLCV, 1, "binance/okx klines", "SHADOW", ""),
    ("E", "Inside Bar", _OHLCV, 2, "binance/okx klines", "SHADOW", ""),
    # --- F: Vadeli Mikroyapı ---------------------------------------------
    ("F", "Funding Rate", ("funding_rate","next_funding_time"), 0, "binance premiumIndex / okx funding-rate (public)", "ACTIVE", "v18: gercek public feed; paper PnL etiketi korunur, olay aninda apply_funding kullanilir"),
    ("F", "Open Interest", ("open_interest",), 0, "binance openInterest / okx open-interest (public)", "ACTIVE", "v18: gercek public feed"),
    ("F", "Mark / Index / Basis", ("mark_price","index_price"), 0, "binance premiumIndex / okx mark-price (public)", "ACTIVE", "v18: gercek public feed"),
    ("F", "Bid-Ask Spread", (), 0, "orderbook dogrulanmamis", "MISSING", ""),
    ("F", "Order Book Imbalance", (), 0, "orderbook dogrulanmamis", "MISSING", ""),
    ("F", "CVD", ("taker_buy_usd","taker_sell_usd"), 0, "binance aggTrade / okx trades (gercek taker akisi)", "ACTIVE", "v16-v17: AkisDefteri CVD15+VWAP60 golgede kullaniliyor"),
    ("F", "Liquidation Flow", (), 0, "dogrulanmamis", "MISSING", ""),
    # --- G: Bağlam --------------------------------------------------------
    ("G", "BTC/ETH korelasyon (kapalı mum)", _CLOSE, 60, "binance/okx klines", "SHADOW", ""),
    ("G", "Rejim dedektörü", _OHLCV, 60, "binance/okx klines", "SHADOW", "ADX + ATR rejimi"),
    ("G", "Sentiment", (), 0, "dogrulanmis public kaynak yok", "MISSING", ""),
)


def build_catalog() -> IndicatorCatalog:
    """Tam envanteri (A-G) oluşturur."""
    entries = [
        IndicatorEntry(
            name=name,
            family=family,
            input_columns=tuple(cols),
            period_warmup=warmup,
            data_source=source,
            status=status,
            last_verified_date=(
                VERIFIED_DATE if status in ("ACTIVE", "SHADOW") else UNVERIFIED
            ),
            note=note,
        )
        for family, name, cols, warmup, source, status, note in _SPEC
    ]
    return IndicatorCatalog(entries=entries)


CATALOG = build_catalog()


def render_catalog_text(catalog: IndicatorCatalog | None = None) -> str:
    """Envanteri düz metin tablo olarak döndürür."""
    cat = catalog or CATALOG
    lines = [
        f"{'AILE':<5}{'GÖSTERGE':<38}{'DURUM':<18}{'WARMUP':<8}{'KAYNAK'}",
        "-" * 100,
    ]
    for fam in ("A", "B", "C", "D", "E", "F", "G"):
        rows = cat.by_family(fam)
        if not rows:
            continue
        lines.append(f"\n[{fam}] {cat.FAMILY_NAMES[fam]}  ({len(rows)} gösterge)")
        for e in rows:
            lines.append(
                f"{'':<5}{e.name:<38}{e.status:<18}{e.period_warmup:<8}{e.data_source}"
            )
    counts = ", ".join(f"{k}={v}" for k, v in cat.status_counts().items())
    lines.append("\nTOPLAM: %d gösterge | %s" % (cat.total(), counts))
    return "\n".join(lines)
