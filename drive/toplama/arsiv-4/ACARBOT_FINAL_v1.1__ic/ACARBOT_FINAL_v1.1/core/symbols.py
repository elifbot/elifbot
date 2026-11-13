"""Tradable-asset exclusions shared by live paper execution and backtests."""

BLACKLISTED_ASSETS = frozenset({
    "EVAA", "BULLA", "INIT", "Q", "JCT", "BLESS", "IDOL", "AIN", "IRYS",
    "XPIN", "DOS", "XAN", "ARB", "AVAX", "OP", "SOL", "BNB", "UNI", "LINK",
})
_QUOTE_ASSETS = ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH")
_EXCHANGE_PREFIXES = frozenset({"BINANCE", "OKX"})


def base_asset(symbol: str) -> str:
    normalized = symbol.upper().strip()
    if ":" in normalized:
        prefix, remainder = normalized.split(":", 1)
        normalized = remainder if prefix in _EXCHANGE_PREFIXES else prefix
    if "_" in normalized:
        normalized = normalized.split("_", 1)[0]
    normalized = normalized.replace("/", "").replace("-", "")
    for suffix in ("SWAP", "PERPETUAL"):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    if len(normalized) > 6 and normalized[-6:].isdigit():
        dated_base = normalized[:-6]
        if any(dated_base.endswith(quote) for quote in _QUOTE_ASSETS):
            normalized = dated_base
    for quote in _QUOTE_ASSETS:
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)]
    return normalized


def is_blacklisted(symbol: str) -> bool:
    return base_asset(symbol) in BLACKLISTED_ASSETS
