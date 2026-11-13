"""FINAL v1.5 — Tüm coin evreni keşfi.

Kullanıcı isteği (7 Kasım 2026): 12 sembol değil, borsadaki TÜM USDT
çiftleri aynı anda taranacak (Binance 500+, OKX 200+; pratikte daha fazla).

- Binance: exchangeInfo → status=TRADING, quoteAsset=USDT
  (futures doğrudan erişimde contractType=PERPETUAL; ayna modunda spot listesi)
- OKX: instruments SWAP → state=live, settleCcy=USDT, ctType=linear

Sonuçlar sıralı ve tekildir; çağıran taraf periyodik yenileyebilir.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def binance_usdt_symbols(client) -> list[str]:
    """Binance'teki işlem gören tüm USDT çiftleri (futures veya ayna-spot)."""
    raw = client._get_json("/fapi/v1/exchangeInfo", {})
    if not isinstance(raw, dict) or not isinstance(raw.get("symbols"), list):
        raise ValueError("Binance exchangeInfo beklenmeyen biçim")
    out: list[str] = []
    for item in raw["symbols"]:
        if not isinstance(item, dict):
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        status = item.get("status")
        if status not in ("TRADING", None):  # spot=TRADING; bazı yanıtlarda alan yok
            continue
        # Futures yanıtında yalnız perpetual; spot aynasında alan bulunmaz.
        contract = item.get("contractType")
        if contract is not None and contract != "PERPETUAL":
            continue
        symbol = str(item.get("symbol", "")).upper()
        if symbol:
            out.append(symbol)
    return sorted(set(out))


def okx_usdt_swaps(client) -> list[str]:
    """OKX'teki canlı tüm lineer USDT perpetual swap enstrümanları."""
    raw = client._get_json("/api/v5/public/instruments", {"instType": "SWAP"})
    if not isinstance(raw, dict) or raw.get("code") != "0":
        raise ValueError("OKX instruments beklenmeyen biçim")
    data = raw.get("data")
    if not isinstance(data, list):
        raise ValueError("OKX instruments veri listesi yok")
    out: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if (
            item.get("state") == "live"
            and item.get("settleCcy") == "USDT"
            and item.get("ctType") == "linear"
        ):
            inst_id = str(item.get("instId", "")).upper()
            if inst_id:
                out.append(inst_id)
    return sorted(set(out))


def discover(name: str, client) -> list[str]:
    if name == "binance":
        symbols = binance_usdt_symbols(client)
    elif name == "okx":
        symbols = okx_usdt_swaps(client)
    else:
        raise ValueError(f"bilinmeyen borsa: {name}")
    logger.info("Coin evreni [%s]: %d sembol", name, len(symbols))
    return symbols
