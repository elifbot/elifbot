"""
scanner/universe.py — KALDIRAÇLI KRİPTO VADELİ evren taraması.

Kapsam (kesin sınır):
  * Binance  : USDⓈ-M **PERPETUAL** vadeli kontratlar (quoteAsset = USDT)
  * OKX      : **USDT-SWAP** vadeli kontratlar
  * Spot işlem YOK. Spot uç noktası yalnızca "bu bir kripto mu?" filtresi için
    kullanılır; spot fiyatı/emri hiçbir zaman işlem kararına girmez.
  * ABD hisse / ETF / emtia / pre-IPO kontratları ELENİR.

Filtre yöntemi (borsa bazlı):
  Binance: `contractType == "PERPETUAL"` ve `quoteAsset == "USDT"`.
           Binance vadeli piyasasında hisse kontratı yoktur; yine de
           `underlyingType` alanı "COIN" değilse elenir (savunma katmanı).
  OKX    : `instId` `-USDT-SWAP` ile bitmeli VE base paritesinin OKX spot
           piyasasında `-USDT` paritesi bulunmalı. Hisse kontratlarının
           (SNDK, SOXL, SKHYNIX, XAU, CL...) spot paritesi yoktur.

USD hacim formülü:
  OKX     : volCcy24h (= kontrat × ctVal, BASE birim) × last
  Binance : quoteVolume (doğrudan USDT notional)
"""
from __future__ import annotations

from dataclasses import dataclass

# Deny-list: bilinen hisse/endeks sembolleri (ikinci savunma katmanı).
# UNVERIFIED: tam liste değildir; spot-parite filtresi asıl savunmadır.
STOCK_LIKE_DENYLIST: frozenset[str] = frozenset(
    {
        "TSEM", "HYUNDAI", "AXTI", "CNPY", "QUANT", "NES", "BB",
        "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "MSTR", "COIN",
        "SNDK", "SOXL", "SKHYNIX", "SPCX", "XAU", "XAG", "CL", "NG", "SPX", "NDX",
    }
)

MIN_USD_VOLUME = 2_000_000.0


@dataclass(frozen=True)
class RawTicker:
    """Borsadan gelen, normalize edilmiş tek ticker."""

    exchange: str
    symbol: str
    last: float
    volume_usd_24h: float
    change_24h_pct: float | None
    is_crypto_future: bool
    reject_reason: str = ""


@dataclass(frozen=True)
class UniverseEntry:
    """Taramaya giren enstrüman."""

    exchange: str
    symbol: str
    last: float
    volume_usd_24h: float
    volume_base_24h: float
    change_24h_pct: float | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.exchange, self.symbol)


def _f(v: object, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def base_symbol(inst_id: str) -> str:
    """'BTC-USDT-SWAP' -> 'BTC' · 'BTCUSDT' -> 'BTC' · '1000PEPEUSDT' -> 'PEPE'."""
    raw = inst_id.upper()
    if "-" in raw:
        base = raw.split("-")[0]
    else:
        base = raw
        for quote in ("USDT", "USDC", "USD"):
            if raw.endswith(quote):
                base = raw[: -len(quote)]
                break
    if base.startswith("1000") and len(base) > 5:
        base = base[4:]
    return base


def split_okx_binance_overlap(okx_symbols, binance_symbols):
    """OKX USDT perp sembollerini Binance'te de listelenenlerden ayır.

    Borsa yazımları farklı olduğundan karşılaştırma normalize edilmiş base
    sembolüyle yapılır. Sıra korunur; (kalan OKX, Binance'te de bulunanlar)
    döndürülür. `1000PEPE` gibi çarpanlı sözleşmeler aynı base varlığa eşlenir.
    """
    binance_bases = {base_symbol(s) for s in binance_symbols}
    kept, overlap = [], []
    for symbol in okx_symbols:
        target = overlap if base_symbol(symbol) in binance_bases else kept
        target.append(symbol)
    return kept, overlap


def is_stock_like(symbol: str) -> bool:
    """Deny-list kontrolü (sembol adı ya da instId verilebilir)."""
    base = base_symbol(symbol)
    return base in STOCK_LIKE_DENYLIST or symbol.upper() in STOCK_LIKE_DENYLIST


# ---------------------------------------------------------------------------
# Borsa bazlı normalize ediciler
# ---------------------------------------------------------------------------
def normalize_okx_tickers(
    tickers: list[dict], spot_bases: set[str] | None = None
) -> list[RawTicker]:
    """
    OKX `/api/v5/market/tickers` yanıtını `RawTicker` listesine çevirir.

    Kripto vadeli sayılma koşulu:
      instId `-USDT-SWAP` ile bitmeli
      ve (spot_bases verilmişse) base paritesi spot piyasada `-USDT` olarak
      listelenmiş olmalı.
    """
    out: list[RawTicker] = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        inst = t.get("instId")
        if not isinstance(inst, str):
            continue

        last = _f(t.get("last"))
        vol_base = _f(t.get("volCcy24h"))
        open_24h = _f(t.get("open24h"))
        change = ((last / open_24h) - 1.0) * 100.0 if open_24h > 0 else None

        is_swap = inst.endswith("-USDT-SWAP")
        base = base_symbol(inst)
        stock = is_stock_like(inst)
        no_spot = bool(spot_bases is not None) and base not in (spot_bases or set())

        reason = ""
        crypto_ok = is_swap and not stock
        if not is_swap:
            reason = "swap_degil"
            crypto_ok = False
        elif stock:
            reason = "hisse_denylist"
        elif no_spot:
            reason = "spot_paritesi_yok"
            crypto_ok = False

        out.append(
            RawTicker(
                exchange="okx",
                symbol=inst,
                last=last,
                volume_usd_24h=vol_base * last if (last > 0 and vol_base > 0) else 0.0,
                change_24h_pct=change,
                is_crypto_future=crypto_ok,
                reject_reason=reason,
            )
        )
    return out


def normalize_binance_tickers(tickers: list[dict]) -> list[RawTicker]:
    """
    Binance `/fapi/v1/ticker/24hr` yanıtını `RawTicker` listesine çevirir.

    Not: Bu uç noktada `contractType` alanı YOKTUR; perpetual filtresi
    `fetch_instruments()` üzerinden gelen sembol kümesiyle uygulanır
    (bkz. `filter_by_symbols`). `quoteVolume` doğrudan USDT notional'dır.
    """
    out: list[RawTicker] = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        sym = t.get("symbol")
        if not isinstance(sym, str):
            continue
        last = _f(t.get("lastPrice"))
        quote_vol = _f(t.get("quoteVolume"))
        change = _f(t.get("priceChangePercent"), default=float("nan"))
        is_usdt = sym.upper().endswith("USDT")
        stock = is_stock_like(sym)
        reason = ""
        if not is_usdt:
            reason = "usdt_degil"
        elif stock:
            reason = "hisse_denylist"
        out.append(
            RawTicker(
                exchange="binance",
                symbol=sym,
                last=last,
                volume_usd_24h=quote_vol if (last > 0 and quote_vol > 0) else 0.0,
                change_24h_pct=None if change != change else change,  # NaN -> None
                is_crypto_future=is_usdt and not stock,
                reject_reason=reason,
            )
        )
    return out


def filter_by_symbols(
    tickers: list[RawTicker], allowed: set[str], exchange: str
) -> list[RawTicker]:
    """
    Enstrüman listesinden gelen izinli sembollere göre süzer.

    Binance'te `contractType == PERPETUAL` filtresini burada uygularız.
    """
    out: list[RawTicker] = []
    for t in tickers:
        if t.exchange != exchange:
            out.append(t)
            continue
        if t.symbol in allowed:
            out.append(t)
        else:
            out.append(
                RawTicker(
                    exchange=t.exchange,
                    symbol=t.symbol,
                    last=t.last,
                    volume_usd_24h=t.volume_usd_24h,
                    change_24h_pct=t.change_24h_pct,
                    is_crypto_future=False,
                    reject_reason=t.reject_reason or "perpetual_degil",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Evren kurucu
# ---------------------------------------------------------------------------
def build_universe(
    raw: list[RawTicker],
    *,
    min_usd_volume: float = MIN_USD_VOLUME,
    limit: int = 40,
) -> list[UniverseEntry]:
    """Kripto vadeli + likidite eşiğini geçen enstrümanları USD hacme göre sıralar."""
    out: list[UniverseEntry] = []
    for t in raw:
        if not t.is_crypto_future:
            continue
        if t.last <= 0 or t.volume_usd_24h < min_usd_volume:
            continue
        out.append(
            UniverseEntry(
                exchange=t.exchange,
                symbol=t.symbol,
                last=t.last,
                volume_usd_24h=t.volume_usd_24h,
                volume_base_24h=0.0,
                change_24h_pct=t.change_24h_pct,
            )
        )
    out.sort(key=lambda e: e.volume_usd_24h, reverse=True)
    return out[:limit]


def rejection_report(raw: list[RawTicker]) -> dict[str, int]:
    """Neden elendiğinin sayımı (denetim izi)."""
    counts: dict[str, int] = {}
    for t in raw:
        if t.is_crypto_future:
            continue
        key = t.reject_reason or "bilinmeyen"
        counts[key] = counts.get(key, 0) + 1
    return counts
