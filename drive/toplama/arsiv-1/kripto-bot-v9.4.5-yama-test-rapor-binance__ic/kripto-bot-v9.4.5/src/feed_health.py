"""v9.4.2 — Veri akışı sağlığı ve Binance USDⓈ-M WebSocket yönlendirmesi.

Bağımlılıksız (aiohttp/ccxt gerektirmez) saf yardımcılar:

1. Binance 2026-03-06 duyurusuyla vadeli WS'i /public, /market, /private diye böldü;
   eski /ws ve /stream adresleri 2026-04-23'te kapatıldı. Taşınmamış bağlantı YALNIZ
   /public verisini (bookTicker, depth) alır; aggTrade/markPrice/kline/ticker
   (/market) sessizce susar. v9.4.1 canlı testinde "BBO var, aggTrade 0, hata 133"
   kusurunun kök nedeni budur.
2. Eski `healthy` bayrağı tek bir last_ts'e bakıyordu; BBO güncellemesi trade-tape
   yokluğunu maskeliyordu. Burada BBO ve trade-tape ayrı ayrı denetlenir.
"""
from __future__ import annotations

from typing import Any

BINANCE_FUTURES_WS_BASE = "wss://fstream.binance.com"

# Binance duyurusundaki kategori eşlemesi (Important WebSocket Change Notice, 2026-03-06).
_PUBLIC_PREFIXES = ("bookTicker", "!bookTicker", "depth")
_MARKET_PREFIXES = (
    "aggTrade", "markPrice", "!markPrice", "kline", "ticker", "!ticker", "miniTicker",
    "!miniTicker", "forceOrder", "!forceOrder", "compositeIndex", "!contractInfo", "assetIndex",
    "!assetIndex",
)


def binance_futures_stream_category(stream_suffix: str) -> str:
    """'bookTicker' -> 'public'; 'aggTrade' -> 'market'. Bilinmeyen akış hata verir (sessiz susmayı önler)."""
    s = str(stream_suffix)
    if s.startswith(_PUBLIC_PREFIXES):
        return "public"
    if s.startswith(_MARKET_PREFIXES):
        return "market"
    raise ValueError(f"Bilinmeyen Binance vadeli akış türü (kategori belirlenemedi): {stream_suffix!r}")


def binance_futures_ws_url(stream_suffix: str, stream_path: str) -> str:
    """Birleşik (combined) akış adresi. Kategoriler tek bağlantıda KARIŞTIRILAMAZ."""
    cat = binance_futures_stream_category(stream_suffix)
    return f"{BINANCE_FUTURES_WS_BASE}/{cat}/stream?streams={stream_path}"


def binance_futures_single_stream_url(stream_name: str) -> str:
    """Tek akış için /{kategori}/ws/ adresi. '!ticker@arr' -> /market ; 'btcusdt@aggTrade' -> /market."""
    key = stream_name.split("@", 1)[0] if stream_name.startswith("!") else stream_name.split("@", 1)[-1]
    return f"{BINANCE_FUTURES_WS_BASE}/{binance_futures_stream_category(key)}/ws/{stream_name}"


def venue_feed_status(
    stats: dict[str, Any],
    now_s: float,
    *,
    bbo_max_age_sec: float = 20.0,
    trade_max_age_sec: float = 30.0,
    started_at: float | None = None,
    warmup_grace_sec: float = 60.0,
    require_trades: bool = True,
) -> dict[str, Any]:
    """Venue sağlığı = taze BBO VE taze trade-tape. Biri eksikse healthy=False ve alarm üretir."""
    last_bbo = float(stats.get("last_bbo_ts") or 0.0)
    last_trade = float(stats.get("last_trade_ts") or 0.0)
    bbo_ok = last_bbo > 0 and (now_s - last_bbo) < bbo_max_age_sec
    trade_ok = last_trade > 0 and (now_s - last_trade) < trade_max_age_sec
    in_grace = started_at is not None and (now_s - started_at) < warmup_grace_sec
    alarms: list[str] = []
    if not bbo_ok and not in_grace:
        alarms.append("BBO_STALE")
    if require_trades and not trade_ok and not in_grace:
        alarms.append("TRADE_TAPE_STALE" if int(stats.get("ticks") or 0) > 0 else "TRADE_TAPE_ABSENT")
    healthy = (bbo_ok and (trade_ok or not require_trades)) or (in_grace and not alarms)
    return {
        "healthy": bool(healthy),
        "bbo_healthy": bool(bbo_ok),
        "trade_tape_healthy": bool(trade_ok),
        "alarms": alarms,
    }
