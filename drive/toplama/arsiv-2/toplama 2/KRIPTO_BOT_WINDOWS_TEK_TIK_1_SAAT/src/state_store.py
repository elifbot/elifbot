"""SQLite WAL Kalıcı Durum Deposu + Otomatik `.jsonl.gz` Arşiv & `VACUUM` Çöp Toplayıcı."""
from __future__ import annotations

import asyncio
import gzip
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .risk import Position


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
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            if self.wal_mode:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
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
