"""
data/okx_swap_feed.py — OKX V5 USDT-linear SWAP public veri akışı.

Yalnızca iki public uç nokta kullanılır:
  /api/v5/market/candles       (mum verisi)
  /api/v5/public/instruments   (ctVal / lotSz / tickSz)

Kritik kurallar:
  * confirm == "1" olmayan (kapanmamış) mumlar KULLANILMAZ.
  * Hacim birimi KONTRAT'tır; base birime çevrim ctVal ile yapılır.
    ctVal <= 0 ise çevrim yapılmaz, sembol atlanır.
Kimlik doğrulama YOKTUR. Sadece GET kullanılır.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

import pandas as pd
import requests

from data.feed_utils import (
    CandleValidationError,
    ensure_url_allowed,
    sort_and_dedup,
    validate_candle_row,
)

log = logging.getLogger(__name__)

CANDLES_URL = "https://www.okx.com/api/v5/market/candles"
TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"

_TIMEOUT_SEC = 15
_MAX_RETRIES = 3
_BACKOFF_BASE_SEC = 1.5

# OKX bar kodları (1m haricinde büyük harfli saat kodları kullanılır).
_BAR_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D",
}


class FeedError(RuntimeError):
    """Veri çekme hatası (ağ, HTTP, şema)."""


class FeedAccessError(FeedError):
    """Erişim engeli (403/451) — veri kullanılamıyor."""


def _get_json(session: requests.Session, url: str, params: dict[str, Any]) -> Any:
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
            # Geçici ağ hataları: geri çekilmeli yeniden deneme (jitter'lı).
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


def _unwrap(payload: Any) -> list[Any]:
    """OKX yanıt zarfını açar; code != '0' ise hata fırlatır."""
    if not isinstance(payload, dict):
        raise FeedError("OKX yanıtı sözlük değil")
    code = payload.get("code")
    if code != "0":
        raise FeedError(f"OKX hata kodu {code!r}: {payload.get('msg')!r}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise FeedError("OKX 'data' alanı liste değil")
    return data


class OkxSwapFeed:
    """OKX USDT-linear SWAP mumlarını Binance ile aynı şemaya normalize eder."""

    exchange = "okx"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    # -- enstrüman meta verisi ---------------------------------------------
    def fetch_instruments(self) -> dict[str, dict[str, Any]]:
        """
        instId -> {tick_size, lot_size, min_size, ct_val, ct_val_ccy}.

        ctVal <= 0 olan enstrüman atlanır (hacim çevrimi yapılamaz).
        """
        data = _unwrap(_get_json(self._session, INSTRUMENTS_URL, {"instType": "SWAP"}))

        out: dict[str, dict[str, Any]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            inst_id = item.get("instId")
            if not isinstance(inst_id, str):
                continue
            try:
                ct_val = float(item.get("ctVal", "0") or 0)
                tick = float(item.get("tickSz", "0") or 0)
                lot = float(item.get("lotSz", "0") or 0)
                min_size = float(item.get("minSz", "0") or 0)
            except (TypeError, ValueError):
                log.warning("OKX alanları sayıya çevrilemedi, atlandı: %s", inst_id)
                continue
            if ct_val <= 0:
                log.warning("ctVal <= 0, hacim çevrimi yapılamaz, atlandı: %s", inst_id)
                continue
            if tick <= 0 or lot <= 0:
                log.warning("tickSz/lotSz pozitif değil, atlandı: %s", inst_id)
                continue
            out[inst_id] = {
                "tick_size": tick,
                "lot_size": lot,
                "min_size": min_size,
                "ct_val": ct_val,
                "ct_val_ccy": item.get("ctValCcy"),
            }
        if not out:
            raise FeedError("OKX instruments'tan geçerli enstrüman çıkmadı")
        return out

    # -- mumlar -------------------------------------------------------------
    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        limit: int,
        *,
        ct_val: float | None = None,
    ) -> pd.DataFrame:
        """
        KAPANMIŞ mumları artan sırada döndürür.

        OKX satır şeması: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        confirm != "1" olan satırlar (kapanmamış mum) atılır.

        Hacim: contracts * ct_val -> base birim. ct_val verilmezse hacim
        KONTRAT cinsinden bırakılır ve 'volume_is_contracts' = True işaretlenir.
        """
        bar = _BAR_MAP.get(interval)
        if bar is None:
            raise FeedError(f"desteklenmeyen interval: {interval}")

        data = _unwrap(
            _get_json(
                self._session,
                CANDLES_URL,
                {"instId": symbol, "bar": bar, "limit": int(limit)},
            )
        )
        if not data:
            raise FeedError(f"boş OKX mum yanıtı: {symbol}")

        rows: list[dict[str, Any]] = []
        skipped_unconfirmed = 0
        for item in data:
            if not isinstance(item, (list, tuple)) or len(item) < 9:
                raise FeedError("bozuk OKX mum satırı")

            confirm = str(item[8])
            if confirm != "1":
                skipped_unconfirmed += 1
                continue

            open_time = int(item[0])
            contracts = float(item[5])
            if ct_val is not None and ct_val > 0:
                volume_base = contracts * ct_val
            else:
                volume_base = contracts

            row = {
                "open_time": open_time,
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": volume_base,
                # OKX 'ts' açılış zamanıdır; 1m varsayımıyla kapanış eklenir.
                "close_time": open_time + 60_000,
                "quote_volume": float(item[7]) if len(item) > 7 else float("nan"),
                "contracts": contracts,
            }
            try:
                validate_candle_row(row)
            except CandleValidationError as exc:
                log.warning("geçersiz OKX mumu atıldı (%s): %s", symbol, exc)
                continue
            rows.append(row)

        if skipped_unconfirmed:
            log.debug("%s: %d kapanmamış mum atıldı", symbol, skipped_unconfirmed)
        if not rows:
            raise FeedError(f"doğrulanmış kapalı mum yok: {symbol}")

        df = sort_and_dedup(pd.DataFrame(rows))
        df.attrs["exchange"] = self.exchange
        df.attrs["symbol"] = symbol
        df.attrs["volume_is_contracts"] = ct_val is None or ct_val <= 0
        return df

    # -- spot pariteler (saf kripto filtresi) ------------------------------
    def fetch_spot_bases(self) -> set[str]:
        """
        OKX SPOT piyasasında `-USDT` paritesi olan base para birimlerini döndürür.

        Neden: hisse/emtia/pre-IPO kontratlarının spot paritesi YOKTUR.
        Bu kümeyi kullanarak "saf kripto" evreni kurulabilir.

        Sınırlama: spot paritesi henüz açılmamış YENİ kripto listeleri de
        elenir (ör. yeni bir token). Muhafazakâr tercih.
        """
        data = _unwrap(
            _get_json(self._session, INSTRUMENTS_URL, {"instType": "SPOT"})
        )
        bases: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            inst = item.get("instId")
            if isinstance(inst, str) and inst.endswith("-USDT"):
                bases.add(inst.split("-")[0].upper())
        if not bases:
            raise FeedError("spot enstrüman listesi boş")
        return bases

    # -- ticker'lar (hacim taraması) ---------------------------------------
    def fetch_tickers(self, inst_type: str = "SWAP") -> list[dict]:
        """
        Tüm SWAP ticker'larını döndürür (hacim sıralaması için).

        Doğrulama: `last > 0` ve `volCcy24h >= 0` olmayan kayıtlar atılır.
        USD hacim hesabı çağıran tarafa aittir (bkz. scanner/universe.py).
        """
        data = _unwrap(_get_json(self._session, TICKERS_URL, {"instType": inst_type}))
        out: list[dict] = []
        for t in data:
            if not isinstance(t, dict):
                continue
            inst = t.get("instId")
            if not isinstance(inst, str) or not inst:
                continue
            last = t.get("last")
            try:
                last_f = float(last)  # type: ignore[arg-type]
                vol_base = float(t.get("volCcy24h") or 0)
            except (TypeError, ValueError):
                log.warning("ticker alanları geçersiz, atlandı: %s", inst)
                continue
            if last_f <= 0 or vol_base < 0:
                continue
            out.append({**t, "last": last_f, "volCcy24h": vol_base})
        if not out:
            raise FeedError("ticker listesi boş veya geçersiz")
        return out

    def close(self) -> None:
        self._session.close()
