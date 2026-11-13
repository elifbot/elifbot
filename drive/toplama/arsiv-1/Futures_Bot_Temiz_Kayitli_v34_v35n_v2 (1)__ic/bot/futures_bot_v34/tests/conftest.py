"""pytest yapılandırması — futures_bot/ dizinini sys.path'e ekler."""
from __future__ import annotations

import math
import os
import random
import sys

import pandas as pd
import pytest

BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_ROOT not in sys.path:
    sys.path.insert(0, BOT_ROOT)


def make_ohlcv(
    bars: int = 260,
    start: float = 100.0,
    drift: float = 0.35,
    noise: float = 0.6,
    seed: int = 7,
) -> pd.DataFrame:
    """Deterministik, sentetik OHLCV üretir (yalnızca test fixture'ı)."""
    rng = random.Random(seed)
    rows = []
    price = start
    ts0 = 1_700_000_000_000
    for i in range(bars):
        open_p = price
        close_p = max(0.5, open_p + drift + rng.gauss(0, noise))
        high_p = max(open_p, close_p) + abs(rng.gauss(0, noise / 2))
        low_p = max(0.01, min(open_p, close_p) - abs(rng.gauss(0, noise / 2)))
        rows.append(
            {
                "open_time": ts0 + i * 60_000,
                "open": round(open_p, 4),
                "high": round(high_p, 4),
                "low": round(low_p, 4),
                "close": round(close_p, 4),
                "volume": round(abs(rng.gauss(100, 25)) + 1.0, 4),
                "close_time": ts0 + i * 60_000 + 60_000,
            }
        )
        price = close_p
    return pd.DataFrame(rows)


def make_trending(bars: int = 260, slope: float = 1.0, start: float = 100.0) -> pd.DataFrame:
    """Kesin artan/azalan seri (ribbon yön testleri için)."""
    rows = []
    ts0 = 1_700_000_000_000
    for i in range(bars):
        c = start + slope * i
        rows.append(
            {
                "open_time": ts0 + i * 60_000,
                "open": c - slope / 2,
                "high": c + abs(slope),
                "low": c - abs(slope),
                "close": c,
                "volume": 100.0,
                "close_time": ts0 + i * 60_000 + 60_000,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()


@pytest.fixture
def uptrend() -> pd.DataFrame:
    return make_trending(260, slope=1.0)


@pytest.fixture
def downtrend() -> pd.DataFrame:
    return make_trending(260, slope=-1.0, start=400.0)


@pytest.fixture
def flat() -> pd.DataFrame:
    df = make_trending(260, slope=0.0, start=100.0)
    df["high"] = 100.5
    df["low"] = 99.5
    return df
