"""Hacim odaklı KALDIRAÇLI KRİPTO VADELİ tarama testleri."""
from __future__ import annotations

import pandas as pd
import pytest

from scanner.spike import ANI_DUSUS, ANI_YUKSELIS, NORMAL, compute_spike, rank_spikes
from scanner.universe import (
    build_universe,
    filter_by_symbols,
    is_stock_like,
    normalize_binance_tickers,
    normalize_okx_tickers,
    rejection_report,
)
from tests.conftest import make_ohlcv


def _okx(inst: str, last: float, vol_ccy: float, open24h: float | None = None) -> dict:
    return {
        "instId": inst,
        "last": str(last),
        "volCcy24h": str(vol_ccy),
        "open24h": str(open24h if open24h is not None else last),
    }


def _bnb(sym: str, last: float, quote_vol: float, pct: float = 0.0) -> dict:
    return {
        "symbol": sym,
        "lastPrice": str(last),
        "quoteVolume": str(quote_vol),
        "priceChangePercent": str(pct),
    }


SPOT = {"BTC", "ETH", "SOL", "SATS", "XRP", "DOGE", "PEPE"}


# ---------------------------------------------------------------------------
# OKX normalize
# ---------------------------------------------------------------------------
def test_okx_usd_volume_uses_price_times_base() -> None:
    """USD hacim = volCcy24h × last (ham volCcy değil)."""
    raw = normalize_okx_tickers(
        [_okx("SATS-USDT-SWAP", 1e-8, 2.995e13), _okx("SOL-USDT-SWAP", 100.0, 6_000_000.0)],
        spot_bases=SPOT,
    )
    by = {r.symbol: r for r in raw}
    assert by["SOL-USDT-SWAP"].volume_usd_24h == pytest.approx(600_000_000.0)
    assert by["SATS-USDT-SWAP"].volume_usd_24h == pytest.approx(299_500.0)


def test_okx_only_usdt_swap_is_crypto_future() -> None:
    """Yalnızca -USDT-SWAP kripto vadeli sayılır."""
    raw = normalize_okx_tickers(
        [_okx("BTC-USDT-SWAP", 80_000.0, 100.0), _okx("BTC-USD-SWAP", 80_000.0, 100.0)],
        spot_bases=SPOT,
    )
    by = {r.symbol: r for r in raw}
    assert by["BTC-USDT-SWAP"].is_crypto_future
    assert not by["BTC-USD-SWAP"].is_crypto_future
    assert by["BTC-USD-SWAP"].reject_reason == "swap_degil"


def test_okx_stock_contracts_rejected_by_spot_filter() -> None:
    """ABD hisse/ETF/emtia kontratları (spot paritesi yok) ELENİR."""
    raw = normalize_okx_tickers(
        [
            _okx("BTC-USDT-SWAP", 80_000.0, 100.0),
            _okx("SNDK-USDT-SWAP", 50.0, 1_000_000.0),    # SanDisk
            _okx("SOXL-USDT-SWAP", 40.0, 1_000_000.0),    # ETF
            _okx("SKHYNIX-USDT-SWAP", 200.0, 1_000_000.0),  # SK Hynix
            _okx("XAU-USDT-SWAP", 2_000.0, 1_000_000.0),  # altın
        ],
        spot_bases=SPOT,
    )
    crypto = [r.symbol for r in raw if r.is_crypto_future]
    assert crypto == ["BTC-USDT-SWAP"]
    rejected = {r.symbol: r.reject_reason for r in raw if not r.is_crypto_future}
    assert rejected["SNDK-USDT-SWAP"] in ("spot_paritesi_yok", "hisse_denylist")
    assert rejected["XAU-USDT-SWAP"] in ("spot_paritesi_yok", "hisse_denylist")


def test_okx_denylist_blocks_even_with_spot_pair() -> None:
    """Deny-list'te olan sembol, spot paritesi olsa bile elenir."""
    raw = normalize_okx_tickers([_okx("BB-USDT-SWAP", 8.93, 1e6)], spot_bases=SPOT | {"BB"})
    assert not raw[0].is_crypto_future
    assert raw[0].reject_reason == "hisse_denylist"


# ---------------------------------------------------------------------------
# Binance normalize
# ---------------------------------------------------------------------------
def test_binance_quote_volume_is_usd_notional() -> None:
    """Binance quoteVolume doğrudan USDT notional'dır."""
    raw = normalize_binance_tickers([_bnb("BTCUSDT", 80_000.0, 4_500_000_000.0, 1.2)])
    assert raw[0].volume_usd_24h == pytest.approx(4.5e9)
    assert raw[0].change_24h_pct == pytest.approx(1.2)
    assert raw[0].is_crypto_future


def test_binance_non_usdt_rejected() -> None:
    """USDT ile kotelenmeyen sözleşmeler elenir."""
    raw = normalize_binance_tickers([_bnb("BTCBUSD", 80_000.0, 1e9)])
    assert not raw[0].is_crypto_future
    assert raw[0].reject_reason == "usdt_degil"


def test_binance_perpetual_filter_via_symbol_set() -> None:
    """Perpetual olmayan semboller (allowed dışı) filter_by_symbols ile elenir."""
    raw = normalize_binance_tickers(
        [_bnb("BTCUSDT", 80_000.0, 1e9), _bnb("ETHUSDT_240628", 2_500.0, 1e6)]
    )
    out = filter_by_symbols(raw, {"BTCUSDT"}, "binance")
    by = {r.symbol: r for r in out}
    assert by["BTCUSDT"].is_crypto_future
    assert not by["ETHUSDT_240628"].is_crypto_future
    # Çeyreklik kontratlar "BTCUSDT_250926" biçimindedir: hem USDT ile bitmez
    # hem de perpetual kümesinde yoktur. İki savunmadan biri devreye girer.
    assert by["ETHUSDT_240628"].reject_reason in ("perpetual_degil", "usdt_degil")


# ---------------------------------------------------------------------------
# Evren + rapor
# ---------------------------------------------------------------------------
def test_build_universe_sorts_by_usd_desc_and_filters() -> None:
    """Evren USD hacme göre azalan sıralanır; düşük hacim ve kripto-dışı elenir."""
    raw = normalize_okx_tickers(
        [
            _okx("BTC-USDT-SWAP", 80_000.0, 100.0),        # 8.0M USD
            _okx("ETH-USDT-SWAP", 2_500.0, 1_000.0),       # 2.5M USD
            _okx("TINY-USDT-SWAP", 1.0, 10.0),             # eşik altı
            _okx("SNDK-USDT-SWAP", 50.0, 1_000_000.0),     # hisse
        ],
        spot_bases=SPOT,
    )
    uni = build_universe(raw, min_usd_volume=1_000_000.0)
    assert [e.symbol for e in uni] == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    assert uni[0].exchange == "okx"
    assert uni[0].key == ("okx", "BTC-USDT-SWAP")


def test_build_universe_mixes_exchanges_without_merging() -> None:
    """İki borsa aynı evrende ama anahtarları ayrı kalır."""
    raw = normalize_okx_tickers([_okx("BTC-USDT-SWAP", 80_000.0, 100.0)], spot_bases=SPOT)
    raw += normalize_binance_tickers([_bnb("BTCUSDT", 80_000.0, 8_000_000.0)])
    uni = build_universe(raw, min_usd_volume=1_000_000.0)
    assert len(uni) == 2
    assert {e.key for e in uni} == {("okx", "BTC-USDT-SWAP"), ("binance", "BTCUSDT")}


def test_rejection_report_counts_reasons() -> None:
    """Eleme nedenleri sayılır (denetim izi)."""
    raw = normalize_okx_tickers(
        [_okx("BTC-USDT-SWAP", 80_000.0, 100.0), _okx("SNDK-USDT-SWAP", 50.0, 1e6),
         _okx("BTC-USD-SWAP", 80_000.0, 1e6)],
        spot_bases=SPOT,
    )
    rep = rejection_report(raw)
    assert rep.get("swap_degil") == 1
    assert sum(rep.values()) == 2


def test_is_stock_like() -> None:
    """Deny-list kontrolü."""
    assert is_stock_like("BB-USDT-SWAP")
    assert is_stock_like("TSEM-USDT-SWAP")
    assert is_stock_like("SNDK-USDT-SWAP")
    assert not is_stock_like("BTC-USDT-SWAP")
    assert not is_stock_like("BTCUSDT")


# ---------------------------------------------------------------------------
# Spike
# ---------------------------------------------------------------------------
def _spike_frame(n: int = 120, jump: float = 3.0, vol_mult: float = 6.0) -> pd.DataFrame:
    df = make_ohlcv(n, drift=0.0, noise=0.0, start=100.0)
    last = df.index[-1]
    df.loc[last, "close"] = 100.0 * (1 + jump / 100)
    df.loc[last, "high"] = df.loc[last, "close"] * 1.001
    df.loc[last, "volume"] = 100.0 * vol_mult
    return df


def test_spike_rise() -> None:
    m = compute_spike(_spike_frame(), "okx:X", ret_threshold_pct=0.6, rvol_threshold=2.5)
    assert m is not None and m.label == ANI_YUKSELIS


def test_spike_fall() -> None:
    m = compute_spike(_spike_frame(jump=-3.0), "okx:X", ret_threshold_pct=0.6, rvol_threshold=2.5)
    assert m is not None and m.label == ANI_DUSUS


def test_spike_none_without_volume() -> None:
    df = make_ohlcv(120, drift=0.0, noise=0.0, start=100.0)
    df.loc[df.index[-1], "close"] = 103.0
    m = compute_spike(df, "X", ret_threshold_pct=0.6, rvol_threshold=2.5)
    assert m is not None and m.label == NORMAL


def test_spike_insufficient_data() -> None:
    assert compute_spike(make_ohlcv(10), "X") is None


def test_spike_zero_median_volume() -> None:
    df = make_ohlcv(120)
    df["volume"] = 0.0
    assert compute_spike(df, "X") is None


def test_rank_spikes_desc() -> None:
    m1 = compute_spike(_spike_frame(jump=5.0, vol_mult=8.0), "BIG")
    m2 = compute_spike(_spike_frame(jump=0.7, vol_mult=2.6), "SMALL")
    assert m1 and m2
    assert rank_spikes([m2, m1], limit=2)[0].symbol == "BIG"


def test_spike_row_serializable() -> None:
    m = compute_spike(_spike_frame(), "X")
    assert m is not None
    row = m.as_row()
    assert set(row) == {"symbol", "last", "rvol", "volume_z", "ret_k_pct",
                        "range_expansion", "spike_score", "label"}
