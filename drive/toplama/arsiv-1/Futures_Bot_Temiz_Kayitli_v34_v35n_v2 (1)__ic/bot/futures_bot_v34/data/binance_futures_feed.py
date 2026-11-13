"""
data/binance_futures_feed.py — Binance USDⓈ-M Futures public veri akışı.

Yalnızca iki public uç nokta kullanılır:
  /fapi/v1/klines        (mum verisi)
  /fapi/v1/exchangeInfo  (tick/step boyutları)

Kimlik doğrulama YOKTUR: api_key, secret, signature hiçbir yerde geçmez.
Sadece GET kullanılır.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

import pandas as pd
import requests

import config
from scanner.universe import is_stock_like
from data.feed_utils import (
    CandleValidationError,
    ensure_url_allowed,
    sort_and_dedup,
    validate_candle_row,
)

BINANCE_CONTRACT_TYPES = config.BINANCE_CONTRACT_TYPES
BINANCE_QUOTE_ASSET = config.BINANCE_QUOTE_ASSET

log = logging.getLogger(__name__)

KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
TICKER_24H_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"

_TIMEOUT_SEC = 15
_MAX_RETRIES = 3
_BACKOFF_BASE_SEC = 1.5


class FeedError(RuntimeError):
    """Veri çekme hatası (ağ, HTTP, şema)."""


class FeedAccessError(FeedError):
    """Bölgesel/HTTP erişim engeli (ör. 451) — veri kullanılamıyor."""


def _get_json(
    session: requests.Session, url: str, params: dict[str, Any]
) -> Any:
    """Allowlist kontrollü, sınırlı yeniden denemeli GET isteği."""
    ensure_url_allowed(url)

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=_TIMEOUT_SEC)
        except (
            requests.Timeout,
            requests.ConnectionError,          # Connection reset by peer dahil
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            last_error = FeedError(f"ağ hatası: {url}: {exc}")
            wait = _BACKOFF_BASE_SEC * (attempt + 1) + random.uniform(0, 0.4)
            log.warning(
                "ağ hatası (deneme %d/%d, %.1fs sonra tekrar): %s",
                attempt + 1, _MAX_RETRIES, wait, type(exc).__name__,
            )
            time.sleep(wait)
            continue
        except requests.RequestException as exc:
            raise FeedError(f"ağ hatası: {url}: {exc}") from exc

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as exc:
                raise FeedError(f"bozuk JSON: {url}") from exc
        if resp.status_code == 429:
            wait = _BACKOFF_BASE_SEC * (attempt + 1)
            log.warning("429 rate-limit, %.1fs bekleniyor", wait)
            time.sleep(wait)
            last_error = FeedError(f"429 rate limit: {url}")
            continue
        if resp.status_code == 451:
            raise FeedAccessError(f"451 bölgesel erişim engeli: {url}")
        if resp.status_code in (403, 418):
            raise FeedAccessError(f"{resp.status_code} erişim reddedildi: {url}")
        last_error = FeedError(f"HTTP {resp.status_code}: {url}")
        log.warning("HTTP %s (deneme %d/%d)", resp.status_code, attempt + 1, _MAX_RETRIES)

    raise last_error or FeedError(f"istek başarısız: {url}")


class BinanceFuturesFeed:
    """Binance USDⓈ-M futures public mumlarını normalize edilmiş DataFrame'e çevirir."""

    exchange = "binance"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    # -- mumlar -------------------------------------------------------------
    def fetch_candles(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """
        KAPANMIŞ mumları artan sırada döndürür.

        Dönen kolonlar: open_time, open, high, low, close, volume,
        close_time, quote_volume, trades.
        """
        raw = _get_json(
            self._session,
            KLINES_URL,
            {"symbol": symbol, "interval": interval, "limit": int(limit)},
        )
        if not isinstance(raw, list):
            raise FeedError(f"beklenmeyen kline yanıtı: {type(raw).__name__}")
        if not raw:
            raise FeedError(f"boş kline yanıtı: {symbol}")

        rows: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 7:
                raise FeedError("bozuk kline satırı")
            row = {
                "open_time": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "close_time": int(item[6]),
                "quote_volume": float(item[7]) if len(item) > 7 else float("nan"),
                "trades": int(item[8]) if len(item) > 8 else 0,
            }
            try:
                validate_candle_row(row)
            except CandleValidationError as exc:
                log.warning("geçersiz mum atıldı (%s): %s", symbol, exc)
                continue
            rows.append(row)

        if not rows:
            raise FeedError(f"doğrulanmış mum yok: {symbol}")

        df = sort_and_dedup(pd.DataFrame(rows))
        df.attrs["exchange"] = self.exchange
        df.attrs["symbol"] = symbol
        return df

    # -- enstrüman meta verisi ---------------------------------------------
    def fetch_instruments(self) -> dict[str, dict[str, float]]:
        """
        symbol -> {tick_size, step_size, min_qty} eşlemesi döndürür.

        Doğrulama: PRICE_FILTER.tickSize ve LOT_SIZE.stepSize pozitif olmalı.
        """
        payload = _get_json(self._session, EXCHANGE_INFO_URL, {})
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(symbols, list):
            raise FeedError("exchangeInfo şeması beklenmedik")

        out: dict[str, dict[str, object]] = {}
        for sym in symbols:
            if not isinstance(sym, dict):
                continue
            name = sym.get("symbol")
            filters = sym.get("filters")
            if not isinstance(name, str) or not isinstance(filters, list):
                continue

            # --- SADECE KALDIRAÇLI VADELİ: perpetual + USDT + işlem görüyor ---
            contract_type = sym.get("contractType")
            if contract_type is not None and contract_type not in BINANCE_CONTRACT_TYPES:
                continue  # CURRENT_QUARTER / NEXT_QUARTER vb. elenir
            if str(sym.get("quoteAsset") or "") != BINANCE_QUOTE_ASSET:
                continue
            status = sym.get("status")
            if status is not None and status != "TRADING":
                continue
            # Savunma katmanı: hisse/endeks dayanaklı kontrat varsa ele.
            underlying_type = sym.get("underlyingType")
            if underlying_type is not None and underlying_type != "COIN":
                log.warning("kripto olmayan dayanak, atlandı: %s (%s)", name, underlying_type)
                continue
            if is_stock_like(name):
                log.warning("hisse/endeks benzeri sembol, atlandı: %s", name)
                continue
            tick = step = min_qty = None
            for f in filters:
                if not isinstance(f, dict):
                    continue
                if f.get("filterType") == "PRICE_FILTER":
                    tick = f.get("tickSize")
                elif f.get("filterType") == "LOT_SIZE":
                    step = f.get("stepSize")
                    min_qty = f.get("minQty")
            try:
                tick_f = float(tick)  # type: ignore[arg-type]
                step_f = float(step)  # type: ignore[arg-type]
                min_f = float(min_qty) if min_qty is not None else 0.0
            except (TypeError, ValueError):
                log.warning("filtre alanları geçersiz, sembol atlandı: %s", name)
                continue
            if tick_f <= 0 or step_f <= 0:
                log.warning("tick/step pozitif değil, sembol atlandı: %s", name)
                continue
            out[name] = {
                "tick_size": tick_f,
                "step_size": step_f,
                "min_qty": min_f,
                "contract_type": contract_type or "PERPETUAL",
                "quote_asset": BINANCE_QUOTE_ASSET,
            }
        if not out:
            raise FeedError("exchangeInfo'dan geçerli perpetual sembol çıkmadı")
        return out

    # -- 24 saatlik ticker (hacim taraması) --------------------------------
    def fetch_tickers(self) -> list[dict]:
        """
        Tüm USDⓈ-M vadeli kontratların 24 saatlik istatistikleri.

        Alanlar: symbol, lastPrice, quoteVolume (USDT notional),
        priceChangePercent. Doğrulama: lastPrice > 0, quoteVolume >= 0.
        """
        raw = _get_json(self._session, TICKER_24H_URL, {})
        if not isinstance(raw, list):
            raise FeedError(f"beklenmeyen ticker yanıtı: {type(raw).__name__}")
        out: list[dict] = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            sym = t.get("symbol")
            if not isinstance(sym, str):
                continue
            try:
                last_f = float(t.get("lastPrice") or 0)
                qv = float(t.get("quoteVolume") or 0)
            except (TypeError, ValueError):
                log.warning("ticker alanları geçersiz, atlandı: %s", sym)
                continue
            if last_f <= 0 or qv < 0:
                continue
            out.append({**t, "symbol": sym, "lastPrice": last_f, "quoteVolume": qv})
        if not out:
            raise FeedError("Binance ticker listesi boş")
        return out

    def close(self) -> None:
        self._session.close()
