#!/usr/bin/env python3
"""
MEGA-BOT v6 — Tek dosya.

FARKLAR (backtest ↔ canlı):
  • Backtest: tek pozisyon, cooldown yok, max_hold=200 mum zorunlu çıkış,
    SL/TP tam seviyeden dolar, funding 8s dilimle sabit oran.
  • Canlı: çoklu pozisyon (max_positions), cooldown_min var, max_hold
    tf_minutes*cümlesine göre zamanla, monitor 10sn'de bir ticker ile
    kapatır (fitil görmez), funding API'den anlık oran.
  Backtest sonucu iyimser taraftadır — canlıda slipaj + gecikme + fitil
  farkı nedeniyle daha düşük net bekleyin.

DEFERRED (v7 adayları):
  • Order book simülasyonu / gerçek slippage (fill modeli)
  • Confluence oylarının korelasyon gruplaması
  • Bootstrap CI (walk_forward OOS dağılımı)
  • Borsa-side koşullu stop (stopPrice) + HTTPS
"""

import argparse, json, sqlite3, time, threading, os, copy, hmac, warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import pandas as pd
import numpy as np
import ccxt

warnings.filterwarnings("ignore", category=FutureWarning)

# ============================================================
# SABİTLER
# ============================================================
DB_PATH      = "megabot.sqlite"
FEE          = 0.0005
SLIP         = 0.0002
DEFAULT_FUNDING = 0.0001
MIN_TRADES   = 10
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")

# ============================================================
# DB — autocommit + migrasyon + BEGIN IMMEDIATE için hazır
# ============================================================
_schema_checked = False

def db():
    global _schema_checked
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    if not _schema_checked:
        _migrate_and_create(c)
        _schema_checked = True
    return c

def _migrate_and_create(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY, pair TEXT, engine TEXT,
        side TEXT, amount REAL, entry REAL, exit_price REAL,
        stop REAL, take_profit REAL, status TEXT, opened TEXT,
        closed TEXT, pnl REAL, strategy TEXT, reason TEXT);
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY, trade_id INT, ex_order_id TEXT,
        pair TEXT, side TEXT, price REAL, filled REAL, fee REAL, ts TEXT);
    CREATE TABLE IF NOT EXISTS signals(
        id INTEGER PRIMARY KEY, ts TEXT, source TEXT,
        pair TEXT, side TEXT, confidence REAL, meta TEXT);
    CREATE TABLE IF NOT EXISTS dca_state(
        pair TEXT PRIMARY KEY, trade_id INT, base_qty REAL, so_max INT,
        so_step REAL, so_mult REAL, filled INT, avg_price REAL,
        stop_price REAL, opened TEXT);
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS equity(
        id INTEGER PRIMARY KEY, ts TEXT, equity REAL);

    CREATE UNIQUE INDEX IF NOT EXISTS uq_open_spot
        ON trades(pair) WHERE status='open' AND engine='spot';
    CREATE UNIQUE INDEX IF NOT EXISTS uq_open_dca
        ON trades(pair) WHERE status='open' AND engine='dca';
    """)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(dca_state)").fetchall()}
    if "trade_id" not in cols:
        c.execute("ALTER TABLE dca_state ADD COLUMN trade_id INT")
        print("🔧 DB migrasyonu: dca_state.trade_id eklendi")
        for row in c.execute("SELECT pair FROM dca_state").fetchall():
            tr = c.execute(
                "SELECT id FROM trades WHERE pair=? AND engine='dca' "
                "AND status='open' LIMIT 1", (row["pair"],)).fetchone()
            if tr:
                c.execute("UPDATE dca_state SET trade_id=? WHERE pair=?",
                          (tr["id"], row["pair"]))

@contextmanager
def db_ctx():
    """Autocommit modunda çalışır — BEGIN IMMEDIATE'ı çağıran kendi açar."""
    c = db()
    try:
        yield c
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()

def now(): return datetime.now(timezone.utc).isoformat()

def kv_get(key, default=None):
    with db_ctx() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default

def kv_set(key, value):
    with db_ctx() as c:
        c.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (key, str(value)))

# ============================================================
# FUNDING
# ============================================================
def funding_rate_now(gw, pair):
    try:
        return float(gw.ex.fetch_funding_rate(pair)["fundingRate"])
    except Exception:
        return DEFAULT_FUNDING

def funding_cost(position_usd, rate, held_hours):
    return position_usd * rate * int(max(0.0, held_hours) // 8)

# ============================================================
# BORSA KATMANI — cache 60 sn tavan + bulk + ohlcv_raw
# ============================================================
class ExchangeGateway:
    PRICE_MAX_AGE = 60

    def __init__(self, ex="binanceusdm", paper=True):
        self.paper = paper
        self.ex = getattr(ccxt, ex)({
            "apiKey": os.getenv("KEY", ""), "secret": os.getenv("SECRET", ""),
            "enableRateLimit": True})
        self.fee = FEE
        self.slip = SLIP
        self._price_cache = {}
        self._price_ttl = 3.0

    def ohlcv_raw(self, pair, tf="5m", limit=500):
        return pd.DataFrame(self.ex.fetch_ohlcv(pair, tf, limit=limit),
                            columns=["ts", "o", "h", "l", "c", "v"])

    def ohlcv(self, pair, tf="5m", limit=500):
        return indicators(self.ohlcv_raw(pair, tf, limit))

    def price(self, pair, force=False):
        now_ts = time.time()
        cached = self._price_cache.get(pair)
        if not force and cached and (now_ts - cached[1]) < self._price_ttl:
            return cached[0]
        try:
            p = float(self.ex.fetch_ticker(pair)["last"])
            self._price_cache[pair] = (p, now_ts)
            return p
        except Exception:
            if cached and (now_ts - cached[1]) < self.PRICE_MAX_AGE:
                return cached[0]
            return None

    def prices(self, pairs):
        if not pairs:
            return {}
        now_ts = time.time()
        try:
            tickers = self.ex.fetch_tickers(pairs)
            out = {}
            for pair, t in tickers.items():
                p = t.get("last")
                if p and p > 0:
                    self._price_cache[pair] = (float(p), now_ts)
                    out[pair] = float(p)
            return out
        except Exception:
            out = {}
            for p in pairs:
                px = self.price(p)
                if px:
                    out[p] = px
            return out

    def _record(self, trade_id, ex_id, pair, side, price, filled, fee):
        with db_ctx() as c:
            c.execute("""INSERT INTO orders(trade_id,ex_order_id,pair,side,
                         price,filled,fee,ts) VALUES(?,?,?,?,?,?,?,?)""",
                      (trade_id, ex_id, pair, side, price, filled, fee, now()))

    def place(self, pair, side, amount, price=None, trade_id=None,
              reduce_only=False):
        if self.paper:
            p = price if price else (self.price(pair, force=True) or 0)
            fee = amount * p * self.fee
            self._record(trade_id, "PAPER", pair, side, p, amount, fee)
            return {"price": p, "fee": fee, "id": "paper"}
        try:
            amount = float(self.ex.amount_to_precision(pair, amount))
        except Exception:
            pass
        params = {"reduceOnly": True} if reduce_only else {}
        o = self.ex.create_order(pair, "limit" if price else "market",
                                 side, amount, price, params)
        filled = o.get("filled") or amount
        px = price or o.get("price") or o.get("average") or 0
        fee = o.get("fee")
        fee_cost = fee.get("cost", 0) if isinstance(fee, dict) else 0
        self._record(trade_id, o["id"], pair, side, px, filled, fee_cost or 0)
        return o

# ============================================================
# İNDİKATÖRLER — Wilder + HTML uyumlu
# ============================================================
class Indicators:
    @staticmethod
    def ema(s, n): return s.ewm(span=n, adjust=False).mean()

    @staticmethod
    def rsi(s, n=14):
        d = s.diff()
        up = d.clip(lower=0)
        dn = -d.clip(upper=0)
        avg_up = up.ewm(alpha=1/n, adjust=False).mean()
        avg_dn = dn.ewm(alpha=1/n, adjust=False).mean()
        return 100 - 100 / (1 + avg_up / (avg_dn + 1e-9))

    @classmethod
    def macd(cls, s, f=12, s2=26, sig=9):
        line = cls.ema(s, f) - cls.ema(s, s2)
        return line, line.ewm(span=sig, adjust=False).mean()

    @classmethod
    def boll(cls, s, n=20, k=2):
        m = s.rolling(n).mean()
        sd = s.rolling(n).std(ddof=0)
        return m, m + k*sd, m - k*sd

    @classmethod
    def atr(cls, df, n=14):
        h, l, c = df.h, df.l, df.c
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                       axis=1).max(axis=1)
        return tr.ewm(alpha=1/n, adjust=False).mean()

    @staticmethod
    def adx(df, n=14):
        h, l, c = df.h.values, df.l.values, df.c.values
        up = np.diff(h, prepend=h[0])
        dn = -np.diff(l, prepend=l[0])
        plus = np.where((up > dn) & (up > 0), up, 0.0)
        minus = np.where((dn > up) & (dn > 0), dn, 0.0)
        tr = np.maximum.reduce([
            h - l,
            np.abs(h - np.roll(c, 1)),
            np.abs(l - np.roll(c, 1))])
        tr[0] = h[0] - l[0]
        atr_v = pd.Series(tr).ewm(alpha=1/n, adjust=False).mean().values
        pdi = 100 * pd.Series(plus).ewm(alpha=1/n, adjust=False).mean().values / (atr_v + 1e-9)
        mdi = 100 * pd.Series(minus).ewm(alpha=1/n, adjust=False).mean().values / (atr_v + 1e-9)
        dx = 100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9)
        return pd.Series(dx, index=df.index).ewm(alpha=1/n, adjust=False).mean()

    @staticmethod
    def stoch(df, n=14, k=3, d=3):
        ll, hh = df.l.rolling(n).min(), df.h.rolling(n).max()
        fast = 100 * (df.c - ll) / (hh - ll + 1e-9)
        K = fast.rolling(k).mean()
        return K, K.rolling(d).mean()

    @staticmethod
    def obv(df):
        return (np.sign(df.c.diff().fillna(0)) * df.v).cumsum()

    @staticmethod
    def vwap(df):
        typical = (df.h + df.l + df.c) / 3
        day = df.ts // 86_400_000
        return (typical * df.v).groupby(day).cumsum() / df.v.groupby(day).cumsum()

    @staticmethod
    def cci(df, n=20):
        tp = (df.h + df.l + df.c) / 3
        return (tp - tp.rolling(n).mean()) / (0.015 * tp.rolling(n).std() + 1e-9)

    @classmethod
    def supertrend(cls, df, n=10, mult=3):
        N = len(df)
        if N == 0:
            empty = pd.Series(dtype=float)
            return empty, empty
        atr = cls.atr(df, n).values
        h = df.h.values; l = df.l.values; c = df.c.values
        hl2 = (h + l) / 2
        st = np.empty(N); trend = np.empty(N)
        fu = hl2[0] + mult * atr[0] if not np.isnan(atr[0]) else hl2[0]
        fl = hl2[0] - mult * atr[0] if not np.isnan(atr[0]) else hl2[0]
        tr = 1
        st[0] = fl; trend[0] = 1
        for i in range(1, N):
            a = atr[i]
            if np.isnan(a):
                st[i] = st[i-1]; trend[i] = tr
                continue
            ub = hl2[i] + mult * a
            lb = hl2[i] - mult * a
            fu = ub if c[i-1] > fu else min(ub, fu)
            fl = lb if c[i-1] < fl else max(lb, fl)
            if tr == 1 and c[i] < fl: tr = -1
            elif tr == -1 and c[i] > fu: tr = 1
            st[i] = fl if tr == 1 else fu
            trend[i] = tr
        return pd.Series(st, index=df.index), pd.Series(trend, index=df.index)

def indicators(df):
    I, c = Indicators, df.c
    df["ema_fast"] = I.ema(c, 9)
    df["ema_mid"]  = I.ema(c, 21)
    df["ema_slow"] = I.ema(c, 55)
    df["rsi"]      = I.rsi(c)
    df["macd"], df["macd_sig"] = I.macd(c)
    df["bb_m"], df["bb_u"], df["bb_l"] = I.boll(c)
    df["atr"]      = I.atr(df)
    df["adx"]      = I.adx(df)
    df["stoch_k"], df["stoch_d"] = I.stoch(df)
    df["obv"]      = I.obv(df)
    df["obv_s"]    = df["obv"].rolling(10).mean()
    df["vwap"]     = I.vwap(df)
    df["cci"]      = I.cci(df)
    df["st_line"], df["st_trend"] = I.supertrend(df)
    return df

# ============================================================
# SİNYAL + STRATEJİLER
# ============================================================
@dataclass
class Signal:
    pair: str; side: str
    confidence: float = 1.0
    source: str = "strategy"
    meta: dict = field(default_factory=dict)
    def push(self):
        with db_ctx() as c:
            c.execute("INSERT INTO signals(ts,source,pair,side,confidence,meta) "
                      "VALUES(?,?,?,?,?,?)",
                      (now(), self.source, self.pair, self.side,
                       self.confidence, json.dumps(self.meta, default=float)))

class Strategy:
    name = "base"
    params: dict = {}
    def check(self, r, p, pair): return None
    def clone(self):
        inst = copy.deepcopy(self)
        inst.params = dict(self.params)
        return inst

class EmaRsi(Strategy):
    name = "ema_rsi"
    def check(self, r, p, pair):
        if r.ema_fast > r.ema_mid > r.ema_slow and 50 <= r.rsi <= 70:
            return Signal(pair, "long",  meta={"r": "EMA+RSI"})
        if r.ema_fast < r.ema_mid < r.ema_slow and 30 <= r.rsi <= 50:
            return Signal(pair, "short", meta={"r": "EMA+RSI"})
        return None

class MacdStrategy(Strategy):
    name = "macd_trend"
    def check(self, r, p, pair):
        if p.macd <= p.macd_sig and r.macd > r.macd_sig and r.rsi > 50:
            return Signal(pair, "long",  meta={"r": "MACD x"})
        if p.macd >= p.macd_sig and r.macd < r.macd_sig and r.rsi < 50:
            return Signal(pair, "short", meta={"r": "MACD x"})
        return None

class BollBreak(Strategy):
    name = "boll_break"
    def check(self, r, p, pair):
        if p.c < p.bb_u and r.c > r.bb_u: return Signal(pair, "long")
        if p.c > p.bb_l and r.c < r.bb_l: return Signal(pair, "short")
        return None

class Confluence(Strategy):
    name = "confluence"
    params = {"threshold": 4, "atr_mult": 2.5, "atr_tp_mult": 5.0}

    def check(self, r, p, pair):
        votes = []
        votes.append(1 if r.ema_fast > r.ema_mid > r.ema_slow else
                     -1 if r.ema_fast < r.ema_mid < r.ema_slow else 0)
        votes.append(1 if p.macd <= p.macd_sig and r.macd > r.macd_sig else
                     -1 if p.macd >= p.macd_sig and r.macd < r.macd_sig else 0)
        votes.append(1 if r.rsi > 55 else -1 if r.rsi < 45 else 0)
        votes.append(1 if r.adx > 25 and r.ema_fast > r.ema_slow else
                     -1 if r.adx > 25 and r.ema_fast < r.ema_slow else 0)
        votes.append(1 if p.stoch_k <= p.stoch_d and r.stoch_k > r.stoch_d and r.stoch_k < 80 else
                     -1 if p.stoch_k >= p.stoch_d and r.stoch_k < r.stoch_d and r.stoch_k > 20 else 0)
        votes.append(1 if r.obv > r.obv_s and r.obv > p.obv else
                     -1 if r.obv < r.obv_s and r.obv < p.obv else 0)
        votes.append(1 if 0 < r.cci < 100 else -1 if -100 < r.cci < 0 else 0)
        votes.append(int(r.st_trend) if pd.notna(r.st_trend) else 0)
        votes.append(1 if r.c > r.vwap else -1 if r.c < r.vwap else 0)
        votes.append(1 if r.c > r.bb_u else -1 if r.c < r.bb_l else 0)

        score = int(sum(votes))
        th = self.params["threshold"]
        atr_st = (r.atr * self.params["atr_mult"]) if pd.notna(r.atr) else None
        atr_tp = (r.atr * self.params["atr_tp_mult"]) if pd.notna(r.atr) else None
        meta = {"score": score, "r": "confluence",
                "atr_stop": atr_st, "atr_tp": atr_tp}
        if score >= th:
            return Signal(pair, "long",  confidence=min(1, abs(score)/len(votes)), meta=meta)
        if score <= -th:
            return Signal(pair, "short", confidence=min(1, abs(score)/len(votes)), meta=meta)
        return None

STRATEGIES = {s.name: s for s in
              [EmaRsi(), MacdStrategy(), BollBreak(), Confluence()]}

# ============================================================
# BACKTESTER — cumsum + doğru funding
# ============================================================
def backtest(df, strat, cfg, start_i=60, end_i=None):
    s = STRATEGIES[strat] if isinstance(strat, str) else strat
    end_i = end_i if end_i is not None else len(df)
    opened, results = None, []
    sl_mode  = cfg.get("sl_mode", "atr")
    atr_mult = float(cfg.get("atr_mult", 2.5))
    atr_tp_on= bool(cfg.get("atr_tp_on", True))
    atr_tp_m = float(cfg.get("atr_tp_mult", 5.0))
    fixed_stop_pct = float(cfg.get("stop_pct", 0.02))
    risk_usd = float(cfg.get("risk_usd", 50))
    max_hold = int(cfg.get("max_hold", 200))
    tf_hours = float(cfg.get("tf_hours", 5/60))
    equity   = float(cfg.get("equity", 1000))
    max_lev  = float(cfg.get("max_leverage_equiv", 3.0))
    max_pos  = max(1, int(cfg.get("max_positions", 5)))

    for i in range(max(60, start_i), min(end_i, len(df))):
        r, p = df.iloc[i], df.iloc[i-1]

        if opened is not None and i >= opened["i"]:
            exit_price = None
            if opened["side"] == "long":
                if r.l <= opened["stop_price"]:
                    exit_price = min(r.o, opened["stop_price"])
                elif opened["tp_price"] and r.h >= opened["tp_price"]:
                    exit_price = opened["tp_price"]
            else:
                if r.h >= opened["stop_price"]:
                    exit_price = max(r.o, opened["stop_price"])
                elif opened["tp_price"] and r.l <= opened["tp_price"]:
                    exit_price = opened["tp_price"]
            if exit_price is None and (i - opened["i"]) > max_hold:
                exit_price = r.c
            if exit_price is not None:
                gross = (exit_price - opened["entry"]) * opened["amount"] * \
                        (1 if opened["side"] == "long" else -1)
                fees = (opened["entry"] + exit_price) * opened["amount"] * FEE
                slip = (opened["entry"] + exit_price) * opened["amount"] * SLIP
                held_h = (i - opened["i"]) * tf_hours
                rate = DEFAULT_FUNDING if opened["side"] == "long" else -DEFAULT_FUNDING
                funding = funding_cost(opened["entry"] * opened["amount"], rate, held_h)
                pnl = gross - fees - slip - funding
                results.append({
                    "pnl": pnl, "risk": opened["risk_usd"],
                    "r": pnl / opened["risk_usd"] if opened["risk_usd"] else 0,
                    "bars": i - opened["i"], "side": opened["side"]
                })
                opened = None
                continue

        if opened is None and i + 1 < end_i:
            sig = s.check(r, p, "BT")
            if sig and sig.side != "flat":
                entry = float(df.iloc[i+1].o)
                meta = sig.meta or {}
                atr_st = meta.get("atr_stop")
                atr_tp = meta.get("atr_tp")

                if sl_mode == "atr" and atr_st and r.c > 0:
                    stop_pct = atr_st / r.c
                else:
                    stop_pct = fixed_stop_pct
                stop_pct = min(max(stop_pct, 0.0005), 0.5)

                stop_price = (entry * (1 - stop_pct) if sig.side == "long"
                              else entry * (1 + stop_pct))
                tp_price = None
                if atr_tp_on:
                    if atr_tp and r.c > 0:
                        tp_pct = atr_tp / r.c
                    else:
                        tp_pct = stop_pct * (atr_tp_m / max(atr_mult, 0.1))
                    tp_price = (entry * (1 + tp_pct) if sig.side == "long"
                                else entry * (1 - tp_pct))

                rpu = abs(entry - stop_price)
                if rpu <= 0:
                    continue
                amount = risk_usd / rpu
                notional = amount * entry
                max_pair = equity * max_lev / max_pos
                if notional > max_pair:
                    amount = max_pair / entry
                    risk_actual = amount * rpu
                else:
                    risk_actual = risk_usd
                opened = {"entry": entry, "side": sig.side, "i": i+1,
                          "stop_price": stop_price, "tp_price": tp_price,
                          "amount": amount, "risk_usd": risk_actual}

    if not results:
        return {"trades": 0, "warning": "no trades"}
    pnls = pd.Series([x["pnl"] for x in results])
    rs   = pd.Series([x["r"] for x in results])
    eq_seri = equity + pnls.cumsum()
    peak = eq_seri.cummax()
    dd = ((eq_seri - peak) / peak).min()
    wins = (pnls > 0).mean()
    gw = pnls[pnls > 0].sum()
    gl = -pnls[pnls < 0].sum()
    pf = (gw / gl) if gl > 1e-9 else float("inf")
    net = pnls.sum()
    out = {"trades": len(results),
           "net":    round(net, 2),
           "net%":   round(net / equity * 100, 2),
           "win%":   round(wins * 100, 1),
           "PF":     round(pf, 2) if pf != float("inf") else "inf",
           "maxDD%": round(dd * 100, 2),
           "avg_R":  round(rs.mean(), 3)}
    if len(results) < MIN_TRADES:
        out["warning"] = f"low sample ({len(results)} < {MIN_TRADES})"
    return out

# ============================================================
# RİSK YÖNETİCİSİ — BEGIN IMMEDIATE ile atomik rezervasyon
# ============================================================
class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self._init_state()

    def _init_state(self):
        with db_ctx() as c:
            c.execute("INSERT OR IGNORE INTO kv(k,v) VALUES('peak_equity',?)",
                      (str(self.cfg.get("initial_equity", 1000)),))
            c.execute("INSERT OR IGNORE INTO kv(k,v) VALUES('daily_start_equity',?)",
                      (str(self.cfg.get("initial_equity", 1000)),))
            c.execute("INSERT OR IGNORE INTO kv(k,v) VALUES('daily_date','')")
            c.execute("INSERT OR IGNORE INTO kv(k,v) VALUES('kill','0')")
            c.execute("INSERT OR IGNORE INTO kv(k,v) VALUES('kill_reason','')")

    def equity(self, price_lookup=None):
        with db_ctx() as c:
            realized = float(c.execute(
                "SELECT COALESCE(SUM(pnl),0) AS p FROM trades "
                "WHERE status='closed'").fetchone()["p"])
            opens = c.execute(
                "SELECT pair, side, amount, entry FROM trades WHERE status='open'"
            ).fetchall()
        initial = float(self.cfg.get("initial_equity", 1000))
        unrealized = 0.0
        for t in opens:
            px = None
            if price_lookup:
                px = price_lookup(t["pair"])
            if px is None or px <= 0:
                px = float(t["entry"])
            yon = 1 if t["side"] == "long" else -1
            unrealized += yon * (px - float(t["entry"])) * float(t["amount"])
        return initial + realized + unrealized

    def sample_equity(self, price_lookup=None):
        eq = self.equity(price_lookup)
        with db_ctx() as c:
            c.execute("INSERT INTO equity(ts, equity) VALUES(?,?)", (now(), eq))
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            c.execute("DELETE FROM equity WHERE ts < ?", (cutoff,))
        peak = float(kv_get("peak_equity", eq))
        if eq > peak:
            kv_set("peak_equity", eq)
        today = datetime.now(timezone.utc).date().isoformat()
        if kv_get("daily_date") != today:
            kv_set("daily_date", today)
            kv_set("daily_start_equity", eq)
        return eq

    def check_kill(self, price_lookup=None):
        if kv_get("kill") == "1":
            return True, kv_get("kill_reason") or ""
        eq = self.equity(price_lookup)
        peak = float(kv_get("peak_equity", eq))
        daily_start = float(kv_get("daily_start_equity", eq))

        lim = float(self.cfg.get("daily_loss_limit", 0))
        if lim > 0 and (eq - daily_start) <= -lim:
            self._kill(f"Günlük zarar limiti aşıldı ({(eq-daily_start):.2f})")
            return True, kv_get("kill_reason")

        max_dd = float(self.cfg.get("max_dd_pct", 0))
        if max_dd > 0 and peak > 0:
            dd = (1 - eq / peak) * 100
            if dd >= max_dd:
                self._kill(f"Maks DD aşıldı (%{dd:.1f})")
                return True, kv_get("kill_reason")

        if eq <= 0:
            self._kill("Özsermaye tükendi")
            return True, kv_get("kill_reason")
        return False, ""

    def _kill(self, reason):
        kv_set("kill", "1")
        kv_set("kill_reason", reason)

    def reset_kill(self):
        kv_set("kill", "0")
        kv_set("kill_reason", "")
        eq = self.equity()
        kv_set("peak_equity", eq)
        kv_set("daily_start_equity", eq)

    def open_positions_count(self, exclude_trade_id=None):
        with db_ctx() as c:
            q = "SELECT COUNT(*) AS n FROM trades WHERE status='open'"
            params = []
            if exclude_trade_id is not None:
                q += " AND id != ?"
                params.append(exclude_trade_id)
            n = c.execute(q, params).fetchone()["n"]
        return int(n)

    def total_exposure(self, price_lookup=None):
        with db_ctx() as c:
            rows = c.execute(
                "SELECT pair, amount, entry FROM trades WHERE status='open'"
            ).fetchall()
        total = 0.0
        for r in rows:
            px = float(r["entry"])
            if price_lookup:
                p = price_lookup(r["pair"])
                if p: px = p
            total += float(r["amount"]) * px
        return total

    def reserve_trade(self, pair, engine, side, amount, entry, stop, tp,
                      source, notional, price_lookup=None, exclude_trade_id=None):
        """Atomik: BEGIN IMMEDIATE altında kontrol + INSERT tek transaction."""
        if kv_get("kill") == "1":
            return None, "kill switch aktif"
        if notional < float(self.cfg.get("min_notional", 5)):
            return None, "min notional"
        if notional <= 0:
            return None, "notional<=0"

        # HTTP I/O — transaction dışında
        prices = {}
        if price_lookup:
            with db_ctx() as c:
                open_pairs = [r[0] for r in c.execute(
                    "SELECT DISTINCT pair FROM trades WHERE status='open'").fetchall()]
            for p in open_pairs:
                px = price_lookup(p)
                if px and px > 0:
                    prices[p] = px

        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                realized = float(c.execute(
                    "SELECT COALESCE(SUM(pnl),0) FROM trades "
                    "WHERE status='closed'").fetchone()[0])
                opens = c.execute(
                    "SELECT pair, side, amount, entry FROM trades "
                    "WHERE status='open'").fetchall()
                initial = float(self.cfg.get("initial_equity", 1000))
                unrealized = 0.0
                for t in opens:
                    px = prices.get(t["pair"])
                    if px is None or px <= 0:
                        px = float(t["entry"])
                    yon = 1 if t["side"] == "long" else -1
                    unrealized += yon * (px - float(t["entry"])) * float(t["amount"])
                eq = initial + realized + unrealized

                max_pos = int(self.cfg.get("max_positions", 5))
                q = "SELECT COUNT(*) FROM trades WHERE status='open'"
                params = []
                if exclude_trade_id is not None:
                    q += " AND id != ?"
                    params.append(exclude_trade_id)
                n = c.execute(q, params).fetchone()[0]
                if n >= max_pos:
                    c.execute("ROLLBACK")
                    return None, "max_positions"

                max_total = eq * float(self.cfg.get("max_leverage_equiv", 3.0))
                max_pair = max_total / max(1, max_pos)
                if notional > max_pair:
                    c.execute("ROLLBACK")
                    return None, f"per-pair cap ({max_pair:.0f})"

                tot = float(c.execute(
                    "SELECT COALESCE(SUM(amount*entry),0) FROM trades "
                    "WHERE status='open'").fetchone()[0])
                if tot + notional > max_total:
                    c.execute("ROLLBACK")
                    return None, "total exposure"

                try:
                    c.execute("""INSERT INTO trades(pair,engine,side,amount,entry,
                                 stop,take_profit,status,opened,strategy)
                                 VALUES(?,?,?,?,?,?,?,?,?,?)""",
                              (pair, engine, side, amount, entry, stop, tp,
                               "open", now(), source))
                    tid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                    c.execute("COMMIT")
                    return tid, ""
                except sqlite3.IntegrityError:
                    c.execute("ROLLBACK")
                    return None, "duplicate (open)"
            except Exception as e:
                try: c.execute("ROLLBACK")
                except Exception: pass
                return None, str(e)
        finally:
            c.close()

    def last_close_ts(self, pair):
        with db_ctx() as c:
            row = c.execute(
                "SELECT closed FROM trades WHERE pair=? AND status='closed' "
                "ORDER BY closed DESC LIMIT 1", (pair,)).fetchone()
        return row["closed"] if row else None

    def in_cooldown(self, pair, cooldown_min):
        if cooldown_min <= 0:
            return False
        ts = self.last_close_ts(pair)
        if not ts:
            return False
        try:
            last = datetime.fromisoformat(ts)
        except Exception:
            return False
        return ((datetime.now(timezone.utc) - last).total_seconds() / 60
                < cooldown_min)

# ============================================================
# SPOT MOTORU — notional kırpma geri geldi
# ============================================================
class SpotEngine:
    name = "spot"

    def __init__(self, gw, cfg, risk: RiskManager):
        self.gw, self.cfg, self.risk = gw, cfg, risk

    def _other_engine_has_open(self, pair):
        if self.cfg.get("allow_both_engines", False):
            return False
        with db_ctx() as c:
            row = c.execute(
                "SELECT 1 FROM trades WHERE pair=? AND status='open' "
                "AND engine!='spot' LIMIT 1", (pair,)).fetchone()
        return row is not None

    def on_signal(self, sig: Signal, price):
        if self.risk.check_kill(self.gw.price)[0]:
            return None
        pair = sig.pair
        if self.risk.in_cooldown(pair, self.cfg.get("cooldown_min", 0)):
            return None
        if self._other_engine_has_open(pair):
            return None

        meta = sig.meta or {}
        atr_st = meta.get("atr_stop")
        atr_tp = meta.get("atr_tp")

        if self.cfg.get("sl_mode") == "atr" and atr_st and price > 0:
            stop_pct = atr_st / price
        else:
            stop_pct = self.cfg.get("stop_pct", 0.02)
        stop_pct = min(max(stop_pct, 0.0005), 0.5)

        stop = (price * (1 - stop_pct) if sig.side == "long"
                else price * (1 + stop_pct))
        tp = None
        if self.cfg.get("atr_tp_on"):
            if atr_tp and price > 0:
                tp_pct = atr_tp / price
            else:
                tp_pct = stop_pct * (float(self.cfg.get("atr_tp_mult", 5.0))
                                     / max(float(self.cfg.get("atr_mult", 2.5)), 0.1))
            tp = (price * (1 + tp_pct) if sig.side == "long"
                  else price * (1 - tp_pct))

        risk_usd = float(self.cfg.get("risk_usd", 50))
        rpu = abs(price - stop)
        if rpu <= 0:
            return None
        amount = risk_usd / rpu
        notional = amount * price

        eq = self.risk.equity(self.gw.price)
        max_pos = max(1, int(self.cfg.get("max_positions", 5)))
        max_pair = eq * float(self.cfg.get("max_leverage_equiv", 3.0)) / max_pos
        if notional > max_pair:
            amount = max_pair / price
            notional = max_pair
            print(f"[spot] {pair} kırpıldı → risk {amount * rpu:.2f}$ (per-pair cap)")

        tid, err = self.risk.reserve_trade(
            pair, self.name, sig.side, amount, price, stop, tp, sig.source,
            notional, self.gw.price)
        if tid is None:
            print(f"[spot] {pair} açılmadı — {err}")
            return None

        self.gw.place(pair, "buy" if sig.side == "long" else "sell",
                      amount, price, tid)
        print(f"[spot] {pair} {sig.side} @ {price:.6g} · amt={amount:.6g} · "
              f"risk={amount * rpu:.2f}$ · stop={stop:.6g}")
        return tid

    def close_trade(self, tid, price, reason):
        with db_ctx() as c:
            t = c.execute("SELECT * FROM trades WHERE id=? AND status='open'",
                          (tid,)).fetchone()
        if not t:
            return False
        pair = t["pair"]; side = t["side"]
        amount = float(t["amount"]); entry = float(t["entry"])
        if price is None or price <= 0:
            price = self.gw.price(pair, force=True) or entry

        gross = (price - entry) * amount * (1 if side == "long" else -1)
        fees  = (entry + price) * amount * self.gw.fee
        slip  = (entry + price) * amount * self.gw.slip
        try:
            held_h = (datetime.now(timezone.utc)
                      - datetime.fromisoformat(t["opened"])).total_seconds() / 3600
        except Exception:
            held_h = 0.0
        rate = funding_rate_now(self.gw, pair)
        if side == "short":
            rate = -rate
        funding = funding_cost(entry * amount, rate, held_h)
        pnl = gross - fees - slip - funding

        with db_ctx() as c:
            cur = c.execute(
                "UPDATE trades SET status='closed', exit_price=?, closed=?, "
                "pnl=?, reason=? WHERE id=? AND status='open'",
                (price, now(), pnl, reason, tid))
            if cur.rowcount == 0:
                return False

        self.gw.place(pair, "sell" if side == "long" else "buy",
                      amount, None, tid, reduce_only=True)
        print(f"[spot] {pair} kapatıldı ({reason}) · pnl={pnl:.2f}$")
        return True

    def on_price(self, tid, price):
        with db_ctx() as c:
            t = c.execute("SELECT * FROM trades WHERE id=? AND status='open'",
                          (tid,)).fetchone()
        if not t:
            return
        side, stop, tp = t["side"], t["stop"], t["take_profit"]
        hit_sl = price <= stop if side == "long" else price >= stop
        hit_tp = (tp is not None) and (
            price >= tp if side == "long" else price <= tp)
        if hit_sl:
            self.close_trade(tid, price, "SL")
            return
        if hit_tp:
            self.close_trade(tid, price, "TP")
            return
        max_hold = int(self.cfg.get("max_hold", 200))
        if max_hold > 0:
            try:
                held_min = (datetime.now(timezone.utc)
                            - datetime.fromisoformat(t["opened"])).total_seconds() / 60
                tf_min = int(self.cfg.get("tf_minutes", 5))
                if held_min >= max_hold * tf_min:
                    self.close_trade(tid, price, "MAX_HOLD")
            except Exception:
                pass

# ============================================================
# DCA MOTORU — plan rezervi + SO tavanı yok
# ============================================================
class DCAEngine:
    name = "dca"

    def __init__(self, gw, cfg, risk: RiskManager):
        self.gw, self.cfg, self.risk = gw, cfg, risk

    def _load(self, pair):
        with db_ctx() as c:
            row = c.execute("SELECT * FROM dca_state WHERE pair=?",
                            (pair,)).fetchone()
        return dict(row) if row else None

    def _save(self, pair, d):
        with db_ctx() as c:
            if d is None:
                c.execute("DELETE FROM dca_state WHERE pair=?", (pair,))
            else:
                c.execute("""INSERT OR REPLACE INTO dca_state
                             (pair, trade_id, base_qty, so_max, so_step, so_mult,
                              filled, avg_price, stop_price, opened)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (pair, d["trade_id"], d["base_qty"], d["so_max"],
                           d["so_step"], d["so_mult"], d["filled"],
                           d["avg_price"], d["stop_price"], d["opened"]))

    def _other_engine_has_open(self, pair):
        if self.cfg.get("allow_both_engines", False):
            return False
        with db_ctx() as c:
            row = c.execute(
                "SELECT 1 FROM trades WHERE pair=? AND status='open' "
                "AND engine!='dca' LIMIT 1", (pair,)).fetchone()
        return row is not None

    def on_signal(self, sig: Signal, price):
        if sig.side != "long":
            return
        if self.risk.check_kill(self.gw.price)[0]:
            return
        if self._load(sig.pair):
            return
        if self.risk.in_cooldown(sig.pair, self.cfg.get("cooldown_min", 0)):
            return
        if self._other_engine_has_open(sig.pair):
            return

        base_usd = float(self.cfg["base_usd"])
        so_max = int(self.cfg["so_max"])
        so_mult = float(self.cfg["so_mult"])

        # Planı per-pair tavana sığdır
        total_mult = sum(so_mult ** i for i in range(so_max + 1))
        total_plan = base_usd * total_mult

        eq = self.risk.equity(self.gw.price)
        max_pos = max(1, int(self.cfg.get("max_positions", 5)))
        max_pair = eq * float(self.cfg.get("max_leverage_equiv", 3.0)) / max_pos

        if total_plan > max_pair:
            adjusted_base = max_pair / total_mult
            print(f"[dca] {sig.pair} base_usd {base_usd:.1f} → {adjusted_base:.1f} "
                  f"(plan {total_plan:.0f}$ > per-pair {max_pair:.0f}$)")
            base_usd = adjusted_base
            total_plan = base_usd * total_mult

        qty = base_usd / price
        stop_price = price * (1 - self.cfg["stop_pct"])

        tid, err = self.risk.reserve_trade(
            sig.pair, self.name, "long", qty, price, stop_price, None,
            sig.source, total_plan, self.gw.price)
        if tid is None:
            print(f"[dca] {sig.pair} açılmadı — {err}")
            return

        state = {
            "trade_id": tid, "base_qty": qty, "so_max": so_max,
            "so_step": self.cfg["so_step"], "so_mult": so_mult,
            "filled": 0, "avg_price": price, "stop_price": stop_price,
            "opened": now()
        }
        self._save(sig.pair, state)
        self.gw.place(sig.pair, "buy", qty, price, tid)
        print(f"[dca] {sig.pair} base @ {price:.6g} qty={qty:.6g} plan={total_plan:.0f}$")

    def on_price(self, pair, price):
        d = self._load(pair)
        if not d:
            return
        if price <= d["stop_price"]:
            self._close(pair, price, "DCA-SL")
            return

        if d["filled"] < d["so_max"]:
            target = d["avg_price"] * (1 - d["so_step"] * (d["filled"] + 1))
            if price <= target:
                vol = (float(self.cfg["base_usd"])
                       * d["so_mult"] ** (d["filled"] + 1)) / price
                old_qty = d["base_qty"]
                new_qty = old_qty + vol
                d["avg_price"] = (d["avg_price"] * old_qty + price * vol) / new_qty
                d["base_qty"] = new_qty
                d["filled"] += 1
                self._save(pair, d)
                with db_ctx() as c:
                    c.execute("""UPDATE trades SET amount=?, entry=?, stop=?
                                 WHERE id=? AND status='open'""",
                              (new_qty, d["avg_price"], d["stop_price"],
                               d["trade_id"]))
                self.gw.place(pair, "buy", vol, price, d["trade_id"])
                print(f"[dca] {pair} SO#{d['filled']} @ {price:.6g} vol={vol:.6g}")

        if price >= d["avg_price"] * (1 + self.cfg["tp_pct"]):
            self._close(pair, price, "DCA-TP")

    def _close(self, pair, price, reason):
        d = self._load(pair)
        if not d:
            return
        amount = d["base_qty"]; entry = d["avg_price"]
        self.gw.place(pair, "sell", amount, None, d["trade_id"], reduce_only=True)
        gross = (price - entry) * amount
        fees  = (entry + price) * amount * self.gw.fee
        slip  = (entry + price) * amount * self.gw.slip
        try:
            held_h = (datetime.now(timezone.utc)
                      - datetime.fromisoformat(d["opened"])).total_seconds() / 3600
        except Exception:
            held_h = 0.0
        rate = funding_rate_now(self.gw, pair)
        funding = funding_cost(entry * amount, rate, held_h)
        pnl = gross - fees - slip - funding

        with db_ctx() as c:
            cur = c.execute(
                "UPDATE trades SET status='closed', exit_price=?, closed=?, "
                "pnl=?, reason=? WHERE id=? AND status='open'",
                (price, now(), pnl, reason, d["trade_id"]))
            if cur.rowcount == 0:
                return
        self._save(pair, None)
        print(f"[dca] {pair} kapatıldı ({reason}) pnl={pnl:.2f}$")

# ============================================================
# WEBHOOK — DCA dahil kapatır
# ============================================================
def start_webhook(port, spot: SpotEngine, dca, host="0.0.0.0"):
    if not WEBHOOK_TOKEN:
        print("⛔ WEBHOOK_TOKEN yok — webhook başlatılmadı")
        return
    from flask import Flask, request
    app = Flask(__name__)

    @app.post("/signal")
    def sig():
        token = request.headers.get("X-Token", "")
        if not hmac.compare_digest(token, WEBHOOK_TOKEN):
            return {"error": "auth"}, 401
        d = request.get_json(silent=True) or {}
        pair = d.get("pair")
        raw = str(d.get("side", "")).lower()
        side = {"buy": "long", "sell": "short", "long": "long",
                "short": "short", "close": "close"}.get(raw)
        if not pair or not side:
            return {"error": "invalid side/pair"}, 400

        if side == "close":
            with db_ctx() as c:
                rows = c.execute(
                    "SELECT id, engine, pair FROM trades "
                    "WHERE pair=? AND status='open'", (pair,)).fetchall()
            px_raw = d.get("price")
            px = None
            if px_raw is not None:
                try:
                    px = float(px_raw)
                    if px <= 0:
                        px = None
                except (ValueError, TypeError):
                    px = None
            if px is None:
                px = spot.gw.price(pair, force=True)
            if px is None:
                return {"error": "price unavailable"}, 500

            closed = 0
            for row in rows:
                if row["engine"] == "spot":
                    if spot.close_trade(row["id"], px, "WEBHOOK_CLOSE"):
                        closed += 1
                elif row["engine"] == "dca" and dca:
                    dca._close(row["pair"], px, "WEBHOOK_CLOSE")
                    closed += 1
            return {"ok": True, "closed": closed}

        px = d.get("price")
        if not px:
            return {"error": "price required"}, 400
        try:
            px = float(px)
            if px <= 0:
                raise ValueError
        except Exception:
            return {"error": "invalid price"}, 400

        s = Signal(pair=pair, side=side, source="webhook", meta=d)
        s.push()
        tid = spot.on_signal(s, px)
        return {"ok": True, "trade_id": tid}

    threading.Thread(target=lambda: app.run(host=host, port=port,
                                            use_reloader=False,
                                            threaded=True),
                     daemon=True).start()
    print(f"🔗 webhook: POST http://{host}:{port}/signal (X-Token zorunlu)")

# ============================================================
# MONITOR LOOP — DCA her zaman izlenir, kill sonrası devam
# ============================================================
def monitor_loop(gw, spot, dca, risk, interval_sec=10):
    print(f"👁 monitor_loop: {interval_sec}s")
    while True:
        try:
            with db_ctx() as c:
                opens = c.execute(
                    "SELECT id, pair, engine FROM trades WHERE status='open'"
                ).fetchall()

            pairs = list({r["pair"] for r in opens})
            fiyat = gw.prices(pairs) if pairs else {}

            for row in opens:
                pair = row["pair"]
                px = fiyat.get(pair)
                if px is None:
                    px = gw.price(pair)
                if px is None:
                    continue
                if row["engine"] == "spot":
                    spot.on_price(row["id"], px)
                elif row["engine"] == "dca" and dca:
                    dca.on_price(pair, px)

            risk.sample_equity(gw.price)
            killed, reason = risk.check_kill(gw.price)
            if killed:
                print(f"⛔ KILL: {reason} — yeni girişler kapalı, izleme devam")
                if risk.cfg.get("kill_close_positions", True):
                    for row in opens:
                        px = fiyat.get(row["pair"]) or gw.price(row["pair"], force=True)
                        if not px:
                            continue
                        if row["engine"] == "spot":
                            spot.close_trade(row["id"], px, "KILL")
                        elif row["engine"] == "dca" and dca:
                            dca._close(row["pair"], px, "KILL")
        except Exception as e:
            print(f"[monitor] {e}")
        time.sleep(interval_sec)

# ============================================================
# DEFAULTS + auto-fix + fetch_history + yardımcılar
# ============================================================
DEFAULTS = {
    "initial_equity": 1000.0,
    "risk_usd": 50.0,
    "max_positions": 5,
    "max_leverage_equiv": 3.0,
    "min_notional": 5.0,
    "daily_loss_limit": 100.0,
    "max_dd_pct": 25.0,
    "cooldown_min": 30.0,
    "kill_close_positions": True,
    "allow_both_engines": False,
    "engine_mode": "spot_then_dca",
    "sl_mode": "atr",
    "atr_mult": 2.5,
    "atr_tp_on": True,
    "atr_tp_mult": 5.0,
    "stop_pct": 0.02,
    "max_hold": 200,
    "tf_minutes": 5,
    "dca": {"base_usd": 100.0, "so_max": 4, "so_step": 0.02,
            "so_mult": 1.5, "tp_pct": 0.015, "stop_pct": 0.15,
            "cooldown_min": 60.0, "allow_both_engines": False},
}

def _validate_config(cfg):
    eq = float(cfg.get("initial_equity", 1000))
    max_pos = int(cfg.get("max_positions", 5))
    max_lev = float(cfg.get("max_leverage_equiv", 3.0))
    per_pair = eq * max_lev / max(1, max_pos)
    risk_usd = float(cfg.get("risk_usd", 50))

    if risk_usd > 0 and per_pair > 0:
        typical_stop_pct = 0.005
        req_notional = risk_usd / typical_stop_pct
        if req_notional > per_pair:
            new_risk = round(per_pair * typical_stop_pct * 0.8, 2)
            print(f"🔧 auto-fix: risk_usd {risk_usd:.1f}$ → {new_risk:.2f}$ "
                  f"(per-pair cap {per_pair:.0f}$)")
            cfg["risk_usd"] = new_risk

    dca = cfg.get("dca", {})
    base = float(dca.get("base_usd", 100))
    so_max = int(dca.get("so_max", 4))
    so_mult = float(dca.get("so_mult", 1.5))
    stop_pct = float(dca.get("stop_pct", 0.15))
    total_usd = base * sum(so_mult**i for i in range(so_max + 1))
    max_loss = total_usd * stop_pct
    daily = float(cfg.get("daily_loss_limit", 100))
    if daily > 0 and max_loss > daily:
        print(f"⚠ DCA tek pozisyon maks zararı ~{max_loss:.0f}$ > "
              f"daily_loss_limit {daily:.0f}$ — DCA kapat ya da limiti yükselt")

def fetch_history(gw, pair, tf, limit):
    tf_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}.get(tf, 300_000)
    now_ms = int(time.time() * 1000)
    since = now_ms - limit * tf_ms
    out = []
    while len(out) < limit:
        want = min(1000, limit - len(out))
        try:
            batch = gw.ex.fetch_ohlcv(pair, tf, since=since, limit=want)
        except Exception as e:
            print(f"fetch_history {pair}: {e}")
            break
        if not batch:
            break
        out.extend(batch)
        if len(batch) < want:
            break
        since = batch[-1][0] + 1
        time.sleep(0.25)

    if not out:
        return None
    df = pd.DataFrame(out, columns=["ts", "o", "h", "l", "c", "v"])
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return indicators(df)

def _last_ts(pair):
    v = kv_get(f"last_ts:{pair}")
    return int(v) if v else 0

def _set_last_ts(pair, ts):
    kv_set(f"last_ts:{pair}", ts)

def _selection_score(res):
    n = res.get("trades", 0)
    if n < MIN_TRADES:
        return -1e9
    avg_r = res.get("avg_R", 0)
    pf = res.get("PF", 1)
    if pf == "inf":
        pf = 3.0
    return avg_r + (min(pf, 5.0) - 1) * 0.02

# ============================================================
# ÇEKİRDEK DÖNGÜ
# ============================================================
def run(pairs, strategy="confluence", interval="5m", port=5000,
        with_dca=True, with_webhook=False):
    active_cfg = copy.deepcopy(DEFAULTS)
    active_cfg["tf_minutes"] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(interval, 5)
    if not with_dca:
        active_cfg["engine_mode"] = "spot_only"
    if active_cfg.get("engine_mode") == "both":
        active_cfg["allow_both_engines"] = True
        active_cfg["dca"]["allow_both_engines"] = True
    _validate_config(active_cfg)

    gw = ExchangeGateway(paper=True)
    risk = RiskManager(active_cfg)
    spot = SpotEngine(gw, active_cfg, risk)
    dca = DCAEngine(gw, active_cfg["dca"], risk)

    engine_mode = active_cfg.get("engine_mode", "spot_then_dca")
    threading.Thread(target=monitor_loop,
                     args=(gw, spot, dca, risk, 10),
                     daemon=True).start()
    if with_webhook and port:
        start_webhook(port, spot, dca)

    print(f"▶ MEGA-BOT v6 | {strategy} | PAPER | {len(pairs)} pair | "
          f"engine={engine_mode} | risk_usd={active_cfg['risk_usd']:.2f}$")

    seen = set()
    while True:
        killed, reason = risk.check_kill(gw.price)
        if killed:
            print(f"⛔ KILL: {reason}")

        for pair in pairs:
            try:
                df_raw = gw.ohlcv_raw(pair, interval, limit=200)
                last_ts = int(df_raw.iloc[-2].ts)

                if pair not in seen:
                    seen.add(pair)
                    _set_last_ts(pair, last_ts)
                    continue

                if _last_ts(pair) != last_ts:
                    df = indicators(df_raw)
                    sig = STRATEGIES[strategy].check(df.iloc[-2], df.iloc[-3], pair)
                    if sig and sig.side != "flat":
                        sig.push()
                        px = gw.price(pair, force=True) or float(df.iloc[-2].c)
                        opened = False
                        if engine_mode in ("spot_only", "spot_then_dca", "both"):
                            if spot.on_signal(sig, px):
                                opened = True
                        if (not opened) and engine_mode in ("dca_only", "spot_then_dca", "both"):
                            dca.on_signal(sig, px)
                    _set_last_ts(pair, last_ts)
            except Exception as e:
                print(f"[{pair}] döngü hatası: {e}")
        time.sleep(15)

# ============================================================
# SCAN
# ============================================================
def scan(symbol, strategy_name, tf):
    gw = ExchangeGateway(paper=True)
    df = fetch_history(gw, symbol, tf, 1500)
    if df is None or len(df) < 200:
        print("yetersiz veri")
        return
    tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1.0}.get(tf, 5/60)
    active_cfg = copy.deepcopy(DEFAULTS)
    active_cfg["equity"] = active_cfg["initial_equity"]
    active_cfg["tf_hours"] = tf_hours
    _validate_config(active_cfg)

    split = int(len(df) * 2 / 3)
    train = df.iloc[:split].reset_index(drop=True)
    test  = df.iloc[split:].reset_index(drop=True)

    base = STRATEGIES[strategy_name]
    grid = []
    ths = [3, 4, 5, 6] if strategy_name == "confluence" else [None]
    for th in ths:
        for atr_m in [1.5, 2.0, 2.5, 3.0]:
            for atr_tpm in [3, 5, 7]:
                clone = base.clone()
                if th is not None:
                    clone.params["threshold"] = th
                    clone.params["atr_mult"] = atr_m
                    clone.params["atr_tp_mult"] = atr_tpm
                res = backtest(train, clone, active_cfg)
                grid.append((res, th, atr_m, atr_tpm, clone))

    best = max(grid, key=lambda x: _selection_score(x[0]))
    test_res = backtest(test, best[4], active_cfg)
    print("EN İYİ (train):", best[0], "| th:", best[1],
          "| atr_mult:", best[2], "| atr_tp_mult:", best[3])
    print("TEST (OOS):    ", test_res)
    if best[0].get("trades", 0) < MIN_TRADES:
        print(f"⚠ hiçbir kombinasyon MIN_TRADES={MIN_TRADES}'ı geçmedi")

# ============================================================
# WALK-FORWARD
# ============================================================
def walk_forward(symbol, strategy_name, tf, n_folds=3, verbose=True):
    gw = ExchangeGateway(paper=True)
    df = fetch_history(gw, symbol, tf, 3000)
    if df is None or len(df) < 400:
        if verbose:
            print(f"yetersiz veri: {symbol} ({len(df) if df is not None else 0} mum)")
        return None
    tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1.0}.get(tf, 5/60)
    active_cfg = copy.deepcopy(DEFAULTS)
    active_cfg["equity"] = active_cfg["initial_equity"]
    active_cfg["tf_hours"] = tf_hours
    _validate_config(active_cfg)

    n = len(df)
    parca = n // (n_folds + 2)
    if parca < 100:
        if verbose:
            print(f"yetersiz veri: {symbol} parça={parca}")
        return None

    base = STRATEGIES[strategy_name]
    ths = [3, 4, 5, 6] if strategy_name == "confluence" else [None]
    folds = []

    for f in range(n_folds):
        train_bas = f * parca
        train_son = train_bas + parca * 2
        test_bas = train_son
        test_son = min(n, test_bas + parca)
        if test_son - test_bas < 100:
            continue

        train = df.iloc[train_bas:train_son].reset_index(drop=True)
        best = None
        for th in ths:
            for atr_m in [1.5, 2.0, 2.5, 3.0]:
                clone = base.clone()
                if th is not None:
                    clone.params["threshold"] = th
                    clone.params["atr_mult"] = atr_m
                res = backtest(train, clone, active_cfg)
                if res.get("trades", 0) < MIN_TRADES:
                    continue
                if not best or _selection_score(res) > _selection_score(best[0]):
                    best = (res, th, atr_m, clone)
        if not best:
            continue

        test = df.iloc[test_bas:test_son].reset_index(drop=True)
        oos = backtest(test, best[3], active_cfg)
        folds.append({
            "fold": f+1,
            "is": best[0],
            "params": {"threshold": best[1], "atr_mult": best[2]},
            "oos": oos
        })
        if verbose:
            print(f"fold {f+1}: IS net={best[0].get('net', 0):+.2f} "
                  f"| OOS net={oos.get('net', 0):+.2f} "
                  f"trades={oos.get('trades', 0)} | th={best[1]} atr_m={best[2]}")

    if not folds:
        return None

    oos_net = sum(f["oos"].get("net", 0) for f in folds)
    oos_trades = sum(f["oos"].get("trades", 0) for f in folds)
    if verbose:
        print(f"\n=== OOS Özet ({symbol}) ===")
        print(f"toplam OOS net: {oos_net:+.2f} USDT · {oos_trades} işlem · "
              f"{len(folds)} fold")
    return {"symbol": symbol, "folds": folds,
            "oos_net": oos_net, "oos_trades": oos_trades}

def walk_forward_multi(symbols, strategy_name, tf, n_folds=3):
    results = []
    total_net = 0.0
    total_trades = 0
    for sym in symbols:
        r = walk_forward(sym, strategy_name, tf, n_folds, verbose=False)
        if r:
            results.append(r)
            total_net += r["oos_net"]
            total_trades += r["oos_trades"]
            print(f"{sym}: OOS net={r['oos_net']:+.2f} · "
                  f"trades={r['oos_trades']} · folds={len(r['folds'])}")

    print(f"\n=== MULTI-SYMBOL OOS ÖZET ===")
    print(f"Sembol: {len(results)}/{len(symbols)}")
    print(f"Toplam OOS net: {total_net:+.2f} USDT")
    print(f"Toplam OOS işlem: {total_trades}")
    if total_trades > 0:
        print(f"Ortalama net/işlem: {total_net/total_trades:+.2f} USDT")
    return {"results": results, "total_net": total_net,
            "total_trades": total_trades}

# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    ap = argparse.ArgumentParser("megabot")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("--symbol", default="BTC/USDT:USDT")
    f.add_argument("--tf", default="5m")
    f.add_argument("--limit", type=int, default=500)

    r = sub.add_parser("run")
    r.add_argument("--symbols", nargs="+", default=["BTC/USDT:USDT"])
    r.add_argument("--strategy", default="confluence")
    r.add_argument("--interval", default="5m")
    r.add_argument("--no-dca", action="store_true")
    r.add_argument("--webhook", action="store_true")
    r.add_argument("--port", type=int, default=5000)

    b = sub.add_parser("backtest")
    b.add_argument("--symbol", default="BTC/USDT:USDT")
    b.add_argument("--strategy", default="confluence")
    b.add_argument("--tf", default="5m")

    s = sub.add_parser("scan")
    s.add_argument("--symbol", default="BTC/USDT:USDT")
    s.add_argument("--strategy", default="confluence")
    s.add_argument("--tf", default="5m")

    w = sub.add_parser("walk-forward")
    w.add_argument("--symbol", default="BTC/USDT:USDT")
    w.add_argument("--strategy", default="confluence")
    w.add_argument("--tf", default="5m")
    w.add_argument("--folds", type=int, default=3)

    wm = sub.add_parser("walk-forward-multi")
    wm.add_argument("--symbols", nargs="+", required=True)
    wm.add_argument("--strategy", default="confluence")
    wm.add_argument("--tf", default="5m")
    wm.add_argument("--folds", type=int, default=3)

    l = sub.add_parser("listen")
    l.add_argument("--port", type=int, default=5000)

    k = sub.add_parser("reset-kill")
    e = sub.add_parser("equity")

    a = ap.parse_args()

    if a.cmd == "fetch":
        gw = ExchangeGateway(paper=True)
        df = gw.ohlcv(a.symbol, a.tf, a.limit)
        print(df.tail())

    elif a.cmd == "run":
        run(a.symbols, a.strategy, a.interval, a.port,
            with_dca=not a.no_dca, with_webhook=a.webhook)

    elif a.cmd == "backtest":
        gw = ExchangeGateway(paper=True)
        df = gw.ohlcv(a.symbol, a.tf, 1000)
        tf_hours = {"1m": 1/60, "5m": 5/60, "15m": 0.25, "1h": 1.0}.get(a.tf, 5/60)
        active_cfg = copy.deepcopy(DEFAULTS)
        active_cfg["equity"] = active_cfg["initial_equity"]
        active_cfg["tf_hours"] = tf_hours
        _validate_config(active_cfg)
        print(backtest(df, a.strategy, active_cfg))

    elif a.cmd == "scan":
        scan(a.symbol, a.strategy, a.tf)

    elif a.cmd == "walk-forward":
        walk_forward(a.symbol, a.strategy, a.tf, a.folds)

    elif a.cmd == "walk-forward-multi":
        walk_forward_multi(a.symbols, a.strategy, a.tf, a.folds)

    elif a.cmd == "listen":
        active_cfg = copy.deepcopy(DEFAULTS)
        _validate_config(active_cfg)
        gw = ExchangeGateway(paper=True)
        risk = RiskManager(active_cfg)
        spot = SpotEngine(gw, active_cfg, risk)
        dca = DCAEngine(gw, active_cfg["dca"], risk)
        threading.Thread(target=monitor_loop,
                         args=(gw, spot, dca, risk, 10),
                         daemon=True).start()
        start_webhook(a.port, spot, dca)
        print("Ctrl-C ile çık.")
        while True:
            time.sleep(1)

    elif a.cmd == "reset-kill":
        RiskManager(copy.deepcopy(DEFAULTS)).reset_kill()
        print("kill switch sıfırlandı")

    elif a.cmd == "equity":
        active_cfg = copy.deepcopy(DEFAULTS)
        risk = RiskManager(active_cfg)
        gw = ExchangeGateway(paper=True)
        eq = risk.equity(gw.price)
        with db_ctx() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM equity").fetchone()["n"]
        print(f"equity={eq:.2f} (mark-to-market) | örnek={n} | "
              f"kill={kv_get('kill')} | peak={kv_get('peak_equity')}")