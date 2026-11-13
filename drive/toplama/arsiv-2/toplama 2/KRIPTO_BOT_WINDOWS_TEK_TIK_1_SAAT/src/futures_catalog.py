"""Binance/OKX saf kripto USDT perpetual katalogu, TradFi/ABD hisse/ETF filtresi ve ikiz varlık eşleştirmesi."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/USDT$")

# Borsaların USDT perpetual listesinde yer alan kripto-dışı sentetik ABD/global hisse,
# tekil hisse kaldıraçlı ETF'leri, sektör ETF/ETP'leri, endeks, emtia, döviz ve sabit-coin pariteleri.
# Bot YALNIZCA saf kripto USDT-M vadeli (perpetual) kontratlarda işlem açar.
NON_CRYPTO_OR_PEGGED_BASES: frozenset[str] = frozenset(
    {
        # ABD Büyük Teknoloji / S&P 500 / Nasdaq Hisse Kontratları
        "AMZN", "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "GOOG", "META", "NFLX",
        "AVGO", "ORCL", "CRM", "ADBE", "CSCO", "IBM", "INTU", "PANW", "CRWD",
        "SNOW", "PLTR", "SHOP", "UBER", "ABNB", "PYPL", "SQ", "XYZ", "SOFI",
        "AFRM", "UPST", "ROKU", "RDDT", "SNAP", "PINS", "RBLX", "ROBLOX", "TTD",
        "DDOG", "ZS", "MDB", "WDAY", "HUBS", "DOCU", "TWLO", "OKTA",
        # Yarı İletken / Donanım / Optik / Telekom / Veri Merkezi ABD Senetleri
        "INTC", "AMD", "MU", "MRVL", "QCOM", "TXN", "ADI", "NXPI", "MCHP", "KLAC",
        "LRCX", "AMAT", "GFS", "UMC", "ARM", "SMCI", "DELL", "HPQ", "HPE", "PSTG",
        "NTAP", "WDC", "SNDK", "CIEN", "CRDO", "ONDS", "AAOI", "COHR", "LITE",
        "FN", "ANET", "VRT", "ALAB", "SNPS", "CDNS", "FTNT", "ACLS", "ONTO",
        "CAMT", "LSCC", "RMBS", "SITM", "SWKS", "QRVO", "TSEM", "AXTI", "AXT", "TTMI",
        # Kripto Madencilik / Borsa / Yapay Zeka Altyapı Halka Açık ABD Şirket Hisseleri
        "COIN", "MSTR", "HOOD", "MARA", "RIOT", "CLSK", "IREN", "CORZ", "CIFR",
        "HUT", "WULF", "BITF", "BTBT", "APLD", "NBIS", "CRCL", "GLXY", "BKKT",
        "CNPY", "QUANT", "OURA", "CBRS", "SECZ", "APP", "DKNG", "NES",
        # Otomotiv / Uzay / Enerji / Sanayi / Biyoteknoloji / Finans / Perakende ABD Senetleri
        "RIVN", "LCID", "NIO", "XPEV", "BYD", "HYUNDAI", "KIA", "RKLB", "ASTS", "LUNR", "SPCE",
        "JOBY", "ACHR", "SERV", "IONQ", "RGTI", "QBTS", "QUBT", "SOUN", "BBAI",
        "FLNC", "ENPH", "FSLR", "SEDG", "PLUG", "OKLO", "SMR", "NNE", "CCJ", "UEC", "VST", "CEG",
        "MP", "LMT", "NOC", "GD", "RTX", "BA", "GE", "HON",
        "JNJ", "LLY", "UNH", "ABBV", "MRK", "PFE", "AMGN", "TMO", "ABT", "ISRG",
        "VRTX", "MRNA", "BNTX", "RXRX", "HIMS",
        "JPM", "GS", "MS", "BAC", "WFC", "SCHW", "BLK", "AXP", "SPGI", "BRKB",
        "WMT", "COST", "HD", "KO", "PEP", "MCD", "SBUX", "NKE",
        "PG", "DIS", "BKNG", "CVNA", "CELH", "AMC", "DJT", "XOM", "CVX",
        # Asya / Global Hisse Senetleri & Bellek Sepetleri
        "BABA", "TENCENT", "JD", "PDD", "BIDU", "MEITUAN", "XIAOMI", "POPMART",
        "SAMSUNG", "SKHYNIX", "HANMI", "TSM", "ASML", "SONY", "TOYOTA", "SOFTBANK",
        "NINTENDO", "DRAM", "RAM", "NAND",
        # ABD Endeks, Sektör ve Kaldıraçlı ETF / ETP Kontratları
        "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV", "TLT", "IEF", "SHY",
        "HYG", "LQD", "ARKK", "ARKW", "ARKG", "ARKF", "SMH", "SOXX",
        "XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC",
        "EWY", "EWJ", "EWZ", "FXI", "KWEB", "ASHR", "EEM", "EFA", "INDA",
        "TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU",
        "TNA", "TZA", "LABU", "LABD", "FAS", "FAZ", "TECL", "TECS", "FNGU", "FNGD",
        "BOIL", "KOLD", "TMF", "TMV", "UVXY", "SVXY", "VXX", "YINN", "YANG",
        "JNUG", "JDST", "NUGT", "DUST", "GDX", "GDXJ",
        # Tekil ABD Hissesi Kaldıraçlı ETF Kontratları (2x/3x Direxion/GraniteShares vb.)
        "TSLL", "TSLS", "TSLQ", "TSLT", "TSLZ",
        "NVDL", "NVDS", "NVDU", "NVDX", "NVDQ",
        "MSTU", "MSTZ", "MSTX", "MSTP",
        "CONL", "CONY", "AMZU", "AMZD", "AAPU", "AAPD", "MSFU", "MSFD",
        "GGLL", "GGLS", "METU", "METD", "AMDL", "AMDS",
        "MUU", "MUD", "MVLL", "INTW", "SHAZ", "SKUU", "SPCX", "PLTU", "PLTD",
        "SMCX", "SMCL",
        # Spot Kripto ETF Kontratları (Hisse Piyasası ETF Türevleri)
        "BITO", "IBIT", "FBTC", "ARKB", "GBTC", "ETHA", "ETHE", "BITB", "HODL",
        "BRRR", "EZBC", "BTCO", "BTCW", "FETH", "ETHW", "BITX", "BITU", "SBIT",
        "ETHU", "ETHT", "SOLZ", "SOLT",
        # Borsa Endeks & Volatilite Kontratları
        "US500", "SPX", "SP500", "NAS100", "NDX", "US100", "US30", "DJI", "US2000", "RUT",
        "UK100", "DE40", "FR40", "EU50", "JP225", "HK50", "CN50", "AU200", "KR200",
        "VIX", "DXY", "BTCDOM", "DEFI", "BLUEBIRD", "FOOTBALL",
        # Emtia, Enerji & Değerli Madenler
        "XAU", "XAG", "XPT", "XPD", "PAXG", "XAUT", "GOLD", "SILVER", "COPPER", "XCU",
        "WTI", "BRENT", "USOIL", "UKOIL", "NATGAS", "NG", "CL", "GLD", "SLV", "USO", "UNG",
        # Sabit Coin & Majör Döviz (FX) Pariteleri
        "USDC", "FDUSD", "USDE", "DAI", "TUSD", "USDP", "PYUSD", "FRAX", "BUSD",
        "USD1", "RLUSD", "USDD", "EURC", "EURT", "AEUR",
        "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "CNH", "CNY", "HKD",
        "SGD", "KRW", "INR", "TRY", "BRL", "MXN", "ZAR", "RUB",
    }
)

_LEVERAGED_ETP_RE = re.compile(
    r"^(?:CSOP[A-Z0-9]+|[A-Z0-9]{2,}(?:2L|2S|3L|3S|5L|5S))$"
)
_UNIT_PREFIX_RE = re.compile(r"^(?:1000000000|1000000|100000|10000|1000|1M|1B)([A-Z0-9]{3,})$")
_NON_CRYPTO_INFO_TAGS = frozenset(
    {
        "stock", "stocks", "equity", "equities", "etf", "etp",
        "index", "indices", "forex", "fx", "commodity", "commodities",
        "metal", "metals", "tradfi", "share", "shares",
        "usstock", "hkstock", "krstock", "nasdaq", "nyse",
    }
)
_CRYPTO_UNDERLYING_TYPES = frozenset(
    {"coin", "crypto", "cryptocurrency", "token", "digital_asset"}
)
_TAG_SPLIT_RE = re.compile(r"[\s,;/|_\-]+")


def canonical_underlying_asset(symbol: str) -> str:
    """1000SATS/USDT ile SATS/USDT gibi birim çarpanlı ikiz pariteleri ortak köke indirger."""
    base = str(symbol or "").strip().upper().split(":", 1)[0].split("/", 1)[0]
    if not base:
        return ""
    matched = _UNIT_PREFIX_RE.fullmatch(base)
    if matched:
        return matched.group(1)
    return base


def _iter_tag_tokens(raw_value: object) -> Iterable[str]:
    if raw_value is None:
        return
    if isinstance(raw_value, (list, tuple, set, frozenset)):
        for item in raw_value:
            yield from _iter_tag_tokens(item)
        return
    text = str(raw_value).strip().lower()
    if not text:
        return
    yield text
    for part in _TAG_SPLIT_RE.split(text):
        if part:
            yield part


def is_non_crypto_or_pegged_perp(symbol: str, market: Mapping | None = None) -> bool:
    """ABD/global hisse, ETF, endeks, emtia, FX veya sabit-coin kontratı mı?"""
    base = str(symbol or "").strip().upper().split(":", 1)[0].split("/", 1)[0]
    if not base:
        return True
    if base in NON_CRYPTO_OR_PEGGED_BASES:
        return True
    root = canonical_underlying_asset(base)
    if root in NON_CRYPTO_OR_PEGGED_BASES:
        return True
    if _LEVERAGED_ETP_RE.fullmatch(base):
        return True
    if isinstance(market, Mapping):
        info = market.get("info")
        if isinstance(info, Mapping):
            raw_ut = str(info.get("underlyingType") or "").strip().lower()
            if raw_ut and raw_ut not in _CRYPTO_UNDERLYING_TYPES:
                return True
            for key in (
                "assetClass",
                "underlyingType",
                "underlyingSubType",
                "instCategory",
                "contractCategory",
                "category",
                "subType",
                "productType",
                "marketType",
                "contractType",
                "sector",
                "tags",
            ):
                for tok in _iter_tag_tokens(info.get(key)):
                    if tok in _NON_CRYPTO_INFO_TAGS:
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


_VERIFIED_OKX_NATIVE_CRYPTO_BASES: frozenset[str] = frozenset(
    {"OKB", "CRO", "PI", "CORE", "FLR", "CSPR", "XDC", "MX", "BGB", "GT", "HTX"}
)


def build_futures_catalog(
    exchange_markets: Mapping[str, Mapping[str, Mapping]],
    preferred_symbols: list[str] | None = None,
    min_leverage: int = 10,
    max_symbols: int = 0,
    *,
    exclude_non_crypto: bool = True,
) -> tuple[list[str], dict[str, list[str]]]:
    """Borsaların perpetual union listesini ve sembol→borsalar haritasını üretir."""
    per_exchange_symbols: dict[str, list[str]] = {}
    for exchange, markets in exchange_markets.items():
        accepted_syms: list[str] = []
        for market in markets.values():
            symbol = perpetual_symbol(
                market,
                min_leverage=min_leverage,
                exclude_non_crypto=exclude_non_crypto,
            )
            if symbol is not None:
                accepted_syms.append(symbol)
        per_exchange_symbols[exchange] = accepted_syms

    # Binance gerçek vadeli kataloğu yüklüyse (>=50 kripto kontratı), OKX'te sonradan
    # listelenen yeni sentetik hisse/pre-IPO swap'ların sızmasını önlemek için OKX
    # kontratının kök varlığının Binance kripto evreninde (veya doğrulanmış yerel L1/borsa
    # coin listesinde) bulunmasını zorunlu tut.
    binance_syms = per_exchange_symbols.get("binance") or []
    binance_roots: set[str] = (
        {canonical_underlying_asset(s) for s in binance_syms}
        if (exclude_non_crypto and len(binance_syms) >= 50)
        else set()
    )

    support: dict[str, list[str]] = {}
    for exchange, sym_list in per_exchange_symbols.items():
        for symbol in sym_list:
            if binance_roots and exchange != "binance":
                root = canonical_underlying_asset(symbol)
                if root not in binance_roots and root not in _VERIFIED_OKX_NATIVE_CRYPTO_BASES:
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
