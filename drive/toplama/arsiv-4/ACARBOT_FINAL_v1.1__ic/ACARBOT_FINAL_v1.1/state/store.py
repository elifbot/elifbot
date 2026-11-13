"""SQLite durum deposu — süper sürüm.

Eski sürümün operasyonel eleştirileri (Yorum 2) giderildi:
  - `synchronous=FULL` her tick'te fsync yapıyordu → NORMAL (WAL) +
    kritik olaylarda elle checkpoint.
  - `realized_pnl_since_utc_midnight` tüm tabloyu JSON çözüyordu →
    `ts_ms` sütunu + indeks ile SQL SUM.
  - Yedekleme/kurtarma: başlangıçta otomatik sqlite backup.
  - Emir yaşam döngüsü, equity eğrisi ve olay günlüğü tabloları eklendi.
  - Kısılmış kayıt: `save_state_if_due` min aralık uygular.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from core.config import OpsConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    type TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT '',
    motor TEXT NOT NULL DEFAULT '',
    pnl REAL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades (ts_ms);
CREATE INDEX IF NOT EXISTS idx_trades_type_ts ON trades (type, ts_ms);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders (ts_ms);
CREATE TABLE IF NOT EXISTS paper_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS equity_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    equity REAL NOT NULL,
    drawdown_pct REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_points (ts_ms);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    level TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts_ms);
"""


class StateStore:
    def __init__(
        self,
        path: str | Path = "paper_state.sqlite3",
        ops_config: OpsConfig | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ops = ops_config or OpsConfig()
        self._connection = sqlite3.connect(self.path, timeout=10)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA busy_timeout=10000")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()
        self._secure_files()
        self._last_state_save_ms = 0
        self._dirty = False

    def _secure_files(self) -> None:
        try:
            os.chmod(self.path, 0o600)
            for sidecar in (Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
                if sidecar.exists():
                    os.chmod(sidecar, 0o600)
        except OSError:
            self._connection.close()
            raise

    # ------------------------------------------------------------------
    # Yedekleme / kurtarma
    # ------------------------------------------------------------------

    def backup(self, target: str | Path | None = None) -> Path:
        """SQLite backup API ile tutarlı yedek oluşturur."""
        base = self.path.with_suffix("")
        target_path = Path(target) if target else Path(
            f"{base}_backup_{int(datetime.now(timezone.utc).timestamp())}.sqlite3"
        )
        destination = sqlite3.connect(target_path)
        try:
            with destination:
                self._connection.backup(destination)
        finally:
            destination.close()
        os.chmod(target_path, 0o600)
        return target_path

    def rotate_backups(self, keep: int = 5) -> list[Path]:
        base = self.path.with_suffix("")
        backups = sorted(
            self.path.parent.glob(f"{base.name}_backup_*.sqlite3"),
        )
        removed = []
        for old in backups[:-keep] if keep > 0 else backups:
            old.unlink(missing_ok=True)
            removed.append(old)
        return removed

    # ------------------------------------------------------------------
    # Durum kaydı (kısılmış)
    # ------------------------------------------------------------------

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise TypeError("durum yükü sözlük olmalı")
        return json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _decode(raw: str) -> dict[str, Any]:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("kayıtlı durum JSON nesnesi olmalı")
        return value

    def save_state_if_due(
        self, payload: dict[str, Any], now_ms: int, force: bool = False
    ) -> bool:
        """Her tick'te değil, min aralığı aşınca kaydeder (Y2 operasyonel)."""
        if force:
            self.save_state(payload)
            self._last_state_save_ms = now_ms
            self._dirty = False
            return True
        if not self._dirty:
            return False
        if (now_ms - self._last_state_save_ms) / 1000.0 < self.ops.state_save_min_interval_s:
            return False
        self.save_state(payload)
        self._last_state_save_ms = now_ms
        self._dirty = False
        return True

    def mark_dirty(self) -> None:
        self._dirty = True

    def save_state(self, payload: dict[str, Any]) -> None:
        encoded = self._encode(payload)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO paper_state (id, payload) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (encoded,),
            )
        self._secure_files()

    def load_state(self) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload FROM paper_state WHERE id = 1"
        ).fetchone()
        return None if row is None else self._decode(row[0])

    # ------------------------------------------------------------------
    # İşlem kayıtları
    # ------------------------------------------------------------------

    def append_trade(self, trade: dict[str, Any]) -> int:
        ts = trade.get("timestamp", 0)
        if not isinstance(ts, (int, float)):
            ts = 0
        encoded = self._encode(trade)
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO trades (ts_ms, type, symbol, side, motor, pnl, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(ts),
                    str(trade.get("type", "")),
                    str(trade.get("symbol", "")),
                    str(trade.get("side", "")),
                    str(trade.get("motor", "")),
                    float(trade["pnl"]) if isinstance(trade.get("pnl"), (int, float)) else None,
                    encoded,
                ),
            )
        return int(cursor.lastrowid)

    def load_trades(self, limit: int = 1000) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit pozitif tam sayı olmalı")
        rows = self._connection.execute(
            "SELECT payload FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._decode(row[0]) for row in reversed(rows)]

    def realized_pnl_since_utc_midnight(self, now: datetime | None = None) -> float:
        """ts_ms indeksi ile hızlı SQL toplamı (tüm tabloyu JSON-çözmek yok)."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now timezone-bilgili olmalı")
        utc_current = current.astimezone(timezone.utc)
        midnight = datetime.combine(utc_current.date(), time.min, tzinfo=timezone.utc)
        start_ms = int(midnight.timestamp() * 1000)
        row = self._connection.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) FROM trades "
            "WHERE type = 'CLOSE' AND ts_ms >= ?",
            (start_ms,),
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    def append_order_event(
        self, order_id: str, ts_ms: int, symbol: str, status: str,
        payload: dict[str, Any],
    ) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO orders (order_id, ts_ms, symbol, status, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (order_id, int(ts_ms), symbol, status, self._encode(payload)),
            )

    def append_equity_point(
        self, ts_ms: int, equity: float, drawdown_pct: float = 0.0
    ) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO equity_points (ts_ms, equity, drawdown_pct) "
                "VALUES (?, ?, ?)",
                (int(ts_ms), float(equity), float(drawdown_pct)),
            )

    def load_equity_curve(self, limit: int = 100_000) -> list[tuple[int, float]]:
        rows = self._connection.execute(
            "SELECT ts_ms, equity FROM equity_points ORDER BY ts_ms ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(int(r[0]), float(r[1])) for r in rows]

    def append_event(self, ts_ms: int, level: str, code: str, message: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO events (ts_ms, level, code, message) VALUES (?, ?, ?, ?)",
                (int(ts_ms), level, code, message),
            )

    def critical_checkpoint(self) -> None:
        """Kritik olay sonrası WAL checkpoint (pozisyon açma/kapama vb.)."""
        try:
            self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.DatabaseError:
            pass

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
