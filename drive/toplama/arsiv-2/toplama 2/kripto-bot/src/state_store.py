"""Durum Kalıcılığı (State Persistence) — SQLite WAL Modu + 24 Saatlik Log Rotation
(Gzip Arşivleme) ve Otomatik `VACUUM` Çöp Toplayıcı (Garbage Collector).

Özellikler:
  • Otomatik WAL (Write-Ahead Logging) modu (`PRAGMA journal_mode=WAL`),
    `wal_autocheckpoint=1000` ve `journal_size_limit=64MB`.
  • Elektrik/internet kesintisinde açık pozisyonlar, giriş fiyatları, kademe sayısı
    ve kâr kilidi (`locked_profit`) durumları kaybolmaz.
  • Çöp Toplayıcı (Garbage Collector & Log Rotation):
    Her 24 saatte bir (veya isteğe bağlı anında) eski/gereksiz durum kayıtlarını
    `.jsonl.gz` olarak sıkıştırıp arşivler, işlenmiş komut kuyruğunu temizler,
    `PRAGMA wal_checkpoint(TRUNCATE)` ve `VACUUM` + `PRAGMA optimize` çalıştırarak
    veritabanının şişmesini önler.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .risk import Position


class StateStore:
    def __init__(
        self,
        db_path: str | Path = "bot_state.db",
        archive_dir: str | Path | None = None,
        maintenance_interval_sec: float = 86400.0,
    ):
        self.db_path = Path(db_path)
        self.archive_dir = (
            Path(archive_dir)
            if archive_dir
            else self.db_path.resolve().parent / "archives"
        )
        self.maintenance_interval_sec = maintenance_interval_sec
        self.last_vacuum_ts: float = time.time()
        self.vacuum_runs: int = 0
        self.archived_rows_total: int = 0
        self._journal_mode: str = "wal"
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
        if row and row[0]:
            self._journal_mode = str(row[0]).lower()
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")
        conn.execute("PRAGMA journal_size_limit=67108864;")  # 64 MB WAL üst sınırı
        return conn

    def _init_db(self):
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
                    opened_at TEXT NOT NULL,
                    leverage INTEGER NOT NULL DEFAULT 20,
                    margin_usdt REAL NOT NULL DEFAULT 0.0,
                    layers INTEGER NOT NULL DEFAULT 1,
                    last_add_price REAL NOT NULL DEFAULT 0.0,
                    exchange TEXT NOT NULL DEFAULT 'binance',
                    updated_at REAL NOT NULL
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
                    layers INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    balance_usdt REAL NOT NULL,
                    equity_usdt REAL NOT NULL,
                    open_positions INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS arb_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    buy_ex TEXT NOT NULL,
                    sell_ex TEXT NOT NULL,
                    buy_px REAL NOT NULL,
                    sell_px REAL NOT NULL,
                    gross_spread_pct REAL NOT NULL,
                    net_spread_pct REAL NOT NULL,
                    profit_usdt REAL NOT NULL,
                    notional_usdt REAL NOT NULL
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

    def get_wal_status(self) -> dict:
        """SQLite WAL modunu, dosya boyutunu ve bakım istatistiklerini döner."""
        with self._conn() as conn:
            jm = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "journal_mode": str(jm).lower(),
            "wal_active": str(jm).lower() == "wal",
            "db_size_bytes": size_bytes,
            "vacuum_runs": self.vacuum_runs,
            "archived_rows_total": self.archived_rows_total,
            "last_vacuum_ts": self.last_vacuum_ts,
        }

    # -- B) 24 Saatlik Log Rotation (Gzip Sıkıştırma) & VACUUM Çöp Toplayıcı ---
    def run_garbage_collector(
        self,
        max_trades: int = 2000,
        max_equity: int = 2000,
        max_arb: int = 1000,
        archive_gzip: bool = True,
    ) -> dict:
        """Eski/taşan kayıtları `.jsonl.gz` arşivine sıkıştırıp siler, ardından
        `PRAGMA wal_checkpoint(TRUNCATE)` ve `VACUUM` ile veritabanını küçültür."""
        size_before = self.db_path.stat().st_size if self.db_path.exists() else 0
        archived_items: list[dict] = []
        deleted_counts = {"trades": 0, "equity": 0, "arb": 0, "commands": 0}

        with self._conn() as conn:
            # 1) İşlenmiş eski komut kuyruğunu temizle
            cur_cmd = conn.execute(
                "DELETE FROM command_queue WHERE processed = 1"
            )
            deleted_counts["commands"] = max(0, cur_cmd.rowcount)

            # 2) Taşan geçmiş tabloları arşivle ve buda
            table_limits = [
                ("trade_history", max_trades, "trades"),
                ("equity_history", max_equity, "equity"),
                ("arb_history", max_arb, "arb"),
            ]
            for tbl, keep_n, key_lbl in table_limits:
                total_r = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                if total_r > keep_n:
                    overflow_n = total_r - keep_n
                    old_rows = conn.execute(
                        f"SELECT * FROM {tbl} ORDER BY id ASC LIMIT ?",
                        (overflow_n,),
                    ).fetchall()
                    if old_rows:
                        max_old_id = old_rows[-1]["id"]
                        for r in old_rows:
                            archived_items.append(
                                {"table": tbl, "row": dict(r)}
                            )
                        conn.execute(
                            f"DELETE FROM {tbl} WHERE id <= ?", (max_old_id,)
                        )
                        deleted_counts[key_lbl] = len(old_rows)

        archive_file_path = None
        if archived_items and archive_gzip:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            day_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
            arch_file = self.archive_dir / f"state_archive_{day_tag}.jsonl.gz"
            with gzip.open(arch_file, "at", encoding="utf-8") as gz:
                for item in archived_items:
                    gz.write(json.dumps(item, ensure_ascii=False) + "\n")
            archive_file_path = str(arch_file)
            self.archived_rows_total += len(archived_items)

        # 3) WAL Checkpoint + VACUUM + Optimize (Transaction dışında çalıştırılır)
        raw_conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        try:
            raw_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            raw_conn.execute("VACUUM;")
            raw_conn.execute("PRAGMA optimize;")
        finally:
            raw_conn.close()

        self.vacuum_runs += 1
        self.last_vacuum_ts = time.time()
        size_after = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "ok": True,
            "journal_mode": self._journal_mode,
            "deleted": deleted_counts,
            "archived_count": len(archived_items),
            "archive_file": archive_file_path,
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "vacuum_runs": self.vacuum_runs,
        }

    async def maintenance_loop(self):
        """Her 24 saatte bir otomatik SQLite sıkıştırma ve VACUUM çöp toplayıcısını çalıştırır."""
        while True:
            await asyncio.sleep(self.maintenance_interval_sec)
            try:
                res = self.run_garbage_collector()
                print(
                    f"🧹 [SQLite Bakım & VACUUM] Arşivlenen: {res['archived_count']} satır | "
                    f"Boyut: {res['size_before_bytes']}B → {res['size_after_bytes']}B",
                    flush=True,
                )
            except Exception:
                pass

    # -- Açık Pozisyon Kalıcılığı ----------------------------------------------
    def save_position(self, pos: Position, exchange: str = "binance"):
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
                    str(pos.opened_at),
                    int(getattr(pos, "leverage", 20)),
                    float(getattr(pos, "margin_usdt", 0.0)),
                    int(getattr(pos, "layers", 1)),
                    float(getattr(pos, "last_add_price", pos.entry)),
                    exchange,
                    time.time(),
                ),
            )

    def delete_position(self, symbol: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM open_positions WHERE symbol = ?", (symbol,))

    def clear_all_positions(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM open_positions")

    def load_positions(self) -> dict[str, Position]:
        positions: dict[str, Position] = {}
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM open_positions ORDER BY opened_at ASC"
            ).fetchall()
        for r in rows:
            pos = Position(
                symbol=r["symbol"],
                side=r["side"],
                entry=float(r["entry"]),
                qty=float(r["qty"]),
                stop=float(r["stop"]),
                peak=float(r["peak"]),
                locked_profit=bool(r["locked_profit"]),
                opened_at=r["opened_at"],
                leverage=int(r["leverage"]),
                margin_usdt=float(r["margin_usdt"]),
                layers=int(r["layers"]),
                last_add_price=float(r["last_add_price"]),
            )
            positions[pos.symbol] = pos
        return positions

    def startup_recovery_report(self) -> list[str]:
        positions = self.load_positions()
        msgs = []
        for sym, p in positions.items():
            kilit = "AÇIK 🔒" if p.locked_profit else "KAPALI"
            msgs.append(
                f"♻️ [DURUM KURTARILDI] Şu an açık {sym} {p.side} pozisyonum var | "
                f"Giriş: {p.entry:,.4f} | Miktar: {p.qty:.6f} | {p.leverage}x Kaldıraç | "
                f"Kademe: {p.layers} | Stop: {p.stop:,.4f} | Kâr Kilidi: {kilit} — "
                f"Kaldığım yerden devam ediyorum!"
            )
        return msgs

    # -- İşlem Geçmişi & Kasa Eğrisi -------------------------------------------
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
    ):
        roe_pct = pnl_pct * leverage
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO trade_history
                (ts, symbol, side, entry, exit_price, qty, leverage, margin_usdt,
                 pnl_pct, roe_pct, pnl_usdt, reason, layers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
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
                ),
            )

    def get_trades(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trade_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def record_equity(
        self,
        balance_usdt: float,
        equity_usdt: float,
        open_positions: int = 0,
        note: str = "",
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO equity_history (ts, balance_usdt, equity_usdt, open_positions, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    float(balance_usdt),
                    float(equity_usdt),
                    int(open_positions),
                    note,
                ),
            )

    def get_equity_curve(self, limit: int = 300) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM equity_history ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Arbitraj Geçmişi ------------------------------------------------------
    def record_arb(
        self,
        symbol: str,
        buy_ex: str,
        sell_ex: str,
        buy_px: float,
        sell_px: float,
        gross_spread_pct: float,
        net_spread_pct: float,
        profit_usdt: float,
        notional_usdt: float,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO arb_history
                (ts, symbol, buy_ex, sell_ex, buy_px, sell_px, gross_spread_pct,
                 net_spread_pct, profit_usdt, notional_usdt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    symbol,
                    buy_ex,
                    sell_ex,
                    float(buy_px),
                    float(sell_px),
                    float(gross_spread_pct),
                    float(net_spread_pct),
                    float(profit_usdt),
                    float(notional_usdt),
                ),
            )

    def get_arb_history(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM arb_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Genel Anahtar/Değer Durumu --------------------------------------------
    def set_meta(self, key: str, value: Any):
        payload = json.dumps(value, ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO bot_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, payload, time.time()),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM bot_meta WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    # -- Web Paneli Komut Kuyruğu ----------------------------------------------
    def push_command(self, cmd: str, payload: dict | None = None):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO command_queue (ts, cmd, payload, processed) VALUES (?, ?, ?, 0)",
                (time.time(), cmd, json.dumps(payload or {}, ensure_ascii=False)),
            )

    def pop_commands(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, ts, cmd, payload FROM command_queue WHERE processed = 0 ORDER BY id ASC"
            ).fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                conn.executemany(
                    "UPDATE command_queue SET processed = 1 WHERE id = ?",
                    [(i,) for i in ids],
                )
        out = []
        for r in rows:
            try:
                pl = json.loads(r["payload"])
            except Exception:
                pl = {}
            out.append(
                {"id": r["id"], "ts": r["ts"], "cmd": r["cmd"], "payload": pl}
            )
        return out
