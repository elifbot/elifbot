"""Paper signal confirmation: 1h/4h trend, same-venue derivatives and real taker CVD.

Only public HTTPS GET endpoints are used. Every cache/history key includes the
venue; Binance and OKX data, prices, OI, flows, or paper balances are never
combined. Missing or stale confirmation data is represented as unavailable and
fails closed for the enhanced entry path.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

import aiohttp
import pandas as pd

from config import PUBLIC_BINANCE_FAPI_BASE, PUBLIC_OKX_API_BASE
from data.feed_utils import ensure_url_allowed
from indicators.core import adx, ema, macd, rsi_wilder


BINANCE_PUBLIC_BASE = PUBLIC_BINANCE_FAPI_BASE
OKX_BASE = PUBLIC_OKX_API_BASE
MTF_TTL_SEC = 300.0
DERIVATIVES_TTL_SEC = 30.0
MTF_LIMIT = 200
FLOW_MIN_USD = 1_000.0
FLOW_MIN_TRADES = 3
FLOW_MAX_AGE_MS = 15_000
FLOW_IMBALANCE_RATIO = 1.25
FUNDING_CROWD_THRESHOLD = 0.0005
# Local/venue clock skew and candle publication delay guard. The latest HTF
# candle is not considered until two minutes after its nominal close.
MTF_CLOSE_SAFETY_MS = 120_000
PUBLIC_API_MIN_INTERVAL_SEC = 0.25
MAX_SIGNAL_DECISION_AGE_MS = 10_000


@dataclass(frozen=True)
class FlowConfirmation:
    accepted: bool
    reason: str
    cvd15_usd: float | None
    cvd60_usd: float | None
    taker_buy_sell_ratio: float | None
    total15_usd: float | None
    trades15: int
    age_ms: int | None


def _finite(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(obj: Any, name: str, default: float = 0.0) -> float:
    value = _finite(getattr(obj, name, None))
    return default if value is None else value


def _duration_ms(interval: str) -> int:
    return {"1h": 3_600_000, "4h": 14_400_000}[interval]


def _okx_bar(interval: str) -> str:
    return {"1h": "1H", "4h": "4H"}[interval]


def normalize_closed_candles(
    exchange: str,
    interval: str,
    rows: Any,
    asof_ms: int,
) -> pd.DataFrame:
    """Validate, de-duplicate and return only the latest continuous closed suffix."""
    if exchange not in ("binance", "okx") or interval not in ("1h", "4h"):
        raise ValueError("desteklenmeyen MTF venue/timeframe")
    if not isinstance(rows, list):
        raise ValueError("MTF mum yanıtı liste değil")
    duration = _duration_ms(interval)
    parsed: dict[int, tuple[int, float, float, float, float]] = {}
    for row in rows:
        try:
            if exchange == "binance":
                ts = int(row[0])
                o, h, low, close = (float(row[i]) for i in (1, 2, 3, 4))
                closed = int(row[6]) < asof_ms and ts + duration <= asof_ms
            else:
                if len(row) < 9 or str(row[8]) != "1":
                    continue
                ts = int(row[0])
                o, h, low, close = (float(row[i]) for i in (1, 2, 3, 4))
                closed = ts + duration <= asof_ms
        except (TypeError, ValueError, IndexError, OverflowError):
            # Malformed API rows are ignored; semantic duplicate conflicts below
            # are not parse errors and must fail the whole MTF snapshot.
            continue
        values = (o, h, low, close)
        if (ts < 0 or ts % duration != 0 or not closed
                or not all(math.isfinite(v) and v > 0 for v in values)
                or h < max(o, close, low) or low > min(o, close, h)):
            continue
        item = (ts, o, h, low, close)
        if ts in parsed and parsed[ts] != item:
            raise ValueError("aynı MTF mum zamanı için çakışan satırlar")
        parsed[ts] = item
    ordered = sorted(parsed.values())
    suffix: list[tuple[int, float, float, float, float]] = []
    for row in reversed(ordered):
        if suffix and suffix[-1][0] - row[0] != duration:
            break
        suffix.append(row)
    suffix.reverse()
    if not suffix:
        raise ValueError(f"{interval} kapalı mum verisi yok")
    expected_last = (asof_ms // duration) * duration - duration
    if suffix[-1][0] != expected_last:
        raise ValueError(f"{interval} son kapalı mumu güncel değil")
    if len(suffix) < 50:
        raise ValueError(f"{interval} MTF geçmişi yetersiz ({len(suffix)}<50)")
    return pd.DataFrame(suffix, columns=("open_time", "open", "high", "low", "close"))


def compute_htf_trend(frame: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    """v7.8'nin EMA/RSI/MACD/ADX tabanlı HTF skorunun pandas uyarlaması."""
    if timeframe not in ("1h", "4h") or frame is None or len(frame) < 50:
        raise ValueError("MTF trend için yetersiz veri")
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    price = float(close.iloc[-1])
    n = len(close)
    e20_s = ema(close, min(20, max(5, n // 3)))
    e50_s = ema(close, min(50, max(10, n // 2)))
    e200_s = ema(close, min(200, n))
    e20 = _finite(e20_s.iloc[-1])
    e50 = _finite(e50_s.iloc[-1])
    e200 = _finite(e200_s.iloc[-1])
    rsi_v = _finite(rsi_wilder(close, 14).iloc[-1])
    macd_frame = macd(close)
    macd_hist = _finite(macd_frame["macd_hist"].iloc[-1])
    adx_frame = adx(pd.DataFrame({"high": high, "low": low, "close": close}))
    adx_v = _finite(adx_frame["adx"].iloc[-1])
    plus_di = _finite(adx_frame["plus_di"].iloc[-1])
    minus_di = _finite(adx_frame["minus_di"].iloc[-1])
    if any(value is None for value in (e20, e50, e200, rsi_v, macd_hist, adx_v, plus_di, minus_di)):
        raise ValueError("MTF göstergeleri ısınmadı")

    score = 0.0
    if price > e20 > e50:
        score += 30.0
    elif price < e20 < e50:
        score -= 30.0
    else:
        score += 12.0 if price > e50 else -12.0
    score += 10.0 if price > e200 else (-10.0 if price < e200 else 0.0)
    lookback = min(5, len(e20_s) - 1)
    if lookback >= 1:
        previous = _finite(e20_s.iloc[-1 - lookback])
        if previous is not None and previous > 0:
            slope_pct = (e20 - previous) / previous * 100.0
            score += 15.0 if slope_pct > 0.15 else (-15.0 if slope_pct < -0.15 else 0.0)
    score += 15.0 if macd_hist > 0 else (-15.0 if macd_hist < 0 else 0.0)
    if adx_v >= 18:
        score += 15.0 if plus_di > minus_di else -15.0
    score += 15.0 if rsi_v >= 55 else (-15.0 if rsi_v <= 45 else 0.0)
    score = round(max(-100.0, min(100.0, score)), 1)
    trend = "UP" if score >= 15.0 else ("DOWN" if score <= -15.0 else "NEUTRAL")
    return {
        "timeframe": timeframe,
        "trend": trend,
        "score": score,
        "ema20": round(e20, 8),
        "ema50": round(e50, 8),
        "ema200": round(e200, 8),
        "rsi": round(rsi_v, 3),
        "adx": round(adx_v, 3),
    }


def combine_mtf(trend_1h: dict[str, Any], trend_4h: dict[str, Any]) -> dict[str, Any]:
    """v7.8 weighting: 1h 45%, 4h 55%; strong opposing trend blocks the side."""
    score = round(float(trend_1h["score"]) * 0.45 + float(trend_4h["score"]) * 0.55, 1)
    if score <= -15.0:
        trend, allow_long, allow_short = "BEARISH", False, True
    elif score >= 15.0:
        trend, allow_long, allow_short = "BULLISH", True, False
    else:
        trend, allow_long, allow_short = "NEUTRAL", True, True
    return {
        "available": True,
        "score": score,
        "trend": trend,
        "allow_long": allow_long,
        "allow_short": allow_short,
        "1h": trend_1h,
        "4h": trend_4h,
        "reason": "" if trend == "NEUTRAL" else f"{trend.lower()} MTF trend",
    }


def flow_confirmation(flow_book: Any, exchange: str, symbol: str, now_ms: int,
                      side: str, *, min_usd: float = FLOW_MIN_USD,
                      min_trades: int = FLOW_MIN_TRADES,
                      max_age_ms: int = FLOW_MAX_AGE_MS,
                      ratio: float = FLOW_IMBALANCE_RATIO) -> FlowConfirmation:
    """Require recent real trades, directional taker imbalance and CVD."""
    direction = 1 if side == "LONG" else -1 if side == "SHORT" else 0
    if direction == 0 or flow_book is None:
        return FlowConfirmation(False, "orderflow_unavailable", None, None, None, None, 0, None)
    f15 = flow_book.anlik(exchange, symbol, now_ms, 15)
    f60 = flow_book.anlik(exchange, symbol, now_ms, 60)
    age = getattr(f15, "son_islem_yas_ms", None)
    if not f15.hazir or age is None or age > max_age_ms:
        return FlowConfirmation(False, "orderflow_stale_or_empty", None,
                                f60.cvd_usd if f60.hazir else None, None,
                                f15.toplam_usd if f15.hazir else None,
                                int(f15.islem_adedi), age)
    buy = float(f15.alis_usd)
    sell = float(f15.satis_usd)
    total = float(f15.toplam_usd)
    cvd = float(f15.cvd_usd)
    directional = buy if direction > 0 else sell
    opposite = sell if direction > 0 else buy
    directed_ratio = directional / opposite if opposite > 0 else (math.inf if directional > 0 else 0.0)
    reason = ""
    if int(f15.islem_adedi) < min_trades:
        reason = "orderflow_trade_count_low"
    elif total < min_usd:
        reason = "orderflow_notional_low"
    elif cvd * direction <= 0:
        reason = "cvd_opposes_entry"
    elif directed_ratio < ratio:
        reason = "taker_imbalance_weak"
    elif f60.hazir and float(f60.cvd_usd) * direction < -min_usd:
        reason = "cvd_60s_opposes_entry"
    return FlowConfirmation(
        not bool(reason), reason, cvd, float(f60.cvd_usd) if f60.hazir else None,
        directed_ratio if math.isfinite(directed_ratio) else None, total,
        int(f15.islem_adedi), age,
    )


class SignalEnricher:
    """Bounded, cached public-data enrichment for one (venue, symbol) candidate."""

    def __init__(self, *, mtf_ttl_sec: float = MTF_TTL_SEC,
                 derivatives_ttl_sec: float = DERIVATIVES_TTL_SEC,
                 concurrency: int = 4,
                 mtf_close_safety_ms: int = MTF_CLOSE_SAFETY_MS):
        self.mtf_ttl_sec = max(30.0, float(mtf_ttl_sec))
        self.mtf_close_safety_ms = max(0, int(mtf_close_safety_ms))
        self.derivatives_ttl_sec = max(5.0, float(derivatives_ttl_sec))
        self._semaphore = asyncio.Semaphore(max(1, int(concurrency)))
        self._venue_locks: dict[str, asyncio.Lock] = {}
        self._venue_next_request: dict[str, float] = {}
        self._key_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._mtf_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._derivatives_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._oi_previous: dict[tuple[str, str], tuple[float, float, float]] = {}
        self.fetch_errors = 0
        self.fetch_calls = 0
        self.cache_hits = 0
        self.last_error: str | None = None

    async def _json(self, session, url: str, params: dict[str, Any], exchange: str) -> Any:
        ensure_url_allowed(url)
        lock = self._venue_locks.setdefault(exchange, asyncio.Lock())
        async with lock:
            wait = max(0.0, self._venue_next_request.get(exchange, 0.0) - time.monotonic())
            if wait:
                await asyncio.sleep(wait)
            self._venue_next_request[exchange] = (
                time.monotonic() + PUBLIC_API_MIN_INTERVAL_SEC
            )
            async with self._semaphore:
                self.fetch_calls += 1
                timeout = aiohttp.ClientTimeout(total=8)
                async with session.get(url, params=params, timeout=timeout,
                                       allow_redirects=False) as response:
                    response.raise_for_status()
                    body = await response.json(content_type=None)
        return body

    def _key_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        return self._key_locks.setdefault(key, asyncio.Lock())

    async def _mtf(self, session, exchange: str, symbol: str, now_ms: int,
                   binance_base: str) -> dict[str, Any]:
        key = (exchange, symbol)
        cached = self._mtf_cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < self.mtf_ttl_sec:
            self.cache_hits += 1
            return cached[1]
        async with self._key_lock(key):
            cached = self._mtf_cache.get(key)
            now = time.monotonic()
            if cached and now - cached[0] < self.mtf_ttl_sec:
                self.cache_hits += 1
                return cached[1]
            trends = {}
            # Eski kapalı HTF mumu seçerek yerel/venue saat farkı veya mum
            # yayın gecikmesinin kapanmamış mum sızıntısı yaratmasını önle.
            mtf_asof_ms = max(0, int(now_ms) - self.mtf_close_safety_ms)
            for interval in ("1h", "4h"):
                if exchange == "binance":
                    url = f"{binance_base.rstrip('/')}/klines"
                    params = {"symbol": symbol, "interval": interval,
                              "limit": MTF_LIMIT, "endTime": mtf_asof_ms - 1}
                elif exchange == "okx":
                    url = f"{OKX_BASE}/market/candles"
                    params = {"instId": symbol, "bar": _okx_bar(interval), "limit": str(MTF_LIMIT)}
                else:
                    raise ValueError("desteklenmeyen MTF venue")
                rows = await self._json(session, url, params, exchange)
                if exchange == "okx":
                    if (not isinstance(rows, dict) or rows.get("code") != "0"
                            or not isinstance(rows.get("data"), list)):
                        raise ValueError(f"OKX {interval} MTF yanıtı geçersiz")
                    rows = rows["data"]
                frame = normalize_closed_candles(exchange, interval, rows, mtf_asof_ms)
                trends[interval] = compute_htf_trend(frame, interval)
            result = combine_mtf(trends["1h"], trends["4h"])
            self._mtf_cache[key] = (time.monotonic(), result)
            return result

    async def _derivatives(self, session, exchange: str, symbol: str, price: float,
                           now_ms: int, binance_base: str,
                           okx_contract_size: float | None) -> dict[str, Any]:
        key = (exchange, symbol)
        cached = self._derivatives_cache.get(key)
        now_mono = time.monotonic()
        if cached and now_mono - cached[0] < self.derivatives_ttl_sec:
            self.cache_hits += 1
            return cached[1]
        async with self._key_lock(key):
            cached = self._derivatives_cache.get(key)
            now_mono = time.monotonic()
            if cached and now_mono - cached[0] < self.derivatives_ttl_sec:
                self.cache_hits += 1
                return cached[1]
            if exchange == "binance":
                prem_url = f"{binance_base.rstrip('/')}/premiumIndex"
                oi_url = f"{binance_base.rstrip('/')}/openInterest"
                prem, oi_body = await asyncio.gather(
                    self._json(session, prem_url, {"symbol": symbol}, exchange),
                    self._json(session, oi_url, {"symbol": symbol}, exchange),
                )
                funding = _finite(prem.get("lastFundingRate")) if isinstance(prem, dict) else None
                mark = _finite(prem.get("markPrice")) if isinstance(prem, dict) else None
                oi_contracts = _finite(oi_body.get("openInterest")) if isinstance(oi_body, dict) else None
                oi_usd = oi_contracts * (mark or price) if oi_contracts and (mark or price) > 0 else None
            elif exchange == "okx":
                funding_url = f"{OKX_BASE}/public/funding-rate"
                oi_url = f"{OKX_BASE}/public/open-interest"
                funding_body, oi_body = await asyncio.gather(
                    self._json(session, funding_url, {"instId": symbol}, exchange),
                    self._json(session, oi_url, {"instType": "SWAP", "instId": symbol}, exchange),
                )
                frow = (funding_body.get("data") or [{}])[0] if isinstance(funding_body, dict) and funding_body.get("code") == "0" else {}
                orow = (oi_body.get("data") or [{}])[0] if isinstance(oi_body, dict) and oi_body.get("code") == "0" else {}
                funding = _finite(frow.get("fundingRate"))
                oi_usd = _finite(orow.get("oiUsd"))
                if oi_usd is None:
                    oi_ccy = _finite(orow.get("oiCcy"))
                    if oi_ccy is not None:
                        oi_usd = oi_ccy * price
                    else:
                        oi = _finite(orow.get("oi"))
                        factor = _finite(okx_contract_size)
                        if oi is not None and factor is not None and factor > 0:
                            oi_usd = oi * factor * price
            else:
                raise ValueError("desteklenmeyen türev veri venue")

            if funding is not None and abs(funding) > 0.1:
                funding = None
            if oi_usd is not None and (not math.isfinite(oi_usd) or oi_usd <= 0):
                oi_usd = None
            old = self._oi_previous.get(key)
            oi_change = price_change = None
            oi_signal = "NOTR"
            if old and oi_usd is not None:
                old_ts, old_oi, old_price = old
                elapsed = int(now_ms) - int(old_ts)
                if 10_000 <= elapsed <= 300_000 and old_oi > 0 and old_price > 0:
                    oi_change = (oi_usd - old_oi) / old_oi * 100.0
                    price_change = (price - old_price) / old_price * 100.0
                    price_dir = 1 if price_change > 0.05 else (-1 if price_change < -0.05 else 0)
                    if oi_change > 0.5 and price_dir > 0:
                        oi_signal = "YENI_LONG_GIRISI"
                    elif oi_change > 0.5 and price_dir < 0:
                        oi_signal = "YENI_SHORT_GIRISI"
                    elif oi_change < -1.0 and price_dir > 0:
                        oi_signal = "SHORT_KAPAMA_RALLISI"
                    elif oi_change < -1.0 and price_dir < 0:
                        oi_signal = "LONG_TASFIYE_DUSUSU"
            if oi_usd is not None:
                self._oi_previous[key] = (int(now_ms), oi_usd, float(price))
            result = {
                "available": funding is not None and oi_usd is not None,
                "funding_rate": funding,
                "oi_usd": round(oi_usd, 6) if oi_usd is not None else None,
                "oi_change_pct": round(oi_change, 6) if oi_change is not None else None,
                "price_change_pct": round(price_change, 6) if price_change is not None else None,
                "oi_signal": oi_signal,
                "funding_crowding": (
                    "LONG_KALABALIK" if funding is not None and funding >= FUNDING_CROWD_THRESHOLD
                    else "SHORT_KALABALIK" if funding is not None and funding <= -FUNDING_CROWD_THRESHOLD
                    else "DENGELI" if funding is not None else "BILINMIYOR"
                ),
                "source": exchange,
            }
            self._derivatives_cache[key] = (time.monotonic(), result)
            return result

    async def evaluate(self, session, *, exchange: str, symbol: str, side: str,
                       ret_pct: float, price: float, flow_book: Any,
                       okx_contract_size: float | None = None,
                       binance_base: str = BINANCE_PUBLIC_BASE,
                       now_ms: int | None = None) -> dict[str, Any]:
        if exchange not in ("binance", "okx") or side not in ("LONG", "SHORT"):
            raise ValueError("geçersiz sinyal yönü/venue")
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        key = (exchange, symbol)
        try:
            mtf, derivatives = await asyncio.gather(
                self._mtf(session, exchange, symbol, now_ms, binance_base),
                self._derivatives(session, exchange, symbol, float(price), now_ms,
                                  binance_base, okx_contract_size),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            flow_now_ms = max(now_ms, int(time.time() * 1000))
            flow = flow_confirmation(flow_book, exchange, symbol, flow_now_ms, side)
            self.fetch_errors += 1
            self.last_error = f"{key[0]}:{key[1]} {type(exc).__name__}: {str(exc)[:140]}"
            return {
                "accepted": False,
                "reasons": ["signal_intel_fetch_failed"],
                "error": self.last_error,
                "flow": asdict(flow),
                "mtf": {"available": False},
                "derivatives": {"available": False},
            }

        # REST wait may be long under venue rate limits; re-snapshot at decision
        # time so an old 15s CVD cannot remain a valid entry confirmation.
        flow_now_ms = max(now_ms, int(time.time() * 1000))
        flow = flow_confirmation(flow_book, exchange, symbol, flow_now_ms, side)
        reasons: list[str] = []
        side_dir = 1 if side == "LONG" else -1
        if not mtf.get("available"):
            reasons.append("mtf_unavailable")
        elif not mtf.get("allow_long" if side == "LONG" else "allow_short", False):
            reasons.append("mtf_opposes_entry")
        if not derivatives.get("available"):
            reasons.append("funding_or_oi_unavailable")
        funding = _finite(derivatives.get("funding_rate"))
        crowd_dir = 1 if funding is not None and funding >= FUNDING_CROWD_THRESHOLD else (
            -1 if funding is not None and funding <= -FUNDING_CROWD_THRESHOLD else 0
        )
        if crowd_dir == side_dir:
            reasons.append("funding_crowding_opposes_fade")
        oi_signal = str(derivatives.get("oi_signal", "NOTR"))
        opposite_oi = (
            {"YENI_SHORT_GIRISI", "LONG_TASFIYE_DUSUSU"}
            if side == "LONG" else {"YENI_LONG_GIRISI", "SHORT_KAPAMA_RALLISI"}
        )
        if oi_signal in opposite_oi:
            reasons.append("oi_price_matrix_opposes_entry")
        if not flow.accepted:
            reasons.append(flow.reason or "orderflow_not_confirmed")
        return {
            "accepted": not reasons,
            "reasons": reasons,
            "raw_ret_pct": float(ret_pct),
            "side": side,
            "flow": asdict(flow),
            "mtf": mtf,
            "derivatives": derivatives,
        }

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "mtf_ttl_sec": self.mtf_ttl_sec,
            "mtf_close_safety_ms": self.mtf_close_safety_ms,
            "derivatives_ttl_sec": self.derivatives_ttl_sec,
            "public_api_min_interval_sec": PUBLIC_API_MIN_INTERVAL_SEC,
            "fetch_calls": self.fetch_calls,
            "fetch_errors": self.fetch_errors,
            "cache_hits": self.cache_hits,
            "last_error": self.last_error,
            "thresholds": {
                "funding_crowd_abs": FUNDING_CROWD_THRESHOLD,
                "flow_min_usd_15s": FLOW_MIN_USD,
                "flow_min_trades_15s": FLOW_MIN_TRADES,
                "flow_max_age_ms": FLOW_MAX_AGE_MS,
                "flow_directional_ratio": FLOW_IMBALANCE_RATIO,
                "oi_rising_pct": 0.5,
                "oi_falling_pct": -1.0,
                "max_signal_decision_age_ms": MAX_SIGNAL_DECISION_AGE_MS,
            },
        }
