from __future__ import annotations

import asyncio

from src.exchanges import ExchangeManager
from src.futures_catalog import build_futures_catalog, is_non_crypto_or_pegged_perp
from src.trade_quality import winning_core_guard


def _swap_market(symbol: str, max_lev: int = 20) -> dict:
    base = symbol.split("/")[0]
    return {
        "symbol": f"{symbol}:USDT",
        "base": base,
        "quote": "USDT",
        "settle": "USDT",
        "swap": True,
        "contract": True,
        "linear": True,
        "active": True,
        "limits": {"leverage": {"max": max_lev}},
        "info": {},
    }


def test_newly_spotted_okx_equities_are_blocked():
    for stock_sym in (
        "TSEM/USDT",
        "HYUNDAI/USDT",
        "AXTI/USDT",
        "CNPY/USDT",
        "QUANT/USDT",
        "NES/USDT",
        "OURA/USDT",
        "CBRS/USDT",
        "TTMI/USDT",
        "DKNG/USDT",
    ):
        assert is_non_crypto_or_pegged_perp(stock_sym) is True


def test_binance_root_filter_blocks_unknown_okx_equities_when_live_catalog_loaded():
    binance_markets = {
        f"COIN{i}/USDT:USDT": _swap_market(f"COIN{i}/USDT")
        for i in range(55)
    }
    binance_markets["1000BONK/USDT:USDT"] = _swap_market("1000BONK/USDT")
    binance_markets["ORDER/USDT:USDT"] = _swap_market("ORDER/USDT")

    okx_markets = {
        "BONK/USDT:USDT": _swap_market("BONK/USDT"),       # matches 1000BONK root -> KEEP
        "ORDER/USDT:USDT": _swap_market("ORDER/USDT"),     # matches ORDER -> KEEP
        "OKB/USDT:USDT": _swap_market("OKB/USDT"),         # verified native crypto -> KEEP
        "NEWSTOCKX/USDT:USDT": _swap_market("NEWSTOCKX/USDT"),  # unlisted equity -> BLOCK
    }

    symbols, support = build_futures_catalog(
        {"binance": binance_markets, "okx": okx_markets},
        min_leverage=10,
    )
    assert "BONK/USDT" in symbols
    assert "ORDER/USDT" in symbols
    assert "OKB/USDT" in symbols
    assert "NEWSTOCKX/USDT" not in symbols
    assert support["ORDER/USDT"] == ["binance", "okx"]


def test_best_price_rejects_cross_exchange_symbol_collision():
    class _FakeEx:
        def __init__(self, px: float):
            self._px = px

        async def fetch_ticker(self, _sym: str):
            return {"last": self._px}

    broker = object.__new__(ExchangeManager)
    broker._ex = {
        "binance": _FakeEx(0.00748),  # BounceBit crypto
        "okx": _FakeEx(8.9370),       # BlackBerry equity collision!
    }
    broker._default_primary = "binance"
    broker._active_primary = "binance"
    broker._ex_degraded_until = {}
    broker._ex_timeouts = {}
    broker._ex_total_timeouts = {}
    broker._ccxt_symbol = lambda sym: f"{sym}:USDT"
    broker.symbol_exchanges = {"BB/USDT": ["binance", "okx"]}

    ex_name, px = asyncio.run(broker.best_price("BB/USDT", "SHORT"))
    assert ex_name == "binance"
    assert abs(px - 0.00748) < 1e-8
    assert broker.symbol_exchanges["BB/USDT"] == ["binance"]


def test_winning_core_guard_accepts_arkm_winner_and_rejects_lone_spike():
    arkm_indicators = {
        "rsi": 38.5,
        "active_components": {
            "ema_trend": -14.4,
            "supertrend": -8.0,
            "macd": -4.0,
            "obv": -4.0,
            "session_vwap": -4.0,
            "anchored_vwap": -4.0,
        },
    }
    arkm_flow = {
        "squeeze": "YOK",
        "score_components": {
            "taker_delta": -37.8,
            "cvd_direction": -14.0,
            "volume_spike": 0.0,
        },
    }
    res_ok = winning_core_guard(arkm_indicators, arkm_flow, "SHORT", {"min_cekirdek_onay": 3})
    assert res_ok["accepted"] is True

    # Opposing CVD or oversold volume-spike chase must be rejected
    bad_flow = {
        "squeeze": "YOK",
        "score_components": {
            "taker_delta": -30.0,
            "cvd_direction": +14.0,
            "volume_spike": -8.0,
        },
    }
    res_bad = winning_core_guard(arkm_indicators, bad_flow, "SHORT", {"min_cekirdek_onay": 3})
    assert res_bad["accepted"] is False
