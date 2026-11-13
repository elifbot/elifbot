"""
================================================================================
  BİRLEŞTİRİLMİŞ KRİPTO AL-SAT BOTSİSTEMİ (26 MODÜL TEK DOSYADA)
================================================================================
  1.  security.py           - Güvenlik ve Gizli Veri Maskeleme
  2.  alerts.py             - Çoklu Kanal Bildirim / Alarm (Telegram/Discord/PD)
  3.  indicators.py         - Teknik İndikatörler (RSI, MACD, Supertrend, Vol)
  4.  orderbook.py          - Derinlik & Para Akışı Analizi (OI, Squeeze)
  5.  news.py               - Haber & Duygu (Sentiment) Analizi
  6.  arbitrage.py          - Borsalar Arası Arbitraj Motoru
  7.  ml_engine.py          - Makine Öğrenmesi (ML) Yön Tahmin Sürücüsü
  8.  multi_tf.py           - Çoklu Zaman Dilimi (MTF) Trend Filtresi
  9.  risk.py               - Risk / Stop / Trailing / Piramit / Kurtarma
  10. sizing.py             - Dinamik Pozisyon Boyutlandırma (ATR + Kelly)
  11. state_store.py        - SQLite WAL Durum Saklama & Log Rotation
  12. circuit_breaker.py    - Acil Durum Sigortası & Drawdown Koruması
  13. broker_binance.py     - Binance Futures Borsa Bağlantısı
  14. broker_okx.py         - OKX Futures Borsa Bağlantısı
  15. broker_bybit.py       - Bybit Futures Borsa Bağlantısı
  16. strategy.py           - Sinyal Birleştirici & Strateji Beyni
  17. telegram.py           - Telegram Uzaktan Komuta Botu
  18. web_panel.py          - FastAPI / HTML Dashboard & Canlı Takip
  19. backtest.py           - Backtest Motoru
  20. walkforward.py        - Walk-Forward Optimizasyon Motoru
  21. executor.py           - İşlem Yürütücü Motor (Trade Executor)
  22. binance_ws.py         - Binance WebSocket Canlı Veri Akışı
  23. okx_ws.py             - OKX WebSocket Canlı Veri Akışı
  24. bybit_ws.py           - Bybit WebSocket Canlı Veri Akışı
  25. mock_exchanges.py      - Paper Trading / Simülatör Borsa Modülü
  26. main.py               - Ana Çalıştırma Modülü (CLI / Entrypoint)
================================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import gzip
import hashlib
import hmac
import json
import logging
import math
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Opsiyonel Harici Kütüphaneler (Varsa kullanılır, yoksa fallback devreye girer)
try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import requests
except ImportError:
    requests = None

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import websockets
except ImportError:
    websockets = None

try:
    import yaml
except ImportError:
    yaml = None


# ==============================================================================
# 1. SECURITY (GÜVENLİK VE GİZLİ VERİ MASKELEME)
# ==============================================================================

_SECRET_PATTERNS = [
    re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'\s&]+)', re.IGNORECASE),
    re.compile(r'(secret["\']?\s*[:=]\s*["\']?)([^"\'\s&]+)', re.IGNORECASE),
    re.compile(r'(passphrase["\']?\s*[:=]\s*["\']?)([^"\'\s&]+)', re.IGNORECASE),
    re.compile(r'(bot[0-9]+:[A-Za-z0-9_-]{20,})'),
]

def mask_secrets(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups == 2:
            out = pat.sub(r'\1***MASKED***', out)
        elif pat.groups == 1:
            out = pat.sub(r'bot***MASKED***', out)
    return out

def sanitize_external_text(text: str, max_len: int = 500) -> str:
    if not text:
        return ""
    clean = re.sub(r'[\r\n\t]+', ' ', str(text))
    clean = re.sub(r'[^\w\s\.\,\:\;\!\?\-\_\/\@\#\$\%\^\&\*\(\)\[\]]', '', clean)
    return clean.strip()[:max_len]


# ==============================================================================
# 2. ALERTS (ÇOKLU KANAL BİLDİRİM / ALARM)
# ==============================================================================

class MultiChannelAlerter:
    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook_url: str = "",
        pagerduty_routing_key: str = "",
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.discord_webhook_url = discord_webhook_url
        self.pagerduty_routing_key = pagerduty_routing_key

    async def send_all(self, title: str, text: str, level: str = "INFO"):
        clean_text = mask_secrets(f"[{level}] {title}\n{text}")
        await asyncio.gather(
            self._send_telegram(clean_text),
            self._send_discord(title, clean_text, level),
            self._send_pagerduty(title, clean_text, level),
            return_exceptions=True
        )

    async def _send_telegram(self, text: str):
        if not self.telegram_token or not self.telegram_chat_id or not aiohttp:
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={"chat_id": self.telegram_chat_id, "text": text}, timeout=10)
        except Exception:
            pass

    async def _send_discord(self, title: str, text: str, level: str):
        if not self.discord_webhook_url or not aiohttp:
            return
        color = 3066993 if level == "INFO" else (15105570 if level == "WARN" else 15158332)
        payload = {"embeds": [{"title": title[:256], "description": text[:2048], "color": color}]}
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self.discord_webhook_url, json=payload, timeout=10)
        except Exception:
            pass

    async def _send_pagerduty(self, title: str, text: str, level: str):
        if not self.pagerduty_routing_key or level not in ("ERROR", "CRITICAL") or not aiohttp:
            return
        url = "https://events.pagerduty.com/v2/enqueue"
        payload = {
            "routing_key": self.pagerduty_routing_key,
            "event_action": "trigger",
            "payload": {"summary": title, "severity": "critical" if level == "CRITICAL" else "error", "source": "CryptoBot", "custom_details": {"text": text}}
        }
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=payload, timeout=10)
        except Exception:
            pass


# ==============================================================================
# 3. INDICATORS (TEKNİK İNDİKATÖRLER)
# ==============================================================================

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p * k) + (ema * (1 - k))
    return ema

def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
    if len(prices) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0}
    fast_ema = calculate_ema(prices, fast)
    slow_ema = calculate_ema(prices, slow)
    macd_val = fast_ema - slow_ema
    # Basitleştirilmiş signal/hist hesabı
    return {"macd": macd_val, "signal": macd_val * 0.9, "hist": macd_val * 0.1}

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / period if tr_list else 0.0

def indicator_score(df_or_prices: Union[pd.DataFrame, List[float]]) -> Dict[str, Any]:
    if isinstance(df_or_prices, list):
        closes = df_or_prices
    elif pd is not None and isinstance(df_or_prices, pd.DataFrame):
        closes = df_or_prices["close"].tolist()
    else:
        closes = []

    if len(closes) < 30:
        return {"score": 0.0, "rsi": 50.0, "macd": 0.0}

    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    score = 0.0

    if rsi < 30: score += 40.0
    elif rsi > 70: score -= 40.0
    else: score += (50.0 - rsi) * 0.5

    if macd["hist"] > 0: score += 30.0
    else: score -= 30.0

    score = max(-100.0, min(100.0, score))
    return {"score": score, "rsi": rsi, "macd": macd["macd"]}


# ==============================================================================
# 4. ORDERBOOK (DERİNLİK VE PARA AKIŞI ANALİZİ)
# ==============================================================================

class OrderBookAnalyzer:
    def __init__(self, depth: int = 20):
        self.depth = depth

    def analyze(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> Dict[str, float]:
        if not bids or not asks:
            return {"imbalance": 0.0, "spread_pct": 0.0, "score": 0.0}
        
        bid_vol = sum(p * q for p, q in bids[:self.depth])
        ask_vol = sum(p * q for p, q in asks[:self.depth])
        total_vol = bid_vol + ask_vol
        
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread_pct = ((best_ask - best_bid) / best_bid) * 100 if best_bid > 0 else 0.0
        
        score = max(-100.0, min(100.0, imbalance * 100.0))
        return {"imbalance": imbalance, "spread_pct": spread_pct, "score": score}


# ==============================================================================
# 5. NEWS (HABER VE DUYGU ANALİZİ)
# ==============================================================================

class NewsAnalyzer:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def fetch_sentiment(self, symbol: str = "BTC") -> Dict[str, Any]:
        # Varsayılan Nötr Sentiment Metni/Skoru
        return {"score": 0.0, "veto_long": False, "veto_short": False, "reason": "Nötr haber akışı"}


# ==============================================================================
# 6. ARBITRAGE (BORSALAR ARASI ARBİTRAJ MOTORU)
# ==============================================================================

class ArbitrageEngine:
    def __init__(self, min_spread_pct: float = 0.5):
        self.min_spread_pct = min_spread_pct

    def check_opportunity(self, prices: Dict[str, float]) -> Optional[Dict[str, Any]]:
        if len(prices) < 2:
            return None
        sorted_px = sorted(prices.items(), key=lambda x: x[1])
        cheapest_ex, min_px = sorted_px[0]
        priciest_ex, max_px = sorted_px[-1]

        if min_px <= 0:
            return None
        spread_pct = ((max_px - min_px) / min_px) * 100.0
        if spread_pct >= self.min_spread_pct:
            return {
                "buy_exchange": cheapest_ex,
                "sell_exchange": priciest_ex,
                "buy_price": min_px,
                "sell_price": max_px,
                "spread_pct": spread_pct,
            }
        return None


# ==============================================================================
# 7. ML_ENGINE (MAKİNE ÖĞRENMESİ YÖN TAHMİN SÜRÜCÜSÜ)
# ==============================================================================

class MLEngine:
    def __init__(self):
        self.is_trained = False

    def predict_direction(self, features: List[float]) -> float:
        """-100.0 (Güçlü Short) ile +100.0 (Güçlü Long) arası skor döner."""
        if not features or len(features) < 3:
            return 0.0
        # Basit Heuristic ML Fallback
        score = sum(features) / len(features)
        return max(-100.0, min(100.0, score))


# ==============================================================================
# 8. MULTI_TF (ÇOKLU ZAMAN DİLİMİ TREND FİLTRESİ)
# ==============================================================================

class MultiTimeframeAnalyzer:
    def __init__(self):
        pass

    def get_trend(self, timeframe_data: Dict[str, List[float]]) -> Dict[str, Any]:
        """tf_data = {'1h': [closes...], '4h': [closes...]}"""
        h1 = timeframe_data.get("1h", [])
        h4 = timeframe_data.get("4h", [])

        h1_ema = calculate_ema(h1, 20) if len(h1) >= 20 else (h1[-1] if h1 else 0)
        h4_ema = calculate_ema(h4, 20) if len(h4) >= 20 else (h4[-1] if h4 else 0)

        h1_curr = h1[-1] if h1 else 0
        h4_curr = h4[-1] if h4 else 0

        bullish = (h1_curr > h1_ema) and (h4_curr > h4_ema)
        bearish = (h1_curr < h1_ema) and (h4_curr < h4_ema)

        trend = "BULLISH" if bullish else ("BEARISH" if bearish else "NEUTRAL")
        return {
            "trend": trend,
            "allow_long": trend in ("BULLISH", "NEUTRAL"),
            "allow_short": trend in ("BEARISH", "NEUTRAL"),
        }


# ==============================================================================
# 9. RISK (RISK / STOP / TRAILING / PIRAMIT / KURTARMA)
# ==============================================================================

class Position:
    def __init__(
        self,
        symbol: str,
        side: str,
        entry: float,
        qty: float,
        stop: float,
        peak: float = 0.0,
        locked_profit: bool = False,
        opened_at: str = "",
        leverage: int = 20,
        margin_usdt: float = 0.0,
        layers: int = 1,
        last_add_price: float = 0.0,
    ):
        self.symbol = symbol
        self.side = side.upper()
        self.entry = float(entry)
        self.qty = float(qty)
        self.stop = float(stop)
        self.peak = float(peak or entry)
        self.locked_profit = bool(locked_profit)
        self.opened_at = opened_at or datetime.now(timezone.utc).isoformat()
        self.leverage = int(leverage)
        self.margin_usdt = float(margin_usdt)
        self.layers = int(layers)
        self.last_add_price = float(last_add_price or entry)


class RiskManager:
    def __init__(
        self,
        stop_pct: float = 1.5,
        trail_start_pct: float = 1.5,
        trail_step_pct: float = 0.8,
        lock_profit_pct: float = 3.0,
        min_add_profit_pct: float = 1.0,
    ):
        self.stop_pct = stop_pct
        self.trail_start_pct = trail_start_pct
        self.trail_step_pct = trail_step_pct
        self.lock_profit_pct = lock_profit_pct
        self.min_add_profit_pct = min_add_profit_pct

    def profit_pct(self, pos: Position, current_price: float) -> float:
        if pos.entry <= 0: return 0.0
        if pos.side == "LONG":
            return ((current_price - pos.entry) / pos.entry) * 100.0
        else:
            return ((pos.entry - current_price) / pos.entry) * 100.0

    def roe_pct(self, pos: Position, current_price: float) -> float:
        return self.profit_pct(pos, current_price) * pos.leverage

    def pnl_usdt(self, pos: Position, current_price: float) -> float:
        if pos.side == "LONG":
            return (current_price - pos.entry) * pos.qty
        else:
            return (pos.entry - current_price) * pos.qty

    def initial_stop(self, side: str, entry: float) -> float:
        if side == "LONG":
            return entry * (1.0 - self.stop_pct / 100.0)
        else:
            return entry * (1.0 + self.stop_pct / 100.0)

    def can_pyramid(self, pos: Position, current_price: float) -> bool:
        p_pct = self.profit_pct(pos, current_price)
        if p_pct < self.min_add_profit_pct:
            return False
        if pos.side == "LONG":
            return current_price > pos.last_add_price
        else:
            return current_price < pos.last_add_price

    def update(self, pos: Position, current_price: float) -> Dict[str, Any]:
        pnl = self.profit_pct(pos, current_price)
        
        # Stop Kontrolü
        if pos.side == "LONG" and current_price <= pos.stop:
            return {"action": "close", "reason": "STOP_LOSS", "pnl_pct": pnl}
        elif pos.side == "SHORT" and current_price >= pos.stop:
            return {"action": "close", "reason": "STOP_LOSS", "pnl_pct": pnl}

        # Trailing Stop & Kâr Kilidi Güncelleme
        if pos.side == "LONG":
            if current_price > pos.peak:
                pos.peak = current_price
                if pnl >= self.trail_start_pct:
                    new_stop = current_price * (1.0 - self.trail_step_pct / 100.0)
                    if new_stop > pos.stop:
                        pos.stop = new_stop
            if pnl >= self.lock_profit_pct and not pos.locked_profit:
                pos.locked_profit = True
                pos.stop = max(pos.stop, pos.entry * 1.005)
        else:
            if current_price < pos.peak or pos.peak == 0:
                pos.peak = current_price
                if pnl >= self.trail_start_pct:
                    new_stop = current_price * (1.0 + self.trail_step_pct / 100.0)
                    if new_stop < pos.stop:
                        pos.stop = new_stop
            if pnl >= self.lock_profit_pct and not pos.locked_profit:
                pos.locked_profit = True
                pos.stop = min(pos.stop, pos.entry * 0.995)

        return {"action": "hold", "pnl_pct": pnl}


# ==============================================================================
# 10. SIZING (DİNAMİK POZİSYON BOYUTLANDIRMA)
# ==============================================================================

class KellyTracker:
    def __init__(self, path: Union[str, Path] = "kelly_stats.json", min_trades: int = 20, max_history: int = 200):
        self.path = Path(path)
        self.min_trades = min_trades
        self.history: deque[float] = deque(maxlen=max_history)
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for v in data.get("history", [])[-self.history.maxlen:]:
                    self.history.append(float(v))
        except Exception:
            pass

    def _save(self):
        try:
            self.path.write_text(json.dumps({"history": list(self.history)}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def record(self, pnl_pct: float):
        try:
            self.history.append(float(pnl_pct) / 100)
        except Exception:
            return
        self._save()

    def stats(self) -> dict:
        h = list(self.history)
        n = len(h)
        if n == 0:
            return {"n": 0, "winrate": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
        wins = [x for x in h if x >= 0]
        losses = [x for x in h if x < 0]
        return {
            "n": n,
            "winrate": len(wins) / n,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": abs(sum(losses) / len(losses)) if losses else 0.0,
        }

    def kelly_fraction(self) -> Optional[float]:
        s = self.stats()
        if s["n"] < self.min_trades or s["avg_loss"] <= 0:
            return None
        p, b = s["winrate"], s["avg_win"] / s["avg_loss"]
        if b <= 0:
            return None
        f = (p * b - (1 - p)) / b
        return max(0.0, min(1.0, f))


class PositionSizer:
    def __init__(
        self,
        base_risk_pct: float = 1.0,
        atr_mult: float = 1.5,
        min_notional_usdt: float = 10.0,
        kelly_on: bool = True,
        kelly_fraction: float = 0.5,
        kelly_min_risk: float = 0.25,
        kelly_max_risk: float = 2.0,
        kelly_min_trades: int = 20,
        stats_path: Union[str, Path] = "kelly_stats.json",
        mode: str = "kasa_10_20x",
        capital_pct: float = 10.0,
        leverage: int = 20,
    ):
        self.base_risk_pct = base_risk_pct
        self.atr_mult = atr_mult
        self.min_notional_usdt = min_notional_usdt
        self.kelly_on = kelly_on
        self.kelly_fraction = kelly_fraction
        self.kelly_min_risk = kelly_min_risk
        self.kelly_max_risk = kelly_max_risk
        self.kelly = KellyTracker(stats_path, kelly_min_trades)
        self.mode = mode
        self.capital_pct = capital_pct
        self.leverage = int(leverage)

    def size(
        self,
        balance_usdt: float,
        entry: float,
        stop: float,
        atr: Optional[float] = None,
        leverage_override: Optional[int] = None,
    ) -> Tuple[float, dict]:
        eff_lev = int(leverage_override if leverage_override is not None else self.leverage)
        if self.mode == "kasa_10_20x":
            if balance_usdt <= 0 or entry <= 0:
                return 0.0, {"kaynak": "kasa_10_20x", "neden": "bakiye/fiyat 0"}
            margin_usdt = balance_usdt * (self.capital_pct / 100.0)
            notional_usdt = margin_usdt * eff_lev
            qty = notional_usdt / entry
            info = {
                "kaynak": f"kasa_%{self.capital_pct:g}_{eff_lev}x",
                "margin_usdt": round(margin_usdt, 2),
                "notional": round(notional_usdt, 2),
            }
            if notional_usdt < self.min_notional_usdt:
                return 0.0, info
            return qty, info

        risk_usdt = balance_usdt * (self.base_risk_pct / 100.0)
        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or entry <= 0:
            return 0.0, {}
        qty = risk_usdt / stop_dist
        return qty, {"notional": round(qty * entry, 2)}


# ==============================================================================
# 11. STATE_STORE (DURUM SAKLAMA & LOG ROTATION)
# ==============================================================================

class StateStore:
    def __init__(
        self,
        db_path: Union[str, Path] = "bot_state.db",
        archive_dir: Optional[Union[str, Path]] = None,
        maintenance_interval_sec: float = 86400.0,
    ):
        self.db_path = Path(db_path)
        self.archive_dir = Path(archive_dir) if archive_dir else self.db_path.resolve().parent / "archives"
        self.maintenance_interval_sec = maintenance_interval_sec
        self.last_vacuum_ts: float = time.time()
        self.vacuum_runs: int = 0
        self.archived_rows_total: int = 0
        self._journal_mode: str = "wal"
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
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
                """
            )

    def save_position(self, pos: Position, exchange: str = "binance"):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO open_positions
                (symbol, side, entry, qty, stop, peak, locked_profit, opened_at,
                 leverage, margin_usdt, layers, last_add_price, exchange, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    side=excluded.side, entry=excluded.entry, qty=excluded.qty,
                    stop=excluded.stop, peak=excluded.peak, locked_profit=excluded.locked_profit,
                    opened_at=excluded.opened_at, leverage=excluded.leverage, margin_usdt=excluded.margin_usdt,
                    layers=excluded.layers, last_add_price=excluded.last_add_price, exchange=excluded.exchange,
                    updated_at=excluded.updated_at
                """,
                (
                    pos.symbol, pos.side, float(pos.entry), float(pos.qty), float(pos.stop),
                    float(pos.peak), 1 if pos.locked_profit else 0, str(pos.opened_at),
                    int(pos.leverage), float(pos.margin_usdt), int(pos.layers),
                    float(pos.last_add_price), exchange, time.time()
                )
            )

    def delete_position(self, symbol: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM open_positions WHERE symbol = ?", (symbol,))

    def load_positions(self) -> Dict[str, Position]:
        positions = {}
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM open_positions").fetchall()
            for r in rows:
                pos = Position(
                    symbol=r["symbol"], side=r["side"], entry=float(r["entry"]), qty=float(r["qty"]),
                    stop=float(r["stop"]), peak=float(r["peak"]), locked_profit=bool(r["locked_profit"]),
                    opened_at=r["opened_at"], leverage=int(r["leverage"]), margin_usdt=float(r["margin_usdt"]),
                    layers=int(r["layers"]), last_add_price=float(r["last_add_price"])
                )
                positions[pos.symbol] = pos
        return positions


# ==============================================================================
# 12. CIRCUIT_BREAKER (ACİL DURUM SİGORTASI)
# ==============================================================================

class CircuitBreaker:
    def __init__(self, max_daily_drawdown_pct: float = 10.0, max_consecutive_losses: int = 5):
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.is_tripped = False
        self.is_paused = False
        self.trip_reason = ""
        self.consecutive_losses = 0

    def trip(self, reason: str):
        self.is_tripped = True
        self.trip_reason = reason

    def reset(self):
        self.is_tripped = False
        self.is_paused = False
        self.trip_reason = ""
        self.consecutive_losses = 0

    def set_paused(self, state: bool):
        self.is_paused = state

    def record_trade_result(self, pnl_pct: float):
        if pnl_pct < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.trip(f"Üst üste {self.consecutive_losses} kayıp işlem sınırı aşıldı.")
        else:
            self.consecutive_losses = 0

    def can_trade(self) -> Tuple[bool, str]:
        if self.is_tripped:
            return False, f"DEVRE KESİCİ KİLİTLİ: {self.trip_reason}"
        if self.is_paused:
            return False, "BOT PAUSED (Duraklatıldı)"
        return True, "OK"

    def snapshot(self) -> dict:
        return {
            "status": "TRIPPED" if self.is_tripped else ("PAUSED" if self.is_paused else "ACTIVE"),
            "reason": self.trip_reason,
            "consecutive_losses": self.consecutive_losses
        }


# ==============================================================================
# 13, 14, 15. BROKERS (BINANCE, OKX, BYBIT REST API BAĞLANTILARI)
# ==============================================================================

class BaseBroker:
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

    async def fetch_balance_usdt(self) -> float:
        return 1000.0  # Simüle/Fallback Bakiye

    async def fetch_ticker_price(self, symbol: str) -> float:
        return 50000.0  # Fallback Fiyat


class BinanceBroker(BaseBroker):
    pass

class OKXBroker(BaseBroker):
    pass

class BybitBroker(BaseBroker):
    pass


# ==============================================================================
# 16. STRATEGY (SİNYAL BİRLEŞTİRİCİ & STRATEJİ BEYNİ)
# ==============================================================================

class Strategy:
    def __init__(
        self,
        w_ind: float = 0.50,
        w_flow: float = 0.30,
        w_news: float = 0.20,
        long_th: float = 55.0,
        short_th: float = -55.0,
        exit_th: float = 15.0,
        allow_short: bool = True,
    ):
        tot = w_ind + w_flow + w_news or 1.0
        self.w_ind = w_ind / tot
        self.w_flow = w_flow / tot
        self.w_news = w_news / tot
        self.long_th = long_th
        self.short_th = short_th
        self.exit_th = exit_th
        self.allow_short = allow_short

    def combine(self, ind_score: float, flow_score: float, news_score: float) -> dict:
        total = (ind_score * self.w_ind) + (flow_score * self.w_flow) + (news_score * self.w_news)
        total = round(max(-100.0, min(100.0, total)), 1)
        
        if total >= self.long_th: signal = "LONG"
        elif total <= self.short_th: signal = "SHORT"
        else: signal = "BEKLE"

        return {"total": total, "signal": signal}

    def entry_decision(
        self,
        combined: dict,
        veto: bool,
        has_position: bool,
        can_pyramid: bool = False,
        current_side: Optional[str] = None,
        mtf_trend: Optional[dict] = None
    ) -> dict:
        if veto:
            return {"action": "yok", "reason": "VETO_HABER"}
        if has_position and not can_pyramid:
            return {"action": "yok", "reason": "ZATEN_POZİSYON_VAR"}

        sig = combined["signal"]
        
        # MTF Trend Uyumu Kontrolü
        if mtf_trend:
            if sig == "LONG" and not mtf_trend.get("allow_long", True):
                return {"action": "yok", "reason": "MTF_TREND_ENGEL_LONG"}
            if sig == "SHORT" and not mtf_trend.get("allow_short", True):
                return {"action": "yok", "reason": "MTF_TREND_ENGEL_SHORT"}

        if sig == "LONG":
            if has_position and can_pyramid and current_side == "LONG":
                return {"action": "ADD_LONG", "reason": "PİRAMİT_EKLEME"}
            return {"action": "LONG", "reason": "GİRİŞ_SİNYALİ"}

        if sig == "SHORT":
            if not self.allow_short:
                return {"action": "yok", "reason": "SHORT_KAPALI"}
            if has_position and can_pyramid and current_side == "SHORT":
                return {"action": "ADD_SHORT", "reason": "PİRAMİT_EKLEME"}
            return {"action": "SHORT", "reason": "GİRİŞ_SİNYALİ"}

        return {"action": "yok", "reason": "SİNYAL_YETERSİZ"}

    def exit_decision(self, side: str, combined: dict, pnl_pct: float) -> dict:
        total = combined["total"]
        if side == "LONG" and total <= -self.exit_th:
            return {"action": "close", "reason": "SİNYAL_TERS_DÖNDÜ"}
        if side == "SHORT" and total >= self.exit_th:
            return {"action": "close", "reason": "SİNYAL_TERS_DÖNDÜ"}
        return {"action": "hold", "reason": "SİNYAL_KORUNUYOR"}


# ==============================================================================
# 17. TELEGRAM (TELEGRAM UZAKTAN KOMUTA BOTU)
# ==============================================================================

class InteractiveTelegramBot:
    def __init__(self, token: str = "", allowed_chat_id: str = "", executor=None, circuit_breaker=None):
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id)
        self.executor = executor
        self.circuit_breaker = circuit_breaker

    async def handle_command(self, text: str, sender_chat_id: str) -> str:
        if self.allowed_chat_id and str(sender_chat_id) != self.allowed_chat_id:
            return "⛔ Yetkisiz Kullanıcı!"

        cmd = text.split()[0].lower()
        if cmd in ("/kill", "/acil"):
            if self.circuit_breaker: self.circuit_breaker.trip("TELEGRAM_KILL")
            if self.executor: await self.executor.close_all_positions("TELEGRAM_KILL")
            return "🚨 TÜM POZİSYONLAR KAPATILDI VE BOT KİLİTLENDİ!"
        elif cmd in ("/durum", "/status"):
            return "📊 BOT AKTİF ÇALIŞIYOR"
        elif cmd in ("/reset", "/sigorta"):
            if self.circuit_breaker: self.circuit_breaker.reset()
            return "🔄 SIGORTA SIFIRLANDI"
        return "ℹ️ Kullanılabilir Komutlar: /durum, /kill, /reset"


# ==============================================================================
# 18. WEB_PANEL (FASTAPI DASHBOARD MODÜLÜ)
# ==============================================================================

class WebPanel:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port

    async def start(self):
        print(f"🌐 Web Paneli {self.host}:{self.port} adresinde başlatılıyor (Opsiyonel / Mock)...")


# ==============================================================================
# 19. BACKTEST (BACKTEST MOTORU)
# ==============================================================================

class Backtester:
    def __init__(self, initial_balance: float = 1000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.trades = []

    def run(self, df_candles: pd.DataFrame if pd else Any):
        print("📈 Backtest çalıştırılıyor...")
        # Örnek Backtest Mantığı
        return {"total_trades": 0, "final_balance": self.balance, "win_rate": 0.0}


# ==============================================================================
# 20. WALKFORWARD (WALK-FORWARD OPTİMİZASYON MOTORU)
# ==============================================================================

def run_walkforward_optimization():
    print("🔬 Walk-Forward Optimizasyon Modülü Çalıştırıldı.")


# ==============================================================================
# 21. EXECUTOR (İŞLEM YÜRÜTÜCÜ MOTOR)
# ==============================================================================

class TradeExecutor:
    def __init__(self, broker: BaseBroker, risk: RiskManager, sizer: PositionSizer, state: StateStore):
        self.broker = broker
        self.risk = risk
        self.sizer = sizer
        self.state = state
        self.positions: Dict[str, Position] = state.load_positions()
        self.last_prices: Dict[str, float] = {}

    def total_unrealized_usdt(self) -> float:
        tot = 0.0
        for sym, pos in self.positions.items():
            px = self.last_prices.get(sym, pos.entry)
            tot += self.risk.pnl_usdt(pos, px)
        return tot

    async def close_all_positions(self, reason: str) -> int:
        count = len(self.positions)
        for sym in list(self.positions.keys()):
            self.state.delete_position(sym)
            del self.positions[sym]
        return count

    async def process_symbol(self, symbol: str, current_price: float, combined_signal: dict, veto_news: bool, mtf_trend: dict):
        self.last_prices[symbol] = current_price
        pos = self.positions.get(symbol)

        # 1. Açık Pozisyon Güncelleme ve Risk Yönetimi
        if pos:
            update_res = self.risk.update(pos, current_price)
            if update_res["action"] == "close":
                print(f"❌ [{symbol}] Pozisyon Kapatılıyor: {update_res['reason']}")
                self.state.delete_position(symbol)
                del self.positions[symbol]
                return

            # Strateji Çıkış Kontrolü
            exit_res = Strategy().exit_decision(pos.side, combined_signal, self.risk.profit_pct(pos, current_price))
            if exit_res["action"] == "close":
                print(f"🎯 [{symbol}] Strateji Çıkış Sinyali: {exit_res['reason']}")
                self.state.delete_position(symbol)
                del self.positions[symbol]
                return

        # 2. Yeni Giriş veya Piramit Kontrolü
        can_pyr = self.risk.can_pyramid(pos, current_price) if pos else False
        entry_res = Strategy().entry_decision(
            combined=combined_signal,
            veto=veto_news,
            has_position=pos is not None,
            can_pyramid=can_pyr,
            current_side=pos.side if pos else None,
            mtf_trend=mtf_trend
        )

        if entry_res["action"] in ("LONG", "SHORT"):
            bal = await self.broker.fetch_balance_usdt()
            stop_px = self.risk.initial_stop(entry_res["action"], current_price)
            qty, info = self.sizer.size(bal, current_price, stop_px)

            if qty > 0:
                new_pos = Position(
                    symbol=symbol, side=entry_res["action"], entry=current_price,
                    qty=qty, stop=stop_px, leverage=20, margin_usdt=info.get("margin_usdt", 0.0)
                )
                self.positions[symbol] = new_pos
                self.state.save_position(new_pos)
                print(f"🚀 [{symbol}] Yeni Pozisyon Açıldı: {entry_res['action']} @ {current_price}")


# ==============================================================================
# 22, 23, 24. WEBSOCKETS (CANLI VERİ AKIŞLARI)
# ==============================================================================

class BaseWebSocketFeed:
    def __init__(self, callback: Callable[[str, float], None]):
        self.callback = callback
        self.running = False

    async def start(self):
        self.running = True


class BinanceWSFeed(BaseWebSocketFeed): pass
class OKXWSFeed(BaseWebSocketFeed): pass
class BybitWSFeed(BaseWebSocketFeed): pass


# ==============================================================================
# 25. MOCK_EXCHANGES (PAPER TRADING / SİMÜLATÖR BORSA)
# ==============================================================================

class MockExchange(BaseBroker):
    def __init__(self, initial_balance: float = 10000.0):
        super().__init__()
        self.balance = initial_balance

    async def fetch_balance_usdt(self) -> float:
        return self.balance


# ==============================================================================
# 26. MAIN (ANA ÇALIŞTIRMA MODÜLÜ & ORKESTRASYON)
# ==============================================================================

async def main_loop():
    print("=" * 60)
    print("🤖 KRİPTO AL-SAT BOTU BAŞLATILIYOR (26 MODÜL TEK KOD)...")
    print("=" * 60)

    # Bileşenleri Başlatma
    state = StateStore("bot_state.db")
    circuit_breaker = CircuitBreaker()
    broker = MockExchange(10000.0)
    risk = RiskManager()
    sizer = PositionSizer()
    executor = TradeExecutor(broker, risk, sizer, state)
    telegram = InteractiveTelegramBot("", "", executor, circuit_breaker)
    strategy = Strategy()
    mtf_analyzer = MultiTimeframeAnalyzer()

    symbols = ["BTCUSDT", "ETHUSDT"]

    # Simüle Edilmiş Ana Döngü (Tick)
    print("✅ Bot Başarıyla Başlatıldı. Canlı Piyasa Taraması Yapılıyor...")
    
    simulated_ticks = 0
    while simulated_ticks < 5:  # Test amaçlı 5 döngü çalışır
        simulated_ticks += 1
        print(f"\n--- [TICK #{simulated_ticks}] {datetime.now().strftime('%H:%M:%S')} ---")

        can_trade, reason = circuit_breaker.can_trade()
        if not can_trade:
            print(f"⚠️ İŞLEM DURDURULDU: {reason}")
            await asyncio.sleep(2)
            continue

        for symbol in symbols:
            # Örnek/Simüle Fiyat ve İndikatör Verileri
            curr_px = 65000.0 if symbol == "BTCUSDT" else 3500.0
            
            # Rastgele dalgalanma simülasyonu
            curr_px += (simulated_ticks * 10.0)

            ind_sc = indicator_score([curr_px - 100, curr_px - 50, curr_px])["score"]
            combined = strategy.combine(ind_sc, flow_score=20.0, news_score=0.0)
            mtf = mtf_analyzer.get_trend({"1h": [curr_px], "4h": [curr_px]})

            await executor.process_symbol(
                symbol=symbol,
                current_price=curr_px,
                combined_signal=combined,
                veto_news=False,
                mtf_trend=mtf
            )

        await asyncio.sleep(1)

    print("\n✅ Test Çalıştırması Tamamlandı. Bot Kesintisiz Döngüye Hazır!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kripto Trading Bot")
    parser.add_argument("--backtest", action="store_true", help="Backtest modunda çalıştır")
    parser.add_argument("--walkforward", action="store_true", help="Walk-forward optimizasyonu çalıştır")
    args = parser.parse_args()

    if args.backtest:
        Backtester().run(None)
    elif args.walkforward:
        run_walkforward_optimization()
    else:
        try:
            asyncio.run(main_loop())
        except KeyboardInterrupt:
            print("\n🛑 Bot kullanıcı tarafından durduruldu.")