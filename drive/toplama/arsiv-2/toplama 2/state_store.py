"""SQLite WAL Kalıcı Durum Deposu + Otomatik `.jsonl.gz` Arşiv & `VACUUM` Çöp Toplayıcı."""
from __future__ import annotations

import asyncio
import gzip
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .risk import Position


def paper_position_snapshot(pos: Position) -> dict:
    """Persisted fields only; exact values, no rounding or hash collisions."""
    return {'symbol':str(pos.symbol),'side':str(pos.side),'entry':float(pos.entry),
            'qty':float(pos.qty),'stop':float(pos.stop),'peak':float(pos.peak),
            'locked_profit':bool(pos.locked_profit),'opened_at':str(pos.opened_at or ''),
            'leverage':int(pos.leverage),'margin_usdt':float(pos.margin_usdt),
            'layers':int(pos.layers),'last_add_price':float(pos.last_add_price),
            'exchange':str(pos.exchange or 'binance')}


class StateStore:
    """Açık pozisyonlar, işlem geçmişi, özsermaye, komut kuyruğu ve meta durum deposu."""

    def __init__(
        self,
        db_path: str | Path = "bot_state.db",
        *,
        wal_mode: bool = True,
        archive_dir: str | Path | None = None,
        maintenance_interval_sec: float = 86400.0,
    ):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir = (
            Path(archive_dir)
            if archive_dir
            else self.db_path.parent / "archive"
        )
        self.wal_mode = bool(wal_mode)
        self.maintenance_interval_sec = max(60.0, float(maintenance_interval_sec))
        self.gc_runs: int = 0
        self.archived_rows: int = 0
        self.last_gc_ts: float = 0.0
        self._health_pending_tokens = {}  # process-local observation only, never recovery authority
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            if self.wal_mode:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=FULL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_intents (
                    operation_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','OPEN')),
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_close_intents (
                    operation_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','CLOSED')),
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_funding_intents (
                    operation_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPLIED')),
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_layer_intents (
                    operation_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPLIED')),
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS open_positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    qty REAL NOT NULL,
                    stop REAL NOT NULL,
                    peak REAL NOT NULL,
                    locked_profit INTEGER NOT NULL DEFAULT 0,
                    opened_at TEXT NOT NULL DEFAULT '',
                    leverage INTEGER NOT NULL DEFAULT 20,
                    margin_usdt REAL NOT NULL DEFAULT 0.0,
                    layers INTEGER NOT NULL DEFAULT 1,
                    last_add_price REAL NOT NULL DEFAULT 0.0,
                    exchange TEXT NOT NULL DEFAULT 'binance',
                    updated_at REAL NOT NULL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    qty REAL NOT NULL,
                    leverage INTEGER NOT NULL DEFAULT 20,
                    margin_usdt REAL NOT NULL DEFAULT 0.0,
                    pnl_pct REAL NOT NULL,
                    roe_pct REAL NOT NULL DEFAULT 0.0,
                    pnl_usdt REAL NOT NULL DEFAULT 0.0,
                    reason TEXT NOT NULL,
                    layers INTEGER NOT NULL DEFAULT 1,
                    position_id TEXT NOT NULL DEFAULT '',
                    entry_context TEXT NOT NULL DEFAULT '{}',
                    exchange TEXT NOT NULL DEFAULT '',
                    entry_fee_usdt REAL NOT NULL DEFAULT 0.0,
                    exit_fee_usdt REAL NOT NULL DEFAULT 0.0,
                    funding_usdt REAL NOT NULL DEFAULT 0.0,
                    net_pnl_usdt REAL NOT NULL DEFAULT 0.0,
                    mfe_usdt REAL NOT NULL DEFAULT 0.0,
                    mae_usdt REAL NOT NULL DEFAULT 0.0,
                    stop_price REAL,
                    net_breakeven_price REAL
                );

                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    balance_usdt REAL NOT NULL,
                    equity_usdt REAL NOT NULL,
                    open_positions INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS arbitrage_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    buy_exchange TEXT NOT NULL,
                    sell_exchange TEXT NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    qty REAL NOT NULL,
                    net_spread_pct REAL NOT NULL,
                    profit_usdt REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'FILLED'
                );

                CREATE TABLE IF NOT EXISTS bot_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS command_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    cmd TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    processed INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(trade_history)").fetchall()
            }
            if "position_id" not in columns:
                conn.execute(
                    "ALTER TABLE trade_history ADD COLUMN position_id TEXT NOT NULL DEFAULT ''"
                )
            if "entry_context" not in columns:
                conn.execute(
                    "ALTER TABLE trade_history ADD COLUMN entry_context TEXT NOT NULL DEFAULT '{}'"
                )
            migrations = {
                "exchange": "TEXT NOT NULL DEFAULT ''",
                "entry_fee_usdt": "REAL NOT NULL DEFAULT 0.0",
                "exit_fee_usdt": "REAL NOT NULL DEFAULT 0.0",
                "funding_usdt": "REAL NOT NULL DEFAULT 0.0",
                "net_pnl_usdt": "REAL NOT NULL DEFAULT 0.0",
                "mfe_usdt": "REAL NOT NULL DEFAULT 0.0",
                "mae_usdt": "REAL NOT NULL DEFAULT 0.0",
                "stop_price": "REAL",
                "net_breakeven_price": "REAL",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE trade_history ADD COLUMN {name} {definition}"
                    )
            conn.execute(
                """
                UPDATE trade_history
                SET net_pnl_usdt = pnl_usdt - entry_fee_usdt - exit_fee_usdt + funding_usdt
                WHERE net_pnl_usdt = 0.0 AND pnl_usdt != 0.0
                """
            )

    def get_wal_status(self) -> dict:
        """SQLite WAL modunu, dosya boyutunu ve bakım istatistiklerini döner."""
        mode = "unknown"
        try:
            with self._conn() as conn:
                row = conn.execute("PRAGMA journal_mode;").fetchone()
                if row:
                    mode = str(row[0]).lower()
        except Exception:
            pass
        size = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(f"{self.db_path}{suffix}")
            if p.exists():
                try:
                    size += p.stat().st_size
                except OSError:
                    pass
        return {
            "journal_mode": mode,
            "wal_enabled": mode == "wal",
            "db_size_bytes": size,
            "gc_runs": self.gc_runs,
            "archived_rows": self.archived_rows,
            "last_gc_ts": self.last_gc_ts,
        }

    def run_garbage_collector(
        self,
        *,
        max_trades: int = 2000,
        max_equity: int = 2000,
        max_arb: int = 1000,
    ) -> dict:
        """Eski geçmiş kayıtlarını `.jsonl.gz` arşivine taşıyıp `VACUUM` çalıştırır."""
        archived = 0
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        specs = (
            ("trade_history", max(10, int(max_trades))),
            ("equity_history", max(10, int(max_equity))),
            ("arbitrage_history", max(10, int(max_arb))),
        )
        with self._conn() as conn:
            for table, keep in specs:
                total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                overflow = int(total) - keep
                if overflow <= 0:
                    continue
                old_rows = conn.execute(
                    f"SELECT * FROM {table} ORDER BY id ASC LIMIT ?", (overflow,)
                ).fetchall()
                if not old_rows:
                    continue
                arch_file = self.archive_dir / f"{table}_{stamp}.jsonl.gz"
                with gzip.open(arch_file, "at", encoding="utf-8") as gz:
                    for r in old_rows:
                        gz.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
                max_id = old_rows[-1]["id"]
                conn.execute(f"DELETE FROM {table} WHERE id <= ?", (max_id,))
                archived += len(old_rows)
            conn.execute("DELETE FROM command_queue WHERE processed = 1")

        try:
            raw_conn = sqlite3.connect(str(self.db_path), isolation_level=None, timeout=30.0)
            try:
                raw_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                raw_conn.execute("VACUUM;")
            finally:
                raw_conn.close()
        except Exception:
            pass

        self.gc_runs += 1
        self.archived_rows += archived
        self.last_gc_ts = time.time()
        return {"archived": archived, "gc_runs": self.gc_runs}

    async def maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(self.maintenance_interval_sec)
            try:
                self.run_garbage_collector()
            except Exception:
                pass

    # -- Açık Pozisyon Kalıcılığı ----------------------------------------------
    def has_journal_intents(self) -> bool:
        """Paper intent günlük tablolarından herhangi birinde kayıt var mı?"""
        with self._conn() as conn:
            return any((
                conn.execute("SELECT 1 FROM paper_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_close_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_funding_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_layer_intents LIMIT 1").fetchone(),
            ))

    def is_uninitialized_position_only_fixture(self) -> bool:
        """Yalnızca `save_position` ile tohumlanmış, hiçbir günlük/hesap/meta kaydı olmayan taze test DB'si mi?"""
        with self._conn() as conn:
            has_pos = conn.execute("SELECT 1 FROM open_positions LIMIT 1").fetchone() is not None
            if not has_pos:
                return False
            has_any_other = any((
                conn.execute("SELECT 1 FROM paper_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_close_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_funding_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_layer_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM trade_history LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM bot_meta LIMIT 1").fetchone(),
            ))
            return not has_any_other

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    def acquire_writer_lease(self, owner_id: str, ttl_sec: float = 60.0) -> dict:
        """Tek-yazar sahipliği kilidi (single-writer lease) alır; rakip canlı süreç varsa reddeder."""
        if not owner_id:
            raise ValueError("owner_id gerekli")
        now = time.time()
        pid = os.getpid()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM bot_meta WHERE key='bot_writer_lease'").fetchone()
            if row is not None:
                try:
                    cur = json.loads(row["value"])
                except Exception:
                    cur = {}
                cur_owner = str(cur.get("owner_id") or "")
                cur_pid = int(cur.get("pid") or 0)
                expires_at = float(cur.get("expires_at") or 0.0)
                if (
                    cur_owner
                    and cur_owner != owner_id
                    and expires_at > now
                    and self._is_pid_alive(cur_pid)
                ):
                    raise RuntimeError(
                        f"rakip aktif yazar tespit edildi: owner={cur_owner} pid={cur_pid}"
                    )
            lease = {
                "owner_id": owner_id,
                "pid": pid,
                "acquired_at": now,
                "heartbeat_at": now,
                "expires_at": now + max(5.0, float(ttl_sec)),
            }
            conn.execute(
                "INSERT INTO bot_meta (key,value,updated_at) VALUES ('bot_writer_lease',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (json.dumps(lease, ensure_ascii=False, sort_keys=True), now),
            )
        return lease

    def release_writer_lease(self, owner_id: str) -> None:
        if not owner_id:
            return
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM bot_meta WHERE key='bot_writer_lease'").fetchone()
            if row is None:
                return
            try:
                cur = json.loads(row["value"])
            except Exception:
                cur = {}
            if cur.get("owner_id") == owner_id:
                conn.execute("DELETE FROM bot_meta WHERE key='bot_writer_lease'")

    def paper_ledger_health_snapshot(self) -> dict:
        """Read-only health view; strict recovery validator remains unchanged."""
        from .health_reporting import ledger_health_snapshot
        return ledger_health_snapshot(self)

    def verify_paper_ledger_integrity(self) -> dict:
        """Çift taraflı muhasebe (double-entry) denklemi + günlük + meta bütünlüğünü doğrular."""
        with self._conn() as conn:
            qc = conn.execute("PRAGMA quick_check").fetchone()
            if not qc or str(qc[0]).lower() != "ok":
                return {"ok": False, "reason": "sqlite_quick_check_failed"}

            for table in (
                "paper_intents",
                "paper_close_intents",
                "paper_funding_intents",
                "paper_layer_intents",
            ):
                if conn.execute(f"SELECT 1 FROM {table} WHERE status='PENDING' LIMIT 1").fetchone():
                    return {"ok": False, "reason": f"pending_intent:{table}"}

            open_rows = conn.execute("SELECT * FROM open_positions").fetchall()
            trade_rows = conn.execute("SELECT * FROM trade_history").fetchall()
            acc_row = conn.execute("SELECT value FROM bot_meta WHERE key='paper_account'").fetchone()
            meta_row = conn.execute("SELECT value FROM bot_meta WHERE key='position_meta'").fetchone()
            clock_row = conn.execute("SELECT value FROM bot_meta WHERE key='paper_funding_clock'").fetchone()

            has_any_activity = bool(
                open_rows
                or trade_rows
                or acc_row is not None
                or conn.execute("SELECT 1 FROM paper_intents LIMIT 1").fetchone()
                or conn.execute("SELECT 1 FROM paper_close_intents LIMIT 1").fetchone()
                or conn.execute("SELECT 1 FROM paper_funding_intents LIMIT 1").fetchone()
                or conn.execute("SELECT 1 FROM paper_layer_intents LIMIT 1").fetchone()
            )
            if not has_any_activity:
                return {"ok": True, "empty": True, "reason": "clean_empty_db"}

            if acc_row is None:
                return {"ok": False, "reason": "missing_paper_account"}
            try:
                acc = json.loads(acc_row["value"])
                pos_meta = json.loads(meta_row["value"]) if meta_row is not None else {}
                f_clock = json.loads(clock_row["value"]) if clock_row is not None else {}
            except Exception:
                return {"ok": False, "reason": "corrupt_meta_json"}

            if not all(isinstance(x, dict) for x in (acc, pos_meta, f_clock)):
                return {"ok": False, "reason": "invalid_meta_types"}

            for key in ("balance", "start_balance", "total_fees_usdt", "total_funding_usdt"):
                val = acc.get(key)
                if val is None or isinstance(val, bool) or not math.isfinite(float(val)):
                    return {"ok": False, "reason": f"invalid_account_field:{key}"}
            balance = float(acc["balance"])
            start_balance = float(acc["start_balance"])
            total_fees = float(acc["total_fees_usdt"])
            total_funding = float(acc["total_funding_usdt"])
            if start_balance <= 0 or total_fees < -1e-12:
                return {"ok": False, "reason": "negative_fee_or_nonpositive_start"}

            open_entry_fees = 0.0
            open_funding = 0.0
            open_syms = set()
            for r in open_rows:
                sym = str(r["symbol"])
                open_syms.add(sym)
                if r["side"] not in ("LONG", "SHORT"):
                    return {"ok": False, "reason": f"invalid_side:{sym}"}
                for fld in ("entry", "qty", "stop"):
                    fv = float(r[fld])
                    if not math.isfinite(fv) or fv <= 0:
                        return {"ok": False, "reason": f"invalid_pos_{fld}:{sym}"}
                m = pos_meta.get(sym)
                if not isinstance(m, dict) or not m.get("position_id"):
                    return {"ok": False, "reason": f"missing_position_meta:{sym}"}
                ef = m.get("entry_fee_usdt")
                fu = m.get("funding_usdt")
                fc = f_clock.get(sym)
                if (
                    ef is None or isinstance(ef, bool) or not math.isfinite(float(ef)) or float(ef) < -1e-12
                    or fu is None or isinstance(fu, bool) or not math.isfinite(float(fu))
                    or fc is None or isinstance(fc, bool) or not math.isfinite(float(fc)) or float(fc) <= 0
                ):
                    return {"ok": False, "reason": f"invalid_position_cost_or_clock:{sym}"}
                open_entry_fees += float(ef)
                open_funding += float(fu)

            if set(pos_meta.keys()) != open_syms:
                return {"ok": False, "reason": "orphan_position_meta"}

            realized_gross_pnl = 0.0
            closed_entry_fees = 0.0
            closed_exit_fees = 0.0
            closed_funding = 0.0
            for tr in trade_rows:
                for fld in ("pnl_usdt", "entry_fee_usdt", "exit_fee_usdt", "funding_usdt"):
                    tv = float(tr[fld])
                    if not math.isfinite(tv):
                        return {"ok": False, "reason": f"non_finite_trade_{fld}"}
                realized_gross_pnl += float(tr["pnl_usdt"])
                closed_entry_fees += float(tr["entry_fee_usdt"])
                closed_exit_fees += float(tr["exit_fee_usdt"])
                closed_funding += float(tr["funding_usdt"])

            expected_fees = closed_entry_fees + closed_exit_fees + open_entry_fees
            expected_funding = closed_funding + open_funding
            expected_balance = start_balance + realized_gross_pnl - expected_fees + expected_funding

            if not math.isclose(total_fees, expected_fees, rel_tol=1e-9, abs_tol=1e-6):
                return {
                    "ok": False,
                    "reason": f"fee_mismatch:actual={total_fees:.8f},expected={expected_fees:.8f}",
                }
            if not math.isclose(total_funding, expected_funding, rel_tol=1e-9, abs_tol=1e-6):
                return {
                    "ok": False,
                    "reason": f"funding_mismatch:actual={total_funding:.8f},expected={expected_funding:.8f}",
                }
            if not math.isclose(balance, expected_balance, rel_tol=1e-9, abs_tol=1e-5):
                return {
                    "ok": False,
                    "reason": f"cash_conservation_mismatch:actual={balance:.8f},expected={expected_balance:.8f}",
                }

            return {
                "ok": True,
                "empty": False,
                "balance": balance,
                "expected_balance": expected_balance,
                "total_fees_usdt": total_fees,
                "total_funding_usdt": total_funding,
                "open_positions": len(open_rows),
                "closed_trades": len(trade_rows),
            }

    def commit_external_close(
        self,
        symbol: str,
        remaining_pos: Position | None,
        position_meta: dict,
        trade_plans: dict,
        trade_record: dict,
    ) -> None:
        """Paper defteri kullanmayan izole birim testi brokerları için atomik kapanış kaydı."""
        now = time.time()
        meta_json = json.dumps(position_meta, ensure_ascii=False, sort_keys=True, allow_nan=False)
        plans_json = json.dumps(trade_plans, ensure_ascii=False, sort_keys=True, allow_nan=False)
        entry_ctx = trade_record.get("entry_context", {})
        if not isinstance(entry_ctx, str):
            entry_ctx = json.dumps(entry_ctx, ensure_ascii=False, default=str)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if remaining_pos is None:
                conn.execute("DELETE FROM open_positions WHERE symbol = ?", (symbol,))
            else:
                conn.execute(
                    """
                    INSERT INTO open_positions
                    (symbol, side, entry, qty, stop, peak, locked_profit, opened_at,
                     leverage, margin_usdt, layers, last_add_price, exchange, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        side=excluded.side, entry=excluded.entry, qty=excluded.qty,
                        stop=excluded.stop, peak=excluded.peak, locked_profit=excluded.locked_profit,
                        opened_at=excluded.opened_at, leverage=excluded.leverage,
                        margin_usdt=excluded.margin_usdt, layers=excluded.layers,
                        last_add_price=excluded.last_add_price, exchange=excluded.exchange,
                        updated_at=excluded.updated_at
                    """,
                    (
                        remaining_pos.symbol,
                        remaining_pos.side,
                        float(remaining_pos.entry),
                        float(remaining_pos.qty),
                        float(remaining_pos.stop),
                        float(remaining_pos.peak),
                        1 if remaining_pos.locked_profit else 0,
                        str(remaining_pos.opened_at or ""),
                        int(remaining_pos.leverage),
                        float(remaining_pos.margin_usdt),
                        int(remaining_pos.layers),
                        float(remaining_pos.last_add_price),
                        str(remaining_pos.exchange or "binance"),
                        now,
                    ),
                )
            for key, payload in (("position_meta", meta_json), ("trade_plans", plans_json)):
                conn.execute(
                    "INSERT INTO bot_meta (key,value,updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, payload, now),
                )
            conn.execute(
                """
                INSERT INTO trade_history
                (ts, symbol, side, entry, exit_price, qty, pnl_pct, reason,
                 leverage, margin_usdt, pnl_usdt, layers, position_id, entry_context,
                 exchange, entry_fee_usdt, exit_fee_usdt, funding_usdt, net_pnl_usdt,
                 mfe_usdt, mae_usdt, stop_price, net_breakeven_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    float(trade_record.get("ts") or now),
                    str(trade_record["symbol"]),
                    str(trade_record["side"]),
                    float(trade_record["entry"]),
                    float(trade_record["exit_price"]),
                    float(trade_record["qty"]),
                    float(trade_record["pnl_pct"]),
                    str(trade_record["reason"]),
                    int(trade_record.get("leverage", 1)),
                    float(trade_record.get("margin_usdt", 0.0)),
                    float(trade_record.get("pnl_usdt", 0.0)),
                    int(trade_record.get("layers", 1)),
                    str(trade_record.get("position_id", "")),
                    entry_ctx,
                    str(trade_record.get("exchange", "")),
                    float(trade_record.get("entry_fee_usdt", 0.0)),
                    float(trade_record.get("exit_fee_usdt", 0.0)),
                    float(trade_record.get("funding_usdt", 0.0)),
                    float(trade_record.get("net_pnl_usdt", 0.0)),
                    float(trade_record.get("mfe_usdt", 0.0)),
                    float(trade_record.get("mae_usdt", 0.0)),
                    trade_record.get("stop_price"),
                    trade_record.get("net_breakeven_price"),
                ),
            )

    def paper_requires_recovery(self) -> bool:
        """Restart güvenlik kapısı: elle doğrulama sistemi henüz geliştirilmedi.

        Bu sınırlı aday, yeniden açılan finansal DB'yi otomatik kullanmaz.
        Boş, yeni DB dışında her durumda kilitli başlatır.
        """
        with self._conn() as conn:
            return any((
                conn.execute("SELECT 1 FROM paper_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_close_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_funding_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM paper_layer_intents LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM open_positions LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM trade_history LIMIT 1").fetchone(),
                conn.execute("SELECT 1 FROM bot_meta WHERE key='paper_account' LIMIT 1").fetchone(),
            ))

    def prepare_paper_open(self, operation_id: str, request: dict) -> None:
        if not operation_id or not isinstance(request, dict):
            raise ValueError("invalid paper open intent")
        payload = json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Optional protocol for the v9.0 Executor: reject an opening based
            # on a stale process-local paper account BEFORE creating intent or
            # fill. This is not a complete multi-process ownership protocol.
            expected = request.get('_expected_paper_state')
            if expected is not None:
                if not isinstance(expected,dict) or not isinstance(expected.get('symbols'),list) or not isinstance(expected.get('account'),dict):
                    raise ValueError('invalid expected paper state')
                actual_symbols = sorted(row['symbol'] for row in conn.execute('SELECT symbol FROM open_positions'))
                if actual_symbols != sorted(expected['symbols']):
                    raise RuntimeError('paper state changed in another process: positions')
                account_row = conn.execute("SELECT value FROM bot_meta WHERE key='paper_account'").fetchone()
                if account_row is None:
                    if actual_symbols:
                        raise RuntimeError('persisted paper account missing')
                else:
                    saved=json.loads(account_row['value'])
                    if not isinstance(saved,dict):
                        raise RuntimeError('persisted paper account invalid')
                    for key in ('balance','start_balance','total_fees_usdt','total_funding_usdt'):
                        if (key not in saved or key not in expected['account']
                                or isinstance(saved[key],bool) or isinstance(expected['account'][key],bool)
                                or not math.isfinite(float(saved[key])) or not math.isfinite(float(expected['account'][key]))
                                or float(saved[key]) != float(expected['account'][key])):
                            raise RuntimeError('paper state changed in another process: account')
                # State beyond symbols/account matters: another writer may
                # have changed stop, plan, metadata or funding cursor without
                # affecting either. Fields are compared exactly, not rounded.
                if 'positions' in expected:
                    keys=('symbol','side','entry','qty','stop','peak','locked_profit',
                          'opened_at','leverage','margin_usdt','layers','last_add_price','exchange')
                    actual={}
                    for row in conn.execute('SELECT '+','.join(keys)+' FROM open_positions'):
                        record={k:row[k] for k in keys}
                        record['locked_profit']=bool(record['locked_profit'])
                        actual[record['symbol']]=record
                    if actual != expected['positions']:
                        raise RuntimeError('paper state changed in another process: position fields')
                for key in ('position_meta','trade_plans','paper_funding_clock'):
                    if key in expected:
                        row=conn.execute('SELECT value FROM bot_meta WHERE key=?',(key,)).fetchone()
                        saved=json.loads(row['value']) if row is not None else {}
                        if saved != expected[key]:
                            raise RuntimeError('paper state changed in another process: '+key)
            if conn.execute("SELECT 1 FROM paper_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError("unresolved paper intent")
            if conn.execute("SELECT 1 FROM paper_close_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError("unresolved paper close intent")
            if conn.execute("SELECT 1 FROM paper_funding_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError("unresolved paper funding intent")
            if conn.execute("SELECT 1 FROM paper_layer_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError("unresolved paper layer intent")
            conn.execute("INSERT INTO paper_intents VALUES (?,?,?, 'PENDING',?)",
                         (operation_id, str(request['symbol']), payload, time.time()))

        self._health_pending_tokens[("paper_intents", operation_id)] = (os.getpid(), time.monotonic())

    def commit_paper_open(self, operation_id: str, pos: Position, account: dict,
                          position_meta: dict, trade_plans: dict, funding_clock: dict) -> None:
        """Paper açılışında pozisyon, hesap, ek meta ve PENDING->OPEN tek COMMIT.

        Bu yalnız açılış prototipidir; kapanış/funding henüz bu işlemde değildir.
        COMMIT istisnası gerçekleşmedi demek değildir; çağıran kilitli kalır.
        """
        payloads={key:json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
                  for key,value in {'paper_account':account,'position_meta':position_meta,
                                    'trade_plans':trade_plans,'paper_funding_clock':funding_clock}.items()}
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT symbol FROM paper_intents WHERE operation_id=? AND status='PENDING'",
                             (operation_id,)).fetchone()
            if row is None or row['symbol'] != pos.symbol:
                raise RuntimeError("missing or conflicting pending intent")
            conn.execute("""INSERT INTO open_positions
                (symbol,side,entry,qty,stop,peak,locked_profit,opened_at,leverage,
                 margin_usdt,layers,last_add_price,exchange,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pos.symbol,pos.side,float(pos.entry),float(pos.qty),float(pos.stop),
                 float(pos.peak),1 if pos.locked_profit else 0,str(pos.opened_at or ''),
                 int(pos.leverage),float(pos.margin_usdt),int(pos.layers),
                 float(pos.last_add_price),str(pos.exchange or 'binance'),time.time()))
            for key, payload in payloads.items():
                conn.execute("""INSERT INTO bot_meta (key,value,updated_at) VALUES (?,?,?)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                  (key,payload,time.time()))
            changed=conn.execute("UPDATE paper_intents SET status='OPEN' WHERE operation_id=? AND status='PENDING'",
                                 (operation_id,))
            if changed.rowcount != 1:
                raise RuntimeError('paper intent update failed')

    def cancel_unfilled_paper_open(self, operation_id: str, expected_symbol: str) -> None:
        """Pasif Maker limit emri hiç dolmadan (qty=0) iptal/süre-aşımı olduğunda
        hiçbir kasa veya pozisyon değişmediği doğrulandıktan sonra PENDING niyetini kapatır."""
        if not operation_id or not expected_symbol:
            raise ValueError("invalid cancel_unfilled_paper_open arguments")
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT symbol FROM paper_intents WHERE operation_id=? AND status='PENDING'",
                (operation_id,),
            ).fetchone()
            if row is None or str(row["symbol"]) != str(expected_symbol):
                raise RuntimeError("missing or mismatched pending paper open intent")
            pos_exists = conn.execute(
                "SELECT 1 FROM open_positions WHERE symbol=? LIMIT 1",
                (expected_symbol,),
            ).fetchone()
            if pos_exists is not None:
                raise RuntimeError("cannot cancel unfilled intent: position already persisted")
            changed = conn.execute(
                "DELETE FROM paper_intents WHERE operation_id=? AND status='PENDING'",
                (operation_id,),
            )
            if changed.rowcount != 1:
                raise RuntimeError("paper unfilled intent delete failed")

    def prepare_paper_close(self, operation_id: str, symbol: str, qty: float) -> None:
        """Persist close intent before a simulated fill; never used for live orders."""
        qty = float(qty)
        if not operation_id or not symbol or not math.isfinite(qty) or qty <= 0:
            raise ValueError('invalid paper close request')
        payload = json.dumps({'symbol':symbol,'qty':qty}, allow_nan=False, sort_keys=True)
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT 1 FROM paper_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError('unresolved paper open intent')
            if conn.execute("SELECT 1 FROM paper_close_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError('unresolved paper close intent')
            if conn.execute("SELECT 1 FROM paper_funding_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError('unresolved paper funding intent')
            if conn.execute("SELECT 1 FROM paper_layer_intents WHERE status='PENDING' LIMIT 1").fetchone():
                raise RuntimeError('unresolved paper layer intent')
            row = conn.execute('SELECT qty FROM open_positions WHERE symbol=?', (symbol,)).fetchone()
            if row is None or qty > float(row['qty']) + max(1e-12, float(row['qty'])*1e-9):
                raise RuntimeError('paper close does not match persisted position')
            conn.execute("INSERT INTO paper_close_intents VALUES (?,?,?,'PENDING',?)",
                         (operation_id,symbol,payload,time.time()))

        self._health_pending_tokens[("paper_close_intents", operation_id)] = (os.getpid(), time.monotonic())

    def commit_paper_close(self, operation_id: str, symbol: str, original_qty: float,
                           remaining: Position | None, account: dict, position_meta: dict,
                           trade_plans: dict, funding_clock: dict, trade: dict) -> None:
        """Atomic paper close: position, account, trade and metadata in one transaction.

        Any exception, including after COMMIT, is an unknown result to the caller;
        no automatic retries or unlocks. Restart remains fail-closed.
        """
        original_qty = float(original_qty)
        if not math.isfinite(original_qty) or original_qty <= 0:
            raise ValueError('invalid original quantity')
        if trade.get('symbol') != symbol or float(trade['qty']) <= 0:
            raise ValueError('trade does not match close request')
        payloads={key:json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
                  for key,value in {'paper_account':account,'position_meta':position_meta,
                                    'trade_plans':trade_plans,'paper_funding_clock':funding_clock}.items()}
        columns=('ts','symbol','side','entry','exit_price','qty','leverage','margin_usdt',
                 'pnl_pct','roe_pct','pnl_usdt','reason','layers','position_id','entry_context',
                 'exchange','entry_fee_usdt','exit_fee_usdt','funding_usdt','net_pnl_usdt',
                 'mfe_usdt','mae_usdt','stop_price','net_breakeven_price')
        row=dict(trade)
        row['roe_pct']=float(row['pnl_pct'])*int(row['leverage'])
        row['entry_context']=json.dumps(row.get('entry_context') or {},ensure_ascii=False,default=str,allow_nan=False,separators=(',',':'))
        for key in ('ts','entry','exit_price','qty','margin_usdt','pnl_pct','roe_pct','pnl_usdt',
                    'entry_fee_usdt','exit_fee_usdt','funding_usdt','net_pnl_usdt','mfe_usdt','mae_usdt'):
            if not math.isfinite(float(row[key])):
                raise ValueError('non-finite trade field: '+key)
        if float(row['entry']) <= 0 or float(row['exit_price']) <= 0:
            raise ValueError('invalid execution price')
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            intent=conn.execute("SELECT symbol,request_json FROM paper_close_intents WHERE operation_id=? AND status='PENDING'",(operation_id,)).fetchone()
            old=conn.execute('SELECT qty FROM open_positions WHERE symbol=?',(symbol,)).fetchone()
            if intent is None or intent['symbol'] != symbol or old is None:
                raise RuntimeError('missing close intent or position')
            req=json.loads(intent['request_json'])
            if not math.isclose(float(old['qty']),original_qty,rel_tol=1e-9,abs_tol=1e-12):
                raise RuntimeError('persisted quantity changed')
            if float(row['qty']) > float(req['qty'])+max(1e-12,original_qty*1e-9):
                raise RuntimeError('fill exceeds requested close')
            left=original_qty-float(row['qty'])
            if remaining is None:
                if not math.isclose(left,0,rel_tol=0,abs_tol=max(1e-12,original_qty*1e-9)):
                    raise RuntimeError('not fully closed')
                conn.execute('DELETE FROM open_positions WHERE symbol=?',(symbol,))
            else:
                if remaining.symbol != symbol or not math.isclose(float(remaining.qty),left,rel_tol=1e-9,abs_tol=1e-12):
                    raise RuntimeError('invalid remaining position')
                conn.execute('UPDATE open_positions SET qty=?,margin_usdt=?,stop=?,peak=?,updated_at=? WHERE symbol=?',
                             (float(remaining.qty),float(remaining.margin_usdt),float(remaining.stop),float(remaining.peak),time.time(),symbol))
            conn.execute('INSERT INTO trade_history ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                         tuple(row[k] for k in columns))
            for key,payload in payloads.items():
                conn.execute("INSERT INTO bot_meta (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,payload,time.time()))
            changed=conn.execute("UPDATE paper_close_intents SET status='CLOSED' WHERE operation_id=? AND status='PENDING'",(operation_id,))
            if changed.rowcount != 1:
                raise RuntimeError('paper close intent update failed')

    def prepare_paper_funding(self, operation_id: str, symbol: str, request: dict) -> None:
        """Journal a synthetic paper accrual before modifying in-memory account."""
        if not operation_id or not symbol or not isinstance(request, dict):
            raise ValueError('invalid funding intent')
        for key in ('delta','old_balance','old_funding','old_clock','new_clock','qty'):
            if not math.isfinite(float(request[key])):
                raise ValueError('non-finite funding input')
        if float(request['qty']) <= 0 or float(request['new_clock']) <= float(request['old_clock']):
            raise ValueError('invalid funding quantity or clock')
        payload=json.dumps(request,ensure_ascii=False,sort_keys=True,allow_nan=False)
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for table in ('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents'):
                if conn.execute("SELECT 1 FROM "+table+" WHERE status='PENDING' LIMIT 1").fetchone():
                    raise RuntimeError('another paper financial intent is pending')
            pos=conn.execute('SELECT qty FROM open_positions WHERE symbol=?',(symbol,)).fetchone()
            if pos is None or not math.isclose(float(pos['qty']),float(request['qty']),rel_tol=1e-9,abs_tol=1e-12):
                raise RuntimeError('funding position changed or not persisted')
            conn.execute("INSERT INTO paper_funding_intents VALUES (?,?,?,'PENDING',?)",
                         (operation_id,symbol,payload,time.time()))

        self._health_pending_tokens[("paper_funding_intents", operation_id)] = (os.getpid(), time.monotonic())

    def commit_paper_funding(self, operation_id: str, symbol: str, account: dict,
                             position_meta: dict, funding_clock: dict) -> None:
        """One transaction for paper funding balance, per-position meta, clock and intent."""
        payloads={key:json.dumps(value,ensure_ascii=False,default=str,allow_nan=False)
                  for key,value in {'paper_account':account,'position_meta':position_meta,
                                    'paper_funding_clock':funding_clock}.items()}
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            intent=conn.execute("SELECT symbol,request_json FROM paper_funding_intents WHERE operation_id=? AND status='PENDING'",(operation_id,)).fetchone()
            pos=conn.execute('SELECT qty FROM open_positions WHERE symbol=?',(symbol,)).fetchone()
            if intent is None or intent['symbol']!=symbol or pos is None:
                raise RuntimeError('missing paper funding intent or position')
            req=json.loads(intent['request_json'])
            def read(key):
                row=conn.execute('SELECT value FROM bot_meta WHERE key=?',(key,)).fetchone()
                if row is None: raise RuntimeError('missing stored funding metadata: '+key)
                return json.loads(row['value'])
            old_account=read('paper_account'); old_meta=read('position_meta'); old_clock=read('paper_funding_clock')
            eq=lambda a,b: math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-9)
            if (not eq(pos['qty'],req['qty']) or not eq(old_account['balance'],req['old_balance'])
                or not eq(old_meta[symbol].get('funding_usdt',0),req['old_funding'])
                or not eq(old_clock[symbol],req['old_clock'])
                or not eq(account['balance'],req['old_balance']+req['delta'])
                or not eq(position_meta[symbol]['funding_usdt'],req['old_funding']+req['delta'])
                or not eq(funding_clock[symbol],req['new_clock'])):
                raise RuntimeError('funding state changed or accounting mismatch')
            for key,payload in payloads.items():
                conn.execute("INSERT INTO bot_meta (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,payload,time.time()))
            changed=conn.execute("UPDATE paper_funding_intents SET status='APPLIED' WHERE operation_id=? AND status='PENDING'",(operation_id,))
            if changed.rowcount!=1: raise RuntimeError('funding intent update failed')

    def prepare_paper_layer(self, operation_id: str, symbol: str, request: dict) -> None:
        if not operation_id or not symbol or not isinstance(request,dict):
            raise ValueError('invalid layer intent')
        for key in ('original_qty','requested_qty','old_balance','old_fee'):
            if not math.isfinite(float(request[key])):
                raise ValueError('non-finite layer input')
        if float(request['original_qty'])<=0 or float(request['requested_qty'])<=0:
            raise ValueError('invalid layer quantity')
        payload=json.dumps(request,ensure_ascii=False,sort_keys=True,allow_nan=False)
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for table in ('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents'):
                if conn.execute("SELECT 1 FROM "+table+" WHERE status='PENDING' LIMIT 1").fetchone():
                    raise RuntimeError('another paper financial intent is pending')
            pos=conn.execute('SELECT qty FROM open_positions WHERE symbol=?',(symbol,)).fetchone()
            if pos is None or not math.isclose(float(pos['qty']),float(request['original_qty']),rel_tol=1e-9,abs_tol=1e-12):
                raise RuntimeError('layer position changed or not persisted')
            conn.execute("INSERT INTO paper_layer_intents VALUES (?,?,?,'PENDING',?)",(operation_id,symbol,payload,time.time()))

        self._health_pending_tokens[("paper_layer_intents", operation_id)] = (os.getpid(), time.monotonic())

    def commit_paper_layer(self, operation_id: str, pos: Position, fill_qty: float, fill_fee: float,
                           account: dict, position_meta: dict, trade_plans: dict, funding_clock: dict) -> None:
        payloads={key:json.dumps(value,ensure_ascii=False,default=str,allow_nan=False)
                  for key,value in {'paper_account':account,'position_meta':position_meta,
                                    'trade_plans':trade_plans,'paper_funding_clock':funding_clock}.items()}
        if not math.isfinite(float(fill_qty)) or not math.isfinite(float(fill_fee)) or fill_qty<=0 or fill_fee<0:
            raise ValueError('invalid layer fill')
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            intent=conn.execute("SELECT symbol,request_json FROM paper_layer_intents WHERE operation_id=? AND status='PENDING'",(operation_id,)).fetchone()
            old=conn.execute('SELECT qty FROM open_positions WHERE symbol=?',(pos.symbol,)).fetchone()
            if intent is None or intent['symbol']!=pos.symbol or old is None:
                raise RuntimeError('missing layer intent or position')
            req=json.loads(intent['request_json'])
            def read(key):
                row=conn.execute('SELECT value FROM bot_meta WHERE key=?',(key,)).fetchone()
                if row is None: raise RuntimeError('missing stored metadata: '+key)
                return json.loads(row['value'])
            old_account=read('paper_account');old_meta=read('position_meta')
            eq=lambda a,b:math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-9)
            if (not eq(old['qty'],req['original_qty']) or fill_qty>float(req['requested_qty'])+1e-9
                or not eq(pos.qty,float(req['original_qty'])+fill_qty)
                or not eq(old_account['balance'],req['old_balance'])
                or not eq(old_meta[pos.symbol].get('entry_fee_usdt',0),req['old_fee'])
                or not eq(account['balance'],float(req['old_balance'])-fill_fee)
                or not eq(position_meta[pos.symbol]['entry_fee_usdt'],float(req['old_fee'])+fill_fee)):
                raise RuntimeError('layer state changed or accounting mismatch')
            conn.execute("""UPDATE open_positions SET side=?,entry=?,qty=?,stop=?,peak=?,locked_profit=?,opened_at=?,
                         leverage=?,margin_usdt=?,layers=?,last_add_price=?,exchange=?,updated_at=? WHERE symbol=?""",
                (pos.side,float(pos.entry),float(pos.qty),float(pos.stop),float(pos.peak),1 if pos.locked_profit else 0,
                 str(pos.opened_at or ''),int(pos.leverage),float(pos.margin_usdt),int(pos.layers),
                 float(pos.last_add_price),str(pos.exchange or 'binance'),time.time(),pos.symbol))
            for key,payload in payloads.items():
                conn.execute("INSERT INTO bot_meta (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,payload,time.time()))
            changed=conn.execute("UPDATE paper_layer_intents SET status='APPLIED' WHERE operation_id=? AND status='PENDING'",(operation_id,))
            if changed.rowcount!=1:raise RuntimeError('paper layer intent update failed')

    def update_paper_risk_if_unchanged(self, before: dict, pos: Position) -> None:
        """CAS trailing stop/peak with journal exclusion; no account mutation.

        A mismatch or ambiguous write is not retried. This is a narrow paper
        risk update, not a general multi-writer ownership protocol.
        """
        if not isinstance(before,dict) or before.get('symbol') != pos.symbol:
            raise ValueError('invalid old paper position')
        after = paper_position_snapshot(pos)
        immutable = set(before) - {'stop','peak','locked_profit'}
        if any(before.get(key) != after.get(key) for key in immutable):
            raise RuntimeError('unexpected financial mutation in risk update')
        with self._conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for table in ('paper_intents','paper_close_intents','paper_funding_intents','paper_layer_intents'):
                if conn.execute('SELECT 1 FROM '+table+" WHERE status='PENDING' LIMIT 1").fetchone():
                    raise RuntimeError('unresolved paper intent during risk update')
            keys=('symbol','side','entry','qty','stop','peak','locked_profit',
                  'opened_at','leverage','margin_usdt','layers','last_add_price','exchange')
            row=conn.execute('SELECT '+','.join(keys)+' FROM open_positions WHERE symbol=?',(pos.symbol,)).fetchone()
            if row is None:
                raise RuntimeError('paper position missing during risk update')
            actual={key:row[key] for key in keys}
            actual['locked_profit']=bool(actual['locked_profit'])
            if actual != before:
                raise RuntimeError('paper state changed in another process: risk update')
            conn.execute('UPDATE open_positions SET stop=?,peak=?,locked_profit=?,updated_at=? WHERE symbol=?',
                         (float(pos.stop),float(pos.peak),int(bool(pos.locked_profit)),time.time(),pos.symbol))

    def save_position(self, pos: Position, exchange: str | None = None) -> None:
        exchange = exchange or pos.exchange or "binance"
        pos.exchange = exchange
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO open_positions
                (symbol, side, entry, qty, stop, peak, locked_profit, opened_at,
                 leverage, margin_usdt, layers, last_add_price, exchange, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    side=excluded.side,
                    entry=excluded.entry,
                    qty=excluded.qty,
                    stop=excluded.stop,
                    peak=excluded.peak,
                    locked_profit=excluded.locked_profit,
                    opened_at=excluded.opened_at,
                    leverage=excluded.leverage,
                    margin_usdt=excluded.margin_usdt,
                    layers=excluded.layers,
                    last_add_price=excluded.last_add_price,
                    exchange=excluded.exchange,
                    updated_at=excluded.updated_at
                """,
                (
                    pos.symbol,
                    pos.side,
                    float(pos.entry),
                    float(pos.qty),
                    float(pos.stop),
                    float(pos.peak),
                    1 if pos.locked_profit else 0,
                    str(pos.opened_at or ""),
                    int(pos.leverage),
                    float(pos.margin_usdt),
                    int(pos.layers),
                    float(pos.last_add_price),
                    str(exchange),
                    time.time(),
                ),
            )

    def delete_position(self, symbol: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM open_positions WHERE symbol = ?", (symbol,))

    def load_positions(self) -> dict[str, Position]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM open_positions").fetchall()
        positions: dict[str, Position] = {}
        for r in rows:
            pos = Position(
                symbol=str(r["symbol"]),
                side=str(r["side"]),
                entry=float(r["entry"]),
                qty=float(r["qty"]),
                stop=float(r["stop"]),
                peak=float(r["peak"]),
                locked_profit=bool(r["locked_profit"]),
                opened_at=str(r["opened_at"] or ""),
                leverage=int(r["leverage"]),
                margin_usdt=float(r["margin_usdt"]),
                layers=int(r["layers"]),
                last_add_price=float(r["last_add_price"]),
                exchange=str(r["exchange"] or ""),
            )
            positions[pos.symbol] = pos
        return positions

    def startup_recovery_report(self) -> list[str]:
        positions = self.load_positions()
        if not positions:
            return []
        msgs = [f"♻️ SQLite'tan {len(positions)} açık pozisyon kurtarıldı:"]
        for sym, pos in positions.items():
            msgs.append(
                f"  • {sym} ({pos.exchange or 'binance'}) {pos.side} "
                f"qty={pos.qty:.6g} @ {pos.entry:,.4f} | stop={pos.stop:,.4f}"
            )
        return msgs

    # -- İşlem, Özsermaye ve Arbitraj Geçmişi ----------------------------------
    def record_trade(
        self,
        symbol: str,
        side: str,
        entry: float,
        exit_price: float,
        qty: float,
        pnl_pct: float,
        reason: str,
        leverage: int = 20,
        margin_usdt: float = 0.0,
        pnl_usdt: float = 0.0,
        layers: int = 1,
        position_id: str = "",
        entry_context: dict | None = None,
        exchange: str = "",
        entry_fee_usdt: float = 0.0,
        exit_fee_usdt: float = 0.0,
        funding_usdt: float = 0.0,
        net_pnl_usdt: float | None = None,
        mfe_usdt: float = 0.0,
        mae_usdt: float = 0.0,
        stop_price: float | None = None,
        net_breakeven_price: float | None = None,
        ts: float | None = None,
    ) -> None:
        roe_pct = pnl_pct * leverage
        if net_pnl_usdt is None:
            net_pnl_usdt = (
                float(pnl_usdt)
                - float(entry_fee_usdt)
                - float(exit_fee_usdt)
                + float(funding_usdt)
            )
        context_json = json.dumps(
            entry_context or {}, ensure_ascii=False, default=str, separators=(",", ":")
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO trade_history
                (ts, symbol, side, entry, exit_price, qty, leverage, margin_usdt,
                 pnl_pct, roe_pct, pnl_usdt, reason, layers, position_id, entry_context,
                 exchange, entry_fee_usdt, exit_fee_usdt, funding_usdt, net_pnl_usdt,
                 mfe_usdt, mae_usdt, stop_price, net_breakeven_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    float(ts if ts is not None else time.time()),
                    symbol,
                    side,
                    float(entry),
                    float(exit_price),
                    float(qty),
                    int(leverage),
                    float(margin_usdt),
                    float(pnl_pct),
                    float(roe_pct),
                    float(pnl_usdt),
                    reason,
                    int(layers),
                    str(position_id or ""),
                    context_json,
                    str(exchange or ""),
                    float(entry_fee_usdt),
                    float(exit_fee_usdt),
                    float(funding_usdt),
                    float(net_pnl_usdt),
                    float(mfe_usdt),
                    float(mae_usdt),
                    float(stop_price) if stop_price is not None else None,
                    float(net_breakeven_price) if net_breakeven_price is not None else None,
                ),
            )

    def get_trades(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trade_history ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_trades_since(self, since_ts: float, until_ts: float | None = None) -> list[dict]:
        """Oturum/günlük rapor için kapanışları eski→yeni döndürür."""
        query = "SELECT * FROM trade_history WHERE ts >= ?"
        params: list[float] = [float(since_ts)]
        if until_ts is not None:
            query += " AND ts <= ?"
            params.append(float(until_ts))
        query += " ORDER BY ts, id"
        with self._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def record_equity(
        self,
        balance_usdt: float,
        equity_usdt: float,
        open_positions: int = 0,
        ts: float | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO equity_history (ts, balance_usdt, equity_usdt, open_positions)
                VALUES (?, ?, ?, ?)
                """,
                (
                    float(ts if ts is not None else time.time()),
                    float(balance_usdt),
                    float(equity_usdt),
                    int(open_positions),
                ),
            )

    def get_equity_curve(self, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_history ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def record_arbitrage(self, record: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO arbitrage_history
                (ts, symbol, buy_exchange, sell_exchange, buy_price, sell_price,
                 qty, net_spread_pct, profit_usdt, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    float(record.get("executed_at") or time.time()),
                    str(record.get("symbol", "")),
                    str(record.get("buy_exchange", "")),
                    str(record.get("sell_exchange", "")),
                    float(record.get("buy_price", 0.0)),
                    float(record.get("sell_price", 0.0)),
                    float(record.get("qty", 0.0)),
                    float(record.get("net_spread_pct", 0.0)),
                    float(record.get("profit_usdt", 0.0)),
                    str(record.get("status", "FILLED")),
                ),
            )

    def get_arb_history(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM arbitrage_history ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Anahtar-Değer Meta & Uzaktan Komut Kuyruğu ----------------------------
    def set_meta(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO bot_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (str(key), payload, time.time()),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM bot_meta WHERE key = ?", (str(key),)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def push_command(self, cmd: str, payload: dict | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO command_queue (ts, cmd, payload, processed) VALUES (?, ?, ?, 0)",
                (time.time(), str(cmd), json.dumps(payload or {}, ensure_ascii=False)),
            )

    def pop_commands(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, ts, cmd, payload FROM command_queue WHERE processed = 0 ORDER BY id ASC"
            ).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE command_queue SET processed = 1 WHERE id IN ({placeholders})",
                tuple(ids),
            )
        result = []
        for r in rows:
            try:
                pl = json.loads(r["payload"] or "{}")
            except Exception:
                pl = {}
            result.append({"id": r["id"], "ts": r["ts"], "cmd": r["cmd"], "payload": pl})
        return result
