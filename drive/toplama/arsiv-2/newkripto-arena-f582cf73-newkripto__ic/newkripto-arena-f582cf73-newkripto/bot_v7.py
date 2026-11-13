"""Bağımsız tek-dosya v7 Paper İşlem Motoru (çevrimdışı doğrulama ve referans modülü)."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

log = logging.getLogger("bot_v7")


def wilder(series: pd.Series, period: int = 14) -> pd.Series:
    return series.ewm(alpha=1.0 / max(1, int(period)), adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> dict | None:
    """df: yalnızca KAPANMIŞ mumlar. Son kapanmış mumun değerlerini döndürür."""
    if df is None or len(df) < 120:
        return None
    c, h, low = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)

    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()

    delta = c.diff()
    gain = wilder(delta.clip(lower=0.0), 14)
    loss = wilder((-delta.clip(upper=0.0)), 14).replace(0.0, np.nan)
    rsi = (100.0 - (100.0 / (1.0 + gain / loss))).fillna(50.0)

    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_sig = macd.ewm(span=9, adjust=False).mean()

    pc = c.shift(1)
    tr = pd.concat([h - low, (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    atr = wilder(tr, 14).replace(0.0, np.nan)

    up, dn = h.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    plus_di = 100.0 * wilder(plus_dm, 14) / atr
    minus_di = 100.0 * wilder(minus_dm, 14) / atr
    dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)).fillna(0.0)
    adx = wilder(dx, 14)

    close_last = float(c.iloc[-1])
    atr_last = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else close_last * 0.01
    ema20_last = float(ema20.iloc[-1])
    ema50_last = float(ema50.iloc[-1])
    ema200_last = float(ema200.iloc[-1])
    rsi_last = float(rsi.iloc[-1])
    macd_hist = float((macd - macd_sig).iloc[-1])
    adx_last = float(adx.iloc[-1])

    trend = 0
    if ema20_last > ema50_last > ema200_last and close_last > ema20_last:
        trend = 1
    elif ema20_last < ema50_last < ema200_last and close_last < ema20_last:
        trend = -1

    signal = "HOLD"
    if adx_last >= 20.0 and trend == 1 and 45.0 <= rsi_last <= 72.0 and macd_hist > 0:
        signal = "LONG"
    elif adx_last >= 20.0 and trend == -1 and 28.0 <= rsi_last <= 55.0 and macd_hist < 0:
        signal = "SHORT"

    return {
        "close": close_last,
        "ema20": ema20_last,
        "ema50": ema50_last,
        "ema200": ema200_last,
        "rsi": rsi_last,
        "macd_hist": macd_hist,
        "atr": atr_last,
        "adx": adx_last,
        "trend": trend,
        "signal": signal,
    }


@dataclass
class V7Position:
    symbol: str
    side: str
    entry: float
    qty: float
    stop: float
    tp: float
    peak: float
    atr: float
    opened: float
    be_moved: bool = False


class Telegram:
    def __init__(
        self,
        token: str,
        chat_id: str,
        on_cmd: Callable[[str], str] | None = None,
        on_stop: Callable[[], None] | None = None,
    ):
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.on_cmd = on_cmd
        self.on_stop = on_stop
        self.sent: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        self.sent.append(str(text))
        return self.enabled

    def dispatch_local(self, text: str) -> str:
        if self.on_cmd is None:
            return ""
        return self.on_cmd(text.strip())


class Bot:
    """Bağımsız SQLite destekli v7 paper bot çekirdeği."""

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        risk_pct: float = 0.01,
        fee_rate: float = 0.0005,
        slip_rate: float = 0.0002,
        cooldown_sec: float = 900.0,
        daily_loss_limit: float = 0.05,
        max_positions: int = 3,
        data_dir: str | None = None,
    ):
        base_dir = Path(data_dir or os.getenv("DATA_DIR") or ".").expanduser()
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = base_dir / "bot_v7.sqlite3"
        self.initial_cash = float(initial_cash)
        self.risk_pct = float(risk_pct)
        self.fee_rate = float(fee_rate)
        self.slip_rate = float(slip_rate)
        self.cooldown_sec = float(cooldown_sec)
        self.daily_loss_limit = float(daily_loss_limit)
        self.max_positions = int(max_positions)
        self._running = True
        self.prices: dict[str, float] = {}

        self._init_db()
        cash_saved = self._get_kv("cash")
        self.cash = float(cash_saved) if cash_saved is not None else float(initial_cash)
        self.locked = self._get_kv("locked") == "1"
        day_start = self._get_kv("day_start_equity")
        self.day_start_equity = float(day_start) if day_start is not None else self.cash
        self.pos: dict[str, V7Position] = self._load_positions()
        self.last_close: dict[str, float] = {
            s: float(t)
            for s, t in self._db("SELECT symbol, MAX(closed) FROM trades GROUP BY symbol")
            if t is not None
        }

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_TOKEN", "")
        self.tg = Telegram(
            telegram_token,
            os.getenv("TELEGRAM_CHAT_ID", ""),
            self.on_command,
            self.stop,
        )
        log.info(
            "v7 PAPER başladı | kasa=%.2f | açık pozisyon=%d | kilit=%s",
            self.equity(),
            len(self.pos),
            self.locked,
        )

    # ---------------- DB ----------------
    def _db(self, sql: str, params: tuple = ()) -> list[tuple]:
        with sqlite3.connect(str(self.db_file)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            return rows

    def _init_db(self) -> None:
        self._db(
            """
            CREATE TABLE IF NOT EXISTS kv (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            )
            """
        )
        self._db(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                side TEXT NOT NULL,
                entry REAL NOT NULL,
                qty REAL NOT NULL,
                stop REAL NOT NULL,
                tp REAL NOT NULL,
                peak REAL NOT NULL,
                atr REAL NOT NULL,
                opened REAL NOT NULL,
                be_moved INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._db(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry REAL NOT NULL,
                exit REAL NOT NULL,
                qty REAL NOT NULL,
                pnl REAL NOT NULL,
                reason TEXT NOT NULL,
                opened REAL NOT NULL,
                closed REAL NOT NULL
            )
            """
        )

    def _set_kv(self, k: str, v: str) -> None:
        self._db(
            "INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, str(v)),
        )

    def _get_kv(self, k: str) -> str | None:
        rows = self._db("SELECT v FROM kv WHERE k = ?", (k,))
        return rows[0][0] if rows else None

    def _save_position(self, p: V7Position) -> None:
        self._db(
            """
            INSERT INTO positions (symbol, side, entry, qty, stop, tp, peak, atr, opened, be_moved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                side=excluded.side, entry=excluded.entry, qty=excluded.qty,
                stop=excluded.stop, tp=excluded.tp, peak=excluded.peak,
                atr=excluded.atr, opened=excluded.opened, be_moved=excluded.be_moved
            """,
            (
                p.symbol,
                p.side,
                p.entry,
                p.qty,
                p.stop,
                p.tp,
                p.peak,
                p.atr,
                p.opened,
                1 if p.be_moved else 0,
            ),
        )

    def _load_positions(self) -> dict[str, V7Position]:
        rows = self._db(
            "SELECT symbol, side, entry, qty, stop, tp, peak, atr, opened, be_moved FROM positions"
        )
        out: dict[str, V7Position] = {}
        for r in rows:
            p = V7Position(
                symbol=r[0],
                side=r[1],
                entry=float(r[2]),
                qty=float(r[3]),
                stop=float(r[4]),
                tp=float(r[5]),
                peak=float(r[6]),
                atr=float(r[7]),
                opened=float(r[8]),
                be_moved=bool(r[9]),
            )
            out[p.symbol] = p
        return out

    # ---------------- Muhasebe & Risk ----------------
    def unrealized(self) -> float:
        tot = 0.0
        for sym, p in self.pos.items():
            px = self.prices.get(sym, p.entry)
            tot += (px - p.entry) * p.qty if p.side == "LONG" else (p.entry - px) * p.qty
        return tot

    def equity(self) -> float:
        return self.cash + self.unrealized()

    def check_daily_guard(self) -> bool:
        if self.day_start_equity <= 0:
            return False
        dd = (self.day_start_equity - self.equity()) / self.day_start_equity
        if dd >= self.daily_loss_limit:
            self.locked = True
            self._set_kv("locked", "1")
            return True
        return self.locked

    def open_position(
        self, symbol: str, side: str, price: float, atr: float, now: float | None = None
    ) -> V7Position | None:
        now_ts = float(now if now is not None else time.time())
        if self.locked or self.check_daily_guard():
            return None
        if symbol in self.pos or len(self.pos) >= self.max_positions:
            return None
        if (now_ts - self.last_close.get(symbol, -1e12)) < self.cooldown_sec:
            return None
        if price <= 0 or atr <= 0:
            return None

        fill = price * (1.0 + self.slip_rate) if side == "LONG" else price * (1.0 - self.slip_rate)
        stop_dist = 2.0 * atr
        stop = fill - stop_dist if side == "LONG" else fill + stop_dist
        tp = fill + 3.0 * atr if side == "LONG" else fill - 3.0 * atr
        risk_usd = self.equity() * self.risk_pct
        qty = risk_usd / stop_dist
        max_notional = self.cash * 0.90
        if qty * fill > max_notional:
            qty = max_notional / fill
        if qty <= 0:
            return None

        entry_fee = qty * fill * self.fee_rate
        self.cash -= entry_fee
        self._set_kv("cash", f"{self.cash:.8f}")

        p = V7Position(
            symbol=symbol,
            side=side,
            entry=fill,
            qty=qty,
            stop=stop,
            tp=tp,
            peak=fill,
            atr=atr,
            opened=now_ts,
        )
        self.pos[symbol] = p
        self.prices[symbol] = price
        self._save_position(p)
        return p

    def close_position(
        self, symbol: str, price: float, reason: str, now: float | None = None
    ) -> float | None:
        p = self.pos.pop(symbol, None)
        if p is None:
            return None
        now_ts = float(now if now is not None else time.time())
        fill = price * (1.0 - self.slip_rate) if p.side == "LONG" else price * (1.0 + self.slip_rate)
        gross = (fill - p.entry) * p.qty if p.side == "LONG" else (p.entry - fill) * p.qty
        exit_fee = p.qty * fill * self.fee_rate
        net = gross - exit_fee
        self.cash += net
        self.last_close[symbol] = now_ts
        self._set_kv("cash", f"{self.cash:.8f}")
        self._db("DELETE FROM positions WHERE symbol = ?", (symbol,))
        self._db(
            """
            INSERT INTO trades (symbol, side, entry, exit, qty, pnl, reason, opened, closed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (p.symbol, p.side, p.entry, fill, p.qty, net, reason, p.opened, now_ts),
        )
        self.check_daily_guard()
        return net

    def on_tick(self, symbol: str, price: float, now: float | None = None) -> str | None:
        self.prices[symbol] = float(price)
        p = self.pos.get(symbol)
        if p is None:
            return None

        if p.side == "LONG":
            p.peak = max(p.peak, price)
            if not p.be_moved and (price - p.entry) >= 1.5 * p.atr:
                p.stop = max(p.stop, p.entry * (1.0 + 2.0 * self.fee_rate))
                p.be_moved = True
            if p.be_moved:
                p.stop = max(p.stop, p.peak - 1.8 * p.atr)
            if price <= p.stop:
                self.close_position(symbol, price, "STOP", now=now)
                return "STOP"
            if price >= p.tp:
                self.close_position(symbol, price, "TP", now=now)
                return "TP"
        else:
            p.peak = min(p.peak, price)
            if not p.be_moved and (p.entry - price) >= 1.5 * p.atr:
                p.stop = min(p.stop, p.entry * (1.0 - 2.0 * self.fee_rate))
                p.be_moved = True
            if p.be_moved:
                p.stop = min(p.stop, p.peak + 1.8 * p.atr)
            if price >= p.stop:
                self.close_position(symbol, price, "STOP", now=now)
                return "STOP"
            if price <= p.tp:
                self.close_position(symbol, price, "TP", now=now)
                return "TP"

        self._save_position(p)
        return None

    def on_bar(self, symbol: str, df: pd.DataFrame, now: float | None = None) -> str:
        ind = compute_indicators(df)
        if ind is None:
            return "WARMUP"
        px = ind["close"]
        self.prices[symbol] = px
        if symbol in self.pos:
            res = self.on_tick(symbol, px, now=now)
            return res or "HOLD_OPEN"
        if ind["signal"] in ("LONG", "SHORT"):
            opened = self.open_position(symbol, ind["signal"], px, ind["atr"], now=now)
            if opened is not None:
                return f"OPEN_{ind['signal']}"
        return "NO_ENTRY"

    # ---------------- Komutlar ----------------
    def on_command(self, cmd: str) -> str:
        c = cmd.strip().lower()
        if c in ("/durum", "durum", "/status"):
            return f"Kasa={self.cash:.2f} | Equity={self.equity():.2f} | Açık={len(self.pos)} | Kilit={self.locked}"
        if c in ("/kilitac", "/unlock"):
            self.locked = False
            self._set_kv("locked", "0")
            self.day_start_equity = self.equity()
            self._set_kv("day_start_equity", f"{self.day_start_equity:.8f}")
            return "Kilit açıldı."
        if c in ("/kapat", "/kill"):
            for sym in list(self.pos.keys()):
                self.close_position(sym, self.prices.get(sym, self.pos[sym].entry), "KILL")
            self.locked = True
            self._set_kv("locked", "1")
            return "Tüm pozisyonlar kapatıldı ve kilitlendi."
        return "Bilinmeyen komut"

    def stop(self) -> None:
        self._running = False
