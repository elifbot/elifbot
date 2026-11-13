"""SQLite WAL storage for paper state and an append-only trade history."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, path: str | Path = "paper_state.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._connection = sqlite3.connect(self.path, timeout=10)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=10000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._connection.commit()
        self._secure_files()

    def _secure_files(self) -> None:
        try:
            os.chmod(self.path, 0o600)
            for sidecar in (Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
                if sidecar.exists():
                    os.chmod(sidecar, 0o600)
        except OSError:
            self._connection.close()
            raise

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise TypeError("state payload must be a dictionary")
        return json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _decode(raw: str) -> dict[str, Any]:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("stored state must be a JSON object")
        return value

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

    def append_trade(self, trade: dict[str, Any]) -> int:
        encoded = self._encode(trade)
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO trades (payload) VALUES (?)", (encoded,)
            )
        self._secure_files()
        return int(cursor.lastrowid)

    def load_trades(self, limit: int = 1000) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        rows = self._connection.execute(
            "SELECT payload FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._decode(row[0]) for row in reversed(rows)]

    def realized_pnl_since_utc_midnight(self, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        utc_current = current.astimezone(timezone.utc)
        midnight = datetime.combine(utc_current.date(), time.min, tzinfo=timezone.utc)
        start_ms = int(midnight.timestamp() * 1000)
        rows = self._connection.execute(
            "SELECT payload FROM trades ORDER BY id"
        ).fetchall()
        realized = 0.0
        for (raw,) in rows:
            trade = self._decode(raw)
            if (
                trade.get("type") == "CLOSE"
                and isinstance(trade.get("timestamp"), (int, float))
                and trade["timestamp"] >= start_ms
            ):
                pnl = trade.get("pnl")
                if isinstance(pnl, bool) or not isinstance(pnl, (int, float)):
                    raise ValueError("stored close trade has invalid realized PnL")
                realized += float(pnl)
        return realized

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
