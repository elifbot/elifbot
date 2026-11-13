#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kripto-Bot v7 (tek dosya, YALNIZCA PAPER modu)

Eski betikteki sorunların düzeltilmiş hali:
  * Kapanmış mum kullanılır (repaint yok), 1h mumda bir kez tarama
  * Wilder yumuşatmalı RSI / ATR / ADX (TradingView ile uyumlu)
  * Sanal pozisyon: giriş / stop / TP / breakeven / çıkış takibi, komisyon + kayma
  * Risk katmanı: %1 risk, maks pozisyon, aynı yön tavanı, toplam marjin tavanı,
    günlük zarar limiti, likidasyon-stop tamponu, kontrat büyüklüğü + hassasiyet
  * SQLite: (exchange, symbol) anahtarı, açılışta durum yüklenir, kill-switch kalıcıdır
  * Telegram: ayrı thread, update offset, yetki kontrolü, token maskeleme, HTML modu
  * Markets günde 1 kez yüklenir, hacim filtresi, swap/linear/USDT filtresi
  * logging (rotasyonlu), hata yutulmaz, rate-limit beklemesi, düzgün kapanış

Gerçek emir YOKTUR. Canlı emir mantığı src/executor.py tarafında kalmalıdır.
"""
from __future__ import annotations

import html
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import ccxt
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# ----------------------------------------------------------------------------
# AYARLAR
# ----------------------------------------------------------------------------
CFG = {
    "capital": float(os.getenv("START_CAPITAL", "1000")),
    "risk_pct": 0.01,              # işlem başına risk (kasanın %1'i)
    "max_open": 5,                 # toplam açık pozisyon
    "max_same_side": 3,            # aynı yönde en fazla pozisyon (altcoinler korelasyonlu)
    "max_margin_pct": 0.50,        # toplam marjin / kasa
    "daily_loss_limit_pct": 0.05,  # günlük gerçekleşen zarar -> yeni giriş yok
    "max_leverage": 10,
    "liq_buffer": 0.70,            # stop mesafesi <= likidasyon mesafesinin %70'i
    "atr_stop_mult": 1.5,
    "tp_r": 2.5,                   # take-profit = 2.5R
    "be_at_r": 1.0,                # +1R'de stop girişe (breakeven) çekilir
    "fee_pct": 0.0005,             # taker komisyon (tek yön)
    "slip_pct": 0.0005,            # sanal kayma (tek yön)
    "cooldown_s": 3600,
    "min_quote_volume": 20_000_000,  # 24s USDT hacim alt sınırı
    "top_n": 60,                   # hacme göre en iyi N parite (borsa başına)
    "timeframe": "1h",
    "candles": 300,
    "monitor_interval_s": 15,
    "scan_delay_s": 20,            # mum kapanışından sonra beklenecek süre
    "adx_min": 20.0,
}

DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "bot_state_v7.db")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}[CFG["timeframe"]]

# ----------------------------------------------------------------------------
# GİZLİ ANAHTAR MASKELEME + LOGGING
# ----------------------------------------------------------------------------
_SECRETS: list[str] = []


def register_secret(value: str) -> None:
    if value and len(value) >= 6 and value not in _SECRETS:
        _SECRETS.append(value)


def mask(text: str) -> str:
    for s in _SECRETS:
        text = text.replace(s, "***MASKED***")
    return text


class MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


def setup_logging() -> logging.Logger:
    log = logging.getLogger("bot")
    log.setLevel(logging.INFO)
    fmt = MaskingFormatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    sh = logging.StreamHandler(sys.stdout)
    for h in (fh, sh):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


log = setup_logging()

# ----------------------------------------------------------------------------
# İNDİKATÖRLER (Wilder yumuşatma)
# ----------------------------------------------------------------------------


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def compute_indicators(df: pd.DataFrame) -> dict | None:
    """df: yalnızca KAPANMIŞ mumlar. Son kapanmış mumun değerlerini döndürür."""
    if len(df) < 120:
        return None
    c, h, l = df["close"], df["high"], df["low"]

    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()

    d = c.diff()
    g, ls = wilder(d.clip(lower=0), 14), wilder((-d).clip(lower=0), 14)
    rsi = (100 * g / (g + ls)).fillna(50.0)

    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_sig = macd.ewm(span=9, adjust=False).mean()

    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = wilder(tr, 14)

    up, dn = h.diff(), -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    plus_di = 100 * wilder(plus_dm, 14) / atr
    minus_di = 100 * wilder(minus_dm, 14) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = wilder(dx, 14)

    last = {
        "close": c.iloc[-1], "ema20": ema20.iloc[-1], "ema50": ema50.iloc[-1],
        "rsi": rsi.iloc[-1], "macd": macd.iloc[-1], "macd_sig": macd_sig.iloc[-1],
        "atr": atr.iloc[-1], "adx": adx.iloc[-1],
    }
    if any(pd.isna(v) for v in last.values()):
        return None
    return {k: float(v) for k, v in last.items()}


def get_signal(ind: dict) -> str:
    if ind["adx"] < CFG["adx_min"]:
        return "HOLD"
    if ind["close"] > ind["ema50"] and ind["ema20"] > ind["ema50"] and ind["rsi"] < 48 and ind["macd"] > ind["macd_sig"]:
        return "LONG"
    if ind["close"] < ind["ema50"] and ind["ema20"] < ind["ema50"] and ind["rsi"] > 52 and ind["macd"] < ind["macd_sig"]:
        return "SHORT"
    return "HOLD"


def dynamic_leverage(atr_pct: float) -> int:
    if atr_pct >= 0.03:
        return 5
    if atr_pct >= 0.015:
        return 10
    return 20


# ----------------------------------------------------------------------------
# TELEGRAM (ayrı thread, offset, yetki)
# ----------------------------------------------------------------------------
class Telegram:
    def __init__(self, token: str, chat_id: str, handler, stop: threading.Event):
        self.token, self.chat_id, self.handler, self.stop = token, str(chat_id), handler, stop
        self.offset = 0
        register_secret(token)
        self.enabled = bool(token and chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send(self, text: str) -> None:
        if not self.enabled:
            log.info("[TELEGRAM MOCK] %s", text)
            return
        try:
            requests.post(
                self._url("sendMessage"),
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram gönderim hatası: %s", mask(str(e)))

    def _get_updates(self, offset: int, timeout: int):
        r = requests.get(
            self._url("getUpdates"),
            params={"offset": offset, "timeout": timeout},
            timeout=(5, timeout + 10),
        )
        r.raise_for_status()
        return r.json().get("result", [])

    def poll_loop(self) -> None:
        if not self.enabled:
            return
        try:  # açılışta birikmiş eski komutları (ör. eski /kill) atla
            old = self._get_updates(-1, 0)
            if old:
                self.offset = old[-1]["update_id"] + 1
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram ilk senkron hatası: %s", mask(str(e)))
        while not self.stop.is_set():
            try:
                for u in self._get_updates(self.offset, 20):
                    self.offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    cid = str(msg.get("chat", {}).get("id", ""))
                    text = (msg.get("text") or "").strip()
                    if not text.startswith("/"):
                        continue
                    if cid != self.chat_id:
                        log.warning("Yetkisiz Telegram komutu reddedildi (chat=%s)", cid)
                        continue
                    cmd = text.split()[0].split("@")[0].lower()
                    reply = self.handler(cmd)
                    if reply:
                        self.send(reply)
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram poll hatası: %s", mask(str(e)))
                self.stop.wait(5)


# ----------------------------------------------------------------------------
# BOT
# ----------------------------------------------------------------------------
class Bot:
    def __init__(self, exchanges: dict | None = None):
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

        self.exchanges = exchanges or {
            "Binance": ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}}),
            "OKX": ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}}),
        }
        self.markets_loaded: dict[str, float] = {}
        self.fail_counts: dict[str, int] = {n: 0 for n in self.exchanges}
        self.fail_alerted: set[str] = set()
        self.last_mon = 0.0
        self.daily_alert_date = ""

        self.capital = float(self._meta("capital") or CFG["capital"])
        self._set_meta("capital", str(self.capital))
        self.locked = self._meta("locked") == "1"
        self.last_scan_slot = int(self._meta("last_scan_slot") or 0)

        self.pos: dict[tuple[str, str], dict] = {}
        for r in self._db("SELECT exchange,symbol,side,entry,stop,tp,init_risk,qty,margin,leverage,opened,be_done FROM positions"):
            keys = ("exchange", "symbol", "side", "entry", "stop", "tp", "init_risk", "qty", "margin", "leverage", "opened", "be_done")
            p = dict(zip(keys, r))
            self.pos[(p["exchange"], p["symbol"])] = p
        self.cooldown: dict[str, float] = {
            s: t for s, t in self._db("SELECT symbol, MAX(closed) FROM trades GROUP BY symbol")
        }

        self.tg = Telegram(os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""), self.on_command, self.stop)
        log.info("v7 PAPER başladı | kasa=%.2f | açık pozisyon=%d | kilit=%s", self.equity(), len(self.pos), self.locked)

    # ---------------- DB ----------------
    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS positions (
                exchange TEXT, symbol TEXT, side TEXT, entry REAL, stop REAL, tp REAL,
                init_risk REAL, qty REAL, margin REAL, leverage INTEGER, opened REAL,
                be_done INTEGER DEFAULT 0, PRIMARY KEY (exchange, symbol));
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT, exchange TEXT, symbol TEXT, side TEXT,
                entry REAL, exit REAL, qty REAL, pnl REAL, reason TEXT, opened REAL, closed REAL);
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            """
        )
        self.conn.commit()

    def _db(self, sql: str, args: tuple = ()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.fetchall()

    def _meta(self, k: str):
        r = self._db("SELECT v FROM meta WHERE k=?", (k,))
        return r[0][0] if r else None

    def _set_meta(self, k: str, v: str) -> None:
        self._db("INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)", (k, v))

    # ---------------- Hesap ----------------
    def equity(self) -> float:
        return self.capital + self._db("SELECT COALESCE(SUM(pnl),0) FROM trades")[0][0]

    def margin_used(self) -> float:
        with self.lock:
            return sum(p["margin"] for p in self.pos.values())

    def daily_pnl(self) -> float:
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return self._db("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE closed>=?", (midnight,))[0][0]

    def entries_allowed(self) -> bool:
        if self.locked:
            return False
        if self.daily_pnl() <= -CFG["daily_loss_limit_pct"] * self.equity():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self.daily_alert_date != today:
                self.daily_alert_date = today
                self.tg.send("🛑 <b>Günlük zarar limiti aşıldı</b>, yeni giriş UTC gece yarısına kadar durdu.")
            return False
        return True

    # ---------------- Borsa sağlığı ----------------
    def note_ok(self, name: str) -> None:
        self.fail_counts[name] = 0
        self.fail_alerted.discard(name)

    def note_fail(self, name: str, err: Exception) -> None:
        self.fail_counts[name] += 1
        log.warning("%s hatası (%d. ardışık): %s: %s", name, self.fail_counts[name], type(err).__name__, mask(str(err))[:200])
        if self.fail_counts[name] >= 5 and name not in self.fail_alerted:
            self.fail_alerted.add(name)
            self.tg.send(f"⚠️ <b>{html.escape(name)}</b> ardışık 5 hata verdi (ağ/rate-limit/bakım olabilir).")
        if isinstance(err, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
            self.stop.wait(30)

    def ensure_markets(self, name: str) -> None:
        if time.time() - self.markets_loaded.get(name, 0) > 86400:
            self.exchanges[name].load_markets(True)
            self.markets_loaded[name] = time.time()

    def build_universe(self, name: str) -> list[str]:
        ex = self.exchanges[name]
        self.ensure_markets(name)
        valid = {
            s for s, m in ex.markets.items()
            if m.get("swap") and m.get("linear") and m.get("quote") == "USDT"
            and m.get("settle") == "USDT" and m.get("active") is not False
        }
        tickers = ex.fetch_tickers()
        ranked = []
        for s, t in tickers.items():
            if s not in valid:
                continue
            qv = t.get("quoteVolume") or (t.get("baseVolume") or 0) * (t.get("last") or 0)
            if qv >= CFG["min_quote_volume"]:
                ranked.append((qv, s))
        ranked.sort(reverse=True)
        return [s for _, s in ranked[: CFG["top_n"]]]

    # ---------------- Pozisyon açma / kapama ----------------
    def gate(self, symbol: str, side: str) -> str | None:
        with self.lock:
            if any(k[1] == symbol for k in self.pos):
                return "zaten açık"
            if time.time() - self.cooldown.get(symbol, 0) < CFG["cooldown_s"]:
                return "cooldown"
            if len(self.pos) >= CFG["max_open"]:
                return "maks pozisyon"
            if sum(1 for p in self.pos.values() if p["side"] == side) >= CFG["max_same_side"]:
                return "aynı yön tavanı"
            if self.margin_used() >= self.equity() * CFG["max_margin_pct"]:
                return "marjin tavanı"
        return None

    def size_position(self, ex, symbol: str, price: float, atr: float):
        """(qty_coin, leverage, margin, stop_dist) veya (None, neden)."""
        stop_dist = atr * CFG["atr_stop_mult"]
        stop_pct = stop_dist / price
        lev = min(dynamic_leverage(atr / price), CFG["max_leverage"])
        lev = min(lev, int(CFG["liq_buffer"] / stop_pct))  # stop, likidasyondan önce gelmeli
        if lev < 1:
            return None, "stop mesafesi çok geniş"

        equity = self.equity()
        qty = equity * CFG["risk_pct"] / stop_dist
        avail = equity * CFG["max_margin_pct"] - self.margin_used()
        margin = qty * price / lev
        if margin > avail:
            qty *= max(avail, 0) / margin
        m = ex.market(symbol)
        cs = float(m.get("contractSize") or 1)
        try:
            contracts = float(ex.amount_to_precision(symbol, qty / cs))
        except Exception:  # noqa: BLE001
            return None, "hassasiyet hatası"
        lim = m.get("limits", {})
        min_amt = (lim.get("amount") or {}).get("min") or 0
        min_cost = (lim.get("cost") or {}).get("min") or 0
        qty = contracts * cs
        if contracts <= 0 or contracts < min_amt or qty * price < min_cost:
            return None, "minimum lot/notional altında"
        return qty, lev, qty * price / lev, stop_dist

    def open_position(self, name: str, ex, symbol: str, side: str, price: float, atr: float) -> bool:
        res = self.size_position(ex, symbol, price, atr)
        if res[0] is None:
            log.info("%s %s atlandı: %s", name, symbol, res[1])
            return False
        qty, lev, margin, stop_dist = res
        long = side == "LONG"
        fill = price * (1 + CFG["slip_pct"]) if long else price * (1 - CFG["slip_pct"])
        stop = fill - stop_dist if long else fill + stop_dist
        tp = fill + CFG["tp_r"] * stop_dist if long else fill - CFG["tp_r"] * stop_dist
        p = {
            "exchange": name, "symbol": symbol, "side": side, "entry": fill, "stop": stop, "tp": tp,
            "init_risk": stop_dist, "qty": qty, "margin": margin, "leverage": lev,
            "opened": time.time(), "be_done": 0,
        }
        with self.lock:
            self.pos[(name, symbol)] = p
            self._db(
                "INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, symbol, side, fill, stop, tp, stop_dist, qty, margin, lev, p["opened"], 0),
            )
        self.tg.send(
            f"{'🟢' if long else '🔴'} <b>PAPER {side}</b> ({html.escape(name)})\n"
            f"{html.escape(symbol)} @ {fill:.6g}\n"
            f"Stop: {stop:.6g} | TP: {tp:.6g}\n"
            f"Kaldıraç: {lev}x | Marjin: ${margin:.2f} | Risk: ${qty * stop_dist:.2f}"
        )
        return True

    def close_position(self, key: tuple[str, str], price: float, reason: str) -> None:
        with self.lock:
            p = self.pos.pop(key, None)
            if not p:
                return
            long = p["side"] == "LONG"
            fill = price * (1 - CFG["slip_pct"]) if long else price * (1 + CFG["slip_pct"])
            gross = (fill - p["entry"]) * p["qty"] if long else (p["entry"] - fill) * p["qty"]
            fees = CFG["fee_pct"] * (p["entry"] + fill) * p["qty"]
            pnl = gross - fees
            now = time.time()
            self._db("DELETE FROM positions WHERE exchange=? AND symbol=?", key)
            self._db(
                "INSERT INTO trades (exchange,symbol,side,entry,exit,qty,pnl,reason,opened,closed) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (p["exchange"], p["symbol"], p["side"], p["entry"], fill, p["qty"], pnl, reason, p["opened"], now),
            )
            self.cooldown[p["symbol"]] = now
        self.tg.send(
            f"{'✅' if pnl >= 0 else '❌'} <b>PAPER KAPANDI</b> — {html.escape(reason)}\n"
            f"{html.escape(p['symbol'])} {p['side']} | Giriş {p['entry']:.6g} → Çıkış {fill:.6g}\n"
            f"PnL: ${pnl:+.2f} | Kasa: ${self.equity():.2f}"
        )

    def check_position(self, key: tuple[str, str], price: float) -> None:
        with self.lock:
            p = self.pos.get(key)
            if not p:
                return
            long = p["side"] == "LONG"
            fav = (price - p["entry"]) if long else (p["entry"] - price)
            if not p["be_done"] and fav >= CFG["be_at_r"] * p["init_risk"]:
                buf = p["entry"] * CFG["fee_pct"] * 2
                p["stop"] = p["entry"] + buf if long else p["entry"] - buf
                p["be_done"] = 1
                self._db("UPDATE positions SET stop=?, be_done=1 WHERE exchange=? AND symbol=?", (p["stop"], *key))
                log.info("%s %s breakeven'e çekildi", *key)
            hit_stop = price <= p["stop"] if long else price >= p["stop"]
            hit_tp = price >= p["tp"] if long else price <= p["tp"]
            if hit_stop:
                self.close_position(key, price, "BREAKEVEN" if p["be_done"] else "STOP")
            elif hit_tp:
                self.close_position(key, price, "TAKE-PROFIT")

    def monitor_positions(self) -> None:
        self.last_mon = time.time()
        with self.lock:
            keys = list(self.pos)
        for key in keys:
            name, symbol = key
            try:
                price = self.exchanges[name].fetch_ticker(symbol)["last"]
                self.note_ok(name)
                if price:
                    self.check_position(key, float(price))
            except Exception as e:  # noqa: BLE001
                self.note_fail(name, e)

    # ---------------- Tarama ----------------
    def analyze(self, name: str, symbol: str) -> None:
        if any(k[1] == symbol for k in self.pos) or time.time() - self.cooldown.get(symbol, 0) < CFG["cooldown_s"]:
            return
        ex = self.exchanges[name]
        raw = ex.fetch_ohlcv(symbol, CFG["timeframe"], limit=CFG["candles"])
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        if df.empty:
            return
        if df["ts"].iloc[-1] + TF_SECONDS * 1000 > time.time() * 1000:  # oluşmakta olan mumu at
            df = df.iloc[:-1]
        ind = compute_indicators(df)
        if ind is None:
            return
        sig = get_signal(ind)
        if sig == "HOLD":
            return
        why = self.gate(symbol, sig)
        if why:
            log.info("%s %s %s sinyali geçilmedi: %s", name, symbol, sig, why)
            return
        price = float(ex.fetch_ticker(symbol)["last"])
        self.open_position(name, ex, symbol, sig, price, ind["atr"])

    def scan(self) -> None:
        self.last_scan_slot = int(time.time() // TF_SECONDS)
        self._set_meta("last_scan_slot", str(self.last_scan_slot))
        log.info("[SCAN] kapanmış %s mumları taranıyor", CFG["timeframe"])
        seen: set[str] = set()
        for name in self.exchanges:
            try:
                universe = self.build_universe(name)
                self.note_ok(name)
            except Exception as e:  # noqa: BLE001
                self.note_fail(name, e)
                continue
            for symbol in universe:
                if self.stop.is_set() or self.locked or not self.entries_allowed():
                    return
                if symbol in seen:  # aynı coin iki borsada çift taranmasın
                    continue
                seen.add(symbol)
                if time.time() - self.last_mon > CFG["monitor_interval_s"]:
                    self.monitor_positions()
                try:
                    self.analyze(name, symbol)
                except Exception as e:  # noqa: BLE001
                    self.note_fail(name, e)
        log.info("[SCAN] tur bitti | açık=%d | kasa=%.2f", len(self.pos), self.equity())

    def scan_due(self) -> bool:
        now = time.time()
        return int(now // TF_SECONDS) != self.last_scan_slot and now % TF_SECONDS >= CFG["scan_delay_s"]

    # ---------------- Telegram komutları ----------------
    def kill(self) -> None:
        with self.lock:
            self.locked = True
            self._set_meta("locked", "1")
            for key in list(self.pos):
                try:
                    price = float(self.exchanges[key[0]].fetch_ticker(key[1])["last"])
                except Exception:  # noqa: BLE001
                    price = self.pos[key]["entry"]
                self.close_position(key, price, "KILL-SWITCH")

    def on_command(self, cmd: str) -> str | None:
        if cmd == "/durum":
            return (
                f"{'🔒 KİLİTLİ' if self.locked else '🟢 Aktif (PAPER)'}\n"
                f"Kasa: ${self.equity():.2f} | Bugün: ${self.daily_pnl():+.2f}\n"
                f"Açık: {len(self.pos)} | Marjin: ${self.margin_used():.2f}"
            )
        if cmd == "/pozisyonlar":
            with self.lock:
                if not self.pos:
                    return "Açık pozisyon yok."
                return "\n".join(
                    f"{html.escape(p['symbol'])} {p['side']} {p['leverage']}x | giriş {p['entry']:.6g} | stop {p['stop']:.6g} | tp {p['tp']:.6g}"
                    for p in self.pos.values()
                )
        if cmd == "/kill":
            self.kill()
            return "🚨 <b>KILL-SWITCH</b>: pozisyonlar kapatıldı, giriş kilitlendi. Açmak için /resume"
        if cmd == "/resume":
            self.locked = False
            self._set_meta("locked", "0")
            return "🟢 Kilit kaldırıldı, tarama devam ediyor."
        return "Komutlar: /durum /pozisyonlar /kill /resume"

    # ---------------- Ana döngü ----------------
    def run(self) -> None:
        threading.Thread(target=self.tg.poll_loop, daemon=True, name="telegram").start()
        self.tg.send("🤖 v7 PAPER bot başladı. /durum /pozisyonlar /kill /resume")
        while not self.stop.is_set():
            try:
                self.monitor_positions()
                if self.entries_allowed() and self.scan_due():
                    self.scan()
            except Exception:  # noqa: BLE001
                log.exception("Ana döngü hatası")
            self.stop.wait(CFG["monitor_interval_s"])
        log.info("Düzgün kapanış: açık pozisyonlar DB'de saklandı (%d)", len(self.pos))
        self.conn.close()


def main() -> None:
    if os.getenv("MODE", "paper").lower() != "paper":
        sys.exit("Bu dosya yalnızca MODE=paper destekler. Canlı emirler src/executor.py üzerinden yapılmalıdır.")
    bot = Bot()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: bot.stop.set())
    bot.run()


if __name__ == "__main__":
    main()
