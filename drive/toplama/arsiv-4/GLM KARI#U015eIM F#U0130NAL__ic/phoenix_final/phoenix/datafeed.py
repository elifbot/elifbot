"""Kamu veri katmanı: Binance → OKX → Bybit otomatik yedekleme (failover).

AcarBot'un "multi-exchange failover" fikri veri tarafına uygulanır: birincil kaynak
engelli/ağda değilse sıradaki kamu API'si kullanılır. API anahtarı GEREKMEZ — sinyal
arama ve backtest tamamen kamu verisiyle çalışır.

Sembol formatı ccxt biçimidir: "BTC/USDT:USDT" → Binance "BTCUSDT", OKX "BTC-USDT-SWAP",
Bybit "BTCUSDT".
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

TIMEFRAME_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
                "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000}
_OKX_BAR = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1H", "2h": "2H", "4h": "4H"}
_BYBIT_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}


def _get(url: str, timeout: float = 15.0, retries: int = 5) -> dict | list:
    last_err: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PhoenixFinal)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last_err = e
            wait = (8.0 if e.code == 429 else 1.5) * (i + 1)  # 429: uzun geri çekilme
            time.sleep(min(wait, 30.0))
        except Exception as e:  # noqa: BLE001 — ağ hatasında yeniden dene
            last_err = e
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"istek başarısız: {url[:120]} ({last_err})")


def _okx_check(d):
    """OKX HTTP-200-ile-dönen hata kodlarını exception'a çevirir (failover çalışsın)."""
    if isinstance(d, dict) and d.get("code") not in (None, "0"):
        raise RuntimeError(f"OKX hata kodu {d.get('code')}: {str(d.get('msg'))[:80]}")
    return d


def _split(symbol: str) -> str:
    """'BTC/USDT:USDT' → 'BTC'"""
    return symbol.split(":")[0].split("/")[0].upper()


# ---------------------------------------------------------------- kaynaklar
def _fetch_binance(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    sym = symbol.split(":")[0].replace("/", "")
    ms = TIMEFRAME_MS[timeframe]
    out: list[list] = []
    end = int(time.time() * 1000)
    while len(out) < bars:
        limit = min(1500, bars - len(out))
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}"
               f"&interval={timeframe}&limit={limit}&endTime={end}")
        rows = _get(url)
        if not rows:
            break
        out = [r[:6] for r in rows] + out  # klines 12 alanlıdır; ilk 6 yeter
        end = rows[0][0] - ms
        if len(rows) < limit:
            break
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"])
    return df.astype(float)


def _fetch_okx(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    inst = f"{_split(symbol)}-USDT-SWAP"
    ms = TIMEFRAME_MS[timeframe]
    bar = _OKX_BAR[timeframe]
    out: list[list] = []
    # son mumlar: /market/candles (en fazla ~300); daha eski: /market/history-candles
    first = min(300, bars)
    rows = _okx_check(_get(f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar={bar}&limit={first}"))
    out = list(rows.get("data", []))
    while len(out) < bars and out:
        after = out[-1][0]  # elimizdeki en eski ts
        time.sleep(0.15)  # hız limitine saygı
        d = _okx_check(_get(f"https://www.okx.com/api/v5/market/history-candles?instId={inst}&bar={bar}"
                            f"&limit=100&after={after}"))
        older = d.get("data", [])
        if not older:
            break
        out = older + out
        if len(older) < 2:  # kaynak tükendi
            break
    if not out:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame([r[:6] for r in out], columns=["ts", "open", "high", "low", "close", "volume"])
    return df.astype(float)


def _fetch_bybit(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    sym = _split(symbol) + "USDT"
    ms = TIMEFRAME_MS[timeframe]
    out: list[list] = []
    end = int(time.time() * 1000)
    while len(out) < bars:
        limit = min(1000, bars - len(out))
        url = (f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}"
               f"&interval={_BYBIT_MIN[timeframe]}&limit={limit}&end={end}")
        d = _get(url)
        rows = (d.get("result") or {}).get("list", [])
        if not rows:
            break
        end = int(rows[-1][0]) - ms
        out = rows + out
        if len(rows) < limit:
            break
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    return df.astype(float)


_FETCHERS = {"binance": _fetch_binance, "okx": _fetch_okx, "bybit": _fetch_bybit}


def fetch_ohlcv(symbol: str, timeframe: str, bars: int, prefer: list[str] | None = None,
                cache_dir: str | Path | None = None, min_bars: int = 50) -> pd.DataFrame:
    """Kapanmış mumların artan sıralı OHLCV DataFrame'ini döndürür (ts = mum açılış ms).

    Kaynak sırasıyla dener; tümü başarısızsa RuntimeError. cache_dir verilirse CSV önbelleği
    tutar. min_bars: kabul edilebilir en az kapanmış mum (canlı artımlı yoklamada 1).
    """
    ms = TIMEFRAME_MS[timeframe]
    now = int(time.time() * 1000)
    cache_path: Path | None = None
    cached: pd.DataFrame | None = None
    if cache_dir is not None and bars >= min_bars:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe = symbol.replace("/", "_").replace(":", "-")
        cache_path = cache_dir / f"{safe}_{timeframe}.csv"
        if cache_path.exists():
            cached = pd.read_csv(cache_path)
            if len(cached) >= bars and int(cached.ts.iloc[-1]) + ms > now - ms:
                return _trim(cached, bars)
    order = prefer or ["binance", "okx", "bybit"]
    errs: list[str] = []
    for src in order:
        try:
            df = _FETCHERS[src](symbol, timeframe, bars)
            if len(df) < min_bars:
                raise RuntimeError(f"{src}: yetersiz mum ({len(df)})")
            df = _finalize(df, ms)
            if cache_path is not None:
                df.to_csv(cache_path, index=False)
            return _trim(df, bars)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{src}: {e}")
    if cached is not None:
        return _trim(cached, bars)
    raise RuntimeError(f"tüm veri kaynakları başarısız: {'; '.join(errs)}")


def _finalize(df: pd.DataFrame, ms: float) -> pd.DataFrame:
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    # son mum hâlâ açıksa (kapanış süresi geçmediyse) at
    cutoff = int(time.time() * 1000) - ms
    df = df[df.ts <= cutoff]
    return df.reset_index(drop=True)


def _trim(df: pd.DataFrame, bars: int) -> pd.DataFrame:
    return df.tail(bars).reset_index(drop=True)


def to_indexed(df: pd.DataFrame) -> pd.DataFrame:
    """ts (ms) sütununu DatetimeIndex'e çevirir (UTC)."""
    out = df.copy()
    out.index = pd.to_datetime(out.ts, unit="ms", utc=True)
    return out.drop(columns=["ts"])
