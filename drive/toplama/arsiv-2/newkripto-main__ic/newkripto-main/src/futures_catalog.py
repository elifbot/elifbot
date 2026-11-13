"""Binance/OKX USDT perpetual katalogu, kripto-dışı filtre ve ikiz varlık eşleştirmesi."""
from __future__ import annotations

import re
from collections.abc import Mapping

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/USDT$")

# Borsaların USDT perpetual listesinde yer alan kripto-dışı sentetik hisse,
# endeks, ETF/ETP, emtia, döviz ve sabit-coin pariteleri (düşük ATR / komisyon tuzağı).
NON_CRYPTO_OR_PEGGED_BASES: frozenset[str] = frozenset(
    {
        # ABD / Global Hisse Kontratları
        "AMZN", "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "GOOG", "META", "NFLX",
        "COIN", "MSTR", "HOOD", "PLTR", "INTC", "AMD", "BABA", "ORCL", "CRM",
        "UBER", "DIS", "BA", "JPM", "GS", "WMT", "KO", "PEP", "MCD", "NKE",
        "SBUX", "SAMSUNG", "TSM", "ASML", "SONY", "TOYOTA",
        # Endeks & Volatilite Kontratları
        "US500", "SPX", "SP500", "NAS100", "NDX", "US100", "US30", "DJI",
        "UK100", "DE40", "JP225", "HK50", "CN50", "VIX", "UVXY", "DXY",
        # ETF / ETP Kontratları
        "BITO", "IBIT", "FBTC", "ARKB", "GBTC", "ETHA", "ETHE", "BITB", "HODL",
        "QQQ", "SPY", "IWM", "DIA", "TLT", "GLD", "SLV", "USO", "UNG", "ARKK",
        # Emtia & Değerli Madenler
        "XAU", "XAG", "XPT", "XPD", "PAXG", "XAUT", "WTI", "BRENT",
        # Sabit Coin & Majör Döviz (FX) Pariteleri
        "USDC", "FDUSD", "USDE", "DAI", "TUSD", "USDP", "PYUSD", "FRAX", "BUSD",
        "USD1", "RLUSD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "TRY", "BRL",
    }
)

_LEVERAGED_ETP_RE = re.compile(
    r"^(?:CSOP[A-Z0-9]+|[A-Z0-9]{2,}(?:2L|2S|3L|3S|5L|5S))$"
)
_UNIT_PREFIX_RE = re.compile(r"^(?:1000000000|1000000|100000|10000|1000|1M|1B)([A-Z0-9]{3,})$")
_NON_CRYPTO_INFO_TAGS = frozenset(
    {"stock", "stocks", "equity", "equities", "etf", "etp", "index", "forex", "fx", "commodity", "tradfi"}
)


def canonical_underlying_asset(symbol: str) -> str:
    """1000SATS/USDT ile SATS/USDT gibi birim çarpanlı ikiz pariteleri ortak köke indirger."""
    base = str(symbol or "").strip().upper().split(":", 1)[0].split("/", 1)[0]
    if not base:
        return ""
    matched = _UNIT_PREFIX_RE.fullmatch(base)
    if matched:
        return matched.group(1)
    return base


def is_non_crypto_or_pegged_perp(symbol: str, market: Mapping | None = None) -> bool:
    """Sentetik hisse, endeks, kaldıraçlı ETF, emtia, FX veya sabit-coin kontratı mı?"""
    base = str(symbol or "").strip().upper().split(":", 1)[0].split("/", 1)[0]
    if not base:
        return True
    if base in NON_CRYPTO_OR_PEGGED_BASES:
        return True
    if _LEVERAGED_ETP_RE.fullmatch(base):
        return True
    if isinstance(market, Mapping):
        info = market.get("info")
        if isinstance(info, Mapping):
            for key in ("assetClass", "underlyingType", "instCategory", "contractCategory", "category"):
                raw = str(info.get(key) or "").strip().lower()
                if raw in _NON_CRYPTO_INFO_TAGS:
                    return True
    return False


def perpetual_symbol(
    market: Mapping,
    min_leverage: int = 10,
    *,
    exclude_non_crypto: bool = True,
) -> str | None:
    """CCXT market kaydını bot sembolüne çevirir; uygun değilse ``None`` döner."""
    if not isinstance(market, Mapping):
        return None
    if market.get("active") is False or not market.get("swap") or not market.get("contract"):
        return None
    if market.get("linear") is False:
        return None
    quote = str(market.get("quote") or "").upper()
    settle = str(market.get("settle") or "").upper()
    if quote != "USDT" or (settle and settle != "USDT"):
        return None
    leverage_limits = (market.get("limits") or {}).get("leverage") or {}
    leverage_max = leverage_limits.get("max")
    try:
        if leverage_max is not None and float(leverage_max) < float(min_leverage):
            return None
    except (TypeError, ValueError):
        pass
    symbol = str(market.get("symbol") or "").split(":", 1)[0].upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        return None
    if exclude_non_crypto and is_non_crypto_or_pegged_perp(symbol, market):
        return None
    return symbol


def build_futures_catalog(
    exchange_markets: Mapping[str, Mapping[str, Mapping]],
    preferred_symbols: list[str] | None = None,
    min_leverage: int = 10,
    max_symbols: int = 0,
    *,
    exclude_non_crypto: bool = True,
) -> tuple[list[str], dict[str, list[str]]]:
    """Borsaların perpetual union listesini ve sembol→borsalar haritasını üretir."""
    support: dict[str, list[str]] = {}
    for exchange, markets in exchange_markets.items():
        for market in markets.values():
            symbol = perpetual_symbol(
                market,
                min_leverage=min_leverage,
                exclude_non_crypto=exclude_non_crypto,
            )
            if symbol is None:
                continue
            supported = support.setdefault(symbol, [])
            if exchange not in supported:
                supported.append(exchange)

    preferred = [s for s in (preferred_symbols or []) if s in support]
    remaining = sorted(s for s in support if s not in set(preferred))
    symbols = preferred + remaining
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    return symbols, {s: support[s] for s in symbols}
