"""SQLite durum deposu — WAL, yazar kilidi, crash-safe niyet kaydı.

ARŞİVDEN DEVRALINAN DERSLER
  * v9.2'de dolmayan maker emri sonrası SQLite kilitlenmesi vardı: niyet
    (intent) önce yazılır, terminal durum sonra işlenir. Böylece süreç ölse
    bile "PENDING" kaydı kalır ve mutabakatla bağlanır.
  * Writer lease hatası YUTULMAZ; görev hatasına yükseltilir.
  * Eski DB yeni koşuya DEVRALINMAZ. Her koşu temiz DB ile başlar.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..core.clock import get_logger, now_ms
from ..core.types import Decision, Order, Position

log = get_logger("state")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lease (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    owner TEXT NOT NULL, acquired_ms INTEGER NOT NULL, renewed_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY, ts_ms INTEGER NOT NULL,
    exchange TEXT, symbol TEXT, closed_bar_key TEXT,
    accepted INTEGER NOT NULL, reject_code TEXT, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decisions_ts ON decisions(ts_ms);
CREATE INDEX IF NOT EXISTS ix_decisions_symbol ON decisions(symbol, ts_ms);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, intent_id TEXT, ts_ms INTEGER NOT NULL,
    state TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_state ON orders(state);
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY, symbol TEXT, open_ms INTEGER NOT NULL,
    close_ms INTEGER, realized_net REAL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_positions_open ON positions(close_ms);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL, payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind, ts_ms);
CREATE TABLE IF NOT EXISTS equity (
    ts_ms INTEGER PRIMARY KEY, realized REAL, unrealized REAL, total REAL,
    open_positions INTEGER
);
"""


class WriterLeaseError(RuntimeError):
    """Yazar kilidi alınamadı/yenilenemedi — yutulmaz, göreve yükseltilir."""


class StateStore:
    def __init__(self, path: Path | str, fresh: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fresh:
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(self.path) + suffix)
                if p.exists():
                    p.unlink()
        self.owner = uuid.uuid4().hex
        self.conn = sqlite3.connect(str(self.path), timeout=15.0,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.executescript(SCHEMA)
        self._lease_ok = False
        self.counts = {"decisions": 0, "orders": 0, "positions": 0,
                       "events": 0, "equity": 0, "lease_renewals": 0}

    # ---------- lease ----------
    def acquire_lease(self) -> None:
        ts = now_ms()
        try:
            row = self.conn.execute("SELECT owner, renewed_ms FROM lease WHERE id=1").fetchone()
            if row and row["owner"] != self.owner and ts - row["renewed_ms"] < 30_000:
                raise WriterLeaseError(
                    f"Başka yazar aktif: {row['owner'][:8]} "
                    f"({(ts - row['renewed_ms']) / 1000:.1f}s önce yeniledi)")
            self.conn.execute(
                "INSERT INTO lease(id,owner,acquired_ms,renewed_ms) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, "
                "acquired_ms=excluded.acquired_ms, renewed_ms=excluded.renewed_ms",
                (self.owner, ts, ts))
            self._lease_ok = True
        except sqlite3.Error as e:
            raise WriterLeaseError(f"lease alınamadı: {e}") from e

    def renew_lease(self) -> None:
        """Hata YUTULMAZ — çağıran supervisor bunu görev ölümü sayar."""
        ts = now_ms()
        try:
            cur = self.conn.execute(
                "UPDATE lease SET renewed_ms=? WHERE id=1 AND owner=?",
                (ts, self.owner))
            if cur.rowcount != 1:
                raise WriterLeaseError("lease sahibi değişmiş; yenileme başarısız")
            self.counts["lease_renewals"] += 1
        except sqlite3.Error as e:
            raise WriterLeaseError(f"lease yenilenemedi: {e}") from e

    # ---------- meta ----------
    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False, default=str)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    # ---------- yazma ----------
    def write_decision(self, d: Decision) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?,?)",
            (d.decision_id, d.ts_ms, d.exchange, d.symbol, d.closed_bar_key,
             int(d.accepted), d.first_reject,
             json.dumps(d.to_dict(), ensure_ascii=False, default=str)))
        self.counts["decisions"] += 1

    def write_order(self, o: Order) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?)",
            (o.order_id, o.intent_id, o.created_ms, o.state.value,
             json.dumps(o.to_dict(), ensure_ascii=False, default=str)))
        self.counts["orders"] += 1

    def write_position(self, p: Position) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?)",
            (p.position_id, p.symbol, p.entry_ms, p.closed_ms, p.realized_net,
             json.dumps(p.to_dict(), ensure_ascii=False, default=str)))
        self.counts["positions"] += 1

    def write_event(self, kind: str, **payload: Any) -> None:
        self.conn.execute(
            "INSERT INTO events(ts_ms,kind,payload) VALUES(?,?,?)",
            (now_ms(), kind, json.dumps(payload, ensure_ascii=False, default=str)))
        self.counts["events"] += 1

    def write_equity(self, realized: float, unrealized: float,
                     open_positions: int, ts_ms: int | None = None) -> None:
        ts = ts_ms if ts_ms is not None else now_ms()
        self.conn.execute(
            "INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?)",
            (ts, realized, unrealized, realized + unrealized, open_positions))
        self.counts["equity"] += 1

    def commit(self) -> None:
        try:
            self.conn.commit()
        except sqlite3.Error as e:
            log.error("commit hatası: %s", e)
            raise

    # ---------- okuma ----------
    def pending_orders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT payload FROM orders WHERE state IN ('PENDING','OPEN','PARTIAL')"
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def open_positions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT payload FROM positions WHERE close_ms IS NULL").fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def reject_histogram(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT reject_code, COUNT(*) c FROM decisions WHERE accepted=0 "
            "GROUP BY reject_code ORDER BY c DESC").fetchall()
        return {r["reject_code"] or "UNKNOWN": r["c"] for r in rows}

    def equity_curve(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM equity ORDER BY ts_ms").fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        return {
            "path": str(self.path), "writer_lease_ok": self._lease_ok,
            "counts": dict(self.counts),
            "reject_histogram": self.reject_histogram(),
            "note": "Bu DB yalnız bu koşuya aittir; sonraki koşuya devredilmez.",
        }

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.execute("DELETE FROM lease WHERE id=1 AND owner=?", (self.owner,))
            self.conn.close()
        except sqlite3.Error:
            pass