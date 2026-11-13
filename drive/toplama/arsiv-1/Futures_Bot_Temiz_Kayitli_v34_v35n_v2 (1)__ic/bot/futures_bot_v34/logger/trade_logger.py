"""
logger/trade_logger.py — CSV işlem kaydı (allowlist'li alanlar).

Güvenlik: yalnızca FIELDS listesindeki alanlar yazılır. HTTP başlıkları,
yanıt gövdeleri, kimlik bilgileri veya mutlak dosya yolları LOGLANMAZ.
Funding verisi yoksa "bilinmiyor" yazılır; olay bazlı funding uygulanmışsa
pozitif maliyet / negatif gelir tutarı yazılır. Asla teyitsiz sıfır kullanılmaz.
Yazımlar flush+fsync ile diske zorlanır; ``log_missing`` oturum sonunda
portföydeki kapanışlarla CSV arasındaki eksikleri çoğaltmadan tamamlar.
"""
from __future__ import annotations

import csv
import logging
import os
from typing import Iterable

from portfolio.paper_futures import FUNDING_LABEL, TradeRecord

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
    "funding_label",
)

#: Funding verisi bulunmayan kayıtlar için metin etiketi.
FUNDING_UNKNOWN = "bilinmiyor"
FUNDING_APPLIED_LABELS = frozenset({"funding dahil / olay bazlı", "funding kısmi / doğrulanmamış"})


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
        else:
            # Eski 16 kolonlu CSV'yi atomik olarak genislet; bilgi uydurma.
            with open(self.path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                old = tuple(reader.fieldnames or ())
                rows = list(reader)
            if old == tuple(f for f in FIELDS if f != "funding_label"):
                tmp = self.path + ".migration.tmp"
                with open(tmp, "w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=FIELDS)
                    w.writeheader()
                    for row in rows:
                        row["funding_label"] = "eski kayıt / doğrulanmamış"
                        w.writerow(row)
                    fh.flush(); os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            elif old != FIELDS:
                raise ValueError("beklenmeyen işlem CSV başlığı")

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
            # Veri yoksa SAYISAL SIFIR değil açık etiket; olay uygulanmışsa
            # pozitif maliyet / negatif gelir olarak gerçek tutar yazılır.
            "funding_fee": (
                round(rec.funding_fee, 10) if rec.funding_label in FUNDING_APPLIED_LABELS
                else FUNDING_UNKNOWN
            ),
            "opened_at": int(rec.opened_at),
            "closed_at": int(rec.closed_at),
            "reason": rec.reason,
            "funding_label": rec.funding_label,
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
            # Dosyayı kapatmak çoğu durumda yeterli olsa da oturum/kopya
            # sınırında kayıp yaşanmaması için veriyi hemen diske zorla.
            fh.flush()
            os.fsync(fh.fileno())
        log.info("%d işlem kaydedildi: %s", count, self.path)
        return count

    @staticmethod
    def _record_key(rec: TradeRecord) -> tuple[str, ...]:
        return (
            rec.exchange, rec.symbol, rec.side,
            str(int(rec.opened_at)), str(int(rec.closed_at)), rec.reason,
        )

    @staticmethod
    def _row_key(row: dict[str, str]) -> tuple[str, ...]:
        return tuple(row.get(k, "") for k in (
            "exchange", "symbol", "side", "opened_at", "closed_at", "reason",
        ))

    def sync_trades(self, records: Iterable[TradeRecord]) -> int:
        """Kapalı işlem görünümünü atomik güncelle; eksik satırı ekle.

        Tek yazıcı varsayımıyla state -> CSV materialization. Başka oturum
        kayıtları korunur; çakışan kimliklerde sessiz veri kaybı yerine hata.
        """
        records = list(records)
        target = {self._record_key(r): self._row(r) for r in records}
        if len(target) != len(records):
            raise ValueError("tekrarli state islem kimligi")
        rows = self.read_rows(self.path)
        seen = set()
        output = []
        changed = False
        for row in rows:
            key = self._row_key(row)
            if key in seen:
                raise ValueError("tekrarli CSV islem kimligi")
            seen.add(key)
            if key in target:
                new = {k: str(v) for k, v in target[key].items()}
                if row != new: changed = True
                output.append(new)
            else:
                output.append(row)
        for key, row in target.items():
            if key not in seen:
                output.append(row); changed = True
        if not changed: return 0
        tmp = self.path + ".sync.tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="raise")
            w.writeheader(); w.writerows(output); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        return 1

    def log_missing(self, records: Iterable[TradeRecord]) -> int:
        """Portföyde olup CSV'de bulunmayan kapanışları oturum sonunda ekler.

        Anahtar; borsa, sembol, yön, açılış/kapanış zamanı ve nedendir. Bu bir
        ticaret kurtarma/geri alma işlemi değil, yalnızca kayıt mutabakatıdır.
        """
        existing = {self._row_key(row) for row in self.read_rows(self.path)}
        missing: list[TradeRecord] = []
        for rec in records:
            key = self._record_key(rec)
            if key not in existing:
                missing.append(rec)
                existing.add(key)
        return self.log_trades(missing)

    @staticmethod
    def read_rows(path: str) -> list[dict[str, str]]:
        """CSV'yi sözlük listesi olarak okur (test/rapor için)."""
        if not os.path.exists(path):
            return []
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
