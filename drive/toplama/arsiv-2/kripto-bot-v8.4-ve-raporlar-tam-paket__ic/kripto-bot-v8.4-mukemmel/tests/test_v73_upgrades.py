from __future__ import annotations

import asyncio
import time

from src.circuit_breaker import CircuitBreaker
from src.futures_catalog import (
    build_futures_catalog,
    canonical_underlying_asset,
    is_non_crypto_or_pegged_perp,
    perpetual_symbol,
)
from src.moneyflow import MoneyFlow
from src.pdf_v3_prep import pdf_v3_snapshot
from src.risk import RiskManager
from src.shadow_lab import ShadowLab
from src.strategy import Strategy
from src.trade_quality import flow_confidence, pdf_v3_confluence
from tests.test_fixed_runner import FixedBroker, fixed_executor
from tests.test_pdf_indicators import make_df


def _swap_market(symbol: str, **extra) -> dict:
    base = {
        "symbol": symbol,
        "active": True,
        "swap": True,
        "contract": True,
        "linear": True,
        "quote": "USDT",
        "settle": "USDT",
        "limits": {"leverage": {"max": 25}},
    }
    base.update(extra)
    return base


def test_non_crypto_synthetic_perps_are_filtered_from_catalog():
    for bad in (
        "AMZN/USDT",
        "US500/USDT",
        "CSOPSAMSUNG2L/USDT",
        "BITO/USDT",
        "USDC/USDT",
        "XAU/USDT",
        "BTC3L/USDT",
    ):
        assert is_non_crypto_or_pegged_perp(bad)
        assert perpetual_symbol(_swap_market(f"{bad}:USDT")) is None

    assert is_non_crypto_or_pegged_perp(
        "ACME/USDT", {"info": {"assetClass": "stock"}}
    )

    markets = {
        "binance": {
            "CELR": _swap_market("CELR/USDT:USDT"),
            "1INCH": _swap_market("1INCH/USDT:USDT"),
            "AMZN": _swap_market("AMZN/USDT:USDT"),
            "US500": _swap_market("US500/USDT:USDT"),
        },
        "okx": {
            "CHILLGUY": _swap_market("CHILLGUY/USDT:USDT"),
            "CSOP": _swap_market("CSOPSAMSUNG2L/USDT:USDT"),
            "BITO": _swap_market("BITO/USDT:USDT"),
        },
    }
    symbols, _ = build_futures_catalog(markets, min_leverage=10)
    assert symbols == ["1INCH/USDT", "CELR/USDT", "CHILLGUY/USDT"]


def test_twin_asset_deduplication_blocks_1000sats_when_sats_is_open():
    assert canonical_underlying_asset("1000SATS/USDT") == "SATS"
    assert canonical_underlying_asset("SATS/USDT:USDT") == "SATS"
    assert canonical_underlying_asset("1MBABYDOGE/USDT") == "BABYDOGE"
    assert canonical_underlying_asset("1000PEPE/USDT") == "PEPE"
    assert canonical_underlying_asset("1INCH/USDT") == "1INCH"

    broker = FixedBroker()
    executor = fixed_executor(broker)
    asyncio.run(executor._open("SATS/USDT", "SHORT", 0.0003, "TEST"))
    assert "SATS/USDT" in executor.positions

    combined = {
        "total": -70.0,
        "signal": "SHORT",
        "raw_signal": "SHORT",
        "entry_allowed": True,
    }
    asyncio.run(
        executor.on_signal(
            "1000SATS/USDT",
            0.30,
            combined,
            flow_score=-60.0,
            veto=False,
        )
    )
    assert "1000SATS/USDT" not in executor.positions
    assert executor.stats["twin_symbol_filtered"] == 1


def test_flash_crash_scope_isolates_altcoins_and_trips_global_only_on_btc_eth():
    breaker = CircuitBreaker(
        flash_crash_pct=8.0,
        global_shock_symbols=["BTC/USDT", "ETH/USDT"],
        symbol_shock_cooldown_sec=900.0,
    )
    broker = FixedBroker()
    broker.prices.update({"CELR/USDT": 0.02, "DOGE/USDT": 0.15})
    executor = fixed_executor(broker)
    executor.circuit_breaker = breaker

    asyncio.run(executor._open("CELR/USDT", "SHORT", 0.02, "TREND"))
    asyncio.run(executor._open("DOGE/USDT", "SHORT", 0.15, "TREND"))
    # A global close needs an independently received quote for each position.
    asyncio.run(executor.on_price_tick("CELR/USDT", 0.02))
    assert set(executor.positions) == {"CELR/USDT", "DOGE/USDT"}

    # 1) Portföyde olmayan LIGHT/USDT %8.20 sıçrarsa açık işlemler KAPANMAZ!
    asyncio.run(executor.on_price_tick("LIGHT/USDT", 1.000))
    asyncio.run(executor.on_price_tick("LIGHT/USDT", 1.082))
    assert not breaker.tripped
    assert breaker.is_symbol_in_shock("LIGHT/USDT")[0]
    assert set(executor.positions) == {"CELR/USDT", "DOGE/USDT"}
    assert executor.stats["altcoin_shock_isolated"] == 1

    # 2) Portföyde olan DOGE/USDT tek başına %9.0 hareket ederse YALNIZ DOGE kapanır, CELR kalır!
    asyncio.run(executor.on_price_tick("DOGE/USDT", 0.150))
    asyncio.run(executor.on_price_tick("DOGE/USDT", 0.1635))
    assert not breaker.tripped
    assert set(executor.positions) == {"CELR/USDT"}

    # 3) BTC/USDT %8.5 çöküş yaşarsa Global Sigorta atar ve tüm portföy kapanır!
    asyncio.run(executor.on_price_tick("BTC/USDT", 70000.0))
    asyncio.run(executor.on_price_tick("BTC/USDT", 64000.0))
    assert breaker.tripped
    assert not executor.positions


def test_moneyflow_emits_book_levels_and_fixes_shadow_flow_confidence():
    mf = MoneyFlow("SOL/USDT")
    now = time.time()
    for idx in range(10):
        mf.add_trade(100.0 + idx * 0.01, 5.0, False, ts=now - 120 + idx * 10)
    bids = [[100.0 - i * 0.05, 10.0] for i in range(20)]
    asks = [[100.05 + i * 0.05, 8.0] for i in range(20)]
    mf.update_book(bids, asks, depth=20, ts=now - 0.3)

    snap = mf.snapshot()
    assert snap["book_levels"] == 20
    assert snap["book_age_sec"] is not None and snap["book_age_sec"] < 5.0

    fc = flow_confidence(
        snap,
        {
            "pencere_saniye": 300,
            "min_islem_sayisi": 5,
            "min_kapsama_saniye": 60,
            "max_defter_yasi_saniye": 10,
        },
    )
    assert fc["data_ready"] is True
    assert fc["data_missing"] == []


def test_executor_live_volatility_gate_and_net_breakeven_integration():
    broker = FixedBroker()
    executor = fixed_executor(broker)
    executor.min_bb_width_pct = 0.20
    executor.min_atr_pct = 0.10
    executor.net_breakeven_enabled = True
    executor.net_profit_buffer_usdt = 0.05

    combined = {
        "total": -65.0,
        "signal": "SHORT",
        "raw_signal": "SHORT",
        "entry_allowed": True,
    }
    low_vol_ctx = {
        "indicators": {
            "close": 100.0,
            "atr_pct": 0.04,
            "bollinger_bandwidth_pct": 0.09,
        }
    }
    asyncio.run(
        executor.on_signal(
            "FLAT/USDT", 100.0, combined, -55.0, False, entry_context=low_vol_ctx
        )
    )
    assert "FLAT/USDT" not in executor.positions
    assert executor.stats["volatility_filtered"] == 1

    good_vol_ctx = {
        "indicators": {
            "close": 100.0,
            "atr_pct": 0.45,
            "bollinger_bandwidth_pct": 0.85,
        }
    }
    asyncio.run(
        executor.on_signal(
            "TRENDCOIN/USDT", 100.0, combined, -55.0, False, entry_context=good_vol_ctx
        )
    )
    assert "TRENDCOIN/USDT" in executor.positions
    pos = executor.positions["TRENDCOIN/USDT"]
    assert pos.net_breakeven_enabled is True
    assert pos.net_profit_buffer_usdt == 0.05


def test_pdf_v3_confluence_and_opt_in_shadow_variant():
    df = make_df(n=120, trend=0.25, seed=11)
    btc_df = make_df(n=120, trend=0.20, seed=12)
    v3 = pdf_v3_snapshot(df, btc_df=btc_df)
    assert v3["data_ready"] is True

    ctx = {
        "indicators": {"pdf_v3": v3},
        "derivatives_intel": {
            "available": True,
            "crowding": {
                "crowding_state": "SHORT_KALABALIK",
                "smart_money_divergence": "TOP_TRADER_LONG_PERAKENDE_SHORT",
            },
        },
    }
    cfg = {
        "pdf_confluence": {"aktif": True},
        "pdf_v3_confluence": {
            "aktif": True,
            "min_aligned_signals": 2,
            "max_opposed_signals": 2,
        },
    }
    res_long = pdf_v3_confluence(ctx, "LONG", cfg)
    assert res_long["accepted"] is True
    assert res_long["aligned_count"] >= 2

    lab = ShadowLab(
        strategy=Strategy(),
        baseline_risk=RiskManager(stop_model="marj", margin_stop_fraction=0.8, leverage=10),
        runner_exit_cfg={},
        supertrend_trailing=True,
        fee_cfg={},
        config=cfg,
    )
    assert "pdf-v3-confluence" in lab.variants
    assert len(lab.variants) == 8
