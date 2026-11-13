"""Tarihsel funding yükleyici ve kapsama denetimi — v5.6.

SORUN
-----
`BacktestEngine.run()` `funding_rates` parametresini kabul ediyordu,
ama `tools/validate_strategy.py` onu HİÇ geçmiyordu. Sonuç: doğrulama
backtest'i funding'i sıfır sayıyordu ve rapor "funding 0" yazıyordu —
bu "funding yok" değil, "funding HESAPLANMADI" idi.

BU MODÜL
--------
1. Funding CSV'lerini yükler (canlı yol ile aynı biçim).
2. KAPSAMAYI denetler: test penceresinde kaç ödeme dönemi var,
   elimizde kaç tane var? Eksikse açıkça söyler.
3. Veri yoksa `None` döndürür — böylece motor "uygulanmadı" der,
   "sıfır" demez.

FUNDING ÖDEME ZAMANLARI
-----------------------
Binance USD-M ve OKX swap'ta standart dönem 8 saattir
(00:00 / 08:00 / 16:00 UTC). Bazı sembollerde 4 saate düşebilir;
bu yüzden dönem sayısı VERİDEN sayılır, varsayılmaz.

YÖN KURALI
----------
Pozitif funding oranında LONG öder, SHORT alır.
Negatif oranda SHORT öder, LONG alır.
Bu işaret kuralı broker tarafında uygulanır; burada yalnız oran taşınır.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000


@dataclass
class FundingCoverage:
    """Bir sembolün funding kapsaması — ölçülmeyeni gizlemez."""

    symbol: str
    rows: int
    first_ts_ms: int
    last_ts_ms: int
    expected_periods: int
    covered_periods: int

    @property
    def coverage_ratio(self) -> float | None:
        if self.expected_periods <= 0:
            return None
        return self.covered_periods / self.expected_periods

    @property
    def complete(self) -> bool:
        r = self.coverage_ratio
        return r is not None and r >= 0.99

    def to_dict(self) -> dict:
        return {
            "sembol": self.symbol,
            "kayit": self.rows,
            "beklenen_donem": self.expected_periods,
            "kapsanan_donem": self.covered_periods,
            "kapsama_orani": self.coverage_ratio,
            "tam": self.complete,
        }


def load_funding_csv(path: Path) -> list[tuple[int, float]]:
    """`<SYM>_funding.csv` → [(ts_ms, rate), ...] zaman sıralı."""
    rows: list[tuple[int, float]] = []
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                ts = int(float(row["timestamp"]))
                rate = float(row["rate"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append((ts, rate))
    rows.sort(key=lambda r: r[0])
    return rows


def load_funding_dir(
    data_dir: str | Path,
    start_ts_ms: int = 0,
    end_ts_ms: int = 0,
) -> tuple[dict[str, list[tuple[int, float]]], dict[str, FundingCoverage]]:
    """Dizindeki tüm funding CSV'lerini yükle + kapsama raporu.

    Dönüş: (rates, coverage). Hiç dosya yoksa ({}, {}) — çağıran
    bunu "funding UYGULANMADI" olarak raporlamalıdır.
    """
    data_dir = Path(data_dir)
    rates: dict[str, list[tuple[int, float]]] = {}
    coverage: dict[str, FundingCoverage] = {}
    for path in sorted(data_dir.glob("*_funding.csv")):
        symbol = path.stem.replace("_funding", "").upper()
        rows = load_funding_csv(path)
        if not rows:
            continue
        rates[symbol] = rows
        # NOT: start_ts_ms == 0 geçerli bir sınırdır; sentinel olarak
        # KULLANILMAZ (ilk sürümde bu hatadan kapsama hep 0 çıkıyordu).
        if end_ts_ms > 0 and end_ts_ms > start_ts_ms:
            in_win = [r for r in rows if start_ts_ms <= r[0] <= end_ts_ms]
            expected = int((end_ts_ms - start_ts_ms) / FUNDING_INTERVAL_MS) + 1
            covered = len(in_win)
        else:
            expected = covered = 0
        coverage[symbol] = FundingCoverage(
            symbol=symbol, rows=len(rows),
            first_ts_ms=rows[0][0], last_ts_ms=rows[-1][0],
            expected_periods=expected, covered_periods=covered,
        )
    return rates, coverage


def funding_status(
    rates: dict[str, list[tuple[int, float]]],
    coverage: dict[str, FundingCoverage],
) -> dict:
    """Rapor için funding durumu — asla sahte sıfır göstermez."""
    if not rates:
        return {
            "durum": "UYGULANMADI",
            "neden": (
                "Tarihsel funding verisi yüklenmedi. Backtest funding'i "
                "HESAPLAMADI; bu 'funding sıfır' anlamına GELMEZ."
            ),
            "sembol_sayisi": 0,
            "toplam_kayit": 0,
        }
    incomplete = [s for s, c in coverage.items() if not c.complete]
    return {
        "durum": "EKSIK_KAPSAMA" if incomplete else "UYGULANDI",
        "sembol_sayisi": len(rates),
        "toplam_kayit": sum(len(v) for v in rates.values()),
        "eksik_kapsamali_semboller": incomplete,
        "kapsama": {s: c.to_dict() for s, c in coverage.items()},
        "neden": (
            f"{len(incomplete)} sembolde dönem kapsaması tam değil."
            if incomplete else "Tüm sembollerde dönem kapsaması tam."
        ),
    }

def match_funding_symbols(rates, coverage, candle_symbols):
    """Map exchange-qualified candle keys to exactly matching file symbols.

    No ambiguous alias guessing (e.g. spot vs swap). Missing symbols are
    explicitly partial/absent rather than a false UYGULANDI verdict.
    """
    mapped = {}
    matched_cov = {}
    missing = []
    for key in candle_symbols:
        instrument = key.split(":", 1)[-1].upper()
        if instrument in rates and rates[instrument]:
            mapped[key] = rates[instrument]
            if instrument in coverage:
                matched_cov[key] = coverage[instrument]
        else:
            missing.append(key)
    status = funding_status(mapped, matched_cov)
    if mapped and (missing or len(matched_cov) != len(mapped)):
        status["durum"] = "EKSIK_KAPSAMA"
        status["neden"] = "Funding tüm istenen sembolleri kapsamıyor."
    status["eslesmeyen_semboller"] = missing
    status["beklenen_sembol_sayisi"] = len(candle_symbols)
    status["donem_kapsama_uyarisi"] = (
        "Kapsama tahmini 8 saatlik dönem varsayar; farklı funding aralıkları ayrıca doğrulanmalı."
    )
    return mapped, status
