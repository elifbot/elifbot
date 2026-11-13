"""
logger/trade_logger.py — CSV işlem kaydı (allowlist'li alanlar).

Güvenlik: yalnızca FIELDS listesindeki alanlar yazılır. HTTP başlıkları,
yanıt gövdeleri, kimlik bilgileri veya mutlak dosya yolları LOGLANMAZ.
Funding alanı "bilinmiyor" olarak yazılır — asla teyitli sıfır gibi sunulmaz.
"""
from __future__ import annotations

import csv
import logging
import os
from typing import Iterable

from portfolio.paper_futures import TradeRecord

log = logging.getLogger(__name__)

#: Yazılabilecek alanlar (allowlist). Sıra CSV başlığıyla aynıdır.
FIELDS: tuple[str, ...] = (
    "exchange",
    "symbol",
    "side",
    "entry_price",
    "exit_price",
    "qty_base",
    "margin",
    "leverage",
    "entry_fee",
    "exit_fee",
    "gross_pnl",
    "realized_pnl",
    "funding_fee",
    "opened_at",
    "closed_at",
    "reason",
)

#: Funding her zaman bilinmiyor olarak yazılır.
FUNDING_UNKNOWN = "bilinmiyor"


class TradeLogger:
    """Kapalı işlemleri CSV'ye ekler."""

    def __init__(self, path: str = "trades.csv") -> None:
        self.path = path
        self._ensure_header()

    def _ensure_header(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            with open(self.path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(FIELDS)

    def _row(self, rec: TradeRecord) -> dict[str, object]:
        data = {
            "exchange": rec.exchange,
            "symbol": rec.symbol,
            "side": rec.side,
            "entry_price": round(rec.entry_price, 8),
            "exit_price": round(rec.exit_price, 8),
            "qty_base": round(rec.qty_base, 12),
            "margin": round(rec.margin, 8),
            "leverage": round(rec.leverage, 4),
            "entry_fee": round(rec.entry_fee, 10),
            "exit_fee": round(rec.exit_fee, 10),
            "gross_pnl": round(rec.gross_pnl, 10),
            "realized_pnl": round(rec.realized_pnl, 10),
            # Funding çekilmediği için SAYISAL SIFIR değil, açık etiket yazılır.
            "funding_fee": FUNDING_UNKNOWN,
            "opened_at": int(rec.opened_at),
            "closed_at": int(rec.closed_at),
            "reason": rec.reason,
        }
        unknown = set(data) - set(FIELDS)
        if unknown:  # savunma: allowlist dışına çıkılamaz
            raise ValueError(f"allowlist dışı alan: {unknown}")
        return data

    def log_trades(self, records: Iterable[TradeRecord]) -> int:
        """Kayıtları CSV'ye ekler; yazılan satır sayısını döndürür."""
        count = 0
        rows = [self._row(r) for r in records]
        if not rows:
            return 0
        with open(self.path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="raise")
            for row in rows:
                writer.writerow(row)
                count += 1
        log.info("%d işlem kaydedildi: %s", count, self.path)
        return count

    @staticmethod
    def read_rows(path: str) -> list[dict[str, str]]:
        """CSV'yi sözlük listesi olarak okur (test/rapor için)."""
        if not os.path.exists(path):
            return []
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
