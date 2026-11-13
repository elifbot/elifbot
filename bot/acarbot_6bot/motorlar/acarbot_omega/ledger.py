# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA — Atomik İki Aşamalı SQLite Defteri (WAL + PENDING -> COMMIT) (ledger.py)
======================================================================================
Birleştirilen Miras:
  - KRIPTO-BOT v9.5.3 (state_store.py): PENDING niyeti oluşturma, atomik COMMIT/ABORT,
    yetim PENDING tespiti ve matematiksel bakiye mutabakatı (verify_integrity).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .profit_engine import OmegaPosition


@dataclass(frozen=True)
class LedgerIntegrityReport:
    ok: bool
    initial_equity_usd: float
    realized_pnl_sum_usd: float
    expected_cash_usd: float
    stored_cash_usd: float
    open_positions_count: int
    closed_trades_count: int
    stale_pending_intents: int
    discrepancy_usd: float
    errors: List[str]


class AtomicOmegaLedger:
    """Çökme-korumalı (crash-safe) SQLite işlem ve bakiye defteri."""

    def __init__(self, db_path: str | Path = ":memory:", initial_equity_usd: float = 1000.0) -> None:
        self.db_path = str(db_path)
        self.initial_equity_usd = float(initial_equity_usd)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            if self.db_path != ":memory:":
                cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS account_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_equity_usd REAL NOT NULL,
                    cash_balance_usd REAL NOT NULL,
                    updated_ts REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_intents (
                    intent_id TEXT PRIMARY KEY,
                    pos_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_ts REAL NOT NULL,
                    resolved_ts REAL
                );

                CREATE TABLE IF NOT EXISTS open_positions (
                    pos_id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    hard_stop_price REAL NOT NULL,
                    margin_usd REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    opened_ts REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS closed_trades (
                    pos_id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    opened_ts REAL NOT NULL,
                    closed_ts REAL NOT NULL,
                    hold_sec REAL NOT NULL,
                    peak_pnl_usd REAL NOT NULL,
                    net_pnl_usd REAL NOT NULL,
                    trigger_type TEXT NOT NULL,
                    exit_reason TEXT NOT NULL,
                    council_score REAL NOT NULL,
                    edge_to_cost_ratio REAL NOT NULL
                );
                """
            )
            row = cur.execute("SELECT id FROM account_state WHERE id = 1").fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO account_state (id, initial_equity_usd, cash_balance_usd, updated_ts) VALUES (1, ?, ?, ?)",
                    (self.initial_equity_usd, self.initial_equity_usd, time.time()),
                )
            self._conn.commit()

    def prepare_intent(self, pos_id: str, action: str, exchange: str, symbol: str) -> str:
        intent_id = uuid.uuid4().hex[:14]
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO order_intents (intent_id, pos_id, action, exchange, symbol, status, created_ts) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)",
                (intent_id, pos_id, action, exchange, symbol, now),
            )
            self._conn.commit()
        return intent_id

    def commit_open(self, intent_id: str, pos: OmegaPosition) -> None:
        now = time.time()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE order_intents SET status = 'COMMITTED', resolved_ts = ? WHERE intent_id = ?",
                    (now, intent_id),
                )
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO open_positions
                    (pos_id, exchange, symbol, side, entry_price, hard_stop_price, margin_usd, notional_usd, opened_ts, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pos.id,
                        pos.exchange,
                        pos.symbol,
                        pos.side,
                        pos.entry_price,
                        pos.hard_stop_price,
                        pos.margin_usd,
                        pos.notional_usd,
                        pos.opened_ts,
                        json.dumps(pos.to_public_dict(), ensure_ascii=False),
                    ),
                )

    def commit_close(
        self,
        intent_id: str,
        pos: OmegaPosition,
        exit_price: float,
        final_net_pnl_usd: float,
        reason: str,
        closed_ts: float,
    ) -> Dict[str, Any]:
        hold_sec = round(max(0.1, closed_ts - pos.opened_ts), 2)
        rec = {
            "pos_id": pos.id,
            "exchange": pos.exchange,
            "symbol": pos.symbol,
            "side": pos.side_label,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "opened_ts": pos.opened_ts,
            "closed_ts": closed_ts,
            "hold_sec": hold_sec,
            "peak_pnl_usd": round(pos.peak_pnl_usd, 4),
            "net_pnl_usd": round(final_net_pnl_usd, 4),
            "trigger_type": pos.trigger_type,
            "exit_reason": reason,
            "council_score": pos.council_score,
            "edge_to_cost_ratio": pos.edge_to_cost_ratio,
        }
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE order_intents SET status = 'COMMITTED', resolved_ts = ? WHERE intent_id = ?",
                    (closed_ts, intent_id),
                )
                self._conn.execute("DELETE FROM open_positions WHERE pos_id = ?", (pos.id,))
                self._conn.execute(
                    """
                    INSERT INTO closed_trades
                    (pos_id, exchange, symbol, side, entry_price, exit_price, opened_ts, closed_ts,
                     hold_sec, peak_pnl_usd, net_pnl_usd, trigger_type, exit_reason, council_score, edge_to_cost_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec["pos_id"],
                        rec["exchange"],
                        rec["symbol"],
                        rec["side"],
                        rec["entry_price"],
                        rec["exit_price"],
                        rec["opened_ts"],
                        rec["closed_ts"],
                        rec["hold_sec"],
                        rec["peak_pnl_usd"],
                        rec["net_pnl_usd"],
                        rec["trigger_type"],
                        rec["exit_reason"],
                        rec["council_score"],
                        rec["edge_to_cost_ratio"],
                    ),
                )
                self._conn.execute(
                    "UPDATE account_state SET cash_balance_usd = cash_balance_usd + ?, updated_ts = ? WHERE id = 1",
                    (rec["net_pnl_usd"], closed_ts),
                )
        return rec

    def abort_intent(self, intent_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE order_intents SET status = 'ABORTED', resolved_ts = ? WHERE intent_id = ?",
                (time.time(), intent_id),
            )
            self._conn.commit()

    def verify_integrity(self, stale_pending_sec: float = 15.0) -> LedgerIntegrityReport:
        """v9.4.3 / v9.5.3 standardı: Kasa = Başlangıç + ∑(Kapanan Net PnL) ve >15sn PENDING kontrolü."""
        now = time.time()
        errors: List[str] = []
        with self._lock:
            acc = self._conn.execute("SELECT initial_equity_usd, cash_balance_usd FROM account_state WHERE id = 1").fetchone()
            init_eq = float(acc["initial_equity_usd"])
            cash = float(acc["cash_balance_usd"])

            pnl_row = self._conn.execute("SELECT COALESCE(SUM(net_pnl_usd), 0.0) AS s, COUNT(*) AS c FROM closed_trades").fetchone()
            pnl_sum = float(pnl_row["s"])
            closed_cnt = int(pnl_row["c"])

            open_cnt = int(self._conn.execute("SELECT COUNT(*) AS c FROM open_positions").fetchone()["c"])
            stale_cnt = int(
                self._conn.execute(
                    "SELECT COUNT(*) AS c FROM order_intents WHERE status = 'PENDING' AND (? - created_ts) >= ?",
                    (now, stale_pending_sec),
                ).fetchone()["c"]
            )

            expected_cash = init_eq + pnl_sum
            diff = abs(expected_cash - cash)
            if diff > 1e-4:
                errors.append(f"LEDGER_CASH_MISMATCH: beklenen={expected_cash:.4f}, kayıtlı={cash:.4f}")
            if stale_cnt > 0:
                errors.append(f"STALE_PENDING_INTENT: {stale_cnt} adet >{stale_pending_sec}sn asılı niyet")

            return LedgerIntegrityReport(
                ok=(len(errors) == 0),
                initial_equity_usd=round(init_eq, 4),
                realized_pnl_sum_usd=round(pnl_sum, 4),
                expected_cash_usd=round(expected_cash, 4),
                stored_cash_usd=round(cash, 4),
                open_positions_count=open_cnt,
                closed_trades_count=closed_cnt,
                stale_pending_intents=stale_cnt,
                discrepancy_usd=round(diff, 6),
                errors=errors,
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
