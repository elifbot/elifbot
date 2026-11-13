"""
data/feed_utils.py — Ortak mum doğrulama / temizleme yardımcıları.
"""
from __future__ import annotations

import math
from urllib.parse import urlparse

import pandas as pd

REQUIRED_COLUMNS = ("open_time", "open", "high", "low", "close", "volume")


class CandleValidationError(ValueError):
    """Geçersiz mum satırı."""


def validate_candle_row(row: dict) -> None:
    """Tek mum satırını doğrular; geçersizse CandleValidationError fırlatır."""
    for col in REQUIRED_COLUMNS:
        if col not in row:
            raise CandleValidationError(f"eksik kolon: {col}")

    ts = row["open_time"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:
        raise CandleValidationError(f"geçersiz open_time: {ts!r}")

    for col in ("open", "high", "low", "close"):
        v = row[col]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CandleValidationError(f"{col} sayısal değil: {v!r}")
        if not math.isfinite(v) or v <= 0:
            raise CandleValidationError(f"{col} sonlu/pozitif değil: {v!r}")

    vol = row["volume"]
    if isinstance(vol, bool) or not isinstance(vol, (int, float)):
        raise CandleValidationError(f"volume sayısal değil: {vol!r}")
    if not math.isfinite(vol) or vol < 0:
        raise CandleValidationError(f"volume negatif/sonsuz: {vol!r}")

    if row["high"] < row["low"]:
        raise CandleValidationError("high < low")
    if row["high"] < max(row["open"], row["close"]):
        raise CandleValidationError("high, open/close'un altında")
    if row["low"] > min(row["open"], row["close"]):
        raise CandleValidationError("low, open/close'un üstünde")


def validate_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Tüm satırları doğrular; ilk hatada durur. Doğrulanmış veriyi döndürür."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CandleValidationError(f"eksik kolonlar: {missing}")
    records = df[list(REQUIRED_COLUMNS)].to_dict("records")
    for rec in records:
        validate_candle_row(rec)
    return df


def sort_and_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """open_time'a göre artan sıralar, tekrarlarda son kaydı tutar."""
    if df.empty:
        return df.reset_index(drop=True)
    out = df.sort_values("open_time", kind="mergesort").drop_duplicates(
        subset="open_time", keep="last"
    )
    return out.reset_index(drop=True)


def filter_closed_candles(
    df: pd.DataFrame,
    now_ms: int,
    timeframe_ms: int,
    *,
    close_time_col: str = "close_time",
) -> pd.DataFrame:
    """
    Yalnızca KAPANMIŞ mumları döndürür (lookahead koruması).

    close_time kolonu varsa onu, yoksa open_time + timeframe_ms kullanılır.
    """
    if df.empty:
        return df.reset_index(drop=True)
    if close_time_col in df.columns:
        ct = df[close_time_col]
    else:
        ct = df["open_time"] + timeframe_ms
    return df.loc[ct <= now_ms].reset_index(drop=True)


def check_candle_gaps(df: pd.DataFrame, timeframe_ms: int) -> list[tuple[int, int]]:
    """Eksik mum aralıklarını (önceki_ts, sonraki_ts) listesi olarak döndürür."""
    if df is None or len(df) < 2:
        return []
    ts = [int(t) for t in df["open_time"].tolist()]
    gaps: list[tuple[int, int]] = []
    for prev, cur in zip(ts, ts[1:]):
        if cur - prev > timeframe_ms:
            gaps.append((prev, cur))
    return gaps


def to_ms(value: object) -> int:
    """int/float/digit-str zaman damgasını ms'e çevirir; geçersizse hata verir."""
    if isinstance(value, bool):
        raise CandleValidationError("bool zaman damgası olamaz")
    if isinstance(value, (int, float)):
        iv = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        iv = int(value.strip())
    else:
        raise CandleValidationError(f"zaman damgası çözülemedi: {value!r}")
    if iv <= 0:
        raise CandleValidationError(f"zaman damgası pozitif değil: {iv}")
    return iv


def is_url_allowed(url: str) -> bool:
    """URL'yi host + path allowlist'ine göre kontrol eder."""
    from config import ALLOWED_HOSTS, ALLOWED_PATHS

    p = urlparse(url)
    if p.scheme != "https":
        return False
    if p.hostname not in ALLOWED_HOSTS or p.username is not None or p.password is not None:
        return False
    try:
        if p.port not in (None, 443) or p.fragment:
            return False
    except ValueError:
        return False
    if p.hostname.endswith('binance.com') and not p.path.startswith('/fapi/'):
        return False
    if p.hostname == 'www.okx.com' and not p.path.startswith('/api/v5/'):
        return False
    if p.query and any(k in p.query for k in ("api_key", "apikey", "signature", "secret")):
        return False
    return p.path in ALLOWED_PATHS


def ensure_url_allowed(url: str) -> None:
    """Allowlist dışı URL'de PermissionError fırlatır."""
    if not is_url_allowed(url):
        raise PermissionError(f"allowlist dışı URL reddedildi: {url}")
